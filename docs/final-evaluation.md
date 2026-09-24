# Final evaluation — held-out test split (final-v1)

**Run once on 2026-09-24**, under the frozen configuration
[`evaluation/configs/final-v1.json`](../evaluation/configs/final-v1.json),
committed and pushed (`03fb97b`) before any test question was run. The
runners refused the test split unless every setting matched the frozen values
and the working tree was clean, and they refuse to run it again.

| Record | Path |
|---|---|
| Retrieval, both methods | [`retrieval-test-20260924T200218Z.json`](../evaluation/results/retrieval-test-20260924T200218Z.json) |
| End-to-end answers | [`answers-test-nemotron-3-super-120b-a12b-free-20260924T202739Z.json`](../evaluation/results/answers-test-nemotron-3-super-120b-a12b-free-20260924T202739Z.json) |
| Per-question detail and claim verdicts | `evaluation/runs/…` (untracked: they contain reference answers) |

**Scope of every number below:** 50 held-out BioASQ questions (25 fact, 25
list), a controlled collection of 3,653 PubMed titles and abstracts, and one
pinned free model. These are measurements of a research prototype. **They
establish nothing about clinical usefulness or safety**, and no clinician or
domain expert reviewed the answers.

## Summary

| | Target | Result | |
|---|---|---:|:---:|
| **Hard gates** (software correctness) | all hold | all hold | ✅ |
| Answered | ≥ 70% | **88%** (44/50) | ✅ |
| Service unavailable | ≤ 25% | **8%** (4/50) | ✅ |
| Fact strict accuracy (all attempted) | ≥ 0.35 | **0.40** | ✅ |
| List F1 (all attempted) | ≥ 0.25 | **0.53** | ✅ |
| Claims supported by their quotes | ≥ 85% | **85.6%** (89/104) | ✅ narrowly |
| **Claims unsupported** | ≤ 5% | **5.8%** (6/104) | ❌ **missed** |
| End-to-end latency, p50 | ≤ 45s | **20.9s** | ✅ |
| Retrieval Recall@10, BM25 / vector | ≥ 0.55 each | **0.703 / 0.665** | ✅ |
| Retrieval MRR@10, BM25 / vector | ≥ 0.70 each | **0.857 / 0.828** | ✅ |

**Nine of ten quality targets were met and one was missed:** 6 of 104
claims went beyond their quoted evidence. The system is reported as an
**evaluated prototype with that limitation**. The miss stands; tuning after
seeing test results would need a new, separately identified evaluation cycle
with new held-out data.

## 1. Software correctness (hard gates, technical PRD 9.3)

Checked independently of the producing code by
[`scripts/evaluation/check_gates.py`](../scripts/evaluation/check_gates.py):

| Gate | Result |
|---|---|
| Complete accounting: every held-out question has a result | ✅ 50 of 50 |
| Distinct outcomes: exactly one of the five per response | ✅ |
| No unknown-source citations | ✅ 357 citations checked |
| Displayed excerpts match the stored source at their offsets | ✅ 105 excerpts checked |
| No answer-key leakage | ✅ only the question text reaches retrieval and generation; the application never imports the benchmark package (enforced by a test) |

## 2. Retrieval (both methods, no generation)

| Test, n=50 | BM25 | Vector |
|---|---:|---:|
| Recall@5 | 0.521 | 0.501 |
| Recall@10 | 0.703 | 0.665 |
| MRR@10 | 0.857 | 0.828 |
| A relevant paper in the top 10 | 50/50 | 50/50 |
| Latency p50 | 3 ms | about 185 ms |

| By type | Recall@10 BM25 | Recall@10 Vector | MRR@10 BM25 | MRR@10 Vector |
|---|---:|---:|---:|---:|
| Fact (25) | 0.694 | 0.616 | 0.847 | 0.805 |
| List (25) | 0.713 | 0.714 | 0.867 | 0.851 |

Both methods did somewhat better than in development (0.639 / 0.652). As in
development, **no claim is made that either method is better**: the gap on 50
questions is within the paired intervals measured in development (±0.04). The
collection deliberately contains every reference paper, so these figures
measure ranking inside a controlled collection, not discovery across PubMed.

## 3. End-to-end answers (BM25 retrieval, prompt 2, 4 attempts / 2 retries)

| Outcome | Fact (25) | List (25) | All (50) |
|---|---:|---:|---:|
| Answered | 21 | 23 | 44 |
| Insufficient evidence | 1 | 1 | 2 |
| Service unavailable | 3 | 1 | 4 |

| Score | All attempted | Answered only |
|---|---:|---:|
| Fact strict accuracy | **0.40** | 0.48 |
| List precision / recall / F1 | 0.62 / 0.51 / **0.53** | F1 0.58 |

- **Denominators include every attempted question.** The 4 service-unavailable
  outcomes (2 timeouts, 1 provider overload, 1 answer rejected by citation
  validation on every attempt) and the 2 abstentions score zero, so failures
  cannot improve a result.
- **Fact accuracy matched development** (0.40–0.44 across three runs).
- **List F1 was well above development** (0.27–0.35). This probably reflects
  the particular 25 held-out list questions (several have short, closed
  answer sets, such as the four histological types of lung cancer) rather
  than any change. A single run of 25 questions is not evidence of better
  list answering.
- **Exact-match scoring undercounts.** Synonyms and format differences score
  as wrong, as documented in development. Normalization v1 was frozen and
  not changed after seeing answers.

### Claim support: 104 claims in the 44 answered responses

Rubric as in development. **Reviewer: Claude (AI model) acting as the
developer reviewer; not expert-validated.**

| Verdict | Claims | |
|---|---:|---:|
| Supported | 89 | 85.6% |
| Unclear | 9 | 8.7% |
| Unsupported | 6 | 5.8% |

The six unsupported claims:

1. **Four in one answer:** anti-hepcidin "is indicated for" four anaemias.
   The sources call it a *potential* therapeutic and a *candidate*. **The
   answer turned investigational use into an indication.** This is the most
   consequential failure in the evaluation.
2. **An inference absent from the quote:** "imbalance leads to elevated free
   IL-18".
3. **An empty quote:** a claim that the AsCNAR algorithm detects UPD cites
   the quote *"The performance of the new algorithm, called"*. The quote is
   genuine source text, long enough to pass validation, and supports nothing.

Unclear claims were mostly thin quotes: the subject resolved only as "It" or
"them", only drug names given without the trial, a claim about keto-acid
analogues stated as one about the amino acids, or a scope word added
("for lipidomics").

**What this means:** citation validation guarantees that every quote is
genuine and every source is real (the hard gates). It **does not guarantee
that a claim says only what its quote says**. About 1 claim in 17 overstated
its evidence. Readers must check the highlighted quote, which is why the
interface shows it next to every answer.

## 4. Operations

| | Test run |
|---|---|
| Provider attempts | 123, **$0** (the free model; this project's key has recorded no spend) |
| Provider failures | 18 attempts (10 overloaded, 8 timeouts); 3 questions ended unanswered for provider reasons |
| Validation rejections | 9 attempts in 7 questions: the retry with feedback recovered 4; 3 ended unanswered (1 by validation alone, 2 with provider errors as well) |
| End-to-end latency | p50 20.9s; max 92.7s (the 90s deadline plus overhead) |

## 5. Known limitations

- **One free model.** Its outputs vary between runs even at temperature 0;
  development saw list F1 vary by about 0.08 with identical settings. A single
  held-out run carries that uncertainty.
- **Provider reliability.** The free endpoint was overloaded or slow on 15% of
  attempts here, and on up to 49% in development. The demo reports "service
  unavailable" rather than guessing.
- **Controlled collection.** It contains every reference paper; results do
  not transfer to open-ended PubMed search.
- **BioASQ labels are incomplete**, and exact match undercounts correct
  answers.
- **The claim review was done by an AI reviewer**, not a domain expert.
- **No clinical validation.** This is not medical advice.

## Development versus test

| | Development (3 runs, same settings) | Test (1 run) |
|---|---|---|
| Answered of 50 | 37–40 | 44 |
| Fact accuracy | 0.40–0.44 | 0.40 |
| List F1 | 0.27–0.35 | 0.53 |
| Claims supported / unsupported | 90% / 1% (one run, 87 claims) | 85.6% / 5.8% |
| Retrieval Recall@10, BM25 / vector | 0.639 / 0.652 | 0.703 / 0.665 |

The largest change between development and test is in claim support, which
got worse, and that is the target that was missed.
