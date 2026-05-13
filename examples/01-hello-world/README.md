# 01 — Hello World

The shortest possible end-to-end Wake demo. Runs a one-shot agent against a
local server and prints its reply.

## What it does

1. Starts the Wake API server in the background (`wake server --local`).
2. Calls `wake run "Say hello in 3 languages..."`, which:
   - Creates an ephemeral agent backed by `claude-opus-4-7`.
   - Creates a session for that agent.
   - Sends the message as a `user.message` event.
   - Streams `assistant.delta` / `assistant.message` events back, printing
     the answer as it arrives.
3. Stops the server when the script exits (`trap`).

## Prerequisites

- `pip install -e ".[dev]"` from the repo root.
- `ANTHROPIC_API_KEY` exported in your shell — the harness slice needs it to
  talk to the Claude API.

## Run

```bash
cd examples/01-hello-world
./run.sh
```

Expected output (abridged):

```
[wake] starting server at http://127.0.0.1:8080
session sess_01H… on agent agt_01H…
Hello! Bonjour! Olá!
```

## Inspecting the event log

After the script finishes, the server is gone — but if you re-run with the
server kept alive (comment out the `trap`), you can replay everything:

```bash
wake session list
wake session events <SESSION_ID>
```

That should print the full ordered log: `user.message`, `status running`,
`assistant.delta` × N, `assistant.message`, `status idle`.
