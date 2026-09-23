"""Evaluation-only benchmark code (technical PRD sections 3.1 and 4).

Nothing in this package may be imported by the API: it handles reference
answers, relevant-paper labels, and split assignments. `tests/test_benchmark.py`
enforces that `app.py` and the retrieval/answer modules do not import it.
"""
