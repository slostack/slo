"""``now`` tool — current UTC timestamp (sub-spec 01.e §4.4).

Demonstrates a real LangChain tool with a no-arg schema. Useful for
agents that need to write timestamps into logs / DB records or reason
about freshness.
"""

from __future__ import annotations

NOW_PROMPT_SNIPPET: str = "return the current UTC timestamp"

from datetime import datetime, timezone

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict

__all__ = [
    "NowSchemaDAO",
    "NowTool",
    "now_tool",
]


class NowSchemaDAO(BaseModel):
    """LangChain args schema for the now tool (no arguments)."""

    model_config = ConfigDict(
        title="NowSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class NowTool:
    @classmethod
    async def invoke(cls) -> str:
        """Return the current UTC time as an ISO 8601 string.

        Returns:
            str: ``YYYY-MM-DDTHH:MM:SS.ffffff+00:00``.
        """
        return datetime.now(tz=timezone.utc).isoformat()


@tool(name_or_callable="now", args_schema=NowSchemaDAO)
async def now_tool() -> str:
    """Return the current UTC timestamp in ISO 8601 format.

    Returns:
        str: Current UTC time as an ISO 8601 string.
    """
    return await NowTool.invoke()


if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        print("---[ scenario 1: current time ]---")
        print(await NowTool.invoke())

        print("\n---[ scenario 2: two calls; second should be later ]---")
        t1 = await NowTool.invoke()
        t2 = await NowTool.invoke()
        print(f"t1={t1}")
        print(f"t2={t2}")
        print(f"t2 >= t1: {t2 >= t1}")

    asyncio.run(main())
