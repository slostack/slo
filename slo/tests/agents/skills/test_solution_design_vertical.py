"""Vertical design documentary contracts, independent of example frameworks."""

import hashlib
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[3] / "skills/coding/solution-design/SKILL.md"


@pytest.mark.parametrize(
    ("heading", "contracts"),
    [
        ("Always explain the current state", ("verified paths", "greenfield", "by behavior")),
        (
            "First design step: domains and intuitive data structures",
            (
                "| Meaning |",
                "| Ownership |",
                "| Representation |",
                "| Identity and lifetime |",
                "| Rules |",
                "| Operations |",
                "| Authority |",
                "absent",
                "runtime validation",
            ),
        ),
        ("Identify workflows end to end", ("User action", "Persisted outcome", "queued", "correlation")),
        (
            "Define interfaces before implementation bodies",
            ("PublishMessages.execute", "Caller:", "Guarantees:", "Failures:"),
        ),
        (
            "Application services: one public workflow entry point",
            ("validate_request", "publish_effects", "idempotency", "atomic"),
        ),
        (
            "Design tests alongside the contracts",
            (
                "End-to-end journey",
                "Application service",
                "Domain service",
                "Focused unit test",
                "Boundary / contract test",
                "eventual outcome",
            ),
        ),
        (
            "Present specifications top down; implementation details last",
            ("8. Tests and acceptance criteria", "SQLAlchemy", "pure SQL", "backfill", "rollback"),
        ),
        (
            "Keep the result readable and concise",
            ("not applicable", "Design completion", "every state change", "boundary contract"),
        ),
    ],
)
def test_vertical_subsection_contract(heading: str, contracts: tuple[str, ...]) -> None:
    """Each subsection states its required behaviors, not merely its title."""
    text = PATH.read_text()
    section = text.split(f"### {heading}\n")[1].split("\n##")[0]
    for contract in contracts:
        assert contract in section


def test_original_skill_bytes_survive_only_authorized_reconciliation() -> None:
    """Removing the addendum and four enumerated edits recovers the three-way source pin."""
    text = PATH.read_text()
    start = text.index("\n## Vertical solution design\n")
    end = text.index("\n## 4. Design", start)
    text = text[:start] + text[end:]
    text = text.replace(
        "and saving design.md, and design complete vertical solutions domain-first.",
        "and saving design.md.",
    )
    text = text.replace(
        "- Design complete vertical slices domain-first and present them journey-first; see `## Vertical solution design`.\n",
        "",
    )
    text = text.replace(
        "When the design covers a full vertical slice, apply the presentation order in\n"
        "`## Vertical solution design`: its sections refine this document's Approach,\n"
        "Modules and seams, and Main journeys rather than replacing this contract.\n\n",
        "",
    )
    text = text.replace(
        "\n- Current state is explained with verified paths before proposed changes.\n"
        "- Every state change has an identified owning domain.\n"
        "- Interfaces and their behavioral documentation precede implementation bodies.\n"
        "- Each application service exposes one primary public execution entry point.\n"
        "- Journey, application-service, domain, focused, and boundary tests are identified with setup and assertions.\n"
        "- Database changes are described as migrations.\n",
        "",
    )
    assert hashlib.sha256(text.encode()).hexdigest() == (
        "244bf2d0f2841e6427c7dc8f913a3a43d52cc94871de601d194a8b1cabda8ebc"
    )


def test_vertical_orders_and_equivalent_examples() -> None:
    """Design and explanation orders differ; boundary examples share one concept."""
    text = PATH.read_text()
    assert "and design complete vertical solutions domain-first" in text
    assert "rather than replacing this contract" in text
    assert "Database changes are described as migrations" in text
    assert (
        text.index("## 3. Define")
        < text.index("\n## Vertical solution design\n")
        < text.index("## 4. Design")
    )
    for phrase in (
        "Design order:",
        "Presentation order:",
        "class OutboundMessageDAO",
        "type OutboundMessageDAO struct",
        "interface OutboundMessageDAO",
        'json:"message_id"',
        "readonly messageId: string",
        "message_id: str = Field(min_length=1)",
    ):
        assert phrase in text
