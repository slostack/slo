#!/bin/bash
cd /root/Code/tui-refactor/slo
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
unset SLO_OPENAI_API_KEY SLO_KIMI_FOR_CODING_API_KEY SLO_OPENROUTER_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY
which python
poetry run python --version
PYTHONPATH="$PWD" poetry run pytest -q tests/tui/test_chat_transcript_precise_scroll.py tests/tui/test_chat_transcript_closure.py tests/tui/test_chat_transcript_navigation.py tests/tui/test_scroll_follow.py tests/tui/test_chat_transcript.py > docs/implementation/96-chat-transcript/precise-regression.log 2>&1
result=$?
printf '%s\n' "$result" > docs/implementation/96-chat-transcript/precise-regression.exit
tail -50 docs/implementation/96-chat-transcript/precise-regression.log
exit "$result"
