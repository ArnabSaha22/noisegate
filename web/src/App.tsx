import { useCallback, useEffect, useRef, useState } from "react";
import { AgentEvent, getThreadId, resetThreadId, streamQuery } from "./api";
import { ChatMessage, Message } from "./components/ChatMessage";
import { AgentTrace, TraceStep } from "./components/AgentTrace";
import { Composer } from "./components/Composer";

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [trace, setTrace] = useState<TraceStep[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [threadId, setThreadId] = useState(getThreadId);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, trace]);

  const send = useCallback(
    async (question: string) => {
      if (streaming) return;

      setMessages((m) => [...m, { role: "user", content: question }]);
      // Placeholder assistant message that fills in as tokens arrive.
      setMessages((m) => [...m, { role: "assistant", content: "", sources: [] }]);
      setTrace([]);
      setStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      const patchLast = (fn: (m: Message) => Message) =>
        setMessages((all) => {
          const copy = [...all];
          copy[copy.length - 1] = fn(copy[copy.length - 1]);
          return copy;
        });

      const onEvent = (e: AgentEvent) => {
        switch (e.type) {
          case "node":
            setTrace((t) => [
              ...t,
              { node: e.node, status: e.status ?? "", plan: e.plan ?? [] },
            ]);
            break;
          case "sources":
            patchLast((m) => ({ ...m, sources: e.sources }));
            break;
          case "token":
            // Append as it arrives -- this is the real streaming, not a replay.
            patchLast((m) => ({ ...m, content: m.content + e.text }));
            break;
          case "done":
            patchLast((m) => ({
              ...m,
              content: m.content || e.answer,
              sources: e.sources?.length ? e.sources : m.sources,
              status: e.status,
            }));
            break;
          case "error":
            patchLast((m) => ({ ...m, content: m.content, error: e.message }));
            break;
        }
      };

      try {
        await streamQuery(question, threadId, { onEvent, signal: controller.signal });
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          patchLast((m) => ({ ...m, error: "Could not reach the agent service." }));
        }
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [streaming, threadId],
  );

  const stop = () => abortRef.current?.abort();

  const clearConversation = () => {
    abortRef.current?.abort();
    setMessages([]);
    setTrace([]);
    // A new thread id also resets the agent's server-side memory for this user.
    setThreadId(resetThreadId());
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">◑</span>
          <div>
            <h1>NoiseGate</h1>
            <p className="tagline">Agentic RAG over your documents</p>
          </div>
        </div>

        <div className="panel">
          <h2>How it answers</h2>
          <ol className="pipeline">
            <li><b>Plan</b> — decides if retrieval is even needed</li>
            <li><b>Retrieve</b> — 15 nearest chunks from 3,846</li>
            <li><b>Rerank</b> — a cross-encoder keeps the best 5</li>
            <li><b>Answer</b> — grounded in those 5, with sources</li>
          </ol>
        </div>

        {trace.length > 0 && <AgentTrace steps={trace} live={streaming} />}

        <div className="sidebar-footer">
          <div className="thread">
            <span className="label">Memory</span>
            <code>{threadId.slice(0, 8)}</code>
          </div>
          <button className="ghost" onClick={clearConversation} disabled={!messages.length}>
            Clear conversation
          </button>
        </div>
      </aside>

      <main className="chat">
        {messages.length === 0 ? (
          <EmptyState onPick={send} />
        ) : (
          <div className="messages">
            {messages.map((m, i) => (
              <ChatMessage
                key={i}
                message={m}
                streaming={streaming && i === messages.length - 1}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        )}

        <Composer onSend={send} onStop={stop} streaming={streaming} />
      </main>
    </div>
  );
}

const EXAMPLES = [
  "How do I automatically scale pods based on CPU usage?",
  "How do I schedule a recurring job in Kubernetes?",
  "How can I monitor the status of a running job?",
  "How do I set up a parallel work queue?",
];

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="empty">
      <h2>Ask about the indexed documentation</h2>
      <p>
        Answers come only from the ingested corpus — 3,846 chunks, of which most are
        deliberate distractors. If nothing relevant exists, the retrieval stage has
        nothing to offer.
      </p>
      <div className="examples">
        {EXAMPLES.map((q) => (
          <button key={q} onClick={() => onPick(q)}>
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
