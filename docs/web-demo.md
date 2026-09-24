# Milestone 5 — Web demo

Status: **deployed 2026-09-24.**

| | URL |
|---|---|
| Website | https://bla-frontend-gilt.vercel.app |
| Backend | https://bla-backend.vercel.app (`/api/health`, `/api/coverage`, `POST /api/answer`) |

## What a visitor can do

- Ask a focused biomedical fact or list question, and read the answer with
  numbered citations [1] [2] that link to the sources.
- Answer **one** clarification question when the question is missing a
  material detail. The original question is carried by a signed 10-minute
  token, and there is no second round.
- Inspect every source: title, journal, year, and PMID; any PubMed notice
  (corrected, expression of concern); the quoted sentences; an expandable
  abstract with the quoted spans highlighted; and a link to PubMed.
- See plain outcomes when there is no answer: not enough evidence, outside
  scope, or service unavailable.
- Read the collection's scope (abstracts only, a fixed collection, not all of
  PubMed) and the fact that this is a research prototype, not medical advice.

## Public-demo protections (technical PRD 8.1–8.2)

Shared state lives in **Upstash Redis** (free plan, via the Vercel
integration). Every serverless instance sees the same counters.

| Control | Setting | Response when exceeded |
|---|---|---|
| Questions per visitor | 5 per hour, keyed by a salted hash of the network address that rotates daily | 429 with a plain message; no provider request is sent |
| Site-wide provider attempts | 300 per UTC day, of the account's 1,000 free; counted before each dispatch | 429, "daily question limit" |
| Repeated submissions | One request key per submission; a duplicate while running is refused, and a finished one is replayed for 10 minutes | 409, or the stored result |
| Quota store unreachable | Generation fails closed | 503 |
| Provider failures | 4 attempts, 2 retries, 45s per request, 90s per question | 503 / 504 with a plain message |

The store holds counters and short-lived request records only: no question
text, no IP addresses, no accounts.

## The collection on the server

The backend deployment bundles the frozen collection
(`bioasq14b-v1`, 3,653 papers, SHA-256 `3652a06b…deea9`) as a read-only
file, which is not committed to git. It loads and builds the BM25 index in
about 0.7s on a cold start. The demo uses **BM25**, which tied with vector
search in Milestone 3, costs nothing per query, and was the retrieval used
for all answer development.

## Verified in a real browser (headless Chrome, 2026-09-24)

Locally and on the deployed site:

- A real question returned an answer with 5 sources and 3 verified quotes.
- **A double click sent one request.**
- Keyboard: "Show abstract" opens with Enter; `aria-expanded` is set, and the
  quote is highlighted inside the abstract.
- A citation link jumps to its source card.
- Clarification: "What is the recommended starting dose?" asked which drug;
  the follow-up ended in "not enough evidence", with no second clarification.
- Personal medical advice was declined.
- **Phone width (390px): no horizontal scrolling.**
- **The 6th request in an hour from one visitor got HTTP 429** with a plain
  message, before any provider call.
- The CORS preflight from the website's origin is allowed.

## Known limitations

- The free model is sometimes overloaded or slow. The demo then says the
  service is unavailable instead of guessing.
- Answers take about 10–60 seconds, and there is no streaming, so answers are
  validated before they are shown.
- A refresh clears the page. There is no saved history, by design.
