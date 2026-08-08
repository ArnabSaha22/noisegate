from langchain_groq import ChatGroq
from app.agents.state import AgentState
from app.config import settings
import logfire

# Lazy init -- see CLAUDE.md gotcha #2.
#
# Building ChatGroq at module scope means importing this module requires a live
# GROQ_API_KEY, because the Groq client validates it in its constructor. That
# made the module unimportable in CI (no secrets) and added client construction
# to FastAPI startup, which is the cold-start cost gotcha #2 exists to avoid.
#
# temperature=0: routing is a classification, not a creative task.
_llm = None


def _get_llm() -> ChatGroq:
    global _llm
    if _llm is None:
        _llm = ChatGroq(
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL,
            temperature=0,
        )
    return _llm

def planner_node(state: AgentState):
    "The Planner determines if the search is needed based on the entire conversation"

    #Getting the conversation history
    history=""
    for msg in state["messages"][:-1]:
        role="User" if msg["role"] == "user" else "Assistant"
        history+=f"{role}: {msg['content']}\n"

    user_message=state["messages"][-1]["content"] if state["messages"] else ""
    # ROUTING RULE, and why it is shaped this way:
    #
    # The planner decides ROUTE, not whether we know the answer. Only greetings
    # and questions answerable from the conversation itself may skip retrieval.
    # EVERY request for external fact goes to retrieval, whatever the topic --
    # because the relevance floor in retriever.py is the only place that can say
    # "not in the knowledge base", and it only runs on the retrieval path.
    #
    # The previous prompt routed to search only for "Kubernetes, Intel, or
    # Networking" questions, so anything else fell through to CONVERSATIONAL and
    # was answered from the model's own training data, ungrounded and unsourced.
    # Asked for a cookie recipe, it produced one.
    #
    # The output constraint is also explicit: earlier the model sometimes emitted
    # a documentation URL as the "search query", which happened to work only
    # because the URL text embedded near the right content.
    prompt=f"""
            You are the routing planner for a documentation assistant.

            CONVERSATION HISTORY: {history}
            LATEST MESSAGE: {user_message}

            Reply with exactly one of two things:

            1. The single word CONVERSATIONAL -- if and only if the latest
               message is a greeting, small talk, a thank-you, or a question
               answerable using ONLY the conversation history above
               (for example "what is my name?" or "what did I just ask?").

            2. Otherwise, a search query for the documentation index.
               This applies to EVERY request for factual information, on ANY
               topic, even one you believe is unrelated to the documentation.
               Do not decide whether the answer exists -- a later stage checks
               that. Your only job is to phrase the search well.

            The search query must be 3-10 plain keywords describing the topic.
            Do NOT output a URL, a full sentence, quotes, or any explanation.

            Output only CONVERSATIONAL or the keywords, nothing else.
            """
    
    with logfire.span("Planner Decision"):
        decision=_get_llm().invoke(prompt).content.strip()
        logfire.info(f"Intent indentified: {decision}")

    if decision == 'CONVERSATIONAL':
        return{
            "current_query": "CONVERSATIONAL",
            "status": "Handling conversationally (using memory)...",
            "plan": ["Intent: Conversational/Memory", "Retrieval: Skipped"]
        }
    
    return {
        "current_query": decision,
        "status":f"Technical research needed. Searching for: {decision}",
        "plan": ["Intent: Technical", f"Search term: {decision}"]
    }
