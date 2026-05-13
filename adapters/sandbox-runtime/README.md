# wake-sandbox-runtime

`SandboxAdapter` implementation that wraps the npm
[`@anthropic-ai/sandbox-runtime`](https://github.com/anthropic-experimental/sandbox-runtime)
CLI (beta research preview) — bubblewrap on Linux, `sandbox-exec` on macOS —
with a graceful fallback to the Phase 1
[`DockerSandbox`](../../src/wake/sandbox/docker.py).

> **Status:** Phase 4, v0.1.0. Implements the same tool ABI as the Docker
> reference (`bash`, `file_read`, `file_write`, `file_edit`).

---

## Why this adapter

Wake's Phase 1 sandbox uses Docker — fine for local dev, weak isolation in
production. This package swaps in a stronger sandbox without changing the
`SandboxAdapter` contract:

- **Linux** → uses kernel namespaces via [bubblewrap](https://github.com/containers/bubblewrap)
- **macOS** → uses Apple's `sandbox-exec` (Seatbelt) profile
- **Anywhere else** (Windows, BSDs) → falls back to Docker, with a warning

The adapter is a thin async wrapper that shells out to the `sandbox-runtime`
CLI via `asyncio.create_subprocess_exec` with the per-session JSON spec piped
on stdin. No long-running daemon, no pip dependency on the CLI.

---

## Install

```bash
pip install -e adapters/sandbox-runtime
```

### Install the srt CLI

```bash
npm install -g @anthropic-ai/sandbox-runtime
sandbox-runtime --version
```

### Platform setup

#### Linux

```bash
# Debian / Ubuntu
sudo apt install bubblewrap

# Fedora / RHEL
sudo dnf install bubblewrap
```

**Ubuntu 24.04+ gotcha.** The default AppArmor profile blocks unprivileged
user namespaces, which bubblewrap needs:

```bash
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0

# Persist across reboots:
echo "kernel.apparmor_restrict_unprivileged_userns=0" \
  | sudo tee /etc/sysctl.d/60-bwrap.conf
```

Without this, you will get cryptic `bwrap: setting up uid map: Permission
denied` errors. The adapter raises `SandboxUnavailableError` mentioning this
when it detects the issue.

#### macOS

`sandbox-exec` ships with macOS — no setup required. Tested on macOS 14+.

#### Windows / others

No native support. `select_sandbox_backend()` will fall back to Docker.

---

## Usage

### Selector (recommended)

```python
from wake_sandbox_runtime import select_sandbox_backend

# Tries sandbox-runtime first, falls back to Docker, raises if neither works.
backend = await select_sandbox_backend(prefer="sandbox-runtime")

handle = await backend.provision(env)
result = await backend.execute(handle, "bash", {"command": "echo hi"})
await backend.destroy(handle)
```

### Direct construction

```python
from wake_sandbox_runtime import SandboxRuntimeAdapter

adapter = SandboxRuntimeAdapter(
    srt_binary="sandbox-runtime",                      # default
    proxy_url="http://agentgateway.local:8888",        # optional, for proxied egress
)
```

### Environment config

`provision()` reads from `EnvironmentConfig.config`:

| Key                | Type           | Default       | Description                                                |
|--------------------|----------------|---------------|------------------------------------------------------------|
| `workspace`        | `str`          | `/workspace`  | Read- and write-allowed working directory                  |
| `network_mode`     | `str`          | `"none"`      | `"none"` / `"host"` / `"proxied"`                          |
| `read_allow`       | `list[str]`    | `[]`          | Extra paths the sandbox may read                           |
| `write_allow`      | `list[str]`    | `[]`          | Extra paths the sandbox may write                          |
| `read_deny`        | `list[str]`    | `[]`          | Extra paths to deny (mandatory list is always added)       |
| `write_deny`       | `list[str]`    | `[]`          | Extra paths to deny                                        |
| `env`              | `dict[str,str]`| `{}`          | Env vars set inside the sandbox                            |
| `passthrough_env`  | `list[str]`    | `PATH,LANG,…` | Env var names to inherit from the host                     |
| `timeout_seconds`  | `int`          | `60`          | Default tool execution timeout                             |

---

## Mandatory deny paths

The following paths are **always** denied for both read and write, regardless
of what the caller configures. You **cannot** override them via
`read_allow` / `write_allow`:

```
~/.ssh
~/.aws
~/.gnupg
~/.config/gh
~/.kube
~/.docker/config.json
/etc/shadow
/etc/sudoers
/etc/sudoers.d
/root/.ssh
```

This is a defense-in-depth measure: even if a caller misconfigures the
allow-list, common credential locations stay blocked.

---

## Network modes

| Mode       | Behavior                                                          |
|------------|-------------------------------------------------------------------|
| `none`     | No network access (default)                                       |
| `host`     | Full host networking — use with caution                           |
| `proxied`  | Sets `HTTP_PROXY` / `HTTPS_PROXY` to `proxy_url`; expects an egress proxy (e.g. agentgateway) |

The `proxied` mode is what you want in production: route all egress through
an [agentgateway](https://github.com/agentgateway/agentgateway) sidecar that
applies allowlists and credential injection per the
[Phase 4 vault adapter](../vault-infisical/README.md).

---

## Fallback semantics

`select_sandbox_backend(prefer="sandbox-runtime")` walks this ladder:

1. Detect platform — Linux+bwrap or macOS → continue, else step 4.
2. Run `sandbox-runtime --version` — exit 0 → return `SandboxRuntimeAdapter`.
3. Otherwise → log a warning and step 4.
4. Try `DockerSandbox()` — succeeds → return it.
5. Else → raise `SandboxUnavailableError`.

Pass `strict=True` to skip the fallback entirely.

---

## Entry-point discovery

Registered under the `wake.sandboxes` entry-point group:

```toml
[project.entry-points."wake.sandboxes"]
sandbox-runtime = "wake_sandbox_runtime.adapter:create"
```

The factory `create()` returns a default-configured `SandboxRuntimeAdapter`.
A future `SandboxRegistry.discover()` (analogous to `AdapterRegistry` for
harness adapters) will pick this up automatically.

---

## Testing

```bash
# Unit tests (mocked subprocess) — fast, hermetic.
pytest adapters/sandbox-runtime/tests/ -q

# Integration tests against the real srt CLI — opt-in.
pytest adapters/sandbox-runtime/tests/integration -m integration
```

The integration tests verify:

- `~/.ssh/id_rsa` is unreadable from inside the sandbox.
- A basic `echo hello` round-trips.

They auto-skip when `sandbox-runtime` is not on `PATH`.

---

## Example

See [`examples/restricted_bash.py`](examples/restricted_bash.py):

```bash
python adapters/sandbox-runtime/examples/restricted_bash.py
```

Runs `ls /etc | head` (allowed) and tries `cat ~/.ssh/id_rsa` (denied).
Works whether srt or Docker is the active backend.

---

## Limitations (v0.1.0)

- No support for persistent state across `provision()` calls — each `execute()`
  starts a fresh sandboxed process. This matches the Phase 1 ABI but means
  shell session state (cwd, env exports) does not persist between tool calls.
  A future version may add session-scoped daemons.
- No GPU / `--device` passthrough yet.
- Image / package preinstall happens via the workspace mount, not by building
  a sandbox image. For richer environment provisioning, layer Docker
  underneath.
