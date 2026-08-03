import logfire
import os
from dotenv import load_dotenv

# Logfire MUST be configured before importing any app module (see CLAUDE.md gotcha #1).
# If any module emits a Logfire call first, the library silently drops into no-op mode
# and ALL tracing disappears with no error. That is also why this reads the token with
# raw os.getenv() instead of importing app.config.settings — importing settings here
# would pull in app code ahead of configure(). Do not "tidy" this into the imports below.
load_dotenv()
logfire.configure(token=os.getenv("LOGFIRE_TOKEN"))

import json

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from app.agents.graph import rag_agent
from app.services.gcp.redis_semantic_cache import check_cache, update_cache

from pydantic import BaseModel
from typing import Optional

#Initializing the FastAPI
app=FastAPI(title="Enterprise Agentic RAG API")

# CORS exists for LOCAL DEVELOPMENT ONLY.
#
# In production the React app is served by the same origin that proxies these
# routes, so no cross-origin request ever happens and this middleware does
# nothing. During development Vite serves on :5173 while the API is on :8000 --
# different origins, so the browser blocks the call before it is sent.
#
# Origins are an explicit allowlist rather than "*": this API costs real money
# per call (Vertex embeddings + Groq tokens), so it should never be callable
# from arbitrary web pages.
_dev_origins = os.getenv(
    "CORS_ALLOW_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _dev_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

class QueryRequest(BaseModel):
    q:str
    thread_id:Optional[str] = "default_user"


def _sse(event: str, data) -> str:
    """Format one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

# # Instrument FastAPI to link UI traces to backend traces in Logfire
# try:
#     logfire.instrument_fastapi(app)
#     print("✅ Logfire FastAPI instrumentation enabled.")
# except Exception as e:
#     print(f"⚠️ Logfire FastAPI instrumentation skipped: {e}")

@app.get("/")
def home():
    return {"message":"Enterprise Langraph RAG API is Live"}

@app.get("/graph")
def get_graph_image():
    """
    Returns the Mermaid image of the agent's workflow.
    """
    try:
        png_bytes=rag_agent.get_graph().draw_mermaid_png()
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        return {"error": f"Could not generate graph image: {e}"}

@app.post("/query")
def query(request: QueryRequest):
    """
    Executes the LangGraph RAG flow with memory using a POST request.
    """
    q=request.q
    thread_id=request.thread_id

    initial_state={
        "messages": [{"role": "user", "content": q}],
        "current_query": q,
        "documents": [],
        "plan": ["Start"],
        "status": "Initializing Graph..."
    }

    #Configuration for Memory (Thread ID)
    config={"configurable": {"thread_id": thread_id}}
    try:
        # 1. Check Semantic Cache first (Redis)
        cached_response=check_cache(q)
        if cached_response:
            return {
                "question": q,
                "answer": cached_response,
                "thought_process": ["Served from Semantic Cache(Redis)"],
                "status": "Cache HIT",
                "sources": []
            }        
        # 2. Cache MISS: Run the full Agentic Graph
        # Run the graph synchronously to preserve Logfire context variables
        final_output=rag_agent.invoke(initial_state, config=config)
        answer=final_output.get("final_answer")

        # 3. Update Cache with the new answer
        if answer:
            update_cache(q, answer)    

        return {
            "question": q,
            "answer": answer,
            "thought_process": final_output.get("status"),
            "status": final_output.get("status"),
            "sources": final_output.get("documents", [])
        }    
    except Exception as e:
        logfire.error(f"Backend Execution Failed: {e}")
        return{
            "question":q,
            "answer": "I apologize, but I encountered an internal error while processing your request. Please try again later.",
            "thought_process": ["Error encountered during execution."],
            "status": "error",
            "sources": []
        }

@app.post("/query/stream")
def query_stream(request: QueryRequest):
    """
    Same agent flow as /query, streamed as Server-Sent Events.

    WHY THIS EXISTS
    ---------------
    The Streamlit UI "streamed" answers by waiting for the complete response and
    then animating it character by character with time.sleep(). That is a
    typewriter effect, not streaming -- the user still waits the full latency
    before seeing anything.

    This endpoint emits real progress as it happens:

        event: node    -> a graph node finished (planner decided, retriever ran)
        event: sources -> the reranked chunks, as soon as retrieval completes
        event: token   -> individual tokens from the responder, as generated
        event: done    -> terminal frame carrying the assembled answer
        event: error   -> something failed; the stream ends

    GOTCHA #3 IS PRESERVED. This uses the SYNCHRONOUS rag_agent.stream(), not an
    async variant. The checkpointer is a sync PostgresSaver in production, and a
    sync saver inside an async route raises NotImplementedError on aget_tuple.
    FastAPI runs a sync generator in a threadpool, so this stays correct.
    Do not "modernise" this to `async def` without switching to AsyncPostgresSaver.
    """
    q = request.q
    thread_id = request.thread_id

    initial_state = {
        "messages": [{"role": "user", "content": q}],
        "current_query": q,
        "documents": [],
        "plan": ["Start"],
        "status": "Initializing Graph...",
    }
    config = {"configurable": {"thread_id": thread_id}}

    def event_stream():
        try:
            # Cache first, exactly as /query does. A hit still streams, so the
            # client needs no special case -- it just arrives almost instantly.
            cached = check_cache(q)
            if cached:
                yield _sse("node", {"node": "cache", "status": "Served from semantic cache"})
                yield _sse("token", cached)
                yield _sse("done", {"answer": cached, "status": "Cache HIT", "sources": []})
                return

            answer_parts: list[str] = []
            sources: list = []

            # stream_mode=["updates", "messages"] gives BOTH levels at once:
            #   updates  -> whole-node results, for progress reporting
            #   messages -> per-token LLM output, for the typing effect
            for mode, chunk in rag_agent.stream(
                initial_state, config=config, stream_mode=["updates", "messages"]
            ):
                if mode == "updates":
                    for node_name, update in (chunk or {}).items():
                        if not isinstance(update, dict):
                            continue
                        yield _sse("node", {
                            "node": node_name,
                            "status": update.get("status"),
                            "plan": update.get("plan"),
                        })
                        if update.get("documents"):
                            sources = update["documents"]
                            yield _sse("sources", sources)

                elif mode == "messages":
                    message, meta = chunk
                    # Only the responder's tokens are the answer. The planner
                    # also calls an LLM, and leaking its routing decision into
                    # the answer stream would show the user internal reasoning.
                    if meta.get("langgraph_node") != "responder":
                        continue
                    text = getattr(message, "content", "") or ""
                    if text:
                        answer_parts.append(text)
                        yield _sse("token", text)

            answer = "".join(answer_parts)
            if answer:
                update_cache(q, answer)

            yield _sse("done", {
                "answer": answer,
                "status": "Response generated.",
                "sources": sources,
            })

        except Exception as e:
            logfire.error(f"Streaming execution failed: {e}")
            yield _sse("error", {"message": "Internal error while processing your request."})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Cloud Run sits behind a proxy that will buffer the response and
            # defeat streaming entirely unless told not to.
            "X-Accel-Buffering": "no",
        },
    )
