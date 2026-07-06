"""``edit`` tool — exact-text replacement on a single file (sub-spec 01.d §4.3).

Follows ``awesome-agi/build-agent-tools.md`` conventions. Each
``EditOperationDAO.oldText`` must match a unique, non-overlapping region.
Edits are applied in reverse offset order so earlier offsets stay valid.
Description text is lifted verbatim from pi ``edit.ts:300``.
"""

from __future__ import annotations

EDIT_PROMPT_SNIPPET: str = (
    "make precise edits to a file with exact-text replacement, "
    "including multiple disjoint edits in one call"
)

from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_error, log_info
from src.agents.tools._blocking import run_blocking_tool_call

__all__ = [
    "EditOperationDAO",
    "EditSchemaDAO",
    "EditTool",
    "edit_tool",
]


class EditOperationDAO(BaseModel):
    """A single (oldText, newText) replacement instruction."""

    oldText: str = Field(
        description="Exact text region to replace. Must be unique in the file.",
    )
    newText: str = Field(
        description="Replacement text for this targeted edit.",
    )

    model_config = ConfigDict(
        title="EditOperationDAO",
        extra="ignore",
        from_attributes=True,
    )


class EditSchemaDAO(BaseModel):
    """LangChain args schema for the edit tool."""

    path: str = Field(description="Path to the file to edit")
    edits: list[EditOperationDAO] = Field(
        description="List of exact-text replacements to apply.",
    )

    model_config = ConfigDict(
        title="EditSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class EditTool:
    @classmethod
    async def invoke(cls, path: str, edits: list[EditOperationDAO]) -> str:
        """Apply a batch of exact-text edits.

        Args:
            path (str): Path to the file to edit.
            edits (list[EditOperationDAO]): Replacements to apply. Each
                ``oldText`` must appear exactly once in the file and must
                not overlap any other edit's region.

        Returns:
            str: ``"Applied N edit(s) to <path>"`` on success, or
                ``"Error: ..."`` on validation/IO failure.
        """
        return await run_blocking_tool_call(
            func=cls._invoke_sync,
            path=path,
            edits=edits,
        )

    @classmethod
    def _invoke_sync(
        cls,
        *,
        path: str,
        edits: list[EditOperationDAO],
    ) -> str:
        """Apply a batch of exact-text edits synchronously.

        Args:
            path (str): Path to the file to edit.
            edits (list[EditOperationDAO]): Exact-text replacements to apply.

        Returns:
            str: Confirmation on success, or an error message.
        """
        try:
            target = Path(path)
            if not target.exists():
                return f"Error: file not found: {path}"
            if target.is_dir():
                return f"Error: path is a directory: {path}"
            if not edits:
                return "Error: edits list is empty"

            try:
                content = target.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                return f"Error: cannot decode {path} as UTF-8: {exc}"

            located: list[tuple[int, int, str]] = []
            for index, op in enumerate(edits):
                try:
                    start: int = cls._find_unique(haystack=content, needle=op.oldText)
                except ValueError as exc:
                    return f"Error in edits[{index}]: {exc}"
                end: int = start + len(op.oldText)
                located.append((start, end, op.newText))

            located_sorted: list[tuple[int, int, str]] = sorted(
                located,
                key=lambda item: item[0],
            )
            for prev, current in zip(located_sorted, located_sorted[1:]):
                if cls._overlaps(a=(prev[0], prev[1]), b=(current[0], current[1])):
                    return (
                        f"Error: overlapping edits at offsets "
                        f"({prev[0]}, {prev[1]}) and ({current[0]}, {current[1]}). "
                        f"Merge them into a single edit covering the union."
                    )

            edited: str = content
            for start, end, new_text in sorted(
                located_sorted,
                key=lambda item: item[0],
                reverse=True,
            ):
                edited = edited[:start] + new_text + edited[end:]

            target.write_text(edited, encoding="utf-8")
            return f"Applied {len(edits)} edit(s) to {target}"
        except Exception as exc:  # noqa: BLE001 — surface to model
            log_error(msg=f"EditTool failed for {path}", e=exc, stack_trace=False)
            return f"Error: edit failed: {exc}"

    @classmethod
    def _find_unique(cls, haystack: str, needle: str) -> int:
        """Return the start index of ``needle`` in ``haystack`` if exactly one match.

        Raises:
            ValueError: when the match count is not exactly 1.
        """
        count = haystack.count(needle)
        if count == 0:
            raise ValueError(f"oldText not found in file: {needle!r}")
        if count > 1:
            raise ValueError(
                f"oldText matches {count} times; provide more surrounding context to "
                f"make it unique: {needle!r}"
            )
        return haystack.index(needle)

    @classmethod
    def _overlaps(cls, a: tuple[int, int], b: tuple[int, int]) -> bool:
        return not (a[1] <= b[0] or b[1] <= a[0])


@tool(name_or_callable="edit", args_schema=EditSchemaDAO)
async def edit_tool(path: str, edits: list[EditOperationDAO]) -> str:
    """Edit a single file using exact text replacement. Every edits[].oldText must match a unique, non-overlapping region of the original file. If two changes affect the same block or nearby lines, merge them into one edit instead of emitting overlapping edits. Do not include large unchanged regions just to connect distant changes.

    Args:
        path (str): Path to the file to edit.
        edits (list[EditOperationDAO]): Edits to apply, in any order.

    Returns:
        str: Confirmation of edits applied, or an error message.
    """
    log_info(msg=f"Using Edit Tool with path: {path} ({len(edits)} edit(s))")
    return await EditTool.invoke(path=path, edits=edits)


if __name__ == "__main__":
    # Quick test harness: exercises EditTool against three scenarios.
    import asyncio
    import tempfile

    async def main() -> None:
        # Scenario 1 — happy path: single unique replacement.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
            fh.write("hello world\nfoo bar\n")
            target = fh.name
        print("---[ scenario 1: replace 'world' -> 'slo' ]---")
        print(
            await EditTool.invoke(
                path=target,
                edits=[EditOperationDAO(oldText="world", newText="slo")],
            )
        )
        print(f"contents: {Path(target).read_text()!r}")

        # Scenario 2 — multiple non-overlapping edits applied in one batch.
        print("\n---[ scenario 2: two non-overlapping edits ]---")
        print(
            await EditTool.invoke(
                path=target,
                edits=[
                    EditOperationDAO(oldText="hello slo", newText="HELLO SLO"),
                    EditOperationDAO(oldText="foo bar", newText="FOO BAR"),
                ],
            )
        )
        print(f"contents: {Path(target).read_text()!r}")

        # Scenario 3 — error: oldText not found.
        print("\n---[ scenario 3: missing oldText ]---")
        print(
            await EditTool.invoke(
                path=target,
                edits=[EditOperationDAO(oldText="nonexistent", newText="x")],
            )
        )

    asyncio.run(main())

    asyncio.run(main())
