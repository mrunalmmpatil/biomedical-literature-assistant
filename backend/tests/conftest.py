from datetime import date

import pytest

from bla.contracts import Paper
from bla.corpus import content_hash, normalize_text


def paper(pmid: str, title: str, abstract: str, **metadata) -> Paper:
    """A normalized record as ingestion would produce it. Fixture text is
    invented for tests and is not drawn from any benchmark."""
    title, abstract = normalize_text(title), normalize_text(abstract)
    return Paper(
        pmid=pmid,
        title=title,
        abstract=abstract,
        retrieved_on=date(2026, 9, 23),
        content_hash=content_hash(title, abstract),
        **metadata,
    )


@pytest.fixture
def corpus() -> list[Paper]:
    return [
        paper(
            "1001",
            "Allopurinol and xanthine oxidase",
            "Allopurinol is a xanthine oxidase inhibitor that lowers serum urate "
            "and is used in the long-term management of gout.",
        ),
        paper(
            "1002",
            "Metformin in type 2 diabetes",
            "Metformin reduces hepatic glucose production and improves insulin "
            "sensitivity; it is a first-line oral agent for type 2 diabetes.",
        ),
        paper(
            "1003",
            "Interleukin signalling in sepsis",
            "Elevated IL-6 and TNF-α concentrations were associated with mortality "
            "in a cohort of 212 adults with sepsis.",
        ),
        paper(
            "1004",
            "BRCA1 and hereditary breast cancer",
            "Pathogenic BRCA1 variants substantially increase lifetime risk of breast "
            "and ovarian cancer and inform screening decisions.",
        ),
    ]
