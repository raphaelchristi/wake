# Wake Dashboard

Operator UI for [Wake](../README.md) — a durable runtime substrate for AI agents.

This is a [Next.js 15](https://nextjs.org/) App Router single-page application
that talks to the FastAPI backend in `../src/wake/api/` to operate Wake sessions
in production: list & inspect sessions, replay events, monitor metrics, and
manage credentials.

> **Slice scope:** this directory was bootstrapped by the `dashboard-shell`
> slice of Phase 5. Replay UI, metrics, and vault pages are added by the
> sibling slices `dashboard-replay` and `dashboard-metrics-vault`.

## Stack

- **Next.js 15** App Router (RSC + client components)
- **TypeScript strict**
- **Tailwind CSS v4** (CSS-first config)
- **shadcn/ui** primitives + **Lucide** icons
- **TanStack Query v5** for data fetching, **TanStack Table v8** for tables
- **Recharts** for charts
- **Vitest** + **react-testing-library** + **MSW** for unit tests
- **Playwright** for end-to-end tests
- **openapi-typescript** for generating an FastAPI client at build time
- **pnpm** as package manager (>=9)

## Setup

```bash
# from this directory
pnpm install --frozen-lockfile
pnpm dev              # http://localhost:3000
```

The dev server expects the Wake API to be reachable. By default it points at
`http://localhost:8080`; override with `NEXT_PUBLIC_WAKE_API_BASE`.

## Auth

The dashboard authenticates against the Wake API via an API key sent in the
`X-Wake-API-Key` request header.

1. Set `WAKE_API_KEY` in the backend's environment (`uvicorn`/`wake server`)
2. Visit `/login`, paste the key, click _Sign in_
3. The key is persisted in `localStorage` (not in a cookie) on the operator's
   workstation — same model as the CLI

## Scripts

| Script | What it does |
| --- | --- |
| `pnpm dev` | Next.js dev server with HMR |
| `pnpm build` | Production build (standalone output for Docker) |
| `pnpm start` | Serve the production build |
| `pnpm lint` | ESLint (Next.js + TypeScript rules) |
| `pnpm typecheck` | `tsc --noEmit` |
| `pnpm test` | Vitest unit tests (jsdom/happy-dom) |
| `pnpm test:e2e` | Playwright e2e (requires `pnpm build` first) |
| `pnpm format` | Prettier write |
| `pnpm openapi:generate` | Re-generate `src/lib/api/generated.ts` from the backend's `openapi.json` |

## Environment variables

| Var | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_WAKE_API_BASE` | `http://localhost:8080` | **Browser-facing** base URL of the Wake API. Public, baked into the client bundle at build time. |
| `WAKE_API_URL` | falls back to `NEXT_PUBLIC_WAKE_API_BASE` | **Server-side** base URL used by Next.js route handlers (OAuth callback proxy). Private; never exposed to the browser. |
| `WAKE_API_KEY` | unset | Server-side API key injected by `/oauth/callback/api` as `X-Wake-API-Key`. Browser never sees it. |
| `WAKE_OPENAPI_URL` | `http://localhost:8080/openapi.json` | Where `pnpm openapi:generate` fetches the schema |

> **Deprecated:** `NEXT_PUBLIC_API_URL` (pre-Phase-5.1). The client
> still falls back with a `console.warn` for one transition release;
> remove from deploy manifests and use `NEXT_PUBLIC_WAKE_API_BASE`.

## Codegen

The frontend treats the FastAPI OpenAPI document as the source of truth for
API shapes. After backend changes:

```bash
# from this directory, with the backend running:
pnpm openapi:generate

# or against a static schema file at repo root:
WAKE_OPENAPI_URL=file:../openapi.json pnpm openapi:generate
```

Generated types land in `src/lib/api/generated.ts` and are re-exported from
`src/lib/api/types.ts`. **Do not edit `generated.ts` by hand.**

## Layout / theming

- App shell in `src/components/layout/` (sidebar + topbar)
- Dark mode is the default; toggle persists in `localStorage.theme`
- Theme tokens in `src/styles/tokens.css`

## File ownership (slice)

This slice owns:

- `frontend/` scaffolding (build config, eslint, tsconfig, Tailwind)
- `src/app/` shell + login + sessions list + sessions detail shell
- `src/components/{layout,sessions,ui}/`
- `src/lib/{api,auth,format,sse,queryClient}`
- `src/hooks/{useSessions,useSession,useSSE}`
- Backend additive change: filter query params on `GET /v1/sessions`

The replay and metrics/vault slices add their own pages and components into
this Next.js app via the `(authed)/` group layout.

## Testing

- **Unit (`pnpm test`)** — Vitest + react-testing-library. MSW intercepts
  `fetch` for the API client tests.
- **E2E (`pnpm test:e2e`)** — Playwright against a built Next.js standalone
  binary, with the API stubbed via MSW.

CI runs lint → typecheck → test → build on every push to `main`/PRs in
`.github/workflows/frontend-ci.yml`.
