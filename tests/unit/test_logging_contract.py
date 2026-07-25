import ast
from pathlib import Path


def test_best_effort_logs_include_the_caught_error():
    source_root = Path(__file__).parents[2] / "src"
    offenders = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "debug":
                continue
            message = node.args[0]
            if not isinstance(message, ast.Constant) or not isinstance(message.value, str):
                continue
            if "Best-effort operation failed" not in message.value:
                continue
            has_error_arg = len(node.args) > 1
            has_exc_info = any(
                keyword.arg == "exc_info"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
            if not (has_error_arg and has_exc_info):
                offenders.append(path.relative_to(source_root).as_posix())

    assert offenders == []
