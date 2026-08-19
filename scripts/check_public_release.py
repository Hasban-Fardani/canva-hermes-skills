#!/usr/bin/env python3
"""Check that this checkout contains only public-safe skill material.

The checker is deliberately conservative about structure and deliberately
quiet about marker values. Private leak markers can be supplied only through
the test-only ``--forbidden-marker`` option or ``HERMES_RELEASE_MARKERS``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT_FILES = {
    ".gitignore",
    "GUIDE.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
}
SKILL_NAMES = {"brand-copy-studio", "social-content-studio"}
SKILL_DIRS = {"agents", "assets", "references", "scripts"}
ALLOWED_SUFFIXES = {".json", ".md", ".py", ".yaml", ".yml"}
EXPECTED_FILES = ROOT_FILES | {
    ".github/workflows/quality.yml",
    "scripts/check_public_release.py",
    "skills/brand-copy-studio/SKILL.md",
    "skills/brand-copy-studio/agents/openai.yaml",
    "skills/brand-copy-studio/assets/access-policy.template.json",
    "skills/brand-copy-studio/assets/brand-profile.template.json",
    "skills/brand-copy-studio/assets/claim-registry.template.json",
    "skills/brand-copy-studio/assets/provenance.template.json",
    "skills/brand-copy-studio/assets/template-registry.template.json",
    "skills/brand-copy-studio/references/access-policy.md",
    "skills/brand-copy-studio/references/canonical-schema.md",
    "skills/brand-copy-studio/references/workflow.md",
    "skills/brand-copy-studio/scripts/test_validate_brand_bundle.py",
    "skills/brand-copy-studio/scripts/validate_brand_bundle.py",
    "skills/social-content-studio/SKILL.md",
    "skills/social-content-studio/agents/openai.yaml",
    "skills/social-content-studio/assets/content-spec.example.json",
    "skills/social-content-studio/assets/indonesian-fluency-fixtures.json",
    "skills/social-content-studio/references/business-operations.md",
    "skills/social-content-studio/references/content-contract.md",
    "skills/social-content-studio/references/creative-quality.md",
    "skills/social-content-studio/references/integrations.md",
    "skills/social-content-studio/scripts/download_canva_export.py",
    "skills/social-content-studio/scripts/test_download_canva_export.py",
    "skills/social-content-studio/scripts/test_validate_content_spec.py",
    "skills/social-content-studio/scripts/validate_content_spec.py",
}
FORBIDDEN_DIR_NAMES = {
    ".hermes",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "cache",
    "caches",
    "exports",
    "receipts",
    "feedback",
    "fingerprints",
    "approvals",
    "measurements",
    "runtime",
    "node_modules",
}

# Build these prefixes instead of storing a real local path in the checker.
LOCAL_ROOT_NAMES = (
    "Users",
    "home",
    "tmp",
    "var",
    "opt",
    "private",
    "controlled",
    "workspace",
    "Volumes",
    "mnt",
    "root",
)
LOCAL_PREFIXES = tuple(f"/{name}/" for name in LOCAL_ROOT_NAMES)
URL_RE = re.compile(r"\bhttps?://[^\s`\"'<>]+", re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:[\\/]", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[ -])?\d{2,4}[ -]\d{3,4}[ -]\d{3,4}(?!\d)")
HANDLE_RE = re.compile(r"(?<![A-Za-z0-9_])@[A-Za-z0-9_.-]{2,}")
SECRET_VALUE_PATTERNS = (
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
    re.compile(r"\b(?:xox[baprs]|gh[pousr])_[A-Za-z0-9-]{16,}\b", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b", re.IGNORECASE),
    re.compile(
        r"(?i)\b(?:access[_-]?token|refresh[_-]?token|client[_-]?secret|api[_-]?key|password|private[_-]?key)"
        r"\s*[:=]\s*[\"']([^\"']{12,})[\"']"
    ),
)
SENSITIVE_OUTPUT_KEYS = {
    "signed_url",
    "signed_urls",
    "export_url",
    "export_urls",
    "runtime_receipt",
}
SAFE_PLACEHOLDERS = {
    "",
    "null",
    "none",
    "placeholder",
    "placeholder-secret",
    "example",
    "example-value",
    "not_available",
}
SAFE_URL_HOSTS = {"example.com"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check a public-safe Hermes skill release.")
    parser.add_argument("root", nargs="?", default=".", help="Checkout root (default: current directory).")
    parser.add_argument(
        "--forbidden-marker",
        action="append",
        default=[],
        help="Test-only private marker; may be repeated and is never printed.",
    )
    return parser.parse_args(argv)


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def material_relpaths(root: Path) -> tuple[str, ...]:
    """Return tracked/intended files, excluding gitignored test caches."""

    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return tuple(sorted(line.strip() for line in result.stdout.splitlines() if line.strip()))
    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() or path.is_symlink()
        )
    )


def iter_files(root: Path) -> Iterable[Path]:
    for name in material_relpaths(root):
        path = root / name
        if ".git" not in path.relative_to(root).parts:
            yield path


def collect_structure_issues(root: Path) -> list[str]:
    issues: list[str] = []
    if not root.is_dir():
        return ["checkout root is not a directory"]

    for name in material_relpaths(root):
        path = root / name
        parts = path.relative_to(root).parts
        if any(part.casefold() in FORBIDDEN_DIR_NAMES for part in parts[:-1]):
            issues.append(f"forbidden directory: {name}")
            continue
        if path.is_symlink():
            issues.append(f"symlink is not allowed: {name}")
            continue
        name = relative(path, root)
        if name not in EXPECTED_FILES:
            issues.append(f"file is not allowlisted: {name}")
            continue
        if not parts:
            issues.append("unexpected root entry")
        elif len(parts) == 1:
            if parts[0] not in ROOT_FILES:
                issues.append(f"unexpected root file: {name}")
        elif parts[0] == ".github":
            if parts != (".github", "workflows", "quality.yml"):
                issues.append(f"unexpected workflow file: {name}")
        elif parts[0] == "scripts":
            if parts != ("scripts", "check_public_release.py"):
                issues.append(f"unexpected release-script file: {name}")
        elif parts[0] == "skills":
            if len(parts) < 3 or parts[1] not in SKILL_NAMES:
                issues.append(f"unexpected skill path: {name}")
            elif len(parts) >= 3 and parts[2] not in {"SKILL.md", *SKILL_DIRS}:
                issues.append(f"unexpected skill entry: {name}")
            elif path.suffix.casefold() not in ALLOWED_SUFFIXES:
                issues.append(f"file type is not allowlisted: {name}")
        else:
            issues.append(f"unexpected top-level path: {name}")
    return issues


def text_issues(path: Path, root: Path, text: str, markers: tuple[str, ...]) -> list[str]:
    name = relative(path, root)
    if name == "scripts/check_public_release.py":
        return []
    issues: list[str] = []
    for match in URL_RE.finditer(text):
        host = match.group(0).split("//", 1)[1].split("/", 1)[0].split(":", 1)[0].casefold()
        if host not in SAFE_URL_HOSTS:
            issues.append(f"URL-like value: {name}")
            break
    if WINDOWS_PATH_RE.search(text) or any(prefix in text for prefix in LOCAL_PREFIXES):
        issues.append(f"absolute local path: {name}")
    if PHONE_RE.search(text):
        issues.append(f"phone-like value: {name}")
    if path.suffix.casefold() in {".md", ".json", ".yaml", ".yml"} and HANDLE_RE.search(text):
        issues.append(f"account-handle-like value: {name}")
    for pattern in SECRET_VALUE_PATTERNS:
        match = pattern.search(text)
        if match and all(value.casefold() not in SAFE_PLACEHOLDERS for value in match.groups() if value):
            issues.append(f"secret-like value: {name}")
            break
    if any(marker and marker.casefold() in text.casefold() for marker in markers):
        issues.append(f"private marker matched: {name}")
    return issues


def walk_values(value: Any, key: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from walk_values(child_value, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from walk_values(child, key)
    else:
        yield key, value


def json_issues(path: Path, root: Path) -> list[str]:
    name = relative(path, root)
    issues: list[str] = []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        issues.append(f"invalid JSON: {name}")
        return issues
    if not isinstance(document, dict):
        issues.append(f"JSON root is not an object: {name}")
        return issues
    lowered_name = path.name.casefold()
    if any(word in lowered_name for word in ("runtime", "receipt", "generated", "result", "output")):
        if "template" not in lowered_name and "example" not in lowered_name:
            issues.append(f"runtime-looking JSON filename: {name}")
    for key, value in walk_values(document):
        if key.casefold() in SENSITIVE_OUTPUT_KEYS and isinstance(value, str) and value.strip():
            issues.append(f"runtime output value: {name}")
            break
    return issues


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root).resolve()
    env_markers = tuple(item.strip() for item in os.environ.get("HERMES_RELEASE_MARKERS", "").split(","))
    markers = tuple(dict.fromkeys(marker for marker in (*args.forbidden_marker, *env_markers) if marker))

    issues = collect_structure_issues(root)
    for path in iter_files(root):
        if path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        issues.extend(text_issues(path, root, text, markers))
        if path.suffix.casefold() == ".json":
            issues.extend(json_issues(path, root))

    if issues:
        for issue in sorted(set(issues)):
            print(f"FAIL: {issue}")
        return 1
    print("PASS: public-safe release checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
