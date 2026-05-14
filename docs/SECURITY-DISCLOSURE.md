# Security Disclosure — Process & Contact

Companion to `SECURITY.md` (top-level). This document covers the detailed disclosure procedure for security researchers and operators.

## TL;DR

- **Report:** GitHub Security Advisory (preferred) or `security@wake-ai.dev`
- **Response:** Acknowledged in < 48h, assessed in < 5 business days
- **Fix SLA:** Critical < 14 days, High < 30, Medium < 90
- **Public disclosure:** 7 days after patched release
- **Credit:** Listed in `SECURITY.md` after coordinated release

## Reporting channels

### 1. GitHub Security Advisory (preferred)

https://github.com/raphaelchristi/wake/security/advisories/new

Pros:
- Private discussion thread with maintainers
- Embargo enforced automatically
- CVE assignment via GitHub if eligible
- Coordinated disclosure with downstream consumers

Cons:
- Requires GitHub account
- Embargo lifts on advisory publish — coordinate disclosure timing in the thread

### 2. Email (`security@wake-ai.dev`)

For reporters who prefer not to use GitHub, or who need PGP encryption.

PGP fingerprint: `TBD — published in `SECURITY.md` once key generated`.

### 3. In-person / conference disclosure

If you're at a conference and want to disclose to a maintainer in person, we appreciate it but **please follow up in writing** within 24h so we have a record + can start the formal process.

## What "in scope" means

See `SECURITY.md` § Scope for the canonical list. The TL;DR:

✅ **In scope:** API, storage, sandbox, vault, Helm chart, dashboard, SDKs (everything in `src/wake/`, `adapters/*`, `frontend/`, `deploy/helm/wake/`, `sdks/*`)

❌ **Out of scope:** social engineering, physical attacks, brute-forcing keys, third-party dependency CVEs (report upstream first), denial-of-service without bypass

If you're unsure whether something is in scope, **report it anyway** — we'd rather triage 100 marginally-relevant reports than miss a real one.

## What we expect from reporters

1. **Don't exfiltrate data you don't need for the PoC.** A reproducer that demonstrates the issue is more useful than 10GB of stolen tenant data.
2. **Don't degrade the service for other users.** No DoS during testing.
3. **Don't pivot from one vulnerability to find more without explicit invitation.** We may invite further testing during the disclosure thread.
4. **Don't disclose publicly during the embargo.** We'll set a target date together.

## What you can expect from us

1. **Acknowledgement** within 48 hours (yes, weekends included)
2. **Initial triage** within 5 business days (Eastern Time hours)
3. **Honest engagement** — if we disagree on severity, we'll explain why; if we accept your finding, we'll write up the fix together
4. **Credit** in `SECURITY.md` after the fix lands, unless you prefer anonymity
5. **No legal action** for good-faith research within scope (safe harbor — see below)

## Safe harbor

Wake commits to:

- Not pursue legal action against researchers who:
  - Stay within scope (`SECURITY.md` § Scope)
  - Do not violate user privacy beyond minimal PoC
  - Do not destroy/modify data
  - Do not disrupt service for other users
  - Report through one of our channels
  - Honor a reasonable embargo period (typically 7-14 days post-fix)

- Provide a written safe-harbor statement if you ask in writing before testing

## Coordinated disclosure timeline (typical)

```
Day 0:    Report received
Day 1:    Acknowledgement sent
Day 5:    Initial assessment (sev + scope + assignment)
Day 7-N:  Private branch with fix; reporter validates PoC against patch
Day N+1:  Release published (private notification to known downstream)
Day N+7:  Public advisory published
Day N+8:  Credit added to SECURITY.md, blog post if applicable
```

For Critical sev: shorten to Day 14 release target.

## What gets disclosed publicly

After embargo lifts:

- GitHub Security Advisory with technical details
- CVE record (if assigned)
- Release notes for the patched version
- Reporter credit (with reporter's permission)

We do NOT disclose:
- PoC code that's directly weaponizable (we summarize)
- Internal stack traces or logs that leak architecture details unrelated to the bug
- Information that would help attack still-affected legacy versions

## Hardening recommendations (recap from SECURITY.md)

```yaml
# Helm values.yaml — production-safe defaults
auth:
  apiKey: "<random-hex-32>"
  required: true  # WAKE_AUTH_REQUIRED=true — fail-closed
  rbacEnabled: true  # WAKE_RBAC_ENABLED=true — per-route role enforcement

backup:
  enabled: true
  repositoryId: "<cluster-unique-id>"
  s3: { ... }
  restoreTest:
    enabled: true
    schedule: "0 4 * * 0"  # weekly drill

monitoring:
  enabled: true
  # NetworkPolicy externally enforces /metrics access
```

## Acknowledgements

Coordinated-disclosure researchers listed in `SECURITY.md` § Acknowledgements section after fix release.

## Questions?

- General security questions: `security@wake-ai.dev`
- Operator hardening help: GitHub Discussions or `support@wake-ai.dev`
- Policy clarifications: open issue with `security:policy` label
