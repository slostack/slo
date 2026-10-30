"""Removable ChatOpenAI 0.3.35 workaround for interleaved Responses tool calls.

SequencedChatOpenAI replaces ChatOpenAI only at Slo's OpenAI construction sites.
It overrides _astream (upstream's super()._astream_responses bypasses overrides)
and introduces _astream_responses_sequenced. SDK requests, retries and resource
ownership remain unchanged; only function-call assembly is specialized. Sync and
nonstreaming calls, and Chat Completions, retain upstream behavior.

Rollback: restore ChatOpenAI in openai_codex.py, openai_platform.py and the OpenAI
factory in base.py, then remove this file. Recheck the HTTP replay tests before
upgrading langchain-openai: the private conversion/transport seam is version-bound.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from contextlib import aclosing
from typing import Literal, Optional, cast

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import _convert_responses_chunk_to_generation_chunk
from openai import AsyncStream
from openai.types.responses import ResponseFunctionToolCall, ResponseStreamEvent


@dataclass
class _FunctionCall:
    """One response's function identity and append-only argument merge slot."""

    slot: int
    item_id: str
    call_id: str
    name: str
    arguments: str
    output_version: Literal["v0", "responses/v1"]
    completed: bool = False

    def append(self, *, item_id: str, arguments: str) -> ChatGenerationChunk:
        """Append a fragment to both execution and replay representations.

        Args:
            item_id: Provider identity that must match the opened call.
            arguments: New JSON fragment, never a replacement snapshot.

        Returns:
            A chunk with the original call's stable merge index.

        Raises:
            ValueError: The fragment belongs to another or already completed call.
        """
        if item_id != self.item_id or self.completed:
            raise ValueError("Invalid OpenAI function-call sequence.")
        self.arguments += arguments
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content=(
                    [{"type": "function_call", "arguments": arguments, "index": self.slot}]
                    if self.output_version == "responses/v1"
                    else []
                ),
                tool_call_chunks=[
                    {
                        "type": "tool_call_chunk",
                        "args": arguments,
                        "index": self.slot,
                        "name": None,
                        "id": None,
                    }
                ],
            )
        )

    def finish(self, *, item: ResponseFunctionToolCall) -> ChatGenerationChunk:
        """Complete from authoritative JSON without appending it a second time.

        Args:
            item: Provider's completed function call.

        Returns:
            Only the unstreamed suffix, possibly empty.

        Raises:
            ValueError: Identity, JSON shape or final arguments contradict the stream.
        """
        if (
            item.call_id != self.call_id
            or item.name != self.name
            or not item.arguments.startswith(self.arguments)
        ):
            raise ValueError("Inconsistent OpenAI function-call completion.")
        try:
            parsed: object = json.loads(item.arguments)
        except ValueError:
            raise ValueError("Invalid OpenAI function-call arguments.") from None
        if not isinstance(parsed, dict):
            raise ValueError("OpenAI function-call arguments must be an object.")
        chunk = self.append(item_id=item.id or "", arguments=item.arguments[len(self.arguments) :])
        self.completed = True
        return chunk


class _ResponseStreamConverter:
    """Per-invocation converter; live models share no mutable sequencing state."""

    def __init__(self, *, output_version: Literal["v0", "responses/v1"], schema: object) -> None:
        """Own one response's merge indexes and upstream conversion options.

        Args:
            output_version: Existing LangChain output format.
            schema: Existing structured-output schema, forwarded unchanged.
        """
        self._output_version = output_version
        self._schema = schema
        self._current_index = -1
        self._current_output_index = -1
        self._current_sub_index = -1
        self._has_reasoning = False
        self._calls: dict[int, _FunctionCall] = {}
        self._response_completed = False

    def convert(
        self, *, event: ResponseStreamEvent, metadata: dict[str, object]
    ) -> Optional[ChatGenerationChunk]:
        """Route function events by output_index and delegate other event shapes.

        Args:
            event: Parsed OpenAI SSE event.
            metadata: First-chunk response headers, if requested.

        Returns:
            Converted chunk, or None for an upstream non-content event.

        Raises:
            ValueError: A function event is inconsistent or has no opening.
        """
        if event.type == "response.function_call_arguments.delta":
            return self._call(output_index=event.output_index).append(
                item_id=event.item_id, arguments=event.delta
            )
        if event.type == "response.output_item.done" and event.item.type == "function_call":
            return self._call(output_index=event.output_index).finish(item=event.item)
        if event.type == "response.completed":
            self._response_completed = True
        chunk = self._convert_upstream(event=event, metadata=metadata)
        if event.type == "response.output_item.added" and event.item.type == "function_call":
            self._open_call(output_index=event.output_index, item=event.item)
        return chunk

    def require_completed_calls(self) -> None:
        """Prevent a truncated stream from returning executable partial calls.

        Raises:
            ValueError: Any opened function call lacks authoritative completion.
        """
        if self._calls and (
            not self._response_completed or any(not call.completed for call in self._calls.values())
        ):
            raise ValueError("OpenAI stream ended with unfinished function calls.")

    def _call(self, *, output_index: int) -> _FunctionCall:
        """Resolve an opened call or reject an orphan event without exposing payloads."""
        call = self._calls.get(output_index)
        if call is None:
            raise ValueError("OpenAI function-call update has no opening event.")
        return call

    def _open_call(self, *, output_index: int, item: ResponseFunctionToolCall) -> None:
        """Associate the upstream opening slot with its durable provider identity."""
        if output_index in self._calls:
            raise ValueError("Duplicate OpenAI function-call opening event.")
        self._calls[output_index] = _FunctionCall(
            slot=self._current_index,
            item_id=item.id or "",
            call_id=item.call_id,
            name=item.name,
            arguments=item.arguments,
            output_version=self._output_version,
        )

    def _convert_upstream(
        self, *, event: ResponseStreamEvent, metadata: dict[str, object]
    ) -> Optional[ChatGenerationChunk]:
        """Retain upstream text, reasoning, metadata and usage handling unchanged."""
        self._current_index, self._current_output_index, self._current_sub_index, chunk = (
            _convert_responses_chunk_to_generation_chunk(
                chunk=event,
                current_index=self._current_index,
                current_output_index=self._current_output_index,
                current_sub_index=self._current_sub_index,
                # Upstream accepts Pydantic classes AND JSON schema dicts despite its narrow annotation.
                schema=self._schema,  # type: ignore[arg-type]
                metadata=metadata,
                has_reasoning=self._has_reasoning,
                output_version=self._output_version,
            )
        )
        if chunk and "reasoning" in chunk.message.additional_kwargs:
            self._has_reasoning = True
        return chunk


class SequencedChatOpenAI(ChatOpenAI):
    """ChatOpenAI override keeping parallel Responses function arguments attached.

    `_astream` routes async Responses calls to the introduced
    `_astream_responses_sequenced`; all other provider behavior is inherited.
    Each invocation owns its converter and closes its SDK stream on failure or
    cancellation. Slo's graph executes calls only after the model completes.
    """

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncGenerator[ChatGenerationChunk, None]:
        """Override upstream routing, which otherwise bypasses subclass response loops.

        Args:
            messages: Conversation forwarded by LangChain or Slo's model pool.
            stop: Optional stop sequences.
            run_manager: Existing token callback manager.
            kwargs: Bound tools and invocation options.

        Yields:
            Ordered model chunks for this invocation.
        """
        stream = (
            self._astream_responses_sequenced(messages=messages, stop=stop, run_manager=run_manager, **kwargs)
            if self._use_responses_api({**kwargs, **self.model_kwargs})
            # Upstream implements an async generator but annotates it as AsyncIterator.
            else cast(
                AsyncGenerator[ChatGenerationChunk, None],
                super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs),
            )
        )
        async with aclosing(stream):
            async for chunk in stream:
                yield chunk

    async def _astream_responses_sequenced(
        self,
        *,
        messages: list[BaseMessage],
        stop: Optional[list[str]],
        run_manager: Optional[AsyncCallbackManagerForLLMRun],
        **kwargs: object,
    ) -> AsyncGenerator[ChatGenerationChunk, None]:
        """Consume one SDK response using stable call slots instead of arrival order.

        Mirrors the 0.3.35 async Responses transport; no global monkeypatch or
        additional requests. The SDK context owns closure, including exceptions.

        Args:
            messages: Input conversation.
            stop: Optional stop sequences.
            run_manager: Token callback observer.
            kwargs: Invocation options, including structured-output schema.

        Yields:
            Correctly associated chunks, with headers on the first chunk.

        Raises:
            ValueError: Function events are inconsistent or incomplete.
        """
        payload = self._get_request_payload(input_=messages, stop=stop, **{**kwargs, "stream": True})
        response, headers = await self._open_responses_stream(payload=payload)
        converter = _ResponseStreamConverter(
            output_version=self.output_version, schema=kwargs.get("response_format")
        )
        async with response:
            async for event in response:
                chunk = converter.convert(event=event, metadata=headers)
                if chunk is None:
                    continue
                headers = {}
                if run_manager is not None:
                    await run_manager.on_llm_new_token(token=chunk.text, chunk=chunk)
                yield chunk
            converter.require_completed_calls()

    async def _open_responses_stream(
        self,
        *,
        payload: dict[str, object],
    ) -> tuple[AsyncStream[ResponseStreamEvent], dict[str, object]]:
        """Open the SDK stream, retaining the optional upstream response headers.

        Args:
            payload: Request assembled by the existing model's payload policy.

        Returns:
            Owned SDK stream and optional first-chunk headers.
        """
        if self.include_response_headers:
            raw = await self.root_async_client.with_raw_response.responses.create(**payload)
            return raw.parse(), {"headers": dict(raw.headers)}
        return await self.root_async_client.responses.create(**payload), {}
