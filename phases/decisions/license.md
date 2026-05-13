# Decision: License — Apache 2.0

| | |
|---|---|
| **Date** | 2026-05-13 |
| **Status** | Decided |
| **Phase** | 0 (Design Lock) |

## Context

Wake is open source. The license choice affects:
- Who can use it (commercial vs OSS-only)
- Patent grant
- Sublicensing rights
- Compatibility with potential dependencies

## Options considered

### MIT
- **Pros:** Maximum permissiveness; short text; well-understood; compatible with virtually everything.
- **Cons:** No explicit patent grant — leaves users exposed if a contributor later asserts patent rights.

### Apache 2.0
- **Pros:** Explicit patent grant (forfeits patent suits from contributors); corporate-friendly (legal departments accept it readily); compatible with most OSS licenses; well-supported in tooling.
- **Cons:** Longer text; slightly more procedural (NOTICE file convention).

### BSD 3-clause
- **Pros:** Similar to MIT.
- **Cons:** No patent grant; no advantage over MIT or Apache.

### Elastic 2.0 / SSPL / Other source-available
- **Pros:** Prevents large vendors from offering hosted Wake as a service.
- **Cons:** Not OSI-approved; substantially fewer corporate users; harder to attract contributors; would contradict Wake's positioning as universal substrate.

## Decision

**Apache 2.0**.

## Consequences

### Accepted

- Maximum corporate adoption potential
- Patent protection for contributors and users
- Compatible with Apache-licensed components Wake reuses (LiteLLM, agentgateway, Anthropic SDKs)
- Hosted SaaS by third parties is allowed — fine, we're not building one

### Required actions

- Every new source file may include a copyright header:
  ```
  # Copyright 2026 Wake contributors
  # SPDX-License-Identifier: Apache-2.0
  ```
  (Not required, but recommended for adapter packages distributed independently.)
- NOTICE file optional; we'll add one if/when we accept significant attributed contributions.

### Compatibility check

| Component | License | Compatible? |
|---|---|---|
| Anthropic SDK | MIT | ✓ |
| LangGraph / LangChain | MIT | ✓ |
| CrewAI | MIT | ✓ |
| Pydantic AI | MIT | ✓ |
| LiteLLM | MIT | ✓ |
| sandbox-runtime | MIT | ✓ |
| Infisical Agent Vault | MIT (+EE) | ✓ |
| agentgateway | Apache 2.0 | ✓ |
| FastAPI / pydantic / etc. | MIT | ✓ |

All clean.

## Reversibility

Reverting Apache 2.0 → MIT is technically possible (more permissive) but requires consent from all non-trivial contributors. Avoid changing.

Reverting Apache 2.0 → SSPL/Elastic is **impossible** without rewriting from scratch, since it requires revoking grants we already issued.

## Status

`LICENSE` file committed in `24d0c93` (Phase 0). Decision stands.
