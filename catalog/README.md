# Wake Adapter Catalog

Public static site listing conformance-verified HarnessAdapter implementations for Wake. Built as Next.js 15 standalone, exported static (`next export`).

## Setup

```bash
cd catalog
pnpm install
pnpm dev   # http://localhost:3000
```

## Build static export

```bash
pnpm build
# output: out/  (deployable to Vercel/Cloudflare Pages/S3+CloudFront/etc)
```

## Data source

`data/adapters.json` is the source of truth. Each entry:

```json
{
  "slug": "claude-sdk",
  "name": "wake-adapter-claude-sdk",
  "version": "0.1.0",
  "framework": "Anthropic Claude SDK",
  "conformance_score": 10,
  "conformance_max": 10,
  "last_verified": "2026-05-14",
  "maintainers": ["..."],
  "homepage": "...",
  "description": "..."
}
```

## Claiming conformance for your adapter

1. Run `wake-test-conformance` against your adapter implementation
2. Copy `templates/adapter-claim/` into your repo
3. Configure the workflow with your adapter metadata
4. Open PR adding your entry to `catalog/data/adapters.json`

Catalog maintainers verify conformance results before merge.
