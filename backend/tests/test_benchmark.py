"""Benchmark eligibility, grouping, selection, and split. Question records are
invented in BioASQ's shape; none is drawn from the dataset."""

import pathlib

import pytest

from bla.benchmark.bioasq import (
    BenchmarkQuestion,
    Ineligible,
    QuestionType,
    Reason,
    group,
    normalize,
    pmid_from_url,
)
from bla.benchmark.select import (
    EvidenceReason,
    QuotaNotMet,
    Split,
    candidate_order,
    check_evidence,
    select,
    shared_pmids,
)
from tests.conftest import paper

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def raw(qid="q1", qtype="factoid", body="Which enzyme does allopurinol inhibit?", **overrides):
    record = {
        "id": qid,
        "type": qtype,
        "body": body,
        "documents": ["http://www.ncbi.nlm.nih.gov/pubmed/1001"],
        "snippets": [
            {
                "document": "http://www.ncbi.nlm.nih.gov/pubmed/1001",
                "beginSection": "abstract",
                "endSection": "abstract",
                "offsetInBeginSection": 0,
                "offsetInEndSection": 43,
                "text": "Allopurinol is a xanthine oxidase inhibitor",
            }
        ],
        "exact_answer": ["xanthine oxidase", "XO"] if qtype == "factoid" else [["a"], ["b", "B"]],
        "ideal_answer": ["Xanthine oxidase."],
    }
    record.update(overrides)
    return record


# --- Structural eligibility --------------------------------------------------


def test_factoid_maps_to_fact_with_one_answer_item_of_synonyms():
    q = normalize(raw())
    assert isinstance(q, BenchmarkQuestion)
    assert q.type is QuestionType.FACT
    assert q.answers == [["xanthine oxidase", "XO"]]
    assert q.pmids == ["1001"]
    assert q.snippets[0].pmid == "1001"


def test_list_keeps_each_item_with_its_variants():
    q = normalize(raw(qtype="list"))
    assert q.type is QuestionType.LIST
    assert q.answers == [["a"], ["b", "B"]]


def test_both_document_url_formats_parse():
    assert pmid_from_url("http://www.ncbi.nlm.nih.gov/pubmed/123") == "123"
    assert pmid_from_url("https://pubmed.ncbi.nlm.nih.gov/123/") == "123"
    assert pmid_from_url("https://example.org/123") is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"type": "yesno"}, Reason.OUT_OF_SCOPE_TYPE),
        ({"body": "x" * 2001}, Reason.TOO_LONG),
        ({"exact_answer": []}, Reason.NO_ANSWER),
        ({"exact_answer": ["ok", " "]}, Reason.MALFORMED_ANSWER),
        ({"exact_answer": [["nested"]]}, Reason.MALFORMED_ANSWER),
        ({"documents": []}, Reason.NO_DOCUMENTS),
        ({"documents": ["https://example.org/1"]}, Reason.UNPARSEABLE_DOCUMENT),
        ({"snippets": []}, Reason.NO_SNIPPETS),
    ],
)
def test_ineligible_questions_carry_their_first_failing_reason(overrides, reason):
    result = normalize(raw(**overrides))
    assert isinstance(result, Ineligible)
    assert result.reason is reason


def test_any_full_text_snippet_excludes_the_question():
    record = raw()
    record["snippets"].append({**record["snippets"][0], "beginSection": "sections.0"})
    assert normalize(record).reason is Reason.FULL_TEXT_SNIPPET


def test_snippet_from_an_unlisted_document_excludes_the_question():
    record = raw()
    record["snippets"][0]["document"] = "http://www.ncbi.nlm.nih.gov/pubmed/9999"
    assert normalize(record).reason is Reason.SNIPPET_OUTSIDE_DOCUMENTS


@pytest.mark.parametrize(
    "change", [{"offsetInBeginSection": -1}, {"offsetInEndSection": -5}, {"text": "  "}]
)
def test_malformed_snippets_exclude_the_question(change):
    record = raw()
    record["snippets"][0].update(change)
    assert normalize(record).reason is Reason.MALFORMED_SNIPPET


def test_reason_does_not_depend_on_snippet_order():
    record = raw()
    malformed = {**record["snippets"][0], "offsetInBeginSection": -1}
    full_text = {**record["snippets"][0], "beginSection": "sections.0"}
    record["snippets"] = [malformed, full_text]
    assert normalize(record).reason is Reason.FULL_TEXT_SNIPPET


# --- Grouping ----------------------------------------------------------------


def q(qid, body, pmids, qtype=QuestionType.FACT, snippet_pmid=None, text="alpha beta"):
    pmid = snippet_pmid or pmids[0]
    return BenchmarkQuestion(
        id=qid,
        type=qtype,
        body=body,
        answers=[["x"]],
        ideal_answers=[],
        pmids=pmids,
        snippets=[{"pmid": pmid, "section": "abstract", "start": 0, "end": 1, "text": text}],
    )


def test_templated_questions_about_different_entities_stay_apart():
    groups = group(
        [
            q("a", "Which molecule is targeted by Olaratumab?", ["1"]),
            q("b", "Which molecule is targeted by Upadacitinib?", ["2"]),
        ]
    )
    assert groups["a"] != groups["b"]


def test_paraphrases_sharing_papers_group_transitively():
    groups = group(
        [
            q("a", "What are the computational methods for predicting X?", ["1", "2"]),
            q("b", "What are the computational tools for predicting X?", ["1", "2", "3"]),
            q("c", "Different wording entirely", ["1", "2", "3"]),
            q("d", "Unrelated question", ["9"]),
        ]
    )
    assert groups["a"] == groups["b"] == groups["c"] == "a"
    assert groups["d"] == "d"


# --- Evidence, selection, split ---------------------------------------------

SOURCE = paper("1", "A title", "Alpha beta gamma delta.")


def test_evidence_requires_a_snippet_found_in_the_fetched_text():
    assert check_evidence(q("a", "?", ["1"], text="beta gamma"), {"1": SOURCE}).ok
    missing = check_evidence(q("a", "?", ["1"], text="not there"), {"1": SOURCE})
    assert missing.reason is EvidenceReason.NO_SNIPPET_IN_SOURCE
    unresolved = check_evidence(q("a", "?", ["2"]), {"1": SOURCE})
    assert unresolved.reason is EvidenceReason.NO_PAPER_RESOLVED


def test_snippet_whitespace_is_normalized_like_the_corpus():
    assert check_evidence(q("a", "?", ["1"], text="beta \n  gamma"), {"1": SOURCE}).ok


def pool(n_fact=6, n_list=6):
    papers = {}
    questions = []
    for i in range(n_fact + n_list):
        pmid = str(100 + i)
        papers[pmid] = paper(pmid, "t", "alpha beta gamma.")
        qtype = QuestionType.FACT if i < n_fact else QuestionType.LIST
        questions.append(q(f"q{i:02d}", f"distinct question number {i}", [pmid], qtype))
    return questions, papers


def test_selection_fills_quotas_one_per_group_and_splits_each_type_in_half():
    questions, papers = pool()
    groups = {x.id: x.id for x in questions}
    groups["q01"] = "q00"  # q00 and q01 are duplicates: at most one is chosen
    sel = select(candidate_order(questions, groups, seed=7), papers, seed=7, per_type=4)
    assert len(sel.selected) == 8
    assert not {"q00", "q01"} <= set(sel.selected)
    for qtype in QuestionType:
        splits = [s for qid, s in sel.selected.items() if _type_of(questions, qid) == qtype.value]
        assert splits.count(Split.DEVELOPMENT) == splits.count(Split.TEST) == 2


def _type_of(questions, qid):
    return next(x.type.value for x in questions if x.id == qid)


def test_selection_is_reproducible_and_independent_of_input_order():
    questions, papers = pool()
    groups = {x.id: x.id for x in questions}
    a = select(candidate_order(questions, groups, seed=3), papers, seed=3, per_type=4)
    b = select(candidate_order(questions[::-1], groups, seed=3), papers, seed=3, per_type=4)
    assert a.selected == b.selected
    c = select(candidate_order(questions, groups, seed=4), papers, seed=4, per_type=4)
    assert c.selected != a.selected


def test_a_longer_fetched_prefix_does_not_change_the_selection():
    questions, papers = pool()
    groups = {x.id: x.id for x in questions}
    ordered = candidate_order(questions, groups, seed=5)
    short = select(ordered[:10], papers, seed=5, per_type=4)
    full = select(ordered, papers, seed=5, per_type=4)
    assert short.selected == full.selected


def test_questions_without_evidence_are_skipped_and_counted():
    questions, papers = pool()
    del papers["100"]
    groups = {x.id: x.id for x in questions}
    sel = select(candidate_order(questions, groups, seed=1), papers, seed=1, per_type=4)
    assert "q00" not in sel.selected
    if "q00" in sel.rejected:
        assert sel.rejected["q00"] is EvidenceReason.NO_PAPER_RESOLVED


def test_too_few_eligible_questions_is_reported_not_shrunk():
    questions, papers = pool(n_fact=3, n_list=6)
    groups = {x.id: x.id for x in questions}
    with pytest.raises(QuotaNotMet, match="fact"):
        select(candidate_order(questions, groups, seed=1), papers, seed=1, per_type=4)


def test_shared_reference_papers_across_splits_are_reported():
    a, b = q("a", "?", ["1", "2"]), q("b", "?", ["2", "3"])
    shared = shared_pmids({"a": a, "b": b}, {"a": Split.DEVELOPMENT, "b": Split.TEST})
    assert shared == {"2"}


# --- Isolation ---------------------------------------------------------------


def test_application_code_never_imports_the_benchmark_package():
    """Answer keys and split labels must not be reachable from the API."""
    app_files = [BACKEND / "app.py", *(BACKEND / "bla").rglob("*.py")]
    offenders = [
        path.relative_to(BACKEND)
        for path in app_files
        if "benchmark" not in path.parts and "bla.benchmark" in path.read_text()
    ]
    assert offenders == []
