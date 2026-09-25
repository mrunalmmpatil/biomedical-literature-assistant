/**
 * Backend client. Types mirror the response contract in technical PRD 7.1
 * (backend/bla/contracts.py). Nothing here receives reference answers,
 * prompts, provider errors, or credentials: the backend never sends them.
 */

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8010";

export function apiBaseUrl(): string {
  return BASE;
}

export type Outcome =
  | "answered"
  | "needs_clarification"
  | "insufficient_evidence"
  | "unsupported_request"
  | "service_unavailable";

export type Excerpt = { field: "title" | "abstract"; start: number; end: number; text: string };

export type Source = {
  source_id: string;
  pmid: string;
  title: string;
  url: string;
  abstract: string;
  journal: string | null;
  year: number | null;
  source_status: "none_reported" | "corrected" | "expression_of_concern" | "retracted";
  retrieval_rank: number;
  excerpts: Excerpt[];
};

export type AnswerResponse = {
  request_id: string;
  outcome: Outcome;
  message: string;
  answer: {
    items: { text: string; source_ids: string[] }[];
    explanation_claims: { text: string; source_ids: string[] }[];
    qualifications: string[];
  } | null;
  sources: Source[];
  clarification: { question: string; token: string } | null;
  corpus_version: string | null;
  /** For a follow-up: the standalone question actually searched and answered. */
  interpreted_question?: string | null;
  /** Present when a follow-up question may be asked about this response. */
  followup_token?: string | null;
};

export type Coverage = {
  scope: string;
  collection: string;
  snapshot_date: string;
  not_supported: string[];
  limits: { questions_per_hour: number; question_characters: number };
};

/** A failure the page can show as-is. Messages never contain server internals. */
export class AskError extends Error {
  constructor(
    message: string,
    /** The HTTP status, when the service answered at all. */
    readonly status?: number,
  ) {
    super(message);
  }
}

export type AskInput = {
  question: string;
  clarification?: { token: string; answer: string };
  /** Asks about the earlier response that issued this token. */
  followupToken?: string;
};

export async function ask(input: AskInput, signal?: AbortSignal): Promise<AnswerResponse> {
  const body = {
    question: input.question,
    clarification_token: input.clarification?.token ?? null,
    clarification_answer: input.clarification?.answer ?? null,
    followup_token: input.followupToken ?? null,
    // One key per submission: a repeated click on the same submission is
    // answered once by the backend (technical PRD 8.2).
    request_key: crypto.randomUUID(),
  };
  let response: Response;
  try {
    response = await fetch(`${BASE}/api/answer`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch {
    throw new AskError("Could not reach the answer service. Check your connection and try again.");
  }

  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    // fall through to the status-based message
  }
  if (response.ok) return data as AnswerResponse;

  const message =
    (data as { message?: string; detail?: unknown })?.message ??
    (typeof (data as { detail?: unknown })?.detail === "string"
      ? (data as { detail: string }).detail
      : null);
  if (response.status === 422) {
    throw new AskError(
      "The question could not be accepted. Please shorten or rephrase it.",
      422,
    );
  }
  // 503/504 from the answer service still carry a typed outcome body.
  if ((response.status === 503 || response.status === 504) && data && (data as AnswerResponse).request_id) {
    return data as AnswerResponse;
  }
  throw new AskError(
    message ?? `The answer service returned an error (HTTP ${response.status}).`,
    response.status,
  );
}

export async function fetchCoverage(signal?: AbortSignal): Promise<Coverage> {
  const response = await fetch(`${BASE}/api/coverage`, { signal, cache: "no-store" });
  if (!response.ok) throw new AskError(`HTTP ${response.status}`);
  return (await response.json()) as Coverage;
}
