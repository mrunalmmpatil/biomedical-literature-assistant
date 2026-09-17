# Biomedical Literature Assistant — MVP

## Problem Statement

Biomedical researchers answering a literature question must find relevant papers, read their abstracts, and piece together the findings. This takes time, particularly when studies use different terminology or report different results.

A generated summary is useful only if researchers can verify its claims. Missing relevant studies, overlooking limitations, or presenting unsupported conclusions can make a quick answer misleading.

Researchers need a way to get an initial answer, inspect the evidence behind it, and recognize when the available literature is insufficient to answer their question.

## Solution

Build a web-based biomedical literature assistant that answers research questions using published abstracts. A researcher asks a question in plain language and receives a focused answer with citations and the supporting abstracts available for inspection.

The assistant preserves important study context and limitations, acknowledges conflicting findings, and explains when the available evidence cannot support an answer. Its answers are limited to the indexed abstracts; it does not claim to have reviewed the full papers or all biomedical literature.

Use BioASQ fact and list questions to define and evaluate the initial scope. Begin with 100 eligible questions, split equally between development and final testing. Select subject coverage based on suitable questions and reference evidence rather than committing to a specialty in advance. Measure the ability to find relevant papers separately from the quality of the generated answers.

## User Stories

1. As a biomedical researcher, I want to ask a question in plain language, so that I can explore the literature without constructing a complex search query.
2. As a biomedical researcher, I want to understand the topics and publications covered, so that I know whether the assistant is suitable for my question.
3. As a biomedical researcher, I want to see example questions, so that I can understand how to use the assistant.
4. As a biomedical researcher, I want relevant papers found even when they use different terminology, so that I can discover evidence I might otherwise miss.
5. As a biomedical researcher, I want a focused answer to my question, so that I can understand the main findings before reading individual papers.
6. As a biomedical researcher, I want factual claims connected to citations, so that I can verify where the information came from.
7. As a biomedical researcher, I want to inspect the text supporting a claim, so that I can judge whether the interpretation is justified.
8. As a biomedical researcher, I want to see paper titles and available publication details, so that I can identify and locate the original studies.
9. As a biomedical researcher, I want access to the retrieved abstracts, so that I can explore the evidence beyond the summary.
10. As a biomedical researcher, I want relevant study populations and outcomes preserved in the answer, so that I understand where the findings apply.
11. As a biomedical researcher, I want limitations and uncertainty reflected in the answer, so that tentative findings are not presented as established conclusions.
12. As a biomedical researcher, I want disagreements between studies acknowledged, so that I can recognize when the evidence is unsettled.
13. As a biomedical researcher, I want missing details identified as unavailable, so that I do not mistake an assumption for a reported finding.
14. As a biomedical researcher, I want a clear response when evidence is insufficient, so that I know when further investigation is needed.
15. As a biomedical researcher, I want to know that answers are based on abstracts, so that I understand the limits of the summary.
16. As a biomedical researcher, I want a lack of results distinguished from a claim that no evidence exists, so that limited collection coverage does not mislead me.
17. As a user, I want visible progress while my question is processed, so that I know the request is underway.
18. As a user, I want a clear explanation when the service is unavailable, so that I know whether to try again later.
19. As the project author, I want retrieval and answer quality evaluated separately, so that I can identify what needs improvement.
20. As the project author, I want comparisons against a baseline and examples of failures, so that I can demonstrate the system's strengths and limitations.
21. As the project author, I want the project to operate without paid services, so that I can maintain it within my budget.
22. As an AI/ML hiring reviewer, I want a working demonstration and an understandable evaluation report, so that I can assess the project beyond its interface.

## Implementation Decisions

- Deliver a web-based question-answering experience with a direct answer, a brief cited explanation, and an inspectable evidence list.
- Support one research question at a time. Ask one clarifying question when needed; follow-up conversations are deferred.
- Use retrieval-augmented generation: find relevant abstracts first, then generate an answer from that evidence.
- Use abstracts only in the initial version. Full-text papers are deferred.
- Build a mixed collection of supporting abstracts and other papers on related topics. Collection size is determined during implementation; no biomedical specialty has been selected.
- Include citations that let users trace claims to their sources. A citation must identify supporting evidence, not simply a related paper.
- Explain insufficient evidence and service failures as separate outcomes.
- Keep the project within a zero-paid-usage budget.
- Document the detailed architecture, service choices, models, and operating limits separately in the technical PRD.

## Testing Decisions

- Test the complete user workflow: ask a question, receive an answer or a clear explanation, and inspect the cited evidence.
- Evaluate whether relevant papers are found separately from whether the answer is correct and supported.
- Use an existing biomedical benchmark with reference questions and evidence suitable for abstract-based answers.
- Compare retrieval against a baseline using the same questions and literature collection.
- Reserve evaluation questions that are not used while improving the system.
- Check that citations identify the correct papers and that cited text supports the associated claims.
- Cover insufficient evidence, missing information, conflicting findings, invalid input, and service unavailability.
- Test observable behavior rather than internal implementation choices or exact answer wording.
- Report representative failures and the limits of the evaluation. Benchmark results do not establish clinical reliability or usefulness to researchers without further validation.
- There are no existing application tests to reuse. The proposed primary testing boundary is the complete question-to-result workflow, with retrieved papers available for separate evaluation.

## Out of Scope

- Full-text PDF processing, scanned documents, figures, and tables.
- Patient-specific medical advice, diagnosis, or treatment recommendations.
- Hospital-record analysis, clinical dataset querying, and reporting automation.
- Automated systematic reviews, meta-analyses, or publication-ready review writing.
- Comprehensive coverage of all biomedical literature or guaranteed access to the latest publications.
- User accounts, collaboration, document uploads, and saved conversation history in the initial version.
- Paid services and automatic upgrades to paid plans.

## Further Notes

### Project priorities

1. Demonstrate AI/ML engineering capability in a portfolio.
2. Provide a useful starting point for biomedical researchers.
3. Develop practical experience with retrieval-augmented generation and evaluation.

Researcher usefulness remains to be validated. No expert contact or user study has been established yet.

### Milestones

1. Select a suitable benchmark and define the initial literature coverage.
2. Complete the technical PRD.
3. Establish and evaluate literature retrieval.
4. Add answers with citations and assess their quality.
5. Deliver the web interface and verify the complete user workflow.
6. Prepare the demonstration, evaluation report, and documentation.

### Acceptance criteria

- A user can submit an in-scope research question and receive a focused answer with citations.
- The user can inspect the cited abstracts and locate the original papers.
- The interface clearly identifies the abstract-only evidence scope.
- Insufficient evidence and service failures produce understandable responses.
- Retrieval and answer quality have separate documented evaluation results.
- The evaluation includes a baseline comparison, failure examples, and coverage limitations.
- A shareable demonstration and setup documentation are available.
- The project operates within the agreed free-service constraint.

### Open product decisions

- Final topic coverage and approach to collecting researcher feedback.
- Measurable quality targets for the selected task.
- Timeline.
