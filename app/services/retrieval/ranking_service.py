import time
import logfire
from flashrank import Ranker, RerankRequest

# Lazy initialization - Ranker is loaded on first use to ensure logfire.configure() has run
_ranker=None

def _get_ranker() -> Ranker:
    """
    Initialize the FlashRank cross-encoder lazily (gotcha #2: never at import).

    The model comes from settings.RERANK_MODEL so it can be A/B tested via the
    RERANK_MODEL env var -- see scripts/evaluate.py. Previously no model_name was
    passed at all, so FlashRank quietly used its 2-layer TinyBERT default while
    the docs claimed a MiniLM model that does not exist in this library.

    The /tmp fallback matters more than it looks. /tmp is purged by macOS and is
    per-instance memory on Cloud Run, so the cached ONNX file disappears and
    loading raises NO_SUCHFILE. Falling back to the default cache directory keeps
    reranking alive instead of silently degrading to Qdrant order.
    """
    global _ranker
    if _ranker is None:
        from app.config import settings

        model = settings.RERANK_MODEL
        logfire.info(f"Initializing FlashRank reranker ({model})...")
        try:
            # A dedicated cache dir avoids permission issues in production.
            _ranker = Ranker(model_name=model, cache_dir="/tmp/flashrank")
        except Exception as e:
            logfire.warning(f"FlashRank cache_dir load failed ({e}); using default cache dir")
            _ranker = Ranker(model_name=model)
    return _ranker



def rerank_with_scores(query: str, documents: list[str], top_n: int = 5):
    """
    Rerank and return [(text, score), ...], best first.

    Scores are what the relevance floor keys on, so the FAILURE MODE MATTERS:
    when reranking breaks, every score comes back as None rather than 0.0.
    Callers must treat None as "unknown", not "irrelevant" -- otherwise a
    reranker outage would make the agent refuse every question it was asked.
    Fail open, not closed.
    """
    if not documents:
        return []

    try:
        ranker = _get_ranker()
        passages = [{"id": i, "text": doc} for i, doc in enumerate(documents)]
        results = ranker.rerank(RerankRequest(query=query, passages=passages))
        return [(r["text"], float(r["score"])) for r in results[:top_n]]
    except Exception as e:
        logfire.error(f"[Reranker] Scoring failed, falling back to Qdrant order: {e}")
        # None signals "no opinion", so the floor is skipped rather than applied
        # against a score we never actually computed.
        return [(doc, None) for doc in documents[:top_n]]


def rerank_documents(query: str, documents: list[str], top_n: int = 5) -> list[str]:
    if not documents:
        return []

    start_time = time.time()
    logfire.info(f"[Reranker] Sending {len(documents)} docs to FlashRank Cross-Encoder...")

    try:
        ranker = _get_ranker()
        
        # FlashRank expects a list of dictionaries with 'id' and 'text'
        passages = [
            {"id": i, "text": doc}
            for i, doc in enumerate(documents)
        ]

        request = RerankRequest(query=query, passages=passages)
        results = ranker.rerank(request)
        
        # Results are returned sorted by highest semantic score first
        reranked_docs = []
        for res in results[:top_n]:
            reranked_docs.append(res['text'])

        duration = time.time() - start_time
        top_score = results[0]['score'] if results else 'N/A'
        logfire.info(f"[Reranker] Done in {duration:.2f}s. Top semantic score: {top_score}")
        
        return reranked_docs

    except Exception as e:
        logfire.error(f"[Reranker] Semantic Reranking Failed: {e}")
        # Fallback to the original Qdrant order to ensure the user still gets an answer
        return documents[:top_n]        