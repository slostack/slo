"""``echo`` tool — deterministic demo / test (sub-spec 01.e §4.4).

Hidden from the model when no description appears in the system prompt
(matches pi behaviour); used by the faux-provider integration tests in
01.k as a controllable side-effect.
"""

from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_info

__all__ = [
    "EchoSchemaDAO",
    "EchoTool",
    "echo_tool",
]


class EchoSchemaDAO(BaseModel):
    """LangChain args schema for the echo tool."""

    text: str = Field(description="Text to echo back unchanged.")

    model_config = ConfigDict(
        title="EchoSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class EchoTool:
    @classmethod
    async def invoke(cls, text: str) -> str:
        """Echo the input text back unchanged.

        Args:
            text (str): Any string.

        Returns:
            str: The input string verbatim.
        """
        return text


@tool(name_or_callable="echo", args_schema=EchoSchemaDAO)
async def echo_tool(text: str) -> str:
    """Echo the input text back unchanged. Used by the faux-provider test suite as a deterministic side-effect.

    Args:
        text (str): Text to echo.

    Returns:
        str: The input string verbatim.
    """
    log_info(msg=f"Using Echo Tool with text: {text!r}")
    return await EchoTool.invoke(text=text)


if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        print("---[ scenario 1: simple echo ]---")
        print(await EchoTool.invoke(text="hello from slo echo tool"))

        print("\n---[ scenario 2: empty string ]---")
        print(repr(await EchoTool.invoke(text="")))

        print("\n---[ scenario 3: unicode passthrough ]---")
        print(await EchoTool.invoke(text="résumé · café · 日本語"))

    asyncio.run(main())
