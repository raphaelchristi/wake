# Decision: Runtime language — Python

| | |
|---|---|
| **Date** | 2026-05-13 |
| **Status** | Decided |
| **Phase** | 0 (Design Lock) |

## Context

Wake needs a primary implementation language for the core runtime. The HarnessAdapter ABI is language-agnostic in principle (any language with async + entry-point discovery can implement it), but a reference runtime needs ONE language.

## Options considered

### Python
- **Pros:** Largest AI/ML ecosystem; Anthropic SDK, OpenAI SDK, LangChain, LangGraph, CrewAI, Pydantic AI are all primarily Python; MCP Python SDK official; minimal friction for users building agents.
- **Cons:** Weaker type system than Rust/Go; GIL limits CPU-bound parallelism (irrelevant for our I/O-bound workload); packaging quirks.

### Go
- **Pros:** Single static binary distribution; better concurrency primitives; faster cold start than Python; less variance across deployments.
- **Cons:** AI ecosystem is anemic — most frameworks Wake adapts to are Python; would need substantial RPC layer to call Python adapters, adding complexity and latency; smaller pool of contributors who write Go AI code.

### Rust
- **Pros:** Max perf; memory safety; growing AI infra ecosystem (agentgateway, sandbox-runtime parts).
- **Cons:** Steeper learning curve; ecosystem still nascent for agent-level work; would isolate Wake from the Python AI community that benefits most from it.

## Decision

**Python 3.11+** as the primary runtime language.

## Consequences

### Accepted

- Wake runs adapters in-process (Python ↔ Python) — no IPC overhead
- Single ecosystem with all major agent frameworks
- Easy for Python AI devs to contribute
- pyproject.toml workspace pattern works cleanly for adapter packages

### Mitigations for cons

- Use **uv** for fast, reliable package management
- Use `async/await` everywhere — async I/O scales well for Wake's workload
- Type hints strict + mypy --strict to compensate for weak runtime types
- For perf-critical paths (event log append, SSE fan-out) optimize specifically; not a blanket concern

### Open: future polyglot adapters

The HarnessAdapter spec is language-agnostic. **Non-Python adapters** (e.g., Rust adapter for goose, TypeScript adapter for Mastra) can be added later via:

- Subprocess + JSON-RPC over stdio, OR
- HTTP-over-localhost protocol mirroring the in-process Protocol

Decision deferred until concrete user demand. Day-30+ scope.

## Validation

Phases 1-3 were built entirely in Python with this decision in effect. Results:
- Phase 1 skeleton: shipped in 2 weeks of multi-agent wall-clock (28 min real)
- Phase 2 ABI publication: 35 min wall-clock, ABI proven
- Phase 3 framework adapters: 70 min wall-clock, 3 frameworks at 10/10 conformance

No friction attributable to the Python decision. Decision stands.
