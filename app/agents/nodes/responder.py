import logfire
from langchain_groq import ChatGroq
from app.agents.state import AgentState
from app.config import settings

# Lazy init -- see CLAUDE.md gotcha #2, and the note in planner.py.
#
# The Groq client validates its API key in the constructor, so building this at
# module scope made the module unimportable without secrets. That mattered
# beyond CI: the decline path below answers WITHOUT calling an LLM, and it could
# not be tested at all while merely importing the module required a key.
#
# temperature=0.1: slight variation for natural prose, still grounded.
_llm = None


def _get_llm() -> ChatGroq:
    global _llm
    if _llm is None:
        _llm = ChatGroq(
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL,
            temperature=0.1,
        )
    return _llm

def generate_node(state: AgentState):
    """Synthesizes a response using both Documentation Context AND Conversation History."""
    query=state["current_query"]

    #Format the entire history for the LLM
    history_str=""
    for msg in state["messages"][:-1]:
        role="User" if msg["role"]=="user" else "Assistant"
        history_str+=f"{role}: {msg['content']}\n"
    
    user_msg=state["messages"][-1]["content"] if state["messages"] else ""

    if query=="CONVERSATIONAL":
        logfire.info("Generating conversational response using memory")
        prompt=f"""
        You are a friendly and helpful Enterprise AI Assistant.
        Answer the user's latest message using the CONVERSATION HISTORY below.
        
        CONVERSATION HISTORY:
        {history_str}
        
        LATEST MESSAGE:
        "{user_msg}"
        """
    elif not state.get("documents"):
        # The retriever found nothing above the relevance floor. Answer directly
        # rather than asking the LLM to summarise an empty context -- given no
        # material, a model will happily fall back on its own training data and
        # produce a confident, unsourced answer, which is exactly the failure
        # this path exists to prevent.
        #
        # Returning early also skips an LLM call we already know is pointless.
        logfire.info("No relevant context above the floor; declining to answer")
        message = (
            "I don't have information about that in my knowledge base. "
            "I can only answer from the documentation that has been ingested, "
            "and nothing relevant to your question was found there."
        )
        return {
            "final_answer": message,
            "status": "Declined: no relevant documentation.",
            "messages": [{"role": "assistant", "content": message}],
        }

    else:
        #Technical RAG Logic with Token Safety
        logfire.info("Generating technical RAG response")
        max_context_chars = 25000
        full_context = ""

        for doc in state["documents"]:
            if len(full_context) + len(doc) < max_context_chars:
                full_context+=doc + "\n\n"
            else:
                logfire.warning("context truncated to fit GROQ TPM Limits")
                break
        
        prompt = f"""
        You are a Senior Technical Architect. 
        Answer the question using the TECHNICAL CONTEXT provided. 
        
        TECHNICAL CONTEXT:
        {full_context}
        
        CONVERSATION HISTORY:
        {history_str}
        
        USER QUESTION:
        "{user_msg}"
        """
    
    with logfire.span("LLM Synthesis"):
        try:
            response=_get_llm().invoke(prompt)
            logfire.info("Response synthesized successfully")
            return{
                "final_answer": response.content,
                "status": "Response generated.",
                "messages": [{"role": "assistant", "content": response.content}]
            }
        except Exception as e:
            logfire.error(f"LLM Generation Failed :{e}")
            raise e