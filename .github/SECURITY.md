# Security Policy

SYSTEM ENGINEERING is a **foundation / development** system: a reference Python
CLI, an installer, runtime adapters, MCP servers and a local read-only console.
Security reports are taken seriously, but no response-time guarantee is offered.

## Supported versions

Only the latest commit on the `main` branch is maintained. Older commits, forks,
local copies and generated adapters are not patched.

## What is in scope

- `SCRIPTS/` — the reference CLI (`se.py`, `se_core/`) and its MCP servers
- `SE-INSTALLER/` — bootstrap, installer and TUI
- `SE-CONSOLE/` — the local, read-only web console
- `INTEGRATIONS/` — runtime adapters and the code they generate
- `CORE/`, `SCHEMAS/`, `POLICIES/` — contracts, schemas and policy definitions
  where a weakness would let work bypass a gate, an evidence rule or a permission

Out of scope: vulnerabilities in third-party runtimes, models or packages that
SYSTEM ENGINEERING only consumes (report those upstream), and findings that
require an already-compromised machine.

## Reporting a vulnerability

**Do not open a public issue, discussion or pull request with exploit details,
proof-of-concept code, secrets or personal data.**

There is **no private reporting channel available today**: GitHub's private
vulnerability reporting (the "Report a vulnerability" button on the repository's
Security → Advisories page) is turned off for this repository, and no security
email address is published. Do not send technical details to a public page.

Until a private channel exists:

1. Open an issue titled `Security contact request` with **no technical detail** —
   only that you have a security report and need a private channel:
   <https://github.com/SHEMASOFT/SYSTEM-ENGINEERING/issues/new>
2. Wait for the maintainer's reply. He will either say how he wants to receive the
   report, or enable GitHub's private vulnerability reporting so the Security tab
   form becomes available.
3. Send the report (affected version or commit, affected component, steps to
   reproduce, impact and any suggested fix) **only after a channel is confirmed**.

If no channel is confirmed, the project cannot currently receive the report
privately: say so in the issue instead of disclosing the flaw in public.

Please give the maintainer a reasonable window to fix the issue before any public
disclosure, and do not test against systems or data you do not own or have
explicit permission to test.

## What happens next

The maintainer's intent, within the limits of a project maintained in his own
time — no response-time guarantee is offered:

- Review the report and assess its severity.
- If the report is confirmed, fix it on `main`, or record the accepted risk with
  its evidence in the repository.
- Credit you in the fix's commit or release notes, if you want it.

> Maintainer note: enabling GitHub private vulnerability reporting
> (Settings → Security and quality → Advanced Security → Private vulnerability
> reporting) would give the project a real private channel, and this section
> should then point straight at that form. Until then, no private channel is
> claimed here.
