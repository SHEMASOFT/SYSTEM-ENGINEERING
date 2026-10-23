# Support

Where to find help with SYSTEM ENGINEERING, and what to use for each kind of
question.

## Read the documentation first

| What you need | Where |
|---|---|
| Install, run, update | [`DOCS/reference/installation.md`](../DOCS/reference/installation.md) |
| Lifecycle, gates, tasks, artifacts | [`DOCS/reference/core-model.md`](../DOCS/reference/core-model.md) |
| Commands | [`DOCS/reference/commands.md`](../DOCS/reference/commands.md) |
| Work modes (organic / spec / receipt) | [`DOCS/reference/work-modes.md`](../DOCS/reference/work-modes.md) |
| Full documentation index | [`DOCS/README.md`](../DOCS/README.md) |
| Health check of your checkout | `python SCRIPTS/se.py doctor` |

The root [`README.md`](../README.md) also covers requirements, the quickstart and
how the agent layer is generated.

## Ask a question or report a problem

- **Bugs, questions and feature requests** — open an issue:
  <https://github.com/SHEMASOFT/SYSTEM-ENGINEERING/issues>
- Include what you expected, what happened, the exact commands, your OS
  (Windows / WSL / Linux) and the output of `python SCRIPTS/se.py doctor`.
- The bug report form asks for the same information.

## Before you open an issue

- Run `python SCRIPTS/se.py doctor` and `python SCRIPTS/se.py validate`; a failing
  check often names the fix.
- On a fresh machine, open a new terminal after the bootstrap installed Python,
  Node or OpenCode, so the updated `PATH` is loaded.
- Search the existing issues first — the answer may already be there.

## Contributing

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for setup, the CI rules your change
must satisfy, and how to open a pull request. Participation is covered by the
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## Security

Do not report vulnerabilities in a public issue. Follow
[`SECURITY.md`](SECURITY.md).

## Support scope

This is a public project supported through its GitHub issue tracker.
No paid support, service-level agreement or response-time guarantee is offered.
