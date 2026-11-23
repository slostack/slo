"""AttachmentStore: which agent each platform user talks to (108.5 §2 Attach).

Level: service → real JSON file under ``tmp_path``. A reopened store reads the
same file, which proves the choice survives an adapter restart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.channels.attachments import AttachmentStore
from src.channels.dao import AttachmentDAO, InboundTextDAO


class TestAttachmentStore:
    def test_attach_survives_a_reopened_store_and_the_file_is_private(self, tmp_path: Path) -> None:
        channel_id: UUID = uuid4()
        user_id: UUID = uuid4()
        agent_id: UUID = uuid4()
        path: Path = tmp_path / "channels" / f"{channel_id}.json"

        attached: AttachmentDAO = AttachmentStore(path=path, channel_id=channel_id).attach(
            participant_id=user_id, agent_id=agent_id
        )
        reopened: Optional[AttachmentDAO] = AttachmentStore(path=path, channel_id=channel_id).get(
            participant_id=user_id
        )

        assert attached.agent_id == agent_id
        assert reopened is not None
        assert reopened.agent_id == agent_id
        assert reopened.channel_id == channel_id
        assert oct(path.stat().st_mode & 0o777) == "0o600"
        assert not list(path.parent.glob("*.tmp"))

    def test_detach_keeps_a_row_with_no_agent(self, tmp_path: Path) -> None:
        channel_id: UUID = uuid4()
        user_id: UUID = uuid4()
        store: AttachmentStore = AttachmentStore(path=tmp_path / "a.json", channel_id=channel_id)
        first: AttachmentDAO = store.attach(participant_id=user_id, agent_id=uuid4())

        detached: AttachmentDAO = store.detach(participant_id=user_id)

        assert detached.agent_id is None
        assert detached.updated_at >= first.updated_at
        stored: Optional[AttachmentDAO] = AttachmentStore(
            path=tmp_path / "a.json", channel_id=channel_id
        ).get(participant_id=user_id)
        assert stored is not None and stored.agent_id is None

    def test_users_are_independent(self, tmp_path: Path) -> None:
        channel_id: UUID = uuid4()
        alice: UUID = uuid4()
        bob: UUID = uuid4()
        store: AttachmentStore = AttachmentStore(path=tmp_path / "a.json", channel_id=channel_id)
        alice_agent: UUID = uuid4()
        store.attach(participant_id=alice, agent_id=alice_agent)

        store.detach(participant_id=bob)

        alice_row: Optional[AttachmentDAO] = store.get(participant_id=alice)
        assert alice_row is not None and alice_row.agent_id == alice_agent

    def test_missing_file_means_nobody_is_attached(self, tmp_path: Path) -> None:
        store: AttachmentStore = AttachmentStore(path=tmp_path / "absent.json", channel_id=uuid4())

        assert store.get(participant_id=uuid4()) is None
        assert not (tmp_path / "absent.json").exists()

    def test_corrupt_file_is_set_aside_and_treated_as_empty(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "a.json"
        path.write_text("{not json", encoding="utf-8")
        channel_id: UUID = uuid4()
        user_id: UUID = uuid4()

        store: AttachmentStore = AttachmentStore(path=path, channel_id=channel_id)

        assert store.get(participant_id=user_id) is None
        set_aside: list[Path] = list(tmp_path.glob("a.json.corrupt-*"))
        assert len(set_aside) == 1
        assert set_aside[0].read_text(encoding="utf-8") == "{not json"
        store.attach(participant_id=user_id, agent_id=uuid4())
        assert json.loads(path.read_text(encoding="utf-8"))["attachments"]


class TestInboundTextDAO:
    def test_defaults_to_a_normal_send(self) -> None:
        item: InboundTextDAO = InboundTextDAO(
            external_user_ref="42", display_name="sid (telegram)", text="hi"
        )

        assert item.force is False
        assert item.external_message_ref is None

    def test_empty_text_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            InboundTextDAO(external_user_ref="42", display_name="sid (telegram)", text="")
