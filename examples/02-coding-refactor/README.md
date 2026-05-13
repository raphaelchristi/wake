# 02 — Coding Refactor

Demonstrates an agent reading and editing real source files inside a
sandboxed workspace. The agent is asked to rewrite the class-based
`Greeter` in `test_repo/utils.py` into a function/closure style and
to update `main.py` to use the new shape.

## Layout

```
02-coding-refactor/
├── README.md
├── wake.yaml          # declarative agent + environment manifest
├── run.sh             # end-to-end demo script
└── test_repo/         # the workspace the agent is allowed to edit
    ├── main.py
    └── utils.py
```

## What it exercises

- `wake agent create` (with `--tools bash,file_read,file_write,file_edit`).
- `wake environment create` from a YAML config (`wake.yaml`).
- `wake session create` bound to that environment.
- `wake session send` to issue a refactor instruction.
- `wake session stream --follow` to watch the agent reason, call tools, and
  write the results.
- `wake session events --tool-only` after the fact to inspect every
  `tool_use` / `tool_result` pair.

## Prerequisites

- `pip install -e ".[dev]"` from the repo root.
- Docker running locally — the sandbox slice uses Docker by default.
- `ANTHROPIC_API_KEY` exported.

## Run

```bash
cd examples/02-coding-refactor
./run.sh
```

The script copies `test_repo/` into a fresh workspace under
`/tmp/wake-refactor-<timestamp>`, starts the server, creates the agent
and session, sends the refactor message, and streams events until the
turn completes.

Inspect the result:

```bash
diff -r test_repo /tmp/wake-refactor-<timestamp>
```

You should see `Greeter` replaced by a `make_greeter` function (or a
pair of free functions) and `main.py` updated to call the new API.

## Sandbox sanity check

The same session can be asked to read a path outside its workspace —
the sandbox should reject it:

```bash
wake session send <SESSION_ID> "Try to read /etc/passwd"
wake session events <SESSION_ID> --type tool_result --tool-only | tail
```

The latest `tool_result` should carry `is_error=true` with a permission
denied message.
