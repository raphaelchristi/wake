# Wake Adapter Catalog

Public listing of conformance-verified HarnessAdapter implementations. Phase 9 deliverable (Tier 3 gap #13).

> Production: hosted as static site at `catalog.wake.dev` (or similar) — see `catalog/README.md` for build/deploy.

---

## Why a catalog

Wake `wake-test-conformance` suite tests adapters against the ABI spec. **Passing locally** ≠ **trusted by ecosystem**. The catalog turns "adapter passes 10/10 in my repo" into a verifiable public claim:

- 3rd-party authors prove conformance via reproducible workflow
- Wake users see which adapters are blessed before adopting
- HarnessAdapter ABI becomes "the industry standard for Wake-compat" instead of "Wake's API"

---

## Architecture

```
catalog.wake.dev (static site)
├── data/adapters.json        ─ source of truth (curated)
├── /                         ─ index page (sorted, filtered list)
├── /adapters/[slug]/         ─ detail page per adapter
└── /badge/[slug].svg         ─ rendered SVG badge per adapter
```

Built from `catalog/` Next.js 15 standalone. `next export` produces `out/` deployable to:
- Vercel (zero config)
- Cloudflare Pages
- Netlify
- S3 + CloudFront
- GitHub Pages

---

## Listing criteria

Adapter must:

1. **Implement HarnessAdapter ABI v0.1.0** (verified via `wake-test-conformance`)
2. **Pass conformance suite ≥ 8/10** (recommend 10/10)
3. **Public source code** (OSS license preferred)
4. **Active maintenance** (last commit < 6 months at listing time)
5. **Compatible with Wake server version range** (specified in entry)

Catalog maintainers re-verify quarterly.

---

## Claim flow

1. **Adopt template** — copy `templates/adapter-claim/.github/workflows/conformance-claim.yml` to your adapter repo
2. **Configure** — set `adapter_module` input to your import path
3. **Run** — workflow runs conformance + uploads `conformance_results.json` artifact + badge SVG
4. **Submit** — open PR against `raphaelchristi/wake` adding your entry to `catalog/data/adapters.json`:

```diff
 {
   "adapters": [
     { "slug": "claude-sdk", ... },
+    {
+      "slug": "my-framework",
+      "name": "wake-adapter-my-framework",
+      "version": "0.1.0",
+      "homepage": "https://github.com/me/wake-adapter-my-framework",
+      "framework": "My Framework",
+      "conformance_score": 10,
+      "conformance_max": 10,
+      "last_verified": "2026-05-14",
+      "maintainers": ["me"],
+      "description": "..."
+    }
   ]
 }
```

5. **Review** — catalog maintainers run the workflow themselves to verify results before merge
6. **Merge + redeploy** — site rebuilt automatically (or via manual `pnpm build && deploy`)

---

## Badge embed

After merge, embed in your README:

```markdown
[![Wake conformance 10/10](https://catalog.wake.dev/badge/my-framework.svg)](https://catalog.wake.dev/adapters/my-framework/)
```

CLI also generates badge locally:

```bash
wake adapter badge generate --name my-framework --score 10
```

---

## Anti-claim cases

- ❌ Adapter that *almost* implements the ABI (broken `step()` async generator, missing `on_lifecycle`) — listed only after 10/10 or with explicit `wip` flag
- ❌ Adapter that vendors entire framework (instead of wrapping public API)
- ❌ Adapter with security incidents (token leakage, prompt injection bypass) — gets a `security-review-pending` flag

Catalog maintainers can delist with reason — keeping the listing trustworthy.

---

## Roadmap

- Phase 9: initial 4 reference adapters + claim workflow (done)
- Phase 10 (Public Launch): submit 5-10 community adapters
- Phase 11+: badge SLA endpoint (Prometheus probe) + automatic delisting on stale repos
