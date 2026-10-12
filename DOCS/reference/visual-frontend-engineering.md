# Visual Frontend Engineering (ARCH-VFE-001)

Provider-agnostic capability for building, rendering, capturing and structurally reviewing
frontends with **verifiable visual evidence** at zero additional cost. The capability is a
**process + contract**, not a model: it works with the current implementation model (Big Pickle)
and any future model; a vision-capable *review* model (DeepSeek vision) is optional and decoupled.

## Why (research-backed)

Community + academic evidence (an internal research record) converges on one finding: the visual
quality gap is a **missing process** (design direction + real render step + screenshot evidence +
review loop), not a model limitation. The capability is the implementation of that process.

## Components

| Component | Purpose |
|-----------|---------|
| `SKILLS/visual-frontend-engineering/SKILL.md` (SK-0003) | Orchestration contract: direction → build → preview → snapshot → screenshot → review → fix (max 3 rounds) → evidence |
| `TEMPLATES/DESIGN.template.md` | Minimal Design System spec in Google DESIGN.md tuple format (tokens + WCAG contrast + evidence checklist) |
| `SCRIPTS/vfe_capture.py` | Capture runner: loads a page, emits viewport/full-page PNGs + structural JSON. Uses system Chrome via py-playwright `channel="chrome"` — no browser download |
| `TESTS/fixtures/vfe-demo/` | Proof fixture: same page before/after shows FAIL → PASS on automated visual checks |
| Registry (CP-020) | `playwright` → `browser.preview/snapshot/screenshot` (available); `deepseek-vision` → `visual.review` (unknown) |

## Capabilities

Registered in `CORE/capabilities/capabilities.json`:

| Capability | Operation | Provider | Availability | Notes |
|------------|-----------|----------|--------------|-------|
| `browser.preview` | read | playwright | available | open page in real browser |
| `browser.snapshot` | read | playwright | available | structural/a11y snapshot |
| `browser.screenshot` | read | playwright | available | viewport + full-page PNG |
| `visual.review` | read | deepseek-vision | **unknown** | pixel review by vision model; requires provider key |

`visual.review` is honestly registered as `unknown`: no DeepSeek key is observable in this
environment. The skill treats it as **optional** — the loop still produces valid evidence
(structural checks + screenshots) without it. Do NOT flip to `available` until a key is verified.

## Protocol (condensed)

1. Create `DESIGN.md` from `TEMPLATES/DESIGN.template.md`.
2. Build UI to the spec.
3. `python SCRIPTS/vfe_capture.py <page>.html --out <evidence> --job r1` → PNGs + `r1-metrics.json`.
4. Analyze metrics + snapshot; if `visual.review` available, have the vision model review PNGs.
5. Apply fixes; repeat ≤ 3 rounds; stop when no actionable findings or round 3 reached.
6. Report with FACT/VERIFIED tags; each visual claim cites its screenshot.

## Provider decoupling

- The skill never names an implementation model: the same procedure runs under Big Pickle, Claude,
  Codex, Gemini, etc.
- The review step is a separate provider (`visual.review`): swap the vision model without touching
  the skill or the registry mapping (`CORE/capabilities/capabilities.json` is the single
  mapping source).
- Cost: $0 (system Chrome + free implementation model). A later DeepSeek vision integration would
  be billed per token off-peak: ≈ $0.22 cache-miss in / $0.66 out per 1M (see research doc).

## Security / privacy rules

- Never place API keys/tokens in logs, screenshots, artifacts or prompts (POLICIES/secrets.md).
- The vision provider is configured out-of-band; only its *availability* is declared.
- Screenshot evidence may contain real data: use fictitious/seeded data in demos; redact or exclude
  client/production data before committing captures.
- No external render service: screenshots happen locally (system Chrome). Nothing leaves the host
  unless a vision provider is explicitly configured.

## Failure modes guarded

- Provider hang/refuse → retry once, then fail explicitly with partial evidence (never fabricate).
- No runtime → no claims of verifiable visuals (report unknown).
- Blank screenshots (content not loaded) → wait `load` + `networkidle`.
- Loop runaway → hard cap of 3 rounds with explicit stop criteria in the skill.

## Roadmap (future, not implemented)

- A node available later → prefer official `playwright-cli` (`open`/`snapshot`/`screenshot`).
- Wire `deepseek-vision` as the default `visual.review` provider when a key exists (adapter boundary only).
- Pixel-diff baseline (`rN` vs `rN+1`) for regression gates on visual tasks.
- Optional integration with project `artifacts/` DESIGN_SPEC / DESIGN_SYSTEM kinds (DOMAINS/design).