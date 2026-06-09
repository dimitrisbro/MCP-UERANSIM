# CLAUDE.md — MCP-UERANSIM

MCP server for managing UERANSIM 5G simulations over Docker or Kubernetes.
Research project; accompanies the ICIN 2026 paper by Brodimas, Kapoulos, Birbas.

---

## Project layout

```
ueransim_mcp/
  server.py       — entry point; imports tool modules as side-effects to register @mcp.tool()
  app.py          — FastMCP singleton shared by all modules (import mcp from here)
  models.py       — Pydantic response models
  validators.py   — validate_ip, validate_mcc, validate_mnc, validate_nci, validate_hex_key, etc.
  utils.py        — generate_random_suffix(length=4)
  config_ops.py   — returns List[List[str]] sed/awk commands; shared by Docker and K8s tools
  docker_utils.py — get_container_runtime, run_container_command, detect_image_os, get_container_name
  docker_tools.py — 12 Docker @mcp.tool() functions
  k8s_utils.py    — get_k8s_client(kubeconfig=""), exec_in_pod, wait_for_pod_running
  k8s_tools.py    — 12 Kubernetes @mcp.tool() functions (all accept kubeconfig: str = "")

config/           — UERANSIM YAML templates (open5gs-gnb.yaml, open5gs-ue.yaml)
docker/           — Dockerfiles (gnb/ue × ubuntu/alpine) + entrypoint scripts
k8s/              — Kubernetes manifests (namespace.yaml, gnb/ue pod examples)
```

## Running the server

```bash
python main.py
```

## Building Docker images

**Always build from the project root** — COPY paths in the Dockerfiles are relative to it:

```bash
nerdctl build -f docker/gnb_ubuntu.Dockerfile -t ghcr.io/dimitrisbro/mcp-ueransim/ueransim-gnb:latest .
nerdctl build -f docker/ue_ubuntu.Dockerfile  -t ghcr.io/dimitrisbro/mcp-ueransim/ueransim-ue:latest .
```

Images are stored in GHCR under `ghcr.io/dimitrisbro/mcp-ueransim/`.

## Kubernetes cluster

- Default cluster: single-node at `192.168.188.210:6443` (node: `coppilot-server`)
- Namespace: `ueransim` (apply `k8s/namespace.yaml` if missing)
- GHCR pull secret: `ghcr-pull-secret` (already created in `ueransim` namespace)
- Always pass `image_pull_secret='ghcr-pull-secret'` to `k8s_create_gnb` / `k8s_create_ue`
- To target a different cluster, pass `kubeconfig='/path/to/cluster.yaml'` to any K8s tool. Priority: explicit kubeconfig > in-cluster config > default `~/.kube/config`.

## Key design decisions

- **No auto-start**: containers/pods run `tail -f /dev/null` and UERANSIM binaries are started manually by the MCP tools (`attach_gnb_to_core`, `attach_ue_to_gnb`).
- **Config via sed/awk**: scalar fields updated with `sed -i`, YAML block sections (slices) replaced with POSIX awk. Logic lives in `config_ops.py` and is reused by both Docker and K8s tools.
- **busybox awk compatibility**: awk patterns in `config_ops.py` and entrypoint scripts are written to work on both busybox (Alpine) and mawk/gawk (Ubuntu).
- **Container name detection**: `_detect_type()` in `docker_tools.py` infers gnb/ue from the container name prefix. Same logic applies in `k8s_tools.py`.
- **Tool registration**: importing `docker_tools` and `k8s_tools` in `server.py` triggers `@mcp.tool()` decorators as side-effects. Never move the `FastMCP` instance out of `app.py`.

## Config files inside containers

| File | Used by |
|------|---------|
| `/etc/ueransim/open5gs-gnb.yaml` | nr-gnb (gNB) |
| `/etc/ueransim/open5gs-ue.yaml`  | nr-ue  (UE)  |

## UERANSIM version

Targets **v3.2.8**. The `cellAccessType` field (added in v3.2.8) is present in `config/open5gs-gnb.yaml`.
Valid values: `nr`, `nr-leo`, `nr-meo`, `nr-geo`, `nr-othersat` (NTN satellite types).

## Adding new tools

1. Add Pydantic models to `models.py` if needed.
2. Add validators to `validators.py`.
3. Add config command generators to `config_ops.py` (return `List[List[str]]`).
4. Add the `@mcp.tool()` function to `docker_tools.py` or `k8s_tools.py`.
5. No changes to `server.py` or `app.py` needed.

## Verifying tool registration

```bash
python3 -c "from ueransim_mcp.app import mcp; import ueransim_mcp.docker_tools, ueransim_mcp.k8s_tools; print([t.name for t in mcp._tool_manager._tools.values()])"
```

## Packaging the MCP server as a Docker image

The MCP server is distributed as a Docker image so consumers don't need to clone the repo or manage a Python environment. The image uses **stdio transport**: the agent spawns the container, pipes JSON-RPC over stdin/stdout, and tears it down when done.

### Dockerfile (`docker/mcp/server.Dockerfile`)

Always build from the project root:

```bash
nerdctl build -f docker/mcp/server.Dockerfile -t ghcr.io/dimitrisbro/mcp-ueransim/server:latest .
nerdctl push ghcr.io/dimitrisbro/mcp-ueransim/server:latest
```

Login to GHCR once before pushing (needs a GitHub PAT with `write:packages`):

```bash
nerdctl login ghcr.io -u dimitrisbro
```

### Agent config

```json
{
  "mcpServers": {
    "ueransim": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", "/Users/dimitris/.kube:/root/.kube:ro",
        "ghcr.io/dimitrisbro/mcp-ueransim/server:latest"
      ]
    }
  }
}
```

The `-i` flag is mandatory — it keeps stdin open for stdio transport.

### Rules for any MCP server Dockerfile

1. **Keep stdout clean.** Any `print()` or log line written to stdout before `mcp.run()` is called will corrupt the JSON-RPC framing and cause the client to drop the connection immediately. Route all banners and diagnostics to `stderr`.

2. **Install every CLI the server shells out to.** `python:3.12-slim` ships no `docker` or `kubectl` binary. If the server calls `subprocess.run(["docker", ...])`, add `RUN apt-get install -y docker.io` (or copy the static binary). Check all `subprocess` / `shutil.which` calls in `*_utils.py`.

3. **Pin dependencies.** `requirements.txt` must use exact versions (`mcp==X.Y.Z`, `kubernetes==X.Y.Z`). Bare names let a breaking upstream release silently enter the image on a rebuild with no visible git diff.

4. **Handle PID 1 shutdown.** Python ignores SIGTERM by default when running as PID 1, so `docker stop` waits the full 10 s before SIGKILL. Either add `tini` (`RUN apt-get install -y tini` + `ENTRYPOINT ["tini", "--"]`) or register a signal handler in `main.py`.

5. **Don't run as root if mounting the Docker socket.** Add a non-root user and add it to the `docker` group, or document the accepted risk explicitly.
