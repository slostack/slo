"""Real immediate filesystem boundaries and dense cursor parsing decisions."""

import shlex
from pathlib import Path

import pytest

from src.tui.path_suggestion_engine import PathSuggestionEngine


class TestPathSuggestionBoundaries:
    """Cover failures and literal names without duplicating the mounted path-form matrix."""

    @pytest.mark.parametrize(
        argnames="prefix", argvalues=["missing/", "plain.py/", "~slo_nonexistent_user_934817/", "./\x00/"]
    )
    def test_invalid_parent_hides_without_raising(self, tmp_path: Path, prefix: str) -> None:
        """Missing/non-directory parents, unknown users and invalid names are safe hidden results."""
        target = tmp_path / "plain.py"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.touch()
        query = PathSuggestionEngine.query(text=prefix, cursor=len(prefix), workdir=tmp_path)
        assert query is not None
        assert not PathSuggestionEngine.evaluate(query=query).visible

    @pytest.mark.parametrize(
        argnames="text",
        argvalues=["ordinary prose", "/", "  /mo", "use @src/", "use https://example/", "use src/\\"],
    )
    def test_nonpath_contexts_do_not_enumerate(self, tmp_path: Path, text: str) -> None:
        """Commands, mentions, URLs and malformed escapes never become filesystem queries."""
        assert PathSuggestionEngine.query(text=text, cursor=len(text), workdir=tmp_path) is None

    @pytest.mark.parametrize(argnames="quote", argvalues=["", "'", '"'])
    def test_special_names_roundtrip_as_literal_paths(self, tmp_path: Path, quote: str) -> None:
        """Completion is literal: no glob/fuzzy matching, and quotes/Unicode survive insertion."""
        target = tmp_path / "é 'quote\" $dollar `tick` \\slash.txt"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.touch()
        text = "use " + quote + "./é"
        query = PathSuggestionEngine.query(text=text, cursor=len(text), workdir=tmp_path)
        assert query is not None
        state = PathSuggestionEngine.evaluate(query=query)
        assert [row.label for row in state.rows] == [target.name]
        assert shlex.split(state.rows[0].insert_text) == ["./" + target.name]
        for prefix in ("./*", "./quote", "./éq"):
            query = PathSuggestionEngine.query(text=prefix, cursor=len(prefix), workdir=tmp_path)
            assert query is not None
            assert not PathSuggestionEngine.evaluate(query=query).visible
