"use client";

import { useEffect, useRef, useState } from "react";
import {
  ask,
  AskError,
  fetchCoverage,
  type AnswerResponse,
  type Coverage,
} from "@/lib/api";
import { AnswerView } from "./answer-view";
import styles from "./page.module.css";

const MAX_QUESTION = 2000;
const MAX_CLARIFICATION = 1000;

type Pending = { question: string; clarification?: { token: string; answer: string } };

export default function Page() {
  const [question, setQuestion] = useState("");
  const [clarificationAnswer, setClarificationAnswer] = useState("");
  const [result, setResult] = useState<AnswerResponse | null>(null);
  const [asked, setAsked] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchCoverage(controller.signal).then(setCoverage, () => {});
    return () => controller.abort();
  }, []);

  async function submit(payload: Pending) {
    if (pending) return; // duplicate clicks do nothing while a request runs
    setPending(true);
    setError(null);
    try {
      const response = await ask(payload);
      setResult(response);
      setAsked(payload.question);
      if (response.outcome !== "needs_clarification") setClarificationAnswer("");
      requestAnimationFrame(() => resultRef.current?.focus());
    } catch (e) {
      // Entered text is kept so the visitor can retry without retyping.
      setError(e instanceof AskError ? e.message : "Something went wrong. Please try again.");
    } finally {
      setPending(false);
    }
  }

  function onAsk(event: React.FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text) return;
    setResult(null);
    void submit({ question: text });
  }

  function onClarify(event: React.FormEvent) {
    event.preventDefault();
    const answer = clarificationAnswer.trim();
    if (!answer || !result?.clarification || !asked) return;
    void submit({
      question: asked,
      clarification: { token: result.clarification.token, answer },
    });
  }

  const needsClarification = result?.outcome === "needs_clarification" && result.clarification;

  return (
    <main className={styles.main}>
      <header className={styles.header}>
        <h1 className={styles.title}>Biomedical Literature Assistant</h1>
        <p className={styles.lead}>
          Ask a focused biomedical question with a specific answer: a gene, drug, protein,
          disease, or a short list of them. Answers come only from published abstracts in
          a fixed collection, with the supporting text quoted.
        </p>
        <details className={styles.scope}>
          <summary>What this can and cannot answer</summary>
          <ul>
            <li>{coverage?.scope ?? "Published PubMed titles and abstracts only; no full text."}</li>
            <li>
              {coverage?.collection ??
                "A fixed collection of PubMed records; it is not a search of all of PubMed."}
            </li>
            <li>
              Not supported:{" "}
              {(coverage?.not_supported ?? ["personal medical advice"]).join("; ")}.
            </li>
            <li>
              This is a research prototype. It is not medical advice, and answers can be
              wrong or incomplete even when every quote is genuine.
            </li>
            {coverage && (
              <li>
                Limit: {coverage.limits.questions_per_hour} questions per hour. Snapshot date:{" "}
                {coverage.snapshot_date}.
              </li>
            )}
          </ul>
        </details>
      </header>

      <form className={styles.form} onSubmit={onAsk}>
        <label htmlFor="question" className={styles.label}>
          Research question
        </label>
        <textarea
          id="question"
          className={styles.textarea}
          value={question}
          maxLength={MAX_QUESTION}
          rows={3}
          placeholder="e.g. Which kinases phosphorylate the protein Bora?"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onAsk(e);
          }}
          disabled={pending}
          aria-describedby="question-hint"
        />
        <div className={styles.formRow}>
          <span id="question-hint" className={styles.hint}>
            {question.length}/{MAX_QUESTION} · Ctrl/⌘ + Enter to ask
          </span>
          <button className={styles.button} type="submit" disabled={pending || !question.trim()}>
            {pending ? "Working…" : "Ask"}
          </button>
        </div>
      </form>

      <div aria-live="polite" className={styles.status}>
        {pending && (
          <p className={styles.pending}>
            Searching the collection and checking every quote against its source. This
            usually takes 10–60 seconds.
          </p>
        )}
        {error && !pending && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
      </div>

      {needsClarification && !pending && (
        <form className={styles.clarify} onSubmit={onClarify}>
          <label htmlFor="clarification" className={styles.label}>
            {result.clarification!.question}
          </label>
          <input
            id="clarification"
            className={styles.input}
            value={clarificationAnswer}
            maxLength={MAX_CLARIFICATION}
            onChange={(e) => setClarificationAnswer(e.target.value)}
            autoFocus
          />
          <div className={styles.formRow}>
            <span className={styles.hint}>One clarification is allowed per question.</span>
            <button
              className={styles.button}
              type="submit"
              disabled={pending || !clarificationAnswer.trim()}
            >
              Continue
            </button>
          </div>
        </form>
      )}

      <div ref={resultRef} tabIndex={-1} className={styles.resultAnchor}>
        {result && !pending && result.outcome !== "needs_clarification" && (
          <AnswerView result={result} />
        )}
      </div>
    </main>
  );
}
