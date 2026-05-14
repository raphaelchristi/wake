# Wake Adapter Conformance Claim Template

Copy this template into your HarnessAdapter repo to claim conformance and get listed in the [Wake Adapter Catalog](https://catalog.wake.dev/).

## Steps

1. **Copy `.github/workflows/conformance-claim.yml` to your repo's `.github/workflows/`**
2. **Configure secrets/env in the workflow** (your adapter's import path)
3. **Push to main** — the workflow runs `wake-test-conformance` against your adapter
4. **Open a PR against `raphaelchristi/wake`** adding your entry to `catalog/data/adapters.json` with the conformance results JSON attached as a release asset or repo file

## What the workflow does

```yaml
# .github/workflows/conformance-claim.yml
- Install wake-test-conformance
- Run: wake-test-conformance run --adapter <your-adapter>
- Upload conformance_results.json as artifact
- Generate badge SVG via `wake adapter badge`
```

## Required fields in adapters.json entry

```json
{
  "slug": "<unique-slug>",
  "name": "<your-package-name>",
  "version": "<semver>",
  "homepage": "<repo-url>",
  "framework": "<framework-name-like-LangGraph>",
  "conformance_score": <0-10>,
  "conformance_max": 10,
  "last_verified": "<ISO date>",
  "maintainers": ["<github-username>"],
  "description": "<one-paragraph>"
}
```

Catalog maintainers verify the conformance results before merge.
