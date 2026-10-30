#!/usr/bin/env python3
"""Pre-publication audit for the public tree: secrets, PII, internal references, licence files.

Stdlib only. Exit code 0 = clean, 1 = findings. Run before every push to the public repo
and in CI:  python3 scripts/audit_public.py [ROOT]

It scans every text file below ROOT (except .git and this script) for patterns that must
never appear in a public repository: credentials, private network addresses, personal
addresses, and references to private repositories or internal work items.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SELF = Path(__file__).resolve()
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "dist"}
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".yml",
    ".yaml",
    ".txt",
    ".toml",
    ".cfg",
    ".sh",
    ".gitignore",
    "",
}
# A synthetic bearer value that tests use on purpose (documented, not a credential).
ALLOWED_LITERALS = ("test-token-1234567890",)

PATTERNS: dict[str, re.Pattern[str]] = {
    "GitHub token": re.compile(
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|github_pat_[A-Za-z0-9_]{20,}"
    ),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "API key shape": re.compile(
        r"\bsk-[A-Za-z0-9]{20,}\b|\bAKIA[0-9A-Z]{16}\b|\bxox[abp]-[A-Za-z0-9-]{10,}"
    ),
    "long bearer value": re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{24,}={0,2}"),
    "private IPv4 (192.168/10/172.16-31)": re.compile(
        r"\b192\.168\.\d{1,3}\.\d{1,3}\b|\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"
    ),
    "e-mail address": re.compile(
        r"\b[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com\b)[A-Za-z0-9-]+\.[A-Za-z]{2,}\b"
    ),
    "internal work item": re.compile(r"\bWI-\d{4}\b"),
    "private repository": re.compile(
        r"kinetic-it/(?:homeassistant|lokale_alexa|lokale-alexa-website|work-items|governance|"
        r"firma|non-homelab|seriescheck|nexis-app-bridge|hermes-agent|kinetic-it)\b"
    ),
    "internal host/system name": re.compile(
        r"\b(?:werkstatt|hass-os|nexis|hermes-speaker|VM ?20\d|VM ?30\d|LXC ?\d{3}"
        r"|Proxmox|florian)\b",
        re.IGNORECASE,
    ),
    "internal process wording": re.compile(
        r"\b(?:Owner-Go|Regel 28|Werkstatt-Protokoll|CHAT-STARTER)\b"
    ),
}


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.resolve() == SELF:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"LICENSE", "NOTICE"}:
            yield path


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"{path.relative_to(root)}: not valid UTF-8 text")
            continue
        for literal in ALLOWED_LITERALS:
            text = text.replace(literal, "")
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"{path.relative_to(root)}:{number}: {label}")
    return findings


def check_licence_files(root: Path) -> list[str]:
    problems: list[str] = []
    licence = root / "LICENSE"
    if not licence.is_file() or "MIT License" not in licence.read_text(encoding="utf-8"):
        problems.append("LICENSE missing or not MIT")
    notice = root / "NOTICE"
    if not notice.is_file():
        problems.append("NOTICE missing")
    else:
        text = notice.read_text(encoding="utf-8")
        for needle in (
            "Codename-11/hermes-homeassistant",
            "Bailey Dixon",
            "Permission is hereby granted",
        ):
            if needle not in text:
                problems.append(f"NOTICE lacks upstream attribution: {needle!r}")
    return problems


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else SELF.parents[1]
    problems = scan(root) + check_licence_files(root)
    for problem in problems:
        print(f"AUDIT FINDING: {problem}")
    print("PUBLIC_AUDIT=" + ("FAIL" if problems else "PASS"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
