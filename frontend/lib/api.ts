/**
 * Backend client.
 *
 * Milestone 1 scope: readiness only. The question/answer contract in technical
 * PRD section 7.1 arrives with milestone 4; nothing here anticipates its shape.
 */

export type Health = {
  status: string;
  service_version: string;
  corpus_version: string | null;
  providers_configured: {
    pinecone: boolean;
    openrouter: boolean;
  };
};

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function apiBaseUrl(): string {
  return BASE;
}

/** Resolves to the parsed body, or throws with a message safe to show a user. */
export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/api/health`, { signal, cache: "no-store" });
  } catch {
    // A network-level failure. The backend may simply not be running locally.
    throw new Error(`Could not reach the backend at ${BASE}`);
  }
  if (!response.ok) {
    throw new Error(`Backend returned HTTP ${response.status}`);
  }
  return (await response.json()) as Health;
}
