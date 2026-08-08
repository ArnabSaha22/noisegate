import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # --- GCP CONFIG ---
    PROJECT_ID = os.getenv("PROJECT_ID", "dmtxpress")
    LOCATION = os.getenv("LOCATION", "us-central1")
    GCP_DOC_AI_LOCATION = os.getenv("GCP_DOC_AI_LOCATION", "us")
    GCP_DOC_AI_PROCESSOR_ID = os.getenv("GCP_DOC_AI_PROCESSOR_ID")
    RAW_BUCKET = os.getenv("GCP_RAW_BUCKET", "rag-data-raw")
    PROCESSED_BUCKET = os.getenv("GCP_PROCESSED_BUCKET", "rag-data-processed")

    # --- VECTOR DB (QDRANT) ---
    # Prefer the correctly-spelled name (what CLAUDE.md and scripts/healthcheck.py
    # expect); fall back to the historical misspelling so existing .env files and
    # deployed services keep working.
    QDRANT_URL = os.getenv("QDRANT_CLUSTER_ENDPOINT") or os.getenv("QDRAND_ENDPOINT")
    QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
    QDRANT_COLLECTION = "noisegate_rag"

    # --- REASONING ENGINE (GROQ) ---
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_MODEL = "llama-3.3-70b-versatile"

    # --- RERANKER (FLASHRANK, stage 2) ---
    # Env-driven so scripts/evaluate.py can A/B models without a code change.
    #
    # Valid names for this FlashRank build:
    #   ms-marco-TinyBERT-L-2-v2   2 layers,  ~4 MB   (FlashRank's default)
    #   ms-marco-MiniLM-L-12-v2   12 layers, ~34 MB
    #   ms-marco-MultiBERT-L-12 | rank-T5-flan | ce-esci-MiniLM-L12-v2
    #
    # NOTE: CLAUDE.md documents "ms-marco-MiniLM-L-6-v2". No such model exists in
    # FlashRank -- that is a sentence-transformers name. Because the code passed
    # no model_name at all, it had silently been using the TinyBERT default.
    RERANK_MODEL = os.getenv("RERANK_MODEL", "ms-marco-TinyBERT-L-2-v2")

    # Minimum cross-encoder score for retrieved context to be considered
    # relevant at all. Below this the agent says it does not know, instead of
    # answering from whatever happened to be nearest.
    #
    # DERIVED FROM MEASUREMENT, not intuition. From scripts/evaluate.py over the
    # 30-question golden set:
    #
    #   out-of-domain questions       max score  0.0001
    #   in-domain, retrieval SUCCEEDED  min score  0.0076   (76x higher)
    #   in-domain, retrieval FAILED         score  0.0001   (correctly rejected)
    #
    # 0.001 is roughly the geometric midpoint of that window: 10x above the
    # worst nonsense, 7.6x below the weakest genuine hit. Log-scale midpoint
    # because the scores span several orders of magnitude.
    #
    # CAVEAT: only 4 out-of-domain samples inform the lower bound. Revisit this
    # as the golden set grows, and prefer LOWERING it if users report being
    # wrongly refused -- a false refusal is more visible than a weak answer.
    RELEVANCE_FLOOR = float(os.getenv("RELEVANCE_FLOOR", "0.001"))

    # --- DATABASE & CACHE ---
    DB_USER = os.getenv("DB_USER", "rag_admin")
    DB_PASS = os.getenv("DB_PASS")
    DB_NAME = os.getenv("DB_NAME", "rag_memory")
    DB_CONNECTION_NAME = os.getenv("DB_CONNECTION_NAME")
    
    REDIS_HOST = os.getenv("REDIS_HOST")
    REDIS_PORT = os.getenv("REDIS_PORT", "6379")

    # --- ENVIRONMENT MODE ---
    # Set to "true" in your local .env to bypass Cloud SQL/Redis
    LOCAL_MODE = os.getenv("LOCAL_MODE", "false").lower() == "true"

    # --- OBSERVABILITY ---
    LOGFIRE_TOKEN = os.getenv("LOGFIRE_TOKEN")
    LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "true")
    LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
    LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "entreprise_rag")
    LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

# Apply LangChain environment variables for automatic tracing
os.environ["LANGCHAIN_TRACING_V2"] = os.getenv("LANGSMITH_TRACING", "true")
os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGSMITH_API_KEY", "")
os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "rag_scale_test")
os.environ["LANGCHAIN_ENDPOINT"] = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

settings = Settings()