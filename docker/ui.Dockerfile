# UI: React single-page app served by a FastAPI proxy.
#
# Two stages. Node builds the bundle; the runtime image is Python only, so none
# of the 71 MB of node_modules or the Node runtime itself ships to production.

# ---------------------------------------------------------------------------
# Stage 1 -- build the React bundle
# ---------------------------------------------------------------------------
FROM node:20-slim AS webbuild

WORKDIR /web

# Copy manifests first so this layer caches: dependencies are only reinstalled
# when package.json or the lockfile actually change, not on every source edit.
COPY web/package.json web/package-lock.json ./

# `npm ci` (not `npm install`) installs exactly what the lockfile pins and fails
# if the two disagree -- the reproducibility lesson from requirements-lock.txt,
# applied on the JavaScript side.
RUN npm ci --no-audit --no-fund

COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 -- Python runtime serving the built assets
# ---------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY ui/ ./ui/

# Only the compiled output crosses from the build stage.
COPY --from=webbuild /web/dist ./web/dist

EXPOSE 8080

# GOTCHA #10: Cloud Run routes to 8080.
#
# Note this replaces the old Streamlit entrypoint. Streamlit's default port was
# 8501, which made this the service where forgetting the port binding actually
# bit. uvicorn has no such default, but the explicit flag stays for the same
# reason: the port is a contract with Cloud Run, not an implementation detail.
CMD ["uvicorn", "ui.server:app", "--host", "0.0.0.0", "--port", "8080"]
