"use client";

import { useEffect, useState } from "react";
import { apiBaseUrl, fetchHealth, type Health } from "@/lib/api";
import styles from "./page.module.css";

type State =
  | { phase: "loading" }
  | { phase: "ok"; health: Health }
  | { phase: "error"; message: string };

/** Never throws; always settles to a displayable state. */
async function probe(signal?: AbortSignal): Promise<State> {
  try {
    return { phase: "ok", health: await fetchHealth(signal) };
  } catch (error) {
    return {
      phase: "error",
      message: error instanceof Error ? error.message : "Unknown error",
    };
  }
}

export default function Page() {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    probe(controller.signal).then((next) => {
      if (!controller.signal.aborted) setState(next);
    });
    return () => controller.abort();
  }, []);

  const recheck = () => {
    setState({ phase: "loading" });
    probe().then(setState);
  };

  return (
    <main className={styles.main}>
      <p className={styles.eyebrow}>Milestone 1 · service compatibility</p>
      <h1 className={styles.title}>Biomedical Literature Assistant</h1>
      <p className={styles.lead}>
        This page exists to prove the frontend can reach the Python backend. The
        question-and-answer interface is milestone 5.
      </p>

      <section className={styles.card} aria-labelledby="status-heading">
        <div className={styles.cardHead}>
          <h2 id="status-heading">Backend status</h2>
          <button className={styles.button} onClick={recheck}>
            Re-check
          </button>
        </div>

        <p className={styles.target}>
          <span>Target</span>
          <code>{apiBaseUrl()}/api/health</code>
        </p>

        <div aria-live="polite">
          {state.phase === "loading" && <p className={styles.muted}>Checking…</p>}

          {state.phase === "error" && (
            <div className={styles.bad}>
              <strong>Not reachable.</strong>
              <p>{state.message}</p>
              <p className={styles.muted}>
                Start it with <code>uv run uvicorn app:app --port 8010</code> in{" "}
                <code>backend/</code>.
              </p>
            </div>
          )}

          {state.phase === "ok" && (
            <div className={styles.good}>
              <strong>Reachable.</strong>
              <dl className={styles.facts}>
                <dt>Service version</dt>
                <dd>{state.health.service_version}</dd>
                <dt>Corpus version</dt>
                <dd>{state.health.corpus_version ?? "none frozen yet"}</dd>
                <dt>Pinecone configured</dt>
                <dd>{state.health.providers_configured.pinecone ? "yes" : "no"}</dd>
                <dt>OpenRouter configured</dt>
                <dd>{state.health.providers_configured.openrouter ? "yes" : "no"}</dd>
              </dl>
              <p className={styles.muted}>
                &ldquo;Configured&rdquo; means a key is present, not that the provider
                has been called.
              </p>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
