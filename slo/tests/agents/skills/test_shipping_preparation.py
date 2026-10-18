"""Documentary shipping boundaries; these tests do not authorize publication."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_vertical_user_block_preserves_wording_without_trailing_spaces() -> None:
    """Pin the user's block exactly except the authorized whitespace cleanup."""
    text = (ROOT / "skills/coding/solution-design/SKILL.md").read_text(encoding="utf-8")
    block = text.split("## Vertical solution design\n\n")[1].split("**Design order:**")[0]
    assert block == (
        "- Always design a complete solution involving all the components in the systems.\n"
        "- For instance if the system contains a\n"
        "  - frontend, backend, task worker, database, and service\n"
        "  - And if a feature touches all the components, your solution should be structure "
        "as completely deliverable chunks.\n"
        "  - Designing and executing just the backend is a horizontal chunk and can lead "
        "to gaps in the interfaces and seams.\n"
        "  - Always plan for a full vertical slice of self contained work when relevant.\n\n"
    )
    assert "Include only necessary\nparticipants; do not invent a frontend for a CLI-only workflow." in text


def test_shipping_retains_explicit_authorization_and_message_before_commit() -> None:
    """Characterize preserved gates without restoring removed mode exceptions."""
    text = (ROOT / "skills/git-ops/ship-feature/SKILL.md").read_text(encoding="utf-8")
    assert "## Mode\n" not in text
    assert "proceed without pausing" not in text
    assert text.count("wait for explicit approval before continuing") == 2
    assert "Confirm push? (yes/no)" in text
    assert "Confirm merge? (yes/no)" in text
    assert "unless the user explicitly requested it. Confirm-first is the default." in text
    assert "Always show the commit message before executing `git commit`." in text
    assert text.index("Always show the proposed message before committing") < text.index("## Step 6 — Commit")
    workflow = (ROOT / "skills/orchestration/workflows/SKILL.md").read_text(encoding="utf-8")
    assert "explicit operator authorization" in workflow


def test_headless_isolation_boundary_is_historical_not_checkout_relative() -> None:
    """Keep the guide truthful before and after integration without changing launch code."""
    text = (ROOT / "skills/orchestration/headless-orchestration/SKILL.md").read_text(encoding="utf-8")
    section = text.split("Version boundary:")[1].split("### Serial phases")[0]
    assert "This feature worktree predates" not in section
    assert "historical base `7625be3a251339a5c434c27aef721359d52da872`" in section
    assert "`2eca91fcd7d7d1bfca9a0012292c31f882f290b5`" in section
    assert "`sys.executable -I -m src.cli`" in section
    assert "`sys.executable -m src.cli` (no `-I`)" in section
    assert "verify the actual runtime version independently" in section
    assert "Do not remove `-I`" in section
    assert "Shell/CI" in section


def test_research_distinguishes_relocation_baseline_from_accepted_amendments() -> None:
    """Keep preservation provenance historical while retaining frozen exclusions."""
    text = (ROOT / "RESEARCH.md").read_text(encoding="utf-8")
    section = text.split("## Feature 95 scoped skill maintenance")[1].split("## Verification")[0]
    assert "original relocation baseline" in section
    assert "mode-removal" in section
    assert "headless reasoning" in section
    assert "five moved bodies" in section
    assert "runtime user/workflow override precedence are unchanged" in section
    assert "scheduled TUI skills are explicitly frozen" in section
    assert "only that exact source/target pair" in section
