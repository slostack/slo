"""Cursor-local immediate-directory completion; never reads file contents."""

import re
import shlex
from pathlib import Path
from typing import Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.tui.slash_suggestion_engine import SlashSuggestionRowDAO, SlashSuggestionStateDAO


class PathSuggestionQueryDAO(BaseModel):
    """Literal path prefix and whole replacement token captured before filesystem work."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: int = Field(description="Inclusive character offset of the current path token.")
    end: int = Field(description="Exclusive end of the entire token, including text after cursor.")
    prefix: str = Field(description="Decoded literal path prefix through the cursor.")
    quote: str = Field(default="", description="Outer single/double quote to preserve on insertion.")
    workdir: Path = Field(description="Captured session cwd for relative resolution.")


class PathSuggestionReader(Protocol):
    """Off-thread path query boundary used by the app's single retained worker."""

    def evaluate(self, *, query: PathSuggestionQueryDAO) -> SlashSuggestionStateDAO:
        """Return immediate matches for a captured query without interacting with UI.

        Args:
            query: Immutable cursor and cwd capture.

        Returns:
            Menu state for that capture.
        """
        ...


class PathSuggestionEngine:
    """Own path context, shell-style token spelling and immediate prefix enumeration."""

    # Incomplete quotes are intentional while typing. This is tokenization only:
    # no interpolation, globbing, shell execution or file-content access.
    _TOKENS = re.compile(
        pattern=r"""(?:[^\s"'\\]|\\.|"(?:[^"\\]|\\.)*(?:"|$)|'[^']*(?:'|$))+""", flags=re.DOTALL
    )

    @classmethod
    def query(
        cls, *, text: str, cursor: int, workdir: Path, explicit: bool = False
    ) -> Optional[PathSuggestionQueryDAO]:
        """Capture the cursor token without I/O; Tab also admits plain basename prefixes.

        Args:
            text: Full prompt buffer.
            cursor: Character offset of the insertion point.
            workdir: Session cwd, not the process cwd.
            explicit: Whether Tab requested discovery. Defaults to False.

        Returns:
            Captured query or None outside supported path context.
        """
        token = next(
            (match for match in cls._TOKENS.finditer(text) if match.start() < cursor <= match.end()), None
        )
        if token is None:
            return cls._empty_query(text=text, cursor=cursor, workdir=workdir, explicit=explicit)
        raw = text[token.start() : cursor]
        prefix = cls._decode_prefix(raw=raw)
        if prefix is None or not cls._is_path_context(
            text=text, start=token.start(), prefix=prefix, explicit=explicit
        ):
            return None
        return PathSuggestionQueryDAO(
            start=token.start(),
            end=token.end(),
            prefix=prefix,
            quote=raw[0] if raw[0] in "\"'" else "",
            workdir=workdir,
        )

    @staticmethod
    def _empty_query(
        *, text: str, cursor: int, workdir: Path, explicit: bool
    ) -> Optional[PathSuggestionQueryDAO]:
        """Allow explicit discovery at a blank insertion point, never over another token.

        Args:
            text: Full buffer.
            cursor: Insertion offset.
            workdir: Session cwd.
            explicit: Tab intent.

        Returns:
            Empty cwd query when discovery is safe, otherwise None.
        """
        if not explicit or (cursor < len(text) and not text[cursor].isspace()):
            return None
        return PathSuggestionQueryDAO(start=cursor, end=cursor, prefix="", workdir=workdir)

    @staticmethod
    def _decode_prefix(*, raw: str) -> Optional[str]:
        """Decode literal quotes/escapes, tolerating an unfinished outer quote.

        Args:
            raw: Token spelling through cursor.

        Returns:
            Literal prefix, or None for malformed/dangling escapes.
        """
        for ending in ("", '"', "'"):
            try:
                parts = shlex.split(raw + ending)
                return parts[0] if len(parts) == 1 else None
            except ValueError:
                continue
        return None

    @staticmethod
    def _is_path_context(*, text: str, start: int, prefix: str, explicit: bool) -> bool:
        """Reserve leading command tokens, URLs and mentions; admit literal path contexts.

        Args:
            text: Full buffer.
            start: Token offset.
            prefix: Decoded prefix.
            explicit: Tab intent.

        Returns:
            Whether this token is eligible for path completion.
        """
        if prefix.startswith("@") or "://" in prefix:
            return False
        if not text[:start].strip() and prefix.startswith("/") and "/" not in prefix[1:]:
            return False
        return explicit or "/" in prefix

    @classmethod
    def evaluate(cls, *, query: PathSuggestionQueryDAO) -> SlashSuggestionStateDAO:
        """List matching immediate children off-thread; predictable path failures hide the menu.

        Args:
            query: Captured token and cwd.

        Returns:
            Shared menu state; inaccessible/missing directories produce hidden state.
        """
        try:
            rows = cls._matching_rows(query=query)
        except (OSError, ValueError, RuntimeError):
            return SlashSuggestionStateDAO(visible=False)
        return SlashSuggestionStateDAO(
            visible=bool(rows),
            kind="path",
            replacement_start=query.start,
            replacement_end=query.end,
            rows=rows,
            total_matches=len(rows),
        )

    @classmethod
    def _matching_rows(cls, *, query: PathSuggestionQueryDAO) -> list[SlashSuggestionRowDAO]:
        """Resolve only the parent and sort literal immediate matches.

        Args:
            query: Cursor-local decoded prefix and quote style.

        Returns:
            Directory-first lexical rows; never descends or opens contents.
        """
        parent_text, separator, basename = query.prefix.rpartition("/")
        parent = Path(parent_text + separator or ".").expanduser()
        if not parent.is_absolute():
            parent = query.workdir / parent
        rows = [
            cls._row(child=child, parent_text=parent_text + separator, query=query)
            for child in parent.iterdir()
            if child.name.startswith(basename)
        ]
        return sorted(rows, key=lambda row: (row.detail != "directory", row.label))

    @classmethod
    def _row(cls, *, child: Path, parent_text: str, query: PathSuggestionQueryDAO) -> SlashSuggestionRowDAO:
        """Spell one result safely in the token's outer quote style.

        Args:
            child: Immediate entry (symlink directories remain navigable).
            parent_text: Literal parent prefix, retaining ./, ../ or ~/.
            query: Original quote style.

        Returns:
            Menu row; directories retain an open quote for continued navigation.
        """
        suffix = "/" if child.is_dir() else ""
        return SlashSuggestionRowDAO(
            insert_text=cls._encode_path(
                path=parent_text + child.name + suffix, quote=query.quote, directory=bool(suffix)
            ),
            label=child.name + suffix,
            detail="directory" if suffix else "file",
        )

    @staticmethod
    def _encode_path(*, path: str, quote: str, directory: bool) -> str:
        """Keep directory quotes open, close file quotes, and escape literal special names.

        Args:
            path: Literal completed path.
            quote: Outer quote to preserve, or empty for backslash spelling.
            directory: Whether navigation will continue.

        Returns:
            Token spelling decodable without interpolation by shlex.
        """
        if quote == "'":
            return "'" + path.replace("'", "'\\''") + ("" if directory else "'")
        if quote == '"':
            escaped = path.replace("\\", "\\\\").replace('"', '\\"')
            return '"' + escaped + ("" if directory else '"')
        return re.sub(pattern=r"([\s\\\"'])", repl=r"\\\1", string=path)
