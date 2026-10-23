---
name: Bug report
about: Report a reproducible problem in SYSTEM ENGINEERING
title: "[bug] "
labels: bug
assignees: ""
---

<!--
Before opening this issue:
- Run `python SCRIPTS/se.py doctor` and `python SCRIPTS/se.py validate`.
- Search the existing issues for the same problem.
- Do not paste credentials, tokens, private paths or personal data.
  Security vulnerabilities go through SECURITY.md, never a public issue.
-->

## What happened

<!-- One or two sentences. What did you run, and what went wrong? -->

## What you expected

<!-- What should have happened instead? -->

## Steps to reproduce

1.
2.
3.

## Environment

| Field | Value |
|---|---|
| OS | <!-- Windows / WSL / Linux + version --> |
| Python | <!-- `python --version` --> |
| How SE was installed | <!-- `git clone` only / bootstrap.ps1 / install.sh / tui --> |
| SE version or commit | <!-- `VERSION` file, or `git rev-parse --short HEAD` --> |
| Runtime | <!-- OpenCode / Claude Code / Codex / none --> |

## Health check output

```text
<!-- paste the full output of: python SCRIPTS/se.py doctor  (or python3 on Linux/macOS) -->
```

## Logs or traceback

```text
<!-- paste the relevant output; redact secrets and private paths -->
```
