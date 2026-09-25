"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ask,
  AskError,
  fetchCoverage,
  type AnswerResponse,
  type AskInput,
  type Coverage,
} from "@/lib/api";
import { AnswerView, OUTCOME_TITLES } from "./answer-view";
import styles from "./page.module.css";

const MAX_QUESTION = 2000;
const MAX_CLARIFICATION = 1000;
const MAX_COMPOSER_HEIGHT = 200; // px; the box scrolls beyond this

/** Development-split questions the collection covers (never held-out ones). */
const EXAMPLES = [
  "Which kinases phosphorylate the protein Bora?",
  "Which molecule is targeted by daratumumab?",
  "Which are the subunits of the IkB protein kinase (IKK)?",
];

/**
 * The collection's subject areas, grouped by hand from the 100 BioASQ questions the
 * papers were gathered around. Update this if the collection changes.
 */
const FIELDS: [string, string][] = [
  [
    "Cancer and oncology",
    "brain tumours (glioma, glioblastoma), lung cancer types, melanoma, myeloma, cancer drugs and their targets (HER2, EGFR, KIT), tumour-suppressor genes",
  ],
  [
    "Molecular and cell biology",
    "enzymes, signalling pathways (NF-κB), histone modifications and enhancers, RNA processing, protein complexes, cell division",
  ],
  [
    "Inherited and rare diseases",
    "genetic syndromes and their genes: Duchenne muscular dystrophy, Ehlers-Danlos, Friedreich's ataxia, Charcot-Marie-Tooth, spinal muscular atrophy",
  ],
  [
    "Infection, immunity and vaccines",
    "Klebsiella infections, measles and influenza vaccines, malaria antibodies, lupus, viroids",
  ],
  [
    "Heart and cardiovascular",
    "inherited cardiomyopathies and arrhythmias, calcium handling in heart muscle, cardiac MRI, BNP",
  ],
  [
    "Brain and nervous system",
    "epileptic encephalopathies, prosopagnosia, chemotherapy-induced neuropathy, neurotransmitter metabolism",
  ],
  [
    "Drugs, antibodies and side effects",
    "monoclonal antibodies (dupilumab, teprotumumab), statin side effects, warfarin pharmacogenetics, progesterone-only contraception",
  ],
  [
    "Genomics, bioinformatics and lab methods",
    "genome facts (yeast, C. elegans, X chromosome), R/Bioconductor packages, mass spectrometry, CRISPR",
  ],
];

/** A message the visitor sent. Nothing is saved: a refresh starts a new chat. */
type Sent = {
  kind: "question" | "followup" | "clarification";
  text: string;
};

/** `payload` is kept so a failed reply can be retried exactly as sent. */
type Turn = Sent & { payload: AskInput; result: AnswerResponse };

export default function Page() {
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sending, setSending] = useState<Sent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [skipClarification, setSkipClarification] = useState(false);
  // Turns before this index no longer give context (their token expired).
  const [contextStart, setContextStart] = useState(0);
  const [announcement, setAnnouncement] = useState("");
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const lastAnswerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchCoverage(controller.signal).then(setCoverage, () => {});
    return () => controller.abort();
  }, []);

  // Grow the message box with its text, up to a limit.
  useLayoutEffect(() => {
    const box = composerRef.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, MAX_COMPOSER_HEIGHT)}px`;
  }, [draft]);

  const last = turns.at(-1);
  const clarification =
    !skipClarification && last?.result.outcome === "needs_clarification"
      ? last.result.clarification
      : null;
  // Context comes from the newest reply that searched the collection, so a
  // failed or off-topic reply in between does not end the conversation.
  const followupToken = clarification
    ? undefined
    : (turns.slice(contextStart).findLast((t) => t.result.followup_token)?.result
        .followup_token ?? undefined);
  const busy = sending !== null;

  function scrollTo(target: HTMLElement | null, block: ScrollLogicalPosition) {
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block });
  }

  function send(text: string) {
    text = text.trim();
    if (!text || busy) return; // duplicate sends do nothing while a request runs
    if (clarification && last) {
      const answer = { token: clarification.token, answer: text };
      void submit({ question: last.text, clarification: answer }, { kind: "clarification", text });
    } else {
      const kind = followupToken ? "followup" : "question";
      void submit({ question: text, followupToken }, { kind, text });
    }
  }

  /** Sends the failed last reply's message again, in place of that reply. */
  function retry() {
    if (!last || busy) return;
    setTurns((t) => t.slice(0, -1));
    void submit(last.payload, { kind: last.kind, text: last.text }, last);
  }

  async function submit(payload: AskInput, sent: Sent, retrying?: Turn) {
    setSending(sent);
    setDraft("");
    setError(null);
    setAnnouncement("Working on your question.");
    requestAnimationFrame(() => scrollTo(endRef.current, "end"));
    try {
      const result = await ask(payload);
      setTurns((t) => [...t, { ...sent, payload, result }]);
      setSkipClarification(false);
      setAnnouncement(`${OUTCOME_TITLES[result.outcome]} received.`);
      // Show the start of the reply; answers can be longer than the screen.
      requestAnimationFrame(() => scrollTo(lastAnswerRef.current, "start"));
    } catch (e) {
      if (retrying) {
        setTurns((t) => [...t, retrying]);
      } else {
        // The message goes back in the box so the visitor can resend without retyping.
        setDraft(sent.text);
      }
      if (e instanceof AskError && e.status === 400 && payload.followupToken) {
        // Only an expired or unreadable token gets a 400 here: drop the old context.
        setContextStart(turns.length);
        setError(
          "The earlier conversation can no longer be used as context (answers can be " +
            "followed up for an hour). Send your message again to ask it as a new question.",
        );
      } else {
        setError(e instanceof AskError ? e.message : "Something went wrong. Please try again.");
      }
      setAnnouncement("");
    } finally {
      setSending(null);
      composerRef.current?.focus();
    }
  }

  function newChat() {
    setTurns([]);
    setDraft("");
    setError(null);
    setSkipClarification(false);
    setContextStart(0);
    composerRef.current?.focus();
  }

  const placeholder = clarification
    ? "Reply to the question above…"
    : followupToken
      ? "Ask a follow-up question…"
      : "Ask a focused biomedical question…";

  return (
    <div className={styles.app}>
      <header className={styles.topbar}>
        <h1 className={styles.brand}>Biomedical Literature Assistant</h1>
        {(turns.length > 0 || busy) && (
          <button type="button" className={styles.newChat} onClick={newChat} disabled={busy}>
            New chat
          </button>
        )}
      </header>

      <main className={styles.chat}>
        {turns.length === 0 && !busy && (
          <Welcome coverage={coverage} onPick={send} />
        )}

        {turns.map((turn, i) => (
          <div key={turn.result.request_id + i} className={styles.exchange}>
            <UserMessage sent={turn} />
            <div ref={i === turns.length - 1 ? lastAnswerRef : undefined}>
              <AssistantMessage
                result={turn.result}
                echo={turn.text}
                onRetry={
                  i === turns.length - 1 && turn.result.outcome === "service_unavailable"
                    ? retry
                    : undefined
                }
              />
            </div>
          </div>
        ))}

        {sending && (
          <div className={styles.exchange}>
            <UserMessage sent={sending} />
            <div className={styles.assistantRow}>
              <Avatar />
              <div className={styles.typing}>
                <span className={styles.dots} aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </span>
                Searching the collection and checking every quote against its source. This
                usually takes 10–60 seconds.
              </div>
            </div>
          </div>
        )}

        {error && !busy && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}

        <p className={styles.srOnly} aria-live="polite">
          {announcement}
        </p>
        <div ref={endRef} />
      </main>

      <div className={styles.composerDock}>
        <form
          className={styles.composer}
          onSubmit={(e) => {
            e.preventDefault();
            send(draft);
          }}
        >
          <label htmlFor="message" className={styles.srOnly}>
            {clarification ? clarification.question : placeholder}
          </label>
          <textarea
            id="message"
            ref={composerRef}
            className={styles.composerInput}
            value={draft}
            rows={1}
            maxLength={clarification ? MAX_CLARIFICATION : MAX_QUESTION}
            placeholder={placeholder}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends; Shift+Enter starts a new line. Never while composing
              // characters with an input method.
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                send(draft);
              }
            }}
            autoFocus
          />
          <button
            type="submit"
            className={styles.send}
            disabled={busy || !draft.trim()}
            aria-label="Send"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path
                d="M12 19V5M5 12l7-7 7 7"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </form>
        <p className={styles.footnote}>
          {clarification ? (
            <>
              One clarification is allowed per question.{" "}
              <button
                type="button"
                className={styles.inlineButton}
                onClick={() => setSkipClarification(true)}
              >
                Ask something else instead
              </button>
            </>
          ) : (
            <>
              Answers come only from a fixed set of PubMed abstracts and can be wrong; check
              the quotes. Not medical advice.
              {coverage && <> Limit: {coverage.limits.questions_per_hour} messages per hour.</>}
            </>
          )}
        </p>
      </div>
    </div>
  );
}

function Welcome({
  coverage,
  onPick,
}: {
  coverage: Coverage | null;
  onPick: (question: string) => void;
}) {
  return (
    <section className={styles.welcome} aria-labelledby="welcome-heading">
      <h2 id="welcome-heading" className={styles.welcomeTitle}>
        What would you like to find in the literature?
      </h2>
      <p className={styles.lead}>
        Ask a focused biomedical question with a specific answer: a gene, drug, protein,
        disease, or a short list of them. Every answer quotes the published abstracts it
        comes from, and you can keep asking follow-up questions.
      </p>
      <div className={styles.examples}>
        {EXAMPLES.map((q) => (
          <button key={q} type="button" className={styles.example} onClick={() => onPick(q)}>
            {q}
          </button>
        ))}
      </div>
      <details className={styles.scope}>
        <summary>What this can and cannot answer</summary>

        <h3 className={styles.scopeHeading}>The data</h3>
        <p>
          A fixed collection of 3,653 published papers from PubMed: titles and abstracts
          only, no full text
          {coverage && <>, as of {coverage.snapshot_date}</>}. Every answer is searched for
          in this collection only. The papers were gathered around 100 questions from the
          BioASQ biomedical benchmark, plus related papers on the same topics, so coverage is
          deepest on those topics.
        </p>

        <h3 className={styles.scopeHeading}>Fields covered</h3>
        <ul className={styles.fields}>
          {FIELDS.map(([field, topics]) => (
            <li key={field}>
              <strong>{field}:</strong> {topics}
            </li>
          ))}
        </ul>
        <p>
          Each field is covered through the specific topics listed: “heart and
          cardiovascular”, for example, focuses on inherited heart conditions and cardiac
          imaging.
        </p>

        <h3 className={styles.scopeHeading}>What it answers</h3>
        <p>
          You can ask any question. It answers when the papers
          state the answer: a specific fact or a short list (a gene, drug, protein, disease,
          method), with the supporting sentences quoted and linked to PubMed. When the papers
          do not support an answer, it says so instead of guessing. Follow-up questions use
          your last ten questions and answers as context.
        </p>

        <h3 className={styles.scopeHeading}>What it does not answer</h3>
        <p>
          {(
            coverage?.not_supported ?? [
              "personal medical advice",
              "yes/no or open-ended summary questions",
              "questions outside biomedicine",
            ]
          ).join("; ")}
          ; and anything the collection does not cover. This is a research prototype, not
          medical advice: answers can be wrong or incomplete even when every quote is genuine.
          Nothing is saved, so refreshing the page starts a new chat.
        </p>
      </details>
    </section>
  );
}

function UserMessage({ sent }: { sent: Sent }) {
  return (
    <div className={styles.userRow}>
      <p className={styles.userBubble}>
        <span className={styles.srOnly}>You: </span>
        {sent.text}
      </p>
    </div>
  );
}

function Avatar() {
  return (
    <span className={styles.avatar} aria-hidden="true">
      BL
    </span>
  );
}

function AssistantMessage({
  result,
  echo,
  onRetry,
}: {
  result: AnswerResponse;
  echo: string;
  onRetry?: () => void;
}) {
  // Shown only when the rewrite changed the words, not just capitals or spacing.
  const normalize = (text: string) => text.toLowerCase().replace(/\s+/g, " ").trim();
  const interpreted =
    result.interpreted_question && normalize(result.interpreted_question) !== normalize(echo)
      ? result.interpreted_question
      : null;
  return (
    <div className={styles.assistantRow}>
      <Avatar />
      <div className={styles.assistantBody}>
        <span className={styles.srOnly}>Assistant: </span>
        {interpreted && (
          <p className={styles.interpreted}>Searched as: “{interpreted}”</p>
        )}
        {result.outcome === "needs_clarification" && result.clarification ? (
          <div className={styles.clarifyMessage}>
            <p>{result.message}</p>
            <p className={styles.clarifyQuestion}>{result.clarification.question}</p>
          </div>
        ) : (
          <AnswerView result={result} />
        )}
        {onRetry && (
          <button type="button" className={styles.retry} onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
