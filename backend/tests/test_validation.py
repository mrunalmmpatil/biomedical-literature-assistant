"""Answer validation at the section 6.3 boundary. Model output here is
hand-written; these tests cover software behaviour, not model quality."""

import json

import pytest

from bla.validation import InvalidAnswer, ValidAnswer, validate_answer


@pytest.fixture
def sources(corpus):
    return {"S1": corpus[0], "S2": corpus[2]}


def answer(**overrides):
    body = {
        "outcome": "answered",
        "items": [{"text": "Allopurinol", "source_ids": ["S1"]}],
        "claims": [
            {
                "text": "Allopurinol inhibits xanthine oxidase and lowers urate.",
                "source_ids": ["S1"],
                "quotes": [
                    {
                        "source_id": "S1",
                        "text": "xanthine oxidase inhibitor that lowers serum urate",
                    }
                ],
            }
        ],
        "qualifications": [],
    }
    body.update(overrides)
    return body


def claim(quote_source="S1", quote="xanthine oxidase inhibitor that lowers serum urate", ids=None):
    return {
        "text": "A claim.",
        "source_ids": ids if ids is not None else [quote_source],
        "quotes": [{"source_id": quote_source, "text": quote}],
    }


def test_well_formed_answer_passes_with_server_computed_offsets(sources):
    result = validate_answer(answer(), sources)
    assert isinstance(result, ValidAnswer)
    source_id, excerpt = result.claims[0].excerpts[0]
    assert source_id == "S1"
    assert excerpt.field == "abstract"
    assert sources["S1"].abstract[excerpt.start : excerpt.end] == excerpt.text


def test_json_string_input_is_accepted(sources):
    assert isinstance(validate_answer(json.dumps(answer()), sources), ValidAnswer)


def test_quote_with_different_line_breaks_still_matches(sources):
    body = answer(claims=[claim(quote="xanthine oxidase\n  inhibitor that lowers serum urate")])
    assert isinstance(validate_answer(body, sources), ValidAnswer)


def test_quote_may_come_from_the_title(sources):
    body = answer(claims=[claim(quote="Allopurinol and xanthine oxidase")])
    result = validate_answer(body, sources)
    assert result.claims[0].excerpts[0][1].field == "title"


@pytest.mark.parametrize(
    "body, reason",
    [
        (answer(items=[{"text": "Allopurinol", "source_ids": ["S9"]}]), "unknown source S9"),
        (answer(items=[{"text": "Allopurinol", "source_ids": []}]), "no source cited"),
        (answer(claims=[claim(ids=["S7"], quote_source="S7")]), "unknown source S7"),
        (answer(claims=[claim(quote="xanthine oxidase blocker lowering urate")]), "not found"),
        (answer(claims=[claim(quote="XANTHINE OXIDASE INHIBITOR THAT LOWERS")]), "not found"),
        (answer(claims=[claim(quote="serum urate")]), "not found"),  # too short to verify
        (answer(claims=[claim(quote_source="S2", ids=["S1"])]), "uncited S2"),
        (
            answer(claims=[claim(quote="IL-6 and TNF-α concentrations", quote_source="S1")]),
            "not found",
        ),
        (
            answer(claims=[{"text": "Unquoted.", "source_ids": ["S1"], "quotes": []}]),
            "no supporting quote",
        ),
        (answer(items=[]), "no answer items"),
        (answer(outcome="insufficient_evidence"), "carries answer items"),
    ],
)
def test_any_bad_reference_rejects_the_whole_answer(sources, body, reason):
    result = validate_answer(body, sources)
    assert isinstance(result, InvalidAnswer)
    assert reason in result.reason


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"outcome": "answered"}',
        json.dumps(answer(outcome="probably")),
        json.dumps({**answer(), "url": "https://evil.example"}),  # URLs are server-built
        json.dumps(answer(confidence=0.99)),
    ],
)
def test_malformed_or_extra_output_is_rejected(sources, raw):
    assert isinstance(validate_answer(raw, sources), InvalidAnswer)


def test_one_bad_claim_is_not_silently_dropped(sources):
    body = answer(claims=[answer()["claims"][0], claim(quote="text that appears nowhere at all")])
    assert isinstance(validate_answer(body, sources), InvalidAnswer)


def test_explicit_insufficient_evidence_is_a_valid_outcome(sources):
    body = answer(
        outcome="insufficient_evidence",
        items=[],
        claims=[],
        qualifications=["The retrieved abstracts do not report dosing.", "  "],
    )
    result = validate_answer(body, sources)
    assert isinstance(result, ValidAnswer)
    assert result.outcome == "insufficient_evidence"
    assert result.qualifications == ("The retrieved abstracts do not report dosing.",)
