"""Complete synthetic Responses frames shared by Feature 89 SDK acceptance tests."""

import json


def response_envelope(
    *, model_name: str, output: list[dict[str, object]], completed: bool
) -> dict[str, object]:
    """Build the required response fields for created and completed synthetic frames."""
    return {
        "id": "resp_89_tool" if output and output[0]["type"] == "function_call" else "resp_89_answer",
        "object": "response",
        "created_at": 1,
        "model": model_name,
        "status": "completed" if completed else "in_progress",
        "output": output,
        "error": None,
        "incomplete_details": None,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def encode_frames(*, frames: list[dict[str, object]]) -> bytes:
    """Encode typed events with monotonically increasing per-response sequence numbers."""
    return "".join(
        f"event: {frame['type']}\ndata: {json.dumps({**frame, 'sequence_number': index})}\n\n"
        for index, frame in enumerate(frames)
    ).encode()


def answer_frames(*, model_name: str) -> bytes:
    """Emit a complete second stream whose visible message survives SDK finalization."""
    start = {"id": "msg_89", "type": "message", "role": "assistant", "status": "in_progress", "content": []}
    part = {"type": "output_text", "text": "complete-89", "annotations": []}
    done: dict[str, object] = {**start, "status": "completed", "content": [part]}
    indexes = {"output_index": 0, "content_index": 0, "item_id": "msg_89"}
    return encode_frames(
        frames=[
            {
                "type": "response.created",
                "response": response_envelope(model_name=model_name, output=[], completed=False),
            },
            {"type": "response.output_item.added", "output_index": 0, "item": start},
            {"type": "response.content_part.added", **indexes, "part": {**part, "text": ""}},
            {"type": "response.output_text.delta", **indexes, "delta": "complete-89", "logprobs": []},
            {"type": "response.output_text.done", **indexes, "text": "complete-89", "logprobs": []},
            {"type": "response.content_part.done", **indexes, "part": part},
            {"type": "response.output_item.done", "output_index": 0, "item": done},
            {
                "type": "response.completed",
                "response": response_envelope(model_name=model_name, output=[done], completed=True),
            },
        ]
    )


def tool_frames(*, model_name: str) -> bytes:
    """Emit the complete first response, including fragmented echo arguments and completion."""
    start = {
        "type": "function_call",
        "id": "fc_89",
        "call_id": "call_89",
        "name": "echo",
        "arguments": "",
        "status": "in_progress",
    }
    done: dict[str, object] = {**start, "arguments": '{"text":"echo-89"}', "status": "completed"}
    created = response_envelope(model_name=model_name, output=[], completed=False)
    created["id"] = "resp_89_tool"
    return encode_frames(
        frames=[
            {"type": "response.created", "response": created},
            {"type": "response.output_item.added", "output_index": 0, "item": start},
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_89",
                "output_index": 0,
                "delta": '{"text":',
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_89",
                "output_index": 0,
                "delta": '"echo-89"}',
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_89",
                "output_index": 0,
                "name": "echo",
                "arguments": done["arguments"],
            },
            {"type": "response.output_item.done", "output_index": 0, "item": done},
            {
                "type": "response.completed",
                "response": response_envelope(model_name=model_name, output=[done], completed=True),
            },
        ]
    )
