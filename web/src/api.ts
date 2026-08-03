/**
 * Client for the agent's streaming endpoint.
 *
 * Why not EventSource? The browser's built-in EventSource only issues GET
 * requests and cannot send a JSON body, but the query and thread_id have to go
 * up in a POST. So we read the response body as a stream and parse the
 * Server-Sent Events framing ourselves. That also gives us AbortController,
 * which EventSource does not offer -- needed for the "stop generating" button.
 *
 * All requests go to same-origin /api/... In development Vite proxies that to
 * localhost:8000; in production the FastAPI server that serves this bundle
 * proxies it to the private backend with an ID token attached. The frontend
 * never knows a backend URL and never handles a credential.
 */

export type AgentEvent =
  | { type: "node"; node: string; status: string | null; plan: string[] | null }
  | { type: "sources"; sources: string[] }
  | { type: "token"; text: string }
  | { type: "done"; answer: string; status: string; sources: string[] }
  | { type: "error"; message: string };

export interface StreamHandlers {
  onEvent: (e: AgentEvent) => void;
  signal?: AbortSignal;
}

export async function streamQuery(
  question: string,
  threadId: string,
  { onEvent, signal }: StreamHandlers,
): Promise<void> {
  const res = await fetch("/api/query/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ q: question, thread_id: threadId }),
    signal,
  });

  if (!res.ok || !res.body) {
    onEvent({
      type: "error",
      message: `Backend returned ${res.status}. ${
        res.status === 403
          ? "The server could not authenticate to the agent service."
          : "Please try again."
      }`,
    });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line. Anything after the last
    // separator is a partial frame -- keep it in the buffer for the next chunk,
    // otherwise a token split across a network packet gets mangled.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const evented = parseFrame(frame);
      if (evented) onEvent(evented);
    }
  }
}

function parseFrame(frame: string): AgentEvent | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;

  let payload: unknown;
  try {
    payload = JSON.parse(dataLines.join("\n"));
  } catch {
    return null;
  }

  switch (event) {
    case "token":
      return { type: "token", text: String(payload) };
    case "sources":
      return { type: "sources", sources: payload as string[] };
    case "node": {
      const p = payload as { node: string; status: string | null; plan: string[] | null };
      return { type: "node", node: p.node, status: p.status, plan: p.plan };
    }
    case "done": {
      const p = payload as { answer: string; status: string; sources: string[] };
      return { type: "done", answer: p.answer, status: p.status, sources: p.sources ?? [] };
    }
    case "error":
      return { type: "error", message: (payload as { message: string }).message };
    default:
      return null;
  }
}

/** Stable per-browser conversation id, so the agent's memory survives reloads. */
export function getThreadId(): string {
  const KEY = "noisegate.threadId";
  let id = localStorage.getItem(KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(KEY, id);
  }
  return id;
}

export function resetThreadId(): string {
  const id = crypto.randomUUID();
  localStorage.setItem("noisegate.threadId", id);
  return id;
}
