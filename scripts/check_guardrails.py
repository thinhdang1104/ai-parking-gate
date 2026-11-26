"""Automated architecture and maintainability guardrails for DATN2."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
DOMAIN_DIR = SRC_DIR / "backend" / "domain"

MAX_LINES_PER_FILE = 400
FORBIDDEN_DOMAIN_IMPORTS = {
    "fastapi",
    "uvicorn",
    "starlette",
    "mysql",
    "ultralytics",
    "torch",
    "torchvision",
    "facenet_pytorch",
    "gradio",
}


def check_file_sizes() -> list[str]:
    errors: list[str] = []
    if not SRC_DIR.exists():
        return errors
    for path in sorted(SRC_DIR.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".js"}:
            continue
        line_count = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        if line_count > MAX_LINES_PER_FILE:
            rel = path.relative_to(ROOT)
            errors.append(
                f"[SIZE] {rel}: {line_count} lines (limit {MAX_LINES_PER_FILE})"
            )
    return errors


def check_domain_purity() -> list[str]:
    errors: list[str] = []
    if not DOMAIN_DIR.exists():
        return errors
    for path in sorted(DOMAIN_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_pkg = alias.name.split(".", 1)[0]
                    if top_pkg in FORBIDDEN_DOMAIN_IMPORTS:
                        errors.append(
                            f"[DOMAIN] {rel}:{node.lineno} imports forbidden module '{alias.name}'"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_pkg = node.module.split(".", 1)[0]
                if top_pkg in FORBIDDEN_DOMAIN_IMPORTS:
                    errors.append(
                        f"[DOMAIN] {rel}:{node.lineno} imports from forbidden module '{node.module}'"
                    )
    return errors


def main() -> int:
    errors = check_file_sizes() + check_domain_purity()
    if errors:
        print("GUARDRAILS FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("GUARDRAILS OK (file sizes <= 400 lines, domain layer pure)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
