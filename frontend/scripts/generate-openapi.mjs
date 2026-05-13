#!/usr/bin/env node
/**
 * Generate TypeScript types from the Wake FastAPI OpenAPI document.
 *
 * Usage:
 *   pnpm openapi:generate
 *
 * Reads from WAKE_OPENAPI_URL (default http://localhost:8080/openapi.json)
 * or, if no backend is reachable, from ../openapi.json at the repo root.
 *
 * Writes to src/lib/api/generated.ts. The file is checked in so the build
 * doesn't require a live backend.
 */
import { execSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(__dirname, "..");
const repoRoot = resolve(frontendRoot, "..");

const url = process.env.WAKE_OPENAPI_URL ?? "http://localhost:8080/openapi.json";
const out = resolve(frontendRoot, "src/lib/api/generated.ts");
const fallbackSchema = resolve(repoRoot, "openapi.json");

let source = url;
// If url is http(s) and the endpoint is unreachable, fall back to the
// checked-in openapi.json (Phase 5 ships one at repo root once generated).
if (url.startsWith("http")) {
  try {
    const probe = await fetch(url, { method: "HEAD" });
    if (!probe.ok) throw new Error(`HTTP ${probe.status}`);
  } catch {
    if (existsSync(fallbackSchema)) {
      console.warn(`[openapi] ${url} unreachable, falling back to ${fallbackSchema}`);
      source = fallbackSchema;
    } else {
      console.error(`[openapi] ${url} unreachable and no fallback at ${fallbackSchema}`);
      process.exit(1);
    }
  }
}

console.log(`[openapi] generating ${out} from ${source}`);
execSync(`npx openapi-typescript ${source} -o ${out}`, {
  stdio: "inherit",
  cwd: frontendRoot,
});
console.log("[openapi] done");
