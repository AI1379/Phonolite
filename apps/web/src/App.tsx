import { useEffect, useState } from "react";

/** Unified tool-result envelope (design doc section 8.4). */
interface Envelope<T> {
  ok: boolean;
  result: T;
  warnings: string[];
  artifacts: string[];
  provenance: { tool: string; version: string; inputs: string[] };
}

interface HealthResult {
  service: string;
  version: string;
  music_core_version: string;
}

function App() {
  const [health, setHealth] = useState<Envelope<HealthResult> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((resp) => {
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return resp.json() as Promise<Envelope<HealthResult>>;
      })
      .then(setHealth)
      .catch((err: unknown) => setError(String(err)));
  }, []);

  return (
    <main className="app">
      <h1>Music Agent Workbench</h1>
      <p className="subtitle">Composition IDE — first vertical slice scaffold</p>
      <section className="panel">
        <h2>Server health</h2>
        {error && <p className="error">Cannot reach server: {error}</p>}
        {!error && !health && <p>Loading…</p>}
        {health && (
          <dl>
            <dt>Status</dt>
            <dd>{health.ok ? "ok" : "failed"}</dd>
            <dt>Service</dt>
            <dd>
              {health.result.service} v{health.result.version}
            </dd>
            <dt>music-core</dt>
            <dd>v{health.result.music_core_version}</dd>
          </dl>
        )}
      </section>
    </main>
  );
}

export default App;
