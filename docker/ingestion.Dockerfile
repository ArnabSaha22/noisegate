# Ingestion: Eventarc webhook + document processing pipeline
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# The Office/PDF parsers (unstructured, python-pptx, pypdf) shell out to native
# libraries that are not in the slim base image. Installed before pip so this
# layer caches independently of Python dependency changes.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmagic1 \
        libxml2 \
        libxslt1.1 \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt

# The spaCy model `unstructured` relies on for document partitioning.
#
# It is deliberately NOT in requirements-lock.txt: spaCy models are not
# published to PyPI, so `pip install en_core_web_sm==3.8.0` fails with
# "No matching distribution found" no matter what. They ship as wheels attached
# to GitHub releases, which is what this installs.
#
# Pinned by URL rather than using `python -m spacy download`, because that
# command resolves to whatever version is current and would silently drift.
# Only the ingestion image needs it -- backend and UI never touch `unstructured`.
RUN pip install --no-cache-dir \
    "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"

COPY app/ ./app/

EXPOSE 8080

# processor.py exposes a FastAPI app for the Eventarc webhook. The same module
# also runs as a CLI for local bulk ingestion; only the webhook is served here.
CMD ["uvicorn", "app.ingestion.processor:app", "--host", "0.0.0.0", "--port", "8080"]
