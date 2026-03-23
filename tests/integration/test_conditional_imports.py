"""Tests to prevent conditional import bugs (UnboundLocalError).

Scans all source files for imports inside conditional blocks (if/try without
fallback) where the imported name is later used outside that block scope.
This class of bug causes:
    'cannot access local variable X where it is not associated with a value'
"""

import ast
import os
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"


class _ScopeTracker(ast.NodeVisitor):
    """AST visitor that detects imports trapped inside conditional blocks."""

    def __init__(self) -> None:
        self.issues: list[str] = []
        self.unparseable_files: list[str] = []
        self._filepath = ""

    def check_file(self, filepath: str) -> None:
        self._filepath = filepath
        try:
            with open(filepath, encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filepath)
            self.visit(tree)
        except SyntaxError as e:
            rel = os.path.relpath(filepath, SRC_DIR)
            self.unparseable_files.append(f"{rel}: {e}")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._analyze_function(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    # ------------------------------------------------------------------
    def _analyze_function(self, func: ast.FunctionDef) -> None:
        cond_imports: dict[str, list[tuple[int, ast.AST]]] = {}
        fallback_names: set[str] = set()
        uncond_imports: dict[str, list[int]] = {}

        self._scan_body(
            func.body, cond_imports, fallback_names, uncond_imports, depth=0
        )

        for name, locations in cond_imports.items():
            if name in fallback_names:
                continue

            uncond_lines = uncond_imports.get(name, [])

            for node in ast.walk(func):
                if not (
                    isinstance(node, ast.Name)
                    and node.id == name
                    and isinstance(node.ctx, ast.Load)
                ):
                    continue

                use_line = node.lineno

                if any(self._node_contains(bn, node) for _, bn in locations):
                    continue

                if any(ul < use_line for ul in uncond_lines):
                    continue

                imp_line = locations[0][0]
                rel = os.path.relpath(self._filepath, SRC_DIR)
                self.issues.append(
                    f"{rel}:{use_line} - '{name}' used but only imported "
                    f"conditionally at line {imp_line} (function "
                    f"'{func.name}' line {func.lineno})"
                )
                break

    # ------------------------------------------------------------------
    def _scan_body(self, stmts, cond_imports, fallback_names, uncond_imports, depth):
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            if isinstance(stmt, ast.If):
                self._collect_imports_from(stmt.body, cond_imports, stmt)
                self._collect_imports_from(stmt.orelse, cond_imports, stmt)
                self._scan_body(
                    stmt.body, cond_imports, fallback_names, uncond_imports, depth + 1
                )
                self._scan_body(
                    stmt.orelse, cond_imports, fallback_names, uncond_imports, depth + 1
                )

            elif isinstance(stmt, ast.Try):
                self._collect_imports_from(stmt.body, cond_imports, stmt)
                for handler in stmt.handlers:
                    for hstmt in handler.body:
                        if isinstance(hstmt, ast.Assign):
                            for target in hstmt.targets:
                                if isinstance(target, ast.Name):
                                    fallback_names.add(target.id)
                        elif isinstance(hstmt, (ast.ImportFrom, ast.Import)):
                            for alias in hstmt.names:
                                fallback_names.add(alias.asname or alias.name)
                for fstmt in stmt.finalbody:
                    if isinstance(fstmt, (ast.ImportFrom, ast.Import)):
                        for alias in fstmt.names:
                            fallback_names.add(alias.asname or alias.name)
                self._collect_imports_from(stmt.finalbody, cond_imports, stmt)
                self._scan_body(
                    stmt.body, cond_imports, fallback_names, uncond_imports, depth + 1
                )
                self._scan_body(
                    stmt.finalbody,
                    cond_imports,
                    fallback_names,
                    uncond_imports,
                    depth + 1,
                )

            elif isinstance(stmt, (ast.For, ast.While, ast.With)):
                self._collect_imports_from(stmt.body, cond_imports, stmt)
                self._scan_body(
                    stmt.body, cond_imports, fallback_names, uncond_imports, depth + 1
                )

            elif isinstance(stmt, (ast.ImportFrom, ast.Import)) and depth == 0:
                for alias in stmt.names:
                    n = alias.asname or alias.name
                    uncond_imports.setdefault(n, []).append(stmt.lineno)

    def _collect_imports_from(self, stmts, cond_imports, block_node):
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(stmt, (ast.ImportFrom, ast.Import)):
                for alias in stmt.names:
                    n = alias.asname or alias.name
                    cond_imports.setdefault(n, []).append((stmt.lineno, block_node))
            if hasattr(stmt, "body") and isinstance(stmt.body, list):
                self._collect_imports_from(stmt.body, cond_imports, block_node)
            if hasattr(stmt, "orelse") and isinstance(stmt.orelse, list):
                self._collect_imports_from(stmt.orelse, cond_imports, block_node)
            if hasattr(stmt, "handlers"):
                for h in stmt.handlers:
                    self._collect_imports_from(h.body, cond_imports, block_node)

    @staticmethod
    def _node_contains(parent, target) -> bool:
        return any(node is target for node in ast.walk(parent))


def _collect_all_python_files():
    """Return all .py files under src/."""
    return sorted(SRC_DIR.rglob("*.py"))


class TestConditionalImports:
    """Ensure no import is trapped inside a conditional block without fallback."""

    def test_no_conditional_import_leaks(self):
        """Scan all src/ files for imports that only exist inside
        conditional blocks but are referenced outside them.

        This catches bugs like:
            if condition:
                from module import func
                func(...)  # OK
            func(...)  # UnboundLocalError if condition was False
        """
        tracker = _ScopeTracker()
        py_files = _collect_all_python_files()
        assert py_files, f"No Python files found in {SRC_DIR}"

        for py_file in py_files:
            tracker.check_file(str(py_file))

        if tracker.unparseable_files:
            pytest.fail(
                "Failed to parse source files:\n\n"
                + "\n".join(f"  {f}" for f in tracker.unparseable_files)
            )

        if tracker.issues:
            msg = (
                "Conditional import leak(s) detected - these will cause "
                "'cannot access local variable' errors at runtime:\n\n"
                + "\n".join(f"  {issue}" for issue in tracker.issues)
            )
            pytest.fail(msg)
