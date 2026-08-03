"""
Redis semantic cache for the query path.

A semantic cache differs from a normal key/value cache: instead of matching the
query string exactly, it embeds the query and returns a stored answer when a
PREVIOUS query is close enough in meaning. "How do I scale pods?" can therefore
hit the entry stored for "what is the way to autoscale pods?".

A hit returns in ~50ms and costs zero LLM tokens, so this sits in front of the
whole LangGraph agent in app/main.py.

Two design rules are load-bearing here:

1. GOTCHA #5 — vectorizer. redisvl's SemanticCache defaults to HFTextVectorizer,
   which requires `sentence-transformers`. That package is NOT installed in this
   project, so the default would crash on first use. More importantly, using it
   would mean embedding queries with a DIFFERENT model than the one that built
   the Qdrant index, so cache hits would not correspond to retrieval behaviour.
   We wrap the existing Vertex embed_query in a CustomTextVectorizer to keep one
   embedding model across the entire pipeline. Never reintroduce the HF default.

2. GOTCHA #2 — lazy init. The cache (and the Vertex model behind it) is built
   inside _get_cache(), never at module import. Module-level init delayed FastAPI
   startup enough that Cloud Run's health check killed the container.

The cache is optional infrastructure. Every failure here degrades to "no cache"
rather than breaking the request, because a broken cache must never take down
the query path.
"""

import logfire

from app.config import settings
from app.services.retrieval.embedding import embed_query, embed_texts

# Meaning-distance below which two queries count as the same question.
# Lower = stricter. ~0.15 is tuned for Vertex text-embedding-004.
DISTANCE_THRESHOLD = 0.15

CACHE_NAME = "noisegate_llmcache"

_cache = None          # the SemanticCache instance, built on first use
_cache_disabled = False  # set once we know the cache can't work, to stop retrying


def _cache_is_configured() -> bool:
    """
    Whether a semantic cache should be used at all.

    LOCAL_MODE bypasses Redis entirely so the app runs on a laptop, and
    Memorystore lives on a private IP that is unreachable without the VPC
    connector. Both cases are normal, not errors.
    """
    if settings.LOCAL_MODE:
        return False
    if not settings.REDIS_HOST:
        return False
    return True


def _get_cache():
    """
    Build the SemanticCache on first use, or return None if unavailable.

    Returns None (never raises) so callers can treat "no cache" as a normal
    outcome. Once a build fails we latch _cache_disabled so we don't retry the
    connection on every single request.
    """
    global _cache, _cache_disabled

    if _cache is not None:
        return _cache
    if _cache_disabled or not _cache_is_configured():
        return None

    try:
        from redisvl.extensions.cache.llm import SemanticCache
        from redisvl.utils.vectorize import CustomTextVectorizer

        # GOTCHA #5: reuse the Vertex embedding model rather than redisvl's
        # HuggingFace default, so the cache and the Qdrant index speak the
        # same vector space.
        vectorizer = CustomTextVectorizer(
            embed=embed_query,
            embed_many=embed_texts,
        )

        _cache = SemanticCache(
            name=CACHE_NAME,
            vectorizer=vectorizer,
            distance_threshold=DISTANCE_THRESHOLD,
            redis_url=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}",
        )
        logfire.info(f"Semantic cache ready (threshold={DISTANCE_THRESHOLD})")
        return _cache

    except Exception as e:
        # Unreachable Redis, auth failure, schema conflict — all non-fatal.
        _cache_disabled = True
        logfire.warning(f"Semantic cache unavailable, continuing without it: {e}")
        return None


def check_cache(query: str):
    """
    Look for a semantically similar question already answered.

    Returns the cached answer string, or None on a miss / when caching is off.
    """
    if not query:
        return None

    cache = _get_cache()
    if cache is None:
        return None

    try:
        with logfire.span("Semantic Cache Check"):
            results = cache.check(prompt=query, num_results=1)
            if results:
                logfire.info("Semantic cache HIT")
                return results[0].get("response")
            logfire.info("Semantic cache MISS")
            return None
    except Exception as e:
        logfire.warning(f"Semantic cache check failed: {e}")
        return None


def update_cache(query: str, answer: str) -> None:
    """
    Store an answer so future similar questions can skip the agent entirely.

    Never raises: a failed write must not fail the user's request.
    """
    if not query or not answer:
        return

    cache = _get_cache()
    if cache is None:
        return

    try:
        with logfire.span("Semantic Cache Update"):
            cache.store(prompt=query, response=answer)
            logfire.info("Semantic cache updated")
    except Exception as e:
        logfire.warning(f"Semantic cache update failed: {e}")
