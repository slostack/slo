"""Small failure-path regressions for the Responses sequencing adapter."""

from copy import deepcopy
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

from src.agents.providers.openai_codex import build_chatgpt_backed_chat_openai
from src.agents.providers.openai_responses_sequencing import SequencedChatOpenAI
from langchain_core.messages import HumanMessage
from tests.agents.providers.feature89_responses import encode_frames
from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred
from tests.agents.providers.test_openai_responses_sequencing import call_frames


@pytest.mark.parametrize(
    "fault", ["mismatch", "unfinished", "orphan", "invalid-json", "non-object", "no-terminal"]
)
async def test_inconsistent_stream_never_returns_executable_calls(fault: str) -> None:
    """Broken argument sequences fail instead of returning partial tool calls."""
    frames = deepcopy(call_frames(order="interleaved"))
    if fault == "mismatch":
        cast(dict[str, object], frames[-3]["item"])["arguments"] = '{"path":"wrong.py"}'
    elif fault == "unfinished":
        frames = frames[:-3] + frames[-1:]
    elif fault == "orphan":
        del frames[1]
    elif fault == "invalid-json":
        frames = call_frames(order="done-only")
        cast(dict[str, object], frames[-3]["item"])["arguments"] = '{"path":'
    elif fault == "non-object":
        frames = call_frames(order="done-only")
        cast(dict[str, object], frames[-3]["item"])["arguments"] = "[]"
    else:
        frames = frames[:-1]

    def respond(request: httpx.Request) -> httpx.Response:
        """Supply a malformed vendor stream without accessing the network."""
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=encode_frames(frames=frames),
        )

    token = _build_jwt(claims={"https://api.openai.com/auth": {"chatgpt_account_id": "offline-account"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        chat = build_chatgpt_backed_chat_openai(
            model_name="gpt-5",
            cred=_oauth_cred(access_token=token),
            session_id="sequencing",
            http_async_client=client,
        )
        with pytest.raises(ValueError, match="OpenAI") as error:
            await chat.ainvoke(input="read")
    assert "wrong.py" not in str(error.value)


async def test_closing_pool_stream_closes_the_provider_response() -> None:
    """The model-pool streaming seam releases HTTP resources on early close."""
    response = httpx.Response(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        stream=httpx.ByteStream(encode_frames(frames=call_frames(order="interleaved"))),
    )

    def respond(request: httpx.Request) -> httpx.Response:
        """Hand ownership of the in-memory response to the real SDK."""
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        chat = SequencedChatOpenAI(
            model="gpt-5",
            api_key=SecretStr("offline"),
            use_responses_api=True,
            output_version="responses/v1",
            http_async_client=client,
        )
        stream = chat._astream(messages=[HumanMessage(content="read")])
        await anext(stream)
        assert not response.is_closed
        await stream.aclose()
        assert response.is_closed
