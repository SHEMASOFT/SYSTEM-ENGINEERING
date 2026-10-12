# Work modes

SE runs the same contracts under three work modes. The agent selects the mode
**from the project**, never from habit: the project profile and the nature of the
change decide which modes are **required**, **optional** or **not needed**.

| Mode | What it is | Default |
|---|---|---|
| **organic** | The daily flow: explore, clarify the decisions that matter, execute the authorized change, run checks proportional to the risk. No heavy ceremony for simple work. | Always on |
| **spec** | Formal flow, selected when thinking ahead pays off: proposal, requirements, design and tasks **before** implementing, then verify the result against what was agreed. | When the selection rule fires |
| **receipt** | Evidence-review layer: binds a verdict to the **exact change candidate** (commit / worktree / artifact / release) with the evidence that supports it, so a review can never drift from the version it reviewed. | Whenever work is delivered and reviewed |

> The three compose: organic is the trunk, spec is added when the work must be
> agreed before it is built, receipt is added when the built change must be
> provably the one reviewed.

## Selection rule (what the agent applies)

Read the project first, then apply the table. Inputs, in this order:

1. `profiles.work.type` — `greenfield` | `brownfield`
2. `profiles.work.scale` — `small` | `medium` | `large`
3. `profiles.work.risk` — `low` | `medium` | `high`
4. `criticality` — `low` | `medium` | `high` | `critical` | `unknown`
5. the change itself: does it **define or change a contract** (schema, interface,
   gate, lifecycle, public behavior)?

| Situation | organic | spec | receipt |
|---|---|---|---|
| small + low risk + no contract change | required | not needed | optional |
| medium scale, or risk `medium` | required | optional — recommended when the objective is UNKNOWN | required |
| large scale, or risk `high`, or criticality `high`/`critical` | required | **required** | required |
| defines/changes a contract (schema, interface, gate, lifecycle) | required | **required** | required |
| brownfield area with no tests or evidence | required | recommended | **required** |
| release, merge or acceptance of a delivered change | required | as above | **required** |

Rules that override the table:

- **Unknown is never assumed.** `criticality: unknown` or an UNKNOWN objective is
  resolved during organic exploration and recorded as an ASSUMPTION or a decision
  before spec work starts.
- **Proportionality.** A mode is never used to add ceremony a small change does
  not need; the table is a floor, not a quota.
- **Escalation on surprise.** If organic work discovers the change touches a
  contract or grows beyond its scale, the agent escalates: spec becomes required.

## How each mode runs

| Mode | Records | Commands |
|---|---|---|
| **organic** | tasks, evidence | `se explore` → `se plan` → `se implement` / `se update` → `se verify` |
| **spec** | objective, requirement, **sdd**, (optional **odd**), tasks, decision | `se new objective` / `se new requirement` → `se new sdd` (`se new odd` explores the open design space) → `se plan --create-tasks` → gates |
| **receipt** | **rdd** + evidence, acceptance | `se new rdd` (candidate + evidence + verdict) → link with `linked_change`; `se gate` / `se review` consume it |

The record trio around a decision:

```
ODD  (explore / open)      SDD  (specify / formal)      RDD  (prove the change)
odds/ODD-####              sdds/SDD-####                rdds/RDD-####
alternatives + evaluation  architecture + interfaces    candidate + evidence
                              └──────→ ADR (decided, closed) ──────┘
```

Both `spec` and `receipt` are selected per **change**, not per project: the same
project can run organic for a fix and spec + receipt for a contract change.

## Status

This document is the rule. The next step is to ship it as a canonical skill
(`SKILLS/`, advertised by description and loaded on demand) plus a coordinator
capability in the agent contracts, so the selection rule travels with the agent
instead of being prose it may skip. Until then, the coordinator reads this
document before planning work on a project it has not seen.
