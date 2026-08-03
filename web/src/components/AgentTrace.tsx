export interface TraceStep {
  node: string;
  status: string;
  plan: string[];
}

const LABELS: Record<string, string> = {
  planner: "Planner",
  retriever: "Retriever",
  responder: "Responder",
  cache: "Semantic cache",
};

/**
 * Live view of the agent's decisions.
 *
 * This is the thing the Streamlit UI could not do. It rendered thought_process
 * only after the whole request finished, so the agent's routing was invisible
 * while it mattered. Here each node appears the moment it completes.
 */
export function AgentTrace({ steps, live }: { steps: TraceStep[]; live: boolean }) {
  return (
    <div className="panel trace">
      <h2>
        Agent trace
        {live && <span className="pulse" aria-label="running" />}
      </h2>

      <ol className="trace-list">
        {steps.map((s, i) => (
          <li key={i}>
            <div className="trace-node">{LABELS[s.node] ?? s.node}</div>
            {s.status && <div className="trace-status">{s.status}</div>}
            {s.plan?.length > 0 && (
              <ul className="trace-plan">
                {s.plan.map((p, j) => (
                  <li key={j}>{p}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
