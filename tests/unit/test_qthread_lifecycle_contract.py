"""Static guardrails for native Qt thread lifetime safety."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def _assigned_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_assigned_names(item) for item in target.elts))
    return set()


def _assigns_finished(target: ast.expr, *, allow_bare: bool) -> bool:
    return (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
        and target.attr == "finished"
    ) or (allow_bare and "finished" in _assigned_names(target))


def _finished_shadowing_offenders(root: Path) -> list[str]:
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not any(
                isinstance(base, ast.Name) and base.id in {"QThread", "ManagedQThread"}
                for base in node.bases
            ):
                continue
            for statement in node.body:
                targets = []
                if isinstance(statement, ast.Assign):
                    targets = statement.targets
                elif isinstance(statement, ast.AnnAssign):
                    targets = [statement.target]
                if any(_assigns_finished(target, allow_bare=True) for target in targets):
                    offenders.append(f"{path.relative_to(root)}:{node.name}")
                    break
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for nested in ast.walk(statement):
                        nested_targets = (
                            nested.targets if isinstance(nested, ast.Assign)
                            else [nested.target] if isinstance(nested, ast.AnnAssign)
                            else []
                        )
                        if any(_assigns_finished(target, allow_bare=False) for target in nested_targets):
                            offenders.append(f"{path.relative_to(root)}:{node.name}")
                            break
                    else:
                        continue
                    break
    return offenders


def test_qthread_subclasses_do_not_shadow_native_finished_signal():
    assert _finished_shadowing_offenders(SRC) == []


def test_qthread_shadowing_guard_catches_instance_assignment(tmp_path):
    (tmp_path / "bad.py").write_text(
        "class BadThread(QThread):\n"
        "    def __init__(self):\n"
        "        self.finished: object = object()\n",
        encoding="utf-8",
    )

    assert _finished_shadowing_offenders(tmp_path) == ["bad.py:BadThread"]


def test_qthread_shadowing_guard_ignores_method_local_finished(tmp_path):
    (tmp_path / "good.py").write_text(
        "class GoodThread(QThread):\n"
        "    def run(self):\n"
        "        finished = True\n",
        encoding="utf-8",
    )

    assert _finished_shadowing_offenders(tmp_path) == []


def test_qthread_cleanup_never_uses_force_terminate():
    reviewed_non_qthread_calls = {
        ("app/cleanup.py", "child"),
        ("services/launch_service.py", "process"),
        ("services/customization_service.py", "player"),
        ("ui/utils/audio_utils.py", "process"),
        ("ui/dialogs/mod_diagnostics_dialog.py", "process"),
    }
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "terminate":
                continue
            source = ast.get_source_segment(text, node.func.value) or ""
            relative = path.relative_to(SRC).as_posix()
            if (relative, source) not in reviewed_non_qthread_calls:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")

    assert offenders == []
