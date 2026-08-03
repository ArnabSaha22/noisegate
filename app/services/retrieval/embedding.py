import vertexai
from vertexai.language_models import TextEmbeddingModel
from google.api_core.exceptions import InvalidArgument

from app.config import settings

model = None

# Vertex enforces TWO separate limits, and they bite differently:
#
#   * per text     ~2048 tokens - silently TRUNCATED, no error. Oversized text
#                  looks like it embedded fine but its tail was never read.
#                  Guarded upstream by the 1500-char chunk ceiling in
#                  app/ingestion/chunking/splitters.py.
#   * per request  20000 tokens summed across every text in the call - a hard
#                  400 InvalidArgument.
#
# The old fixed batch of 50 blew the request limit: dense technical text runs
# closer to 2.8 chars/token than the usual 4, so 50 x 1500 chars reached ~22k
# tokens. We therefore batch on a CHARACTER budget with margin, rather than a
# fixed item count.
MAX_BATCH_ITEMS = 25
MAX_BATCH_CHARS = 36_000  # ~14.4k tokens even at a pessimistic 2.5 chars/token


def get_embedding_model():
    global model
    if model is None:
        # Initializing Vertex AI before loading the model
        vertexai.init(project=settings.PROJECT_ID, location=settings.LOCATION)
        # Reverting to TextEmbeddingModel for stability
        model = TextEmbeddingModel.from_pretrained("text-embedding-004")
    return model


def embed_query(query: str):
    """Embeds a single query string using the stable Vertex AI API."""
    model = get_embedding_model()
    embeddings = model.get_embeddings([query])
    return embeddings[0].values


def _iter_batches(texts: list[str]):
    """Group texts so no single request can exceed the per-request token cap."""
    batch: list[str] = []
    chars = 0
    for text in texts:
        if batch and (len(batch) + 1 > MAX_BATCH_ITEMS or chars + len(text) > MAX_BATCH_CHARS):
            yield batch
            batch, chars = [], 0
        batch.append(text)
        chars += len(text)
    if batch:
        yield batch


def _embed_batch(model, batch: list[str]) -> list:
    """
    Embed one batch, halving and retrying if Vertex still rejects it as too large.

    The character budget above is an estimate; text with unusual tokenisation can
    still overshoot. Splitting on InvalidArgument makes that self-correcting
    instead of failing a whole ingestion run. A single text that is still
    rejected is a real error and is allowed to propagate.
    """
    try:
        return [e.values for e in model.get_embeddings(batch)]
    except InvalidArgument:
        if len(batch) == 1:
            raise
        mid = len(batch) // 2
        return _embed_batch(model, batch[:mid]) + _embed_batch(model, batch[mid:])


def embed_texts(texts: list[str]):
    model = get_embedding_model()
    all_embeddings = []
    for batch in _iter_batches(texts):
        all_embeddings.extend(_embed_batch(model, batch))
    return all_embeddings
