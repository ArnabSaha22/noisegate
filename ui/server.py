"""
Serves the React app and proxies API calls to the private backend.

WHY A PROXY AT ALL
------------------
The backend Cloud Run service is private: its IAM grants run.invoker only to
this UI's service account. Calling it requires a Google-signed ID token.

A browser cannot hold a service-account credential -- there is nowhere to put
one that the user cannot read. So the React bundle never talks to the backend
directly. It calls same-origin /api/... and this server, which DOES have an
identity, attaches the token and forwards.

Two things fall out of that, both good:

  * The backend stays private. No allUsers binding, no publicly callable
    endpoint that costs money per request.
  * No CORS in production. Same origin means the browser never even asks.

The alternative -- making the backend public -- would be simpler and worse:
anyone who found the URL could run queries billed to you via Vertex and Groq.
"""

import os
import pathlib

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
DIST = pathlib.Path(__file__).parent.parent / "web" / "dist"

app = FastAPI(title="NoiseGate Web")

# One client for the process. Generous timeout: a cold Cloud Run backend plus a
# full retrieve-rerank-generate cycle can take a while, and the read timeout
# must not cut a stream off mid-answer.
_client = httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=30.0))


def _auth_headers() -> dict:
    """
    Mint an ID token for the backend, or return {} when running locally.

    The audience must be the backend's BASE url. A trailing slash or the /query
    path produces a token Cloud Run rejects with 403 -- an unhelpfully generic
    error that sends you debugging the wrong service.
    """
    try:
        import google.auth.transport.requests
        from google.oauth2 import id_token

        token = id_token.fetch_id_token(
            google.auth.transport.requests.Request(), BACKEND_URL
        )
        return {"Authorization": f"Bearer {token}"}
    except Exception:
        # No metadata server on a laptop, and the local backend has no IAM.
        return {}


@app.get("/health")
async def health():
    """
    Liveness/diagnostic endpoint.

    NOT named /healthz. Google's frontend reserves that exact path on Cloud Run
    and returns its own 404 before the request reaches the container. Verified
    across two separate services: /health, /healthz/, /readyz, /livez, /_healthz
    all arrive normally -- only bare /healthz is swallowed. The symptom is a
    Google-branded 404 page, which looks like a misrouted service rather than a
    reserved path, so it is easy to spend a while debugging the wrong thing.
    """
    return {"status": "ok", "backend": BACKEND_URL, "ui_built": DIST.exists()}


@app.post("/api/query/stream")
async def proxy_stream(request: Request):
    """
    Forward the SSE stream through, chunk by chunk.

    The point of this endpoint is that nothing here buffers. If the proxy
    collected the full response before returning it, token-by-token streaming
    would still "work" but arrive all at once -- which is precisely the fake
    streaming this rewrite exists to replace.
    """
    body = await request.body()

    async def relay():
        try:
            async with _client.stream(
                "POST",
                f"{BACKEND_URL}/query/stream",
                content=body,
                headers={"Content-Type": "application/json", **_auth_headers()},
            ) as upstream:
                if upstream.status_code != 200:
                    detail = (
                        "the UI could not authenticate to the agent service"
                        if upstream.status_code == 403
                        else f"upstream returned {upstream.status_code}"
                    )
                    yield f'event: error\ndata: {{"message": "Backend error: {detail}."}}\n\n'.encode()
                    return

                async for chunk in upstream.aiter_raw():
                    yield chunk
        except Exception:
            yield b'event: error\ndata: {"message": "Lost connection to the agent service."}\n\n'

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Without this, Cloud Run's proxy buffers the whole response and
            # defeats streaming end to end.
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/query")
async def proxy_query(request: Request):
    """Non-streaming fallback, same auth path."""
    body = await request.body()
    try:
        r = await _client.post(
            f"{BACKEND_URL}/query",
            content=body,
            headers={"Content-Type": "application/json", **_auth_headers()},
        )
        return Response(
            content=r.content,
            status_code=r.status_code,
            media_type=r.headers.get("content-type", "application/json"),
        )
    except Exception:
        return Response(
            content='{"error": "Could not reach the agent service."}',
            status_code=502,
            media_type="application/json",
        )


# ---------------------------------------------------------------------------
# Static assets. Mounted LAST so /api and /healthz win over the catch-all.
# ---------------------------------------------------------------------------

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        """
        Serve index.html for any unmatched path.

        A single-page app owns its own routing, so a deep link must return the
        shell rather than a 404 and let the client render the right view.
        """
        candidate = DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
