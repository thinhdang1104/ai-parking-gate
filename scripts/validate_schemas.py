"""Validate project JSON/YAML/SQL schemas and MCP configuration."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
MCP_CONFIG_PATH = ROOT / ".agents" / "mcp_config.json"

_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|pwd|secret|token|api_?key|access_?key|private_?key|credential|dsn)",
    re.IGNORECASE,
)
_ENV_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}$")
_HARDCODED_TOKEN_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,})"
)
_DSN_CRED_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^:@/]+):([^@/]+)@")


def _is_safe_secret_value(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return True
    if _ENV_PLACEHOLDER_RE.fullmatch(stripped):
        return True
    dsn_match = _DSN_CRED_RE.match(stripped)
    if dsn_match:
        password_part = dsn_match.group(2)
        return bool(_ENV_PLACEHOLDER_RE.fullmatch(password_part))
    return False


def _scan_mcp_secrets(node: Any, path: str, errors: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            if isinstance(value, str) and _SENSITIVE_KEY_RE.search(str(key)):
                if not _is_safe_secret_value(value):
                    errors.append(
                        f"[MCP] {child_path}: sensitive value must use ${{...}} placeholder"
                    )
            _scan_mcp_secrets(value, child_path, errors)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            _scan_mcp_secrets(item, f"{path}[{idx}]", errors)
    elif isinstance(node, str):
        if _HARDCODED_TOKEN_RE.search(node):
            errors.append(f"[MCP] {path}: looks like a hardcoded token/API key")
        dsn_match = _DSN_CRED_RE.match(node.strip())
        if dsn_match and not _ENV_PLACEHOLDER_RE.fullmatch(dsn_match.group(2)):
            errors.append(
                f"[MCP] {path}: DSN password must use ${{...}} placeholder"
            )


def validate_mcp_config() -> list[str]:
    errors: list[str] = []
    if not MCP_CONFIG_PATH.exists():
        return errors
    try:
        raw = MCP_CONFIG_PATH.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"[MCP] .agents/mcp_config.json invalid JSON: {exc}"]

    _scan_mcp_secrets(parsed, "", errors)
    return errors


def validate_json_schemas() -> list[str]:
    errors: list[str] = []
    json_files = sorted(SCHEMAS_DIR.glob("*.json"))
    for path in json_files:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            rel = path.relative_to(ROOT)
            errors.append(f"[SCHEMA] {rel} invalid JSON: {exc}")
    return errors


def validate_mysql_schema() -> list[str]:
    sql_path = SCHEMAS_DIR / "mysql_schema.sql"
    if not sql_path.is_file():
        return ["[SCHEMA] Missing schemas/mysql_schema.sql"]
    sql_text = sql_path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?plate_recognition_history[`\"\]]?",
        re.IGNORECASE,
    )
    if not pattern.search(sql_text):
        return [
            "[SCHEMA] schemas/mysql_schema.sql must define table 'plate_recognition_history'"
        ]
    return []


def validate_openapi_schema() -> list[str]:
    openapi_path = SCHEMAS_DIR / "openapi.yaml"
    if not openapi_path.is_file():
        return ["[SCHEMA] Missing schemas/openapi.yaml"]
    text = openapi_path.read_text(encoding="utf-8", errors="replace")

    if yaml is not None:
        try:
            doc = yaml.safe_load(text)
        except Exception as exc:  # pragma: no cover - defensive YAML check
            return [f"[SCHEMA] schemas/openapi.yaml invalid YAML: {exc}"]
        if not isinstance(doc, dict):
            return ["[SCHEMA] schemas/openapi.yaml root must be a mapping"]
        errors: list[str] = []
        if "openapi" not in doc:
            errors.append("[SCHEMA] schemas/openapi.yaml missing 'openapi:' key")
        paths = doc.get("paths")
        if not isinstance(paths, dict):
            errors.append("[SCHEMA] schemas/openapi.yaml missing 'paths:' mapping")
        else:
            for endpoint in ("/api/health", "/api/metrics"):
                if endpoint not in paths:
                    errors.append(
                        f"[SCHEMA] schemas/openapi.yaml missing path '{endpoint}'"
                    )
        return errors

    errors = []
    if not re.search(r"(?m)^openapi\s*:", text):
        errors.append("[SCHEMA] schemas/openapi.yaml missing 'openapi:' key")
    if not re.search(r"(?m)^paths\s*:", text):
        errors.append("[SCHEMA] schemas/openapi.yaml missing 'paths:' key")
    for endpoint in ("/api/health", "/api/metrics"):
        if not re.search(rf"(?m)^\s+['\"]?{re.escape(endpoint)}['\"]?\s*:", text):
            errors.append(
                f"[SCHEMA] schemas/openapi.yaml missing path '{endpoint}'"
            )
    return errors


def main() -> int:
    errors = validate_mcp_config()
    if not SCHEMAS_DIR.exists():
        if errors:
            print("SCHEMA VALIDATION FAILED:")
            for err in errors:
                print(f"  - {err}")
            return 1
        print("SKIP: schemas/ directory does not exist yet")
        return 0

    errors.extend(validate_json_schemas())
    errors.extend(validate_mysql_schema())
    errors.extend(validate_openapi_schema())

    if errors:
        print("SCHEMA VALIDATION FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("SCHEMAS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
