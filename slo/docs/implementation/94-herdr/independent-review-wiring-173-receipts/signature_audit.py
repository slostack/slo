"""Read-only audit of newly added definitions in the finite tracked wiring scope."""

import ast
import subprocess
from pathlib import Path

BASE = "d0e3a756689f2675e5507034d43cd8b272d3c6b8"
PATHS = (
    "src/agents/slo_agent/agent.py",
    "src/agents/slo_agent/sessions/service.py",
    "src/agents/slo_agent/sessions/dao.py",
    "src/agents/slo_agent/orchestrator/bootstrap.py",
    "src/cli/app.py",
    "src/cli/typer_dispatch.py",
    "src/cli/headless.py",
    "src/cli/headless_request.py",
    "src/scheduling/runtime/subprocess_runner.py",
    "src/tui/app.py",
    "src/tui/visualizer_launcher.py",
    "src/tui/workflow_visualizer_loader.py",
    "src/tui/workflows/dao.py",
    "src/tui/workflows/service.py",
    "src/tui/workflows/renderer.py",
    "src/tui/widgets/usage_status_bar.py",
    "tests/cli/test_headless.py",
    "tests/tui/test_app.py",
    "tests/tui/test_workflow_receive_path.py",
    "tests/tui/workflows/test_workflow_app_service.py",
    "tests/tui/workflows/test_workflow_renderer.py",
    "tests/tui/test_visualizer_launcher.py",
    "tests/tui/test_workflow_visualizer_loader.py",
    "tests/tui/test_subagent_event_routing.py",
    "tests/scheduling/test_runtime_helpers.py",
)


def definitions(*, text: str) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Index definitions by lexical ownership so old signatures remain separate."""
    found: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def visit(*, node: ast.AST, scope: str) -> None:
        """Walk statement containers while retaining class and function names."""
        for child in ast.iter_child_nodes(node):
            name = scope
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{scope}.{child.name}"
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[name] = child
            visit(node=child, scope=name)

    visit(node=ast.parse(text), scope="")
    return found


def main() -> None:
    """Compare actual app-relative paths with base blobs without modifying Git."""
    count = 0
    failures: list[str] = []
    for filename in PATHS:
        path = Path(filename)
        assert path.is_file(), filename
        previous = subprocess.check_output(["git", "show", f"{BASE}:slo/{filename}"], text=True)
        old = definitions(text=previous)
        for name, node in definitions(text=path.read_text()).items():
            if name in old:
                continue
            count += 1
            arguments = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            arguments += [arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None]
            missing = [arg.arg for arg in arguments if arg.arg not in ("self", "cls") and arg.annotation is None]
            if node.returns is None:
                missing.append("return")
            if missing:
                failures.append(f"{filename}:{node.lineno} {name}: {', '.join(missing)}")
    print(f"Checked {len(PATHS)} existing paths, {count} new lexical definitions.")
    print("\n".join(failures) if failures else "No incomplete new signatures.")
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
