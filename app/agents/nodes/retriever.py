import logfire
from app.agents.state import AgentState
from app.config import settings
from app.services.retrieval.qdrant_service import search_enterprise_key
from app.services.retrieval.ranking_service import rerank_with_scores


def retrieve_node(state: AgentState):
    """
    Vector search then semantic reranking, with a relevance floor.

    THE FLOOR EXISTS BECAUSE VECTOR SEARCH CANNOT SAY "NO".
    Nearest-neighbour search always returns its 15 nearest points, however far
    away they are. Asked for a cookie recipe, this corpus confidently returns
    passages about restaurant ownership -- and the LLM will then write a fluent
    answer grounded in them. Nearest garbage is still garbage.

    The cross-encoder is what makes declining possible. Measured over the golden
    set (scripts/evaluate.py):

        out-of-domain questions        max score  0.0001
        in-domain, retrieval worked    min score  0.0076

    So a low top score is a reliable signal that nothing relevant was found.
    Note the stage-1 vector scores do NOT separate this way -- 0.688 vs 0.401
    medians, badly overlapping -- which is why the floor is applied after
    reranking rather than before.
    """
    query = state["current_query"]

    with logfire.span("Knowledge Retrieval"):
        logfire.info(f"Searching Qdrant for {query}")
        raw_results = search_enterprise_key(query, limit=15)
        logfire.info(f"Retrieved {len(raw_results)} candidates from Vector DB")

        doc_contents = [doc["content"] for doc in raw_results]

        with logfire.span("Semantic Ranking"):
            scored = rerank_with_scores(query, doc_contents, top_n=5)
            logfire.info("Reranking complete. Keeping top 5 most relevant chunks")

        if not scored:
            logfire.warning("No candidates returned from vector search")
            return {
                "documents": [],
                "status": "No documents found in the knowledge base.",
                "plan": state["plan"] + ["Retrieval: empty"],
            }

        top_score = scored[0][1]

        # top_score is None when reranking failed. Skip the floor in that case:
        # a broken reranker must degrade to "answer from Qdrant order", never to
        # "refuse everything".
        if top_score is not None and top_score < settings.RELEVANCE_FLOOR:
            logfire.info(
                f"Top relevance {top_score:.6f} below floor "
                f"{settings.RELEVANCE_FLOOR}; treating as no relevant context"
            )
            return {
                "documents": [],
                "status": "No sufficiently relevant documentation found.",
                "plan": state["plan"] + [
                    f"Relevance {top_score:.4f} < floor {settings.RELEVANCE_FLOOR}",
                    "Declining to answer from unrelated context",
                ],
            }

        formatted_docs = [f"CONTENT: {doc}" for doc, _ in scored]
        score_note = "unscored" if top_score is None else f"{top_score:.4f}"
        logfire.info(f"Context accepted (top relevance {score_note})")

    return {
        "documents": formatted_docs,
        "status": "Found Technical Context.",
        "plan": state["plan"] + ["Context Retrieved"],
    }
