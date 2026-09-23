import pytest
from pydantic import ValidationError

from bla.corpus import content_hash, normalize_text
from tests.conftest import paper


def test_normalization_collapses_whitespace_and_keeps_symbols():
    assert normalize_text("  TNF-α\n\tlevels  rose  ") == "TNF-α levels rose"
    # Compatibility folding would turn µ into μ and ² into 2; NFC must not.
    assert normalize_text("5 µg/m²") == "5 µg/m²"


def test_content_hash_ignores_layout_but_tracks_text():
    base = content_hash("Title", "An abstract.")
    assert content_hash(" Title ", "An\nabstract.") == base
    assert content_hash("Title", "An abstract!") != base


def test_paper_url_is_built_from_the_stored_pmid():
    assert paper("123", "t", "a").url == "https://pubmed.ncbi.nlm.nih.gov/123/"


@pytest.mark.parametrize("bad", ["", "0123", "PMC123", "12 3", "https://x/1"])
def test_paper_rejects_malformed_pmids(bad):
    with pytest.raises(ValidationError):
        paper(bad, "t", "a")
