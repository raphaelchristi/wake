# Cost Budget Enforcement

> Phase 7 — Tier 1 gap #7. Stops a runaway session from burning real
> money. Reactive (post-step) enforcement against an optional
> per-agent ``max_cost_usd`` budget.

## TL;DR

Add a `max_cost_usd` to your `Agent.metadata` and Wake will interrupt
the session the moment the cumulative event cost crosses the budget:

```python
agent = await client.create_agent(
    name="research-bot",
    model="claude-opus-4-7",
    metadata={
        "max_cost_usd": "1.50",   # interrupt at $1.50 lifetime spend
    },
)
```

The next time the dispatcher steps the session and the running total
crosses the threshold, Wake emits an `interrupt` event with
`reason="cost_budget_exceeded"` and terminates the session.

That's it. No new schema. No new tables. No new endpoints.

---

## Why exists

Before Phase 7, Wake had **zero cost enforcement**. The LiteLLM
callback stamps `cost_usd` on event metadata (`assistant.message`
events carry it), the metrics aggregator reports it on
`GET /v1/metrics/summary`, and the dashboard charts it — but
**nothing stopped a runaway session from burning $1k while you sleep**.

The Roadmap calls this out as Tier 1 gap #7: "Session pode rodar até
R$10k sem ninguém saber". Phase 7 closes it.

---

## Design decisions

### Reactive, not predictive

We do NOT pre-estimate the cost of a step before invoking the adapter
and refuse based on a projected cost. Pre-estimation requires:

* a maintained model-price table (which goes stale fast),
* a tokenizer per model (expensive in CPU + memory),
* a heuristic for prompt-vs-completion ratio (which the model
  controls, not us).

Instead we let the step complete, sum the resulting `cost_usd`
metadata, and interrupt the session if the running total exceeded the
budget. The contract spells this out: **one-step overrun is bounded
by one LLM call** — typically cents, not dollars. Acceptable for v1.

### Per-session running total

We sum `cost_usd` across every event in the session log — payload OR
metadata. Different adapters tag it in different places:

* the bundled Claude SDK adapter writes `payload.cost_usd` on
  `assistant.message`,
* the LiteLLM callbacks write `metadata.cost_usd`,
* tool result events sometimes carry `payload.cost_usd` (rare).

The enforcer sums **both** so the budget total matches the dashboard.

### Soft-attribute semantics

Bad budget data → no enforcement, log a warning. Specifically:

| `max_cost_usd` value | Behaviour |
|---|---|
| missing / `None` | no enforcement |
| `""` (empty) | no enforcement |
| `"not-a-number"` | no enforcement, warn |
| `"0"` or negative | no enforcement |
| `"1.50"` (positive) | enforced at $1.50 |

We never crash the runtime over a misconfigured budget. The contract
calls this out as a hard rule.

### Decimal, not float

`max_cost_usd` and per-event `cost_usd` are summed as
`decimal.Decimal`. Float arithmetic loses precision at the third
decimal place (the typical magnitude of an Anthropic API call), and
the dashboard compares the running total against the budget down to
4 decimal places. Decimal removes any drift.

---

## Wire format

`agent.metadata` is `dict[str, str]` by spec. Wake parses
`max_cost_usd` as `Decimal(str(value))`, so any of these are valid:

```yaml
agent:
  metadata:
    max_cost_usd: "1.50"        # string, common
    max_cost_usd: "10"          # integer-string
    max_cost_usd: 1.5           # YAML number (coerced)
```

There is **no separate column** for the budget — it lives in the
existing metadata bag. This keeps the schema unchanged and means
Phase 6 stores work without migration.

---

## Interrupt event shape

When the budget trips, Wake emits an event with:

```json
{
  "type": "interrupt",
  "payload": {
    "reason": "cost_budget_exceeded",
    "metadata": {
      "total_usd": "1.55",
      "budget_usd": "1.50",
      "agent_id": "01H..."
    }
  }
}
```

Followed immediately by a `status` event transitioning the session to
`terminated`. The session is then ignored by future worker polls.

Downstream consumers (dashboard, audit pipeline, custom alerter) can
filter on `reason == "cost_budget_exceeded"` without parsing free-form
strings.

---

## How sessions transition

```text
running ─── adapter emits events ────► (events carry cost_usd)
              │
              ▼
       dispatcher.run_step() returns
              │
              ▼
       CostBudgetEnforcer.check(session, agent)
              │
              ├── budget unset    → no-op
              ├── total ≤ budget  → no-op
              └── total > budget  ► emit `interrupt` event
                                  ► SessionService.terminate(session)
                                    ► status event "running → terminated"
```

Subsequent worker polls see status=terminated and skip the session.
Any inflight request that races (e.g. user retries `wake session send`
right after the interrupt) hits a 4xx because the session machine
refuses transitions from `terminated`.

---

## Observability

Three signals available out-of-the-box:

* **structlog** — every enforcement check that fires logs:
  ```
  cost_budget.exceeded session_id=... agent_id=...
    total_usd=1.55 budget_usd=1.50
  ```

* **interrupt event** — durable record in the event log.

* **metrics summary** — `GET /v1/metrics/summary` already aggregates
  cost_usd per session; sessions terminated by cost-budget show up
  with the breach total.

If you wire the Phase 7 slice C Prometheus exposition, additionally:

* `wake_cost_usd` histogram (already present pre-Phase 7),
* `wake_sessions_total{status="terminated", reason="cost_budget_exceeded"}`
  counter (added by slice C).

---

## Limitations

### Race window

The check runs **after** `run_step` returns. If a step makes an LLM
call that costs $5 and the budget is $1, the session is interrupted
**after** that $5 already burned. Mitigations:

* Set budgets with headroom (`max_cost_usd = expected * 1.5`).
* For very-tight budgets use the metrics dashboard for alerting; we
  ship a Grafana panel template in `docs/OBSERVABILITY.md`.

### Per-agent, not per-organisation

The budget is on the agent config. Two agents in the same workspace
each get their own budget — there's no organisation-wide spend cap
in Phase 7. That's deferred to Phase 8 (billing aggregator).

### No "soft warn" tier

The enforcer is binary: under budget = OK, over budget = interrupt.
We do not emit a "warning" event at 80% spend. Operators that want
that should subscribe to the cost stream via SSE and emit their own
alert.

---

## Testing

Unit tests in `tests/unit/test_cost_budget.py` cover:

* `parse_budget` handles missing / zero / negative / bad values
* `event_cost` sums payload + metadata, treats bad data as 0
* No budget → no enforcement
* Budget configured but under cap → no-op
* Budget exceeded → `interrupt` event + terminated session
* Idempotent: second check on terminated session is a no-op transition

Run only the budget tests:

```bash
pytest tests/unit/test_cost_budget.py -v
```

---

## Migration / rollout

No migration required. Existing agents without `max_cost_usd` continue
to behave exactly as before (no enforcement). Set the budget on new
or updated agents only when you are ready.

For an organisation-wide rollout:

1. Audit existing agents → which models / typical session costs?
2. Set `max_cost_usd = 2 * p99(session_cost)` on each agent.
3. Wire alerting on the `cost_budget.exceeded` log line.
4. Tighten the cap quarter-over-quarter as p99 drops.

---

## Future work

* Pre-step price-table lookup (Phase 8) — refuse a step whose
  projected cost would clearly exceed the remaining budget.
* Per-workspace + per-organisation aggregate caps (Phase 8 billing).
* Cost reservation pattern (deduct estimated, refund actual) for
  rate-limited multi-agent dispatching.
