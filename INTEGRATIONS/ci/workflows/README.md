# GitHub Actions reference adapter

Copy `se-governance.yml` to the product repository as
`.github/workflows/se-governance.yml`. It is a reference adapter: the neutral
scripts under `../scripts/` do the governance work and can be reused by any
other CI provider.

## Preconditions

1. The product repository contains `PROJECT.json` at its root (or a documented
   subdirectory; change `SE_PROJECT_PATH` in the workflow `env` block).
2. `PROJECT.json.master_system_version` pins an SE release that exists as a tag
   (`vX.Y.Z` or `X.Y.Z`) in `SHEMASOFT/SYSTEM-ENGINEERING` (or the repository
   you configure).
3. The product branch is protected and `se-governance` is a required status
   check. **Without that, a red run does not block a merge.**

## Configuration

Edit the workflow `env` block or pass the `workflow_dispatch` inputs:

| Variable | Default | Meaning |
|---|---|---|
| `SE_REPOSITORY` | `SHEMASOFT/SYSTEM-ENGINEERING` | SE repository (`owner/name`) |
| `SE_REF` | empty | Release tag; empty resolves it from `PROJECT.json` and the remote tags |
| `SE_PROJECT_PATH` | `.` | Path to the project inside the product checkout |

`SE_REF` must identify the release tag, not a branch. The version step enforces
this with `--expected-ref` and `--require-exact-tag`.

### Private SE repository

The workflow uses `permissions: contents: read` and no secrets by default. A
cross-repository checkout of a **private** SE repository needs a read-only
token because `GITHUB_TOKEN` is scoped to the product repository:

1. Create a fine-grained token or deploy key with read access to SE.
2. Store it as `SE_REPOSITORY_TOKEN` in the product repository.
3. Uncomment `token: ${{ secrets.SE_REPOSITORY_TOKEN }}` in the
   `Checkout pinned SE engine` step.
4. Pass `se_ref` explicitly (workflow dispatch) or set `SE_REF` in the workflow
   `env` block. The pre-checkout resolver runs before the engine checkout, so
   it cannot use that token to authenticate `git ls-remote`; the authoritative
   `se_ci_version.py` step still verifies the tag, the engine version and the
   checked-out commit.

Fork pull requests do not receive secrets; run governance only for trusted
branches if the engine is private.

## What the workflow runs

| Step | Script | Blocks? |
|---|---|---|
| Resolve SE release ref | inline provider glue (`git ls-remote`) | yes, if no tag resolves |
| Verify SE release pin | `se_ci_version.py` | yes (`3`) |
| Validate project contracts | `se_ci_validate.py` | yes (`1`/`3`) |
| Evaluate declared gates | `se_ci_gate.py` | yes (`1`/`3`/`4`) |
| SE doctor | `se_ci_doctor.py` | no (information only; `3` if it cannot run) |
| Governance summary | `se_ci_report.py` | publishes and returns the aggregate code |

The inline resolver is provider glue: it only discovers the tag. The
authoritative check is `se_ci_version.py`, which re-verifies the tag, the
engine `VERSION` and the checked-out commit, and fails closed.

The summary step runs with `if: always()` and reads the step reports written to
`$RUNNER_TEMP/se-ci`. Missing reports become `OPERATIONAL_ERROR`, so a crashed
step cannot produce a green summary.

## Required-check setup (GitHub)

1. Settings -> Branches -> branch protection rule for `main`.
2. Require status checks to pass before merging.
3. Select `se-governance` (the job name).
4. Optionally require CODEOWNERS review for `PROJECT.json`, `sdds/`, `rdds/`,
   `evidence/` and `.github/workflows/se-governance.yml`.

SE cannot configure this for you. It is GitHub's enforcement plane.

## Limits

- The template targets `ubuntu-latest`. The scripts themselves are tested on
  Linux and Windows.
- No GitLab, CodeBuild or CodePipeline template is included yet; the neutral
  scripts are the reusable contract for those adapters.
- A tag proves publication, not cryptographic provenance.
- `OPERATING -> ARCHIVED` has no gate, so that transition fails operationally
  instead of passing unverified.
