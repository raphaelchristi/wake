# Contributing to Wake

Thanks for considering contributing to Wake. This project is in **pre-alpha / design phase** — the most valuable contributions right now are **reviewing the specs and architecture before any code is locked in.**

---

## Project status

Wake is in **Phase 0: Design Lock** (see [`phases/PHASE-0-design-lock.md`](./phases/PHASE-0-design-lock.md)).

That means:

- The two core specs (`docs/SPEC-HARNESS-ADAPTER.md` and `docs/SPEC-EVENT-SCHEMA.md`) are at **v0.1.0 draft**, open for public review until they're locked.
- Limited code exists yet — Phase 1 (the skeleton) lands after Phase 0 closes.
- We deliberately do not accept large code PRs at this stage. We accept **spec critique, design feedback, and small code fixes**.

---

## How you can help right now

| What | How |
|---|---|
| Review the specs | Comment on the RFC issues (look for the `rfc` label) |
| Argue with the vision | Open an issue with `discussion` label |
| Suggest reuse | Found existing OSS that solves part of this? Open an issue with `reuse` label |
| Catch documentation bugs | PR welcome — small, surgical, no scope creep |
| Propose adapter targets | Have a framework Wake should adapt for? Comment on the RFC: HarnessAdapter issue |
| Sanity-check the comparison | Found something we got wrong about OpenHands, Multica, MAF, etc.? PR welcome |

If you're not sure where to start, read [`docs/VISION.md`](./docs/VISION.md) and [`docs/FAQ.md`](./docs/FAQ.md), then [`docs/COMPARISON.md`](./docs/COMPARISON.md) — these capture our current thinking and where we may be wrong.

---

## The RFC process

For any change that affects:

- The `HarnessAdapter` interface (`docs/SPEC-HARNESS-ADAPTER.md`)
- The event schema (`docs/SPEC-EVENT-SCHEMA.md`)
- The session lifecycle (states, statuses)
- The tool ABI
- Public REST API contract

…we use an RFC process. Don't open a PR with the change directly. Instead:

1. **Open an issue** using the `RFC` template (or label `rfc` if you create from scratch)
2. **Summarize the proposal** in 1-2 paragraphs
3. **Motivate the change** with a concrete use case the current spec fails to cover
4. **Detail the design** with code snippets / schema diffs
5. **List drawbacks** honestly
6. **Note alternatives** you considered
7. Wait at least **7 days** for community input
8. After consensus (or maintainer decision in case of deadlock), the change is applied via PR referencing the issue

For non-spec changes (docs, examples, tooling, internal refactors): regular PR is fine.

---

## Issue conventions

We use these labels:

- `rfc` — change to a frozen or quasi-frozen spec
- `discussion` — open-ended thinking, not a concrete proposal
- `question` — asking how something works
- `bug` — something Wake claims to do but doesn't
- `enhancement` — net-new feature within the existing scope
- `reuse` — pointing out existing OSS Wake should consume
- `good-first-issue` — bounded, well-defined task suitable for a newcomer
- `help-wanted` — maintainer is open to outside contribution on this

When opening an issue, pick one primary label. The maintainers may relabel.

---

## Pull request conventions

### Branch naming

```
type/short-description

Examples:
  docs/clarify-event-schema
  fix/cli-stream-encoding
  feat/foundation-event-log
```

`type` is one of: `docs`, `fix`, `feat`, `refactor`, `chore`, `test`, `perf`.

### Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/) loosely. Examples:

```
docs: clarify pause_turn semantics in event schema
fix(cli): handle empty SSE chunks gracefully
feat(runtime): add /v1/sessions/:id/interrupt endpoint
test(foundation): cover session state machine edge cases
```

Scopes we use:

- `docs`, `spec`, `phases`
- `foundation`, `runtime`, `cli` (Phase 1 slices)
- `adapter-langgraph`, `adapter-crewai`, `adapter-pydantic-ai`, `adapter-claude-sdk`
- `ci`, `deploy`

### PR description

Use the PR template. Keep it short. Answer:

- **What** — the change in one sentence
- **Why** — link to the issue / RFC
- **How to verify** — what tests should pass, what behavior to observe

### Code quality

- `ruff check` and `ruff format` must pass
- `mypy --strict` should pass for new/changed modules (we're tolerant for now while slices land)
- New code requires tests (unit minimum; integration where applicable)
- New public APIs require docs

### Sign-off

By submitting a PR, you certify the [Developer Certificate of Origin (DCO)](https://developercertificate.org/). Sign your commits:

```bash
git commit -s -m "your message"
```

---

## Local development (when code lands)

```bash
git clone https://github.com/raphaelchristi/wake.git
cd wake
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/unit/
ruff check src/
```

Server (after Phase 1):

```bash
wake server --local
```

CLI:

```bash
wake --help
wake run "hello"
```

---

## Adapter contributions

To contribute a new `HarnessAdapter` (e.g., for AutoGen, LlamaIndex, etc.):

1. Open an RFC issue describing the target framework and the mapping you propose
2. After RFC approval, create a new package under `adapters/<your-framework>/`
3. Implement the `HarnessAdapter` Protocol (`src/wake/adapters/base.py` once Phase 2 lands)
4. Pass the conformance suite (`wake-test-conformance`)
5. Add tests in `adapters/<your-framework>/tests/`
6. Register via `entry_points` in your `pyproject.toml`
7. PR including docs in `docs/adapters/<your-framework>.md`

Adapters get the tag `verified` once they pass conformance. Non-conformant adapters can exist but carry `unverified`.

---

## Code of Conduct

This project follows the [Contributor Covenant 2.1](./CODE_OF_CONDUCT.md). Be kind, be precise, be honest.

---

## Getting help

- Open an issue with label `question`
- Discord (once it launches, Phase 5)
- For private/security matters, email the maintainers at: **valdetaroraphael@gmail.com**

---

## License

By contributing, you agree your contributions are licensed under [Apache 2.0](./LICENSE).
