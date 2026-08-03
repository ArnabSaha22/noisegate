import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

export interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: string[];
  status?: string;
  error?: string;
}

export function ChatMessage({
  message,
  streaming,
}: {
  message: Message;
  streaming: boolean;
}) {
  const isUser = message.role === "user";

  return (
    <article className={`msg ${isUser ? "msg-user" : "msg-assistant"}`}>
      <div className="msg-role">{isUser ? "You" : "NoiseGate"}</div>

      <div className="msg-body">
        {message.error ? (
          <div className="error-box">{message.error}</div>
        ) : message.content ? (
          <>
            <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>
            {/* Caret only while tokens are still arriving. */}
            {streaming && <span className="caret" aria-hidden="true" />}
          </>
        ) : (
          <Thinking />
        )}

        {!isUser && message.sources && message.sources.length > 0 && (
          <Sources sources={message.sources} />
        )}
      </div>
    </article>
  );
}

/** Shown between "request sent" and "first token" -- the retrieval window. */
function Thinking() {
  return (
    <div className="thinking" role="status" aria-label="Retrieving">
      <span /><span /><span />
    </div>
  );
}

function Sources({ sources }: { sources: string[] }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="sources">
      <button className="sources-toggle" onClick={() => setOpen((o) => !o)}>
        {open ? "Hide" : "Show"} {sources.length} retrieved passage
        {sources.length === 1 ? "" : "s"}
      </button>

      {open && (
        <ol className="source-list">
          {sources.map((s, i) => {
            // The retriever prefixes each chunk with "CONTENT: " for the prompt;
            // that is an implementation detail, not something to show a reader.
            const text = s.replace(/^CONTENT:\s*/, "");
            return (
              <li key={i}>
                <div className="source-rank">{i + 1}</div>
                <pre className="source-text">{text}</pre>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
