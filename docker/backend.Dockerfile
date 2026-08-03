# Backend: FastAPI + LangGraph agent
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so code edits don't invalidate the dependency layer.
#
# requirements-lock.txt pins all 214 packages to the exact versions verified
# working. requirements.txt pins only 3 of 40, so building from it would install
# whatever is newest that day -- the exact failure mode that made rebuilding the
# local environment risky. Reproducible builds start here.
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY app/ ./app/

# FlashRank downloads its ONNX model here on first use. Cloud Run gives every
# container a writable in-memory /tmp, which is why ranking_service.py asks for
# this path specifically.
ENV FLASHRANK_CACHE_DIR=/tmp/flashrank

# GOTCHA #10: Cloud Run routes traffic to 8080. Bind it explicitly -- relying on
# a framework default is how services end up "deployed" but unreachable.
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
