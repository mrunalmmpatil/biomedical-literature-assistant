"use client";

import { useState } from "react";
import type { AnswerResponse, Excerpt, Source } from "@/lib/api";
import styles from "./page.module.css";

export const OUTCOME_TITLES: Record<AnswerResponse["outcome"], string> = {
  answered: "Answer",
  needs_clarification: "More detail needed",
  insufficient_evidence: "Not enough evidence",
  unsupported_request: "Outside what this assistant answers",
  service_unavailable: "Service unavailable",
};

export function AnswerView({ result }: { result: AnswerResponse }) {
  // A conversation shows several responses at once; their element IDs must not collide.
  const prefix = `r-${result.request_id}`;
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const numbers = new Map(result.sources.map((s, i) => [s.source_id, i + 1]));
  const cite = (ids: string[]) =>
    ids
      .filter((id) => numbers.has(id))
      .map((id) => (
        <a
          key={id}
          href={`#${prefix}-source-${id}`}
          className={styles.cite}
          onClick={(e) => {
            // Sources start collapsed; open them before jumping to the cited one.
            e.preventDefault();
            setSourcesOpen(true);
            requestAnimationFrame(() => {
              const target = document.getElementById(`${prefix}-source-${id}`);
              target?.scrollIntoView({ block: "center" });
              target?.focus();
            });
          }}
        >
          [{numbers.get(id)}]
        </a>
      ));

  const tone =
    result.outcome === "answered"
      ? styles.good
      : result.outcome === "service_unavailable"
        ? styles.bad
        : styles.neutral;

  return (
    <section className={styles.result} aria-labelledby={`${prefix}-heading`}>
      <div className={`${styles.card} ${tone}`}>
        <h2 id={`${prefix}-heading`} className={styles.resultTitle}>
          {OUTCOME_TITLES[result.outcome]}
        </h2>

        {result.answer ? (
          <>
            <ul className={styles.items}>
              {result.answer.items.map((item, i) => (
                <li key={i}>
                  <strong>{item.text}</strong> {cite(item.source_ids)}
                </li>
              ))}
            </ul>
            {result.answer.explanation_claims.length > 0 && (
              <div className={styles.explanation}>
                <h3 className={styles.subheading}>Why</h3>
                <ul>
                  {result.answer.explanation_claims.map((claim, i) => (
                    <li key={i}>
                      {claim.text} {cite(claim.source_ids)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.answer.qualifications.length > 0 && (
              <div className={styles.qualifications}>
                <h3 className={styles.subheading}>Caveats reported by the sources</h3>
                <ul>
                  {result.answer.qualifications.map((q, i) => (
                    <li key={i}>{q}</li>
                  ))}
                </ul>
              </div>
            )}
            <p className={styles.muted}>{result.message}</p>
          </>
        ) : (
          <>
            <p>{result.message}</p>
            {result.outcome === "insufficient_evidence" && (
              <p className={styles.muted}>
                The papers in this collection report research findings about specific genes,
                proteins, drugs, and diseases, so they rarely define general textbook terms.
                Questions about those specific subjects work best.
              </p>
            )}
          </>
        )}
      </div>

      {result.sources.length > 0 && (
        <details
          className={styles.sources}
          open={sourcesOpen}
          onToggle={(e) => setSourcesOpen(e.currentTarget.open)}
        >
          <summary className={styles.sourcesSummary}>
            Sources ({result.sources.length})
          </summary>
          <p className={styles.muted}>
            The papers retrieved for this question, in retrieval order. Highlighted text is
            what the answer quotes; it was checked word-for-word against the stored abstract.
          </p>
          <ol className={styles.sourceList}>
            {result.sources.map((source, i) => (
              <SourceCard
                key={source.source_id}
                source={source}
                number={i + 1}
                id={`${prefix}-source-${source.source_id}`}
              />
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}

function SourceCard({ source, number, id }: { source: Source; number: number; id: string }) {
  const [open, setOpen] = useState(false);
  const abstractId = `${id}-abstract`;
  const meta = [source.journal, source.year].filter(Boolean).join(" · ");

  return (
    <li id={id} tabIndex={-1} className={styles.source}>
      <p className={styles.sourceTitle}>
        <span className={styles.sourceNumber}>[{number}]</span> {source.title}
      </p>
      <p className={styles.muted}>
        {meta && <>{meta} · </>}PMID {source.pmid}
        {source.source_status !== "none_reported" && (
          <span className={styles.notice}>
            {" "}
            · PubMed notice: {source.source_status.replaceAll("_", " ")}
          </span>
        )}
      </p>
      {source.excerpts.map((e, i) => (
        <blockquote key={i} className={styles.excerpt}>
          “{e.text}”
        </blockquote>
      ))}
      <div className={styles.sourceActions}>
        <button
          type="button"
          className={styles.linkButton}
          aria-expanded={open}
          aria-controls={abstractId}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "Hide abstract" : "Show abstract"}
        </button>
        <a href={source.url} target="_blank" rel="noopener noreferrer" className={styles.link}>
          Open on PubMed ↗
        </a>
      </div>
      {open && (
        <p id={abstractId} className={styles.abstract}>
          <Highlighted text={source.abstract} excerpts={source.excerpts} />
        </p>
      )}
    </li>
  );
}

/** The abstract with quoted spans marked, using server-verified offsets. */
function Highlighted({ text, excerpts }: { text: string; excerpts: Excerpt[] }) {
  const spans = excerpts
    .filter((e) => e.field === "abstract" && text.slice(e.start, e.end) === e.text)
    .sort((a, b) => a.start - b.start);
  const parts: React.ReactNode[] = [];
  let at = 0;
  for (const span of spans) {
    if (span.start < at) continue; // overlapping quote: already marked
    parts.push(text.slice(at, span.start));
    parts.push(<mark key={span.start}>{text.slice(span.start, span.end)}</mark>);
    at = span.end;
  }
  parts.push(text.slice(at));
  return <>{parts}</>;
}
