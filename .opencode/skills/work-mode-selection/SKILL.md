---
name: work-mode-selection
description: Choose the SE work mode (organic / spec / receipt) from the project's declared profile before starting work, instead of by habit. Use before planning or implementing any change to decide how much ceremony the project's type, scale, risk, criticality and contract impact demand, and to make that decision auditable.
metadata:
  system: system-engineering
  schema_version: "1"
  adapter: opencode
  checkpoint: CP-024
---

# work-mode-selection

## purpose

Decide, per project, which work mode governs the change at hand — **organic**,
**spec** or **receipt** — and write that decision down so it is reproducible.
The mode is a function of the project profile, not of the agent's habits: an agent
must be able to say *why* this project gets a full SDD and a review receipt, and
why another gets a one-line change with nothing more.

## when_to_use

- Before planning or implementing any non-trivial change, to pick the ceremony floor.
- When adopting a project (its profile is declared at adoption time), so the first
  changes already follow the right mode.
- When a change looks like it should be "just a tweak" but touches a contract,
  a criticality-`critical` capability, or a high-risk area.

## when_not_to_use

- Never as a substitute for the gates: the mode sets the *floor*, the gates
  (`se gate`, `se verify` G5) keep their authority and can demand more.
- Not for read-only work (exploration, review of an existing candidate) where no
  change is produced.
- Not to raise ceremony "just in case": over-ceremony is a failure mode too.

## inputs

- `PROJECT.json`: `profiles.work.type` (greenfield/brownfield), `profiles.work.scale`
  (small/medium/large), `profiles.work.risk` (low/medium/high), top-level `criticality`.
- The nature of the change: does it change a contract (interface, schema, gate,
  capability, published doc), or only an implementation behind a stable contract?
- `CORE/policies/ceremony.json`: the machine-readable floor the project's profile maps to.

## preconditions

- The project has a `PROJECT.json` with a declared `profiles.work` (or the profile is
  explicitly recorded as unknown, which itself is a finding to resolve before spec work).
- The effective requirements are read from the policy, not invented:
  `se ceremony --project <dir>` reports them.

## procedure

1. **Read the profile.** Load `PROJECT.json` and take `type`, `scale`, `risk` and
   `criticality`. If `profiles.work` is absent, the profile is undeclared — record that.
2. **Classify the contract impact.** Decide whether the change alters a contract that
   others depend on. Contract changes always pull the mode upward.
3. **Resolve the mode.**
   - **organic** — small, low risk, no contract change: change behind a stable
     contract, no design document, no receipt. The floor is "tests + the existing gates".
   - **spec** — a contract changes, or scale/risk is high, or criticality is
     `critical`: write the design (an SDD) before implementing, and have it approved.
   - **receipt** — a review must be bound to the exact candidate: record an RDD whose
     `candidate` names the change and whose `evidence` proves the verdict.
   A change can require more than one: a large, high-risk contract change is spec **and**
   receipt.
4. **Confirm against policy.** Run `se ceremony --project <dir>`; the effective
   requirements must match the mode you chose. `se validate --project` enforces it.
5. **Record the decision** in the task/objective or the RDD, naming the profile fields
   that drove the mode, so a reviewer can reproduce the choice.

## evidence

- The resolved requirements from `se ceremony --project <dir>` (or the policy tiers read).
- For **spec**: the SDD id, or the reason no design doc is required.
- For **receipt**: the RDD id bound to the candidate.
- The profile fields (`type`, `scale`, `risk`, `criticality`) that selected the mode.

## validation

- The mode is valid when the profile fields reproduce it: same profile, same mode.
- A **receipt** mode is not satisfied by "it was reviewed" without an RDD bound to the
  candidate with evidence.
- A **spec** mode is not satisfied by a DRAFT design; the SDD must reach an accepted status.

## failure_modes

- Choosing the mode by habit ("we always write an SDD" / "this is tiny") instead of
  reading the profile.
- Treating `criticality: unknown` as `low` and skipping spec work it will need.
- Raising ceremony for its own sake on small, low-risk, contract-stable changes.
- Declaring a receipt mode and then recording a verdict without evidence.

## outputs

- The selected work mode (organic / spec / receipt) and the profile fields that drove it.
- For spec: an SDD. For receipt: an RDD. Recorded where the change lives.

## restrictions

- READ-ONLY skill: it selects and documents the mode; it does not write project records
  itself (the SDD/RDD are created by their own flows).
- It never lowers a gate or bypasses `se verify`; it sets a floor that gates can raise.
- It must not encode a personal preference as if it were project policy.
