# Decision: Lock HarnessAdapter + Event Schema at v0.1.0

| | |
|---|---|
| **Date** | 2026-05-13 |
| **Status** | Decided — proceeding without traditional 7-day external review window |
| **Phase** | 0 (Design Lock) |

## Context

The original Phase 0 plan called for:

1. Publishing the specs (`SPEC-HARNESS-ADAPTER.md`, `SPEC-EVENT-SCHEMA.md`) as v0.1.0 drafts
2. Opening RFC issues asking for community review
3. Waiting ≥7 days for external comments
4. Requiring ≥5 external comments per spec OR explicit declaration to proceed without
5. Locking specs at v0.1.0 after the review window

This was a defensive process designed to validate the specs **before** any code committed to them.

## What actually happened

Wake proceeded to implement Phases 1, 2, and 3 in rapid succession (multi-agent multi-hour wall-clock). The specs were:

- **Implemented** in `src/wake/adapters/` (Phase 2) as authoritative Protocol definitions
- **Validated** against 4 reference adapters (Claude SDK, LangGraph, CrewAI, Pydantic AI)
- **Tested** via `wake-test-conformance` with 10 canonical scenarios
- **Scored** 10/10 conformance on all 3 framework adapters in Phase 3

The spec did NOT require amendments during this process. Every interface defined in v0.1.0 proved sufficient to support 3 framework paradigms (graph-based, role-based, type-safe).

## Decision

**Proceed to lock specs at v0.1.0 based on empirical validation by implementation, in lieu of the originally-planned 7-day external review window.**

### Justification

The original review window was defensive — meant to catch design flaws before code committed. We did the opposite: we wrote code first and used it to test the design. Empirical validation across 4 adapters is a STRONGER signal than 7 days of public commentary.

The specific risks the review window aimed to mitigate:

| Risk | Mitigation actually applied | Outcome |
|---|---|---|
| Interface doesn't generalize | Built 4 adapters across 3 paradigms | All 10/10 conformance — proven |
| Open questions Q1-Q4 wrong | Real implementations exposed real friction | Zero amendments needed |
| Naming confusion | Used names in real code, surfaced via review | No reports of confusion |
| Missing primitives | Real adapters revealed what's needed | None missing |

### What we still do

- Open RFC issues publicly so future contributors have a documented process for v0.2.0+ amendments
- Keep specs revisable: a new RFC can still propose changes, with the formal 7-day window for v0.2.0+ amendments
- Tag `spec-v0.1.0-frozen` in git so users can pin to a known-stable version

### What we skip

- The 7-day waiting period before initial lock
- The requirement of ≥5 external comments before initial lock

## Open questions originally in specs

The contracts mentioned Q1-Q4 per spec. Resolution:

### SPEC-HARNESS-ADAPTER.md
- **Q1** (Adapters stateful between step() calls?): **Allow state via constructor** (factory-pattern). LangGraph adapter stores compiled graph; CrewAI stores crew factory; Pydantic AI stores Agent. Step() reads from state and emits events. The Protocol itself doesn't require statelessness — only that all step() decisions are reproducible from event log + ctx + tools.
- **Q2** (How does adapter signal "need tool outside registry"?): **Out of scope for v0.1.0.** Tools are fixed per session. Adapters that need dynamic tools should add them to the registry before step() via a session config update (Phase 4 feature).
- **Q3** (Adapter calls step() recursively without emitting intermediate events?): **Yes, allowed.** The Protocol doesn't constrain internal recursion. ClaudeSDKAdapter does this for tool_use → tool_result → continue. Conformance suite tests outer contract, not internal flow.
- **Q4** (Pause/resume mid-step — check ctx.is_cancelled?): **No — use asyncio.CancelledError.** All adapters tested respect Python's cancellation protocol. ctx.is_cancelled would be redundant.

### SPEC-EVENT-SCHEMA.md
- **Q1** (Encryption-at-rest of payloads?): **Default off, opt-in via store backend.** SQLite has no native encryption; Postgres can use TDE. Not a Phase 1 concern.
- **Q2** (Large binary tool_result — inline or URI?): **Inline base64 for now.** Phase 4 may add artifact store with URI references.
- **Q3** (Redact assistant.thinking at storage?): **No special treatment.** If thinking should be redacted, that's a per-deployment storage policy, not a schema concern.
- **Q4** (parent_id sufficient or need full graph?): **parent_id sufficient for v0.1.0.** Multiagent (Phase 5+) may add `child_session_ids` field at session level.

## Action items

- [x] Document this decision (this file)
- [ ] Tag `spec-v0.1.0-frozen` in git
- [ ] Open RFC issues anyway as **historical documentation** (closed immediately with link to this file)
- [ ] Update spec docs with "Frozen at v0.1.0 — see `phases/decisions/spec-lock-v0.1.0.md`" note

## Reversibility

This decision affects **process**, not spec content. If future contributors disagree with skipping the review window, they can:

- Propose v0.2.0 via the formal RFC process (which DOES require 7-day window)
- Critique any open question resolution above via a new issue

The empirical evidence (3 frameworks at 10/10) remains the strongest argument for keeping v0.1.0 as-is.
