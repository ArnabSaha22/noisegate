import { FormEvent, KeyboardEvent, useRef, useState } from "react";

export function Composer({
  onSend,
  onStop,
  streaming,
}: {
  onSend: (q: string) => void;
  onStop: () => void;
  streaming: boolean;
}) {
  const [value, setValue] = useState("");
  const areaRef = useRef<HTMLTextAreaElement | null>(null);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = value.trim();
    if (!q || streaming) return;
    onSend(q);
    setValue("");
    if (areaRef.current) areaRef.current.style.height = "auto";
  };

  // Enter sends, Shift+Enter makes a newline -- the convention people expect
  // from a chat box rather than a form field.
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const grow = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        ref={areaRef}
        rows={1}
        value={value}
        placeholder="Ask about the documentation…"
        onChange={(e) => {
          setValue(e.target.value);
          grow(e.target);
        }}
        onKeyDown={onKeyDown}
        disabled={streaming}
      />

      {streaming ? (
        <button type="button" className="stop" onClick={onStop}>
          Stop
        </button>
      ) : (
        <button type="submit" className="send" disabled={!value.trim()}>
          Send
        </button>
      )}
    </form>
  );
}
