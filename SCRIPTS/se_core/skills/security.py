"""Static security scanner for skill content.

Treats third-party skills as untrusted input. Performs proportionate static
checks on SKILL.md and SKILL.json content. Cannot prove a skill is safe.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# Patterns that indicate potential security risks in skill content
SUSPICIOUS_PATTERNS = [
    (r"rm\s+-rf", "destructive command: rm -rf"),
    (r"del\s+/[sfq]", "destructive command: del /s or /f or /q"),
    (r"curl\s+.*\|\s*(bash|sh|python)", "pipe to shell: curl | bash/sh/python"),
    (r"wget\s+.*\|\s*(bash|sh|python)", "pipe to shell: wget | bash/sh/python"),
    (r"eval\s*\(", "dynamic code execution: eval()"),
    (r"exec\s*\(", "dynamic code execution: exec()"),
    (r"os\.system\s*\(", "shell execution: os.system()"),
    (r"subprocess\.(call|run|Popen)\s*\(", "shell execution: subprocess"),
    (r"__import__\s*\(", "dynamic import: __import__()"),
    (r"base64\.b64decode", "base64 decoding (possible obfuscation)"),
    (r"password|secret|token|api[_\s-]?key|credential", "possible credential reference"),
    (r"requests\.(get|post|put|delete)\s*\(", "network request: requests"),
    (r"urllib\.request", "network request: urllib"),
    (r"socket\.", "network socket usage"),
    (r"open\s*\(\s*['\"]/", "absolute path file access"),
]

# Severity levels
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"


def scan_skill_content(content: str, filename: str = "SKILL.md") -> List[Dict[str, Any]]:
    """Scan skill content for suspicious patterns.

    Returns a list of findings, each with:
    - pattern: the matched pattern description
    - severity: high/medium/low
    - line: line number (1-based)
    - snippet: matched text (truncated)

    This is a static check. It cannot prove a skill is safe.
    """
    findings = []
    lines = content.splitlines()
    for i, line in enumerate(lines, 1):
        for pattern, description in SUSPICIOUS_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                # Determine severity
                if "destructive" in description or "exec" in description or "eval" in description:
                    severity = SEVERITY_HIGH
                elif "network" in description or "credential" in description or "shell" in description:
                    severity = SEVERITY_MEDIUM
                else:
                    severity = SEVERITY_LOW

                findings.append({
                    "pattern": description,
                    "severity": severity,
                    "line": i,
                    "snippet": line.strip()[:120],
                    "file": filename,
                })
    return findings


def scan_skill_dir(skill_dir: str, skill_md_content: str, skill_json: Dict[str, Any]) -> Dict[str, Any]:
    """Scan a skill directory for security issues.

    Returns a report with:
    - findings: list of suspicious patterns found
    - risk_level: overall risk (low/medium/high)
    - has_license: whether license info is present
    - has_source: whether source URL is present
    - issues: list of structural issues
    """
    findings = scan_skill_content(skill_md_content, "SKILL.md")

    issues = []

    # Check for license
    has_license = bool(skill_json.get("license"))
    if not has_license:
        issues.append("missing license")

    # Check for source URL
    has_source = bool(skill_json.get("source_url"))
    if not has_source and skill_json.get("source") not in ("se-native", None):
        issues.append("missing source URL for third-party skill")

    # Check for description
    if not skill_json.get("description") and not skill_json.get("purpose"):
        issues.append("missing description/purpose")

    # Check for dependencies
    deps = skill_json.get("dependencies", [])
    if deps:
        issues.append(f"has {len(deps)} dependencies: {deps}")

    # Determine overall risk level
    if any(f["severity"] == SEVERITY_HIGH for f in findings):
        risk_level = SEVERITY_HIGH
    elif any(f["severity"] == SEVERITY_MEDIUM for f in findings):
        risk_level = SEVERITY_MEDIUM
    elif findings or issues:
        risk_level = SEVERITY_LOW
    else:
        risk_level = "none"

    return {
        "findings": findings,
        "risk_level": risk_level,
        "has_license": has_license,
        "has_source": has_source,
        "issues": issues,
        "finding_count": len(findings),
    }
