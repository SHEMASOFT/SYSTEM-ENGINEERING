# Versioning Strategy

Applies to the SYSTEM-ENGINEERING Master System (the "master product"). Coherent with
`DOCS/reference/versioning.md`; this document is the operational strategy for bumps and compatibility.

## Version source

- `VERSION` at the SYSTEM-ENGINEERING root is the single source of the current version.
- `SYSTEM.json` -> `master_system_version` mirrors `VERSION`.
- `MASTER SYSTEM/VERSION` pins the version of the distribution snapshot.

## SemVer 0.x rules

| Change | Bump |
|--------|------|
| Bug fix that does not change contracts, schema or gates | `0.x.z+1` (patch) |
| Backward-compatible addition (new agent, new command, optional field) | `0.x+1.0` (minor) |
| Breaking change (contract rename/removal, gate change, schema incompatibility) | `0.x+1.0` (minor) with a CHANGELOG `BREAKING` marker; normal release is chief |

Semver normalization: `VERSION` files store the **normalized** form (`0.4.0`) without
`v` prefix; git tags and distribution snapshots use the `v` prefix (`v0.4.0`).

## When to bump

1. Any material contract change (agent.json per ADR-0019, commands.json, SKILL.md).
2. Schema change that invalidates existing artifacts (`requirement`/`pattern` in schema).
3. Adapter behavior change that produces different generated assets.
4. New distribution content published to `MASTER SYSTEM/`.

A documentation-only change that does not affect behavior must NOT bump.

## Release automation

`SCRIPTS/release_master.py` automates the mechanical part of a release without
deciding the bump:

```powershell
python SCRIPTS/release_master.py --check
python SCRIPTS/release_master.py --bump patch --reason "fix: describe the change"
python SCRIPTS/release_master.py --bump minor --reason "feat: describe the change"
```

- `--check` verifies `VERSION`, `SYSTEM.json`, `MASTER SYSTEM/VERSION`,
  `MASTER SYSTEM/MANIFEST.json`, the generated OpenCode adapter manifest, and
  the current-version markers in `README.md` and `DOCS/reference/versioning.md`.
- `--bump` updates those references, inserts the release in
  `MASTER SYSTEM/CHANGELOG.md`, regenerates the OpenCode adapter, rebases the
  documentation coverage baseline, and runs `se validate`, `se doctor`, and the
  full test suite.
- `--dry-run` prints the planned transition without writing.
- The script refuses a dirty working tree unless `--allow-dirty` is passed, and
  refuses a major bump while the system is still on `0.x`.
- Historical references are never rewritten. The operator still commits the
  result and creates the `vX.Y.Z` tag after review.

The same flow is available from GitHub Actions: **Release Master System** ->
**Run workflow**, with `patch`/`minor` and a reason. The workflow opens a release
pull request; review and merge it, then create the `vX.Y.Z` tag. The workflow
does not run the full suite itself; CI does that on the resulting pull request.

## Master System compatibility pinning

- `PROJECT.json.master_system_version` declares the floor version a project expects.
- `se doctor` compares project floor vs installed distribution and flags mismatch.
- Projects never copy CORE/SCHEMAS; they depend on the installed distribution (ADR-0016).

## Compatibility matrix (current)

| Master System version | Schema compatibility | OpenCode adapter | Notes |
|-----------------------|----------------------|------------------|-------|
| 0.10.0 | 1 (contract layer + all record schemas) | implemented (`se adapter opencode`) + project bootstrap (`se init <project>`) | Visual Frontend Engineering (ARCH-VFE-001): skill SK-0003, providers playwright/deepseek-vision, capabilities browser.preview/snapshot/screenshot + visual.review, DESIGN.template, demo (TESTS/fixtures/vfe-demo) |
| 0.9.0 | 1 (contract layer + all record schemas) | implemented (`se adapter opencode`) + project bootstrap (`se init <project>`) | Capability Governance (CP-020): canonical capability registry, capability contracts (skill/task/agent/profiles), CMD-0014 `capabilities`, READ_ONLY contractual |
| 0.8.0 | 1 (contract layer + all record schemas) | implemented (`se adapter opencode`) + project bootstrap (`se init <project>`) | Research adaptation & vNEXT (ARCH-ADAPT-001): Project Profile, adapter capabilities, skill kind; decision record ARCH-WORKFLOW-001 (DECISION PENDING) |
| 0.7.0 | 1 (contract layer + all record schemas) | implemented (`se adapter opencode`) + project bootstrap (`se init <project>`) | Project bootstrap & distribution (CHECKPOINT-005) |
| 0.6.0 | 1 (contract layer + all record schemas) | implemented (`se adapter opencode`) | OpenCode adapter (CHECKPOINT-004) |
| 0.5.0 | 1 (decision, config, domain, task, requirement, agent + contract layer) | planned (ADR-0015, ADR-0017, ADR-0020) | Canonical contract layer (CHECKPOINT-003) |
| 0.4.0 | 1 (decision, config, domain, task, requirement, agent) | planned (ADR-0015 applied) | Distribution layer introduced (CHECKPOINT-001) |
| 0.3.x | 1 | none | pre-distribution |

## Deprecation

- Assets are deprecated (kept but flagged) before removal (ADR-0019).
- Removal of a deprecated artifact is a breaking minor (0.x) and requires an ADR.
- Removal requires regeneration + tests update + CHANGELOG entry.