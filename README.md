# MCP-UERANSIM

MCP tool to manage simulated gNB and UE resources using UERANSIM, on Docker or Kubernetes.

This repo is the implementation of the paper [5G RAN Simulation Enhancement via the Model Context Protocol](https://ieeexplore.ieee.org/document/11481802). If you find this repo useful please cite it:

```bibtex
@INPROCEEDINGS{11481802,
  author={Brodimas, Dimitrios and Kapoulos, Dimitrios and Birbas, Alexios},
  booktitle={2026 29th Conference on Innovation in Clouds, Internet and Networks (ICIN)},
  title={5G RAN Simulation Enhancement via the Model Context Protocol},
  year={2026},
  pages={1-5},
  doi={10.1109/ICIN69025.2026.11481802}}
```

## Overview

MCP-UERANSIM is a Model Context Protocol (MCP) server that provides tools for managing UERANSIM-based 5G network simulations. It supports two backends:

- **Docker** — run gNB and UE nodes as local containers
- **Kubernetes** — run gNB and UE nodes as pods on a remote or local cluster

## Project Structure

```
MCP-UERANSIM/
├── main.py                        # Server entry point
├── requirements.txt               # Python dependencies (mcp, kubernetes)
├── config/                        # UERANSIM configuration templates
│   ├── open5gs-gnb.yaml           # gNB configuration template
│   └── open5gs-ue.yaml            # UE configuration template
├── docker/                        # Docker build files
│   ├── gnb_ubuntu.Dockerfile
│   ├── gnb_alpine.Dockerfile
│   ├── ue_ubuntu.Dockerfile
│   ├── ue_alpine.Dockerfile
│   ├── gnb-entrypoint.sh
│   └── ue-entrypoint.sh
├── k8s/                           # Kubernetes manifests
│   ├── namespace.yaml             # ueransim namespace
│   ├── gnb-pod-example.yaml       # Reference gNB pod spec
│   └── ue-pod-example.yaml        # Reference UE pod spec
└── ueransim_mcp/
    └── server.py                  # MCP server — all 24 tools
```

## Available Tools

### Docker Tools

#### gNB

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `create_gnb` | Create a gNB container | `amf_address`, `amf_port`, `container_name` |
| `list_gnbs` | List all gNB containers | — |
| `delete_gnb` | Delete a gNB container | `container_id_or_name` |
| `get_gnb_logs` | Get logs from a gNB container | `container_id_or_name`, `lines` |
| `attach_gnb_to_core` | Start nr-gnb and connect to AMF | `container_id_or_name`, `amf_address` |

#### UE

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `create_ue` | Create a UE container | `gnb_search_list`, `container_name` |
| `list_ues` | List all UE containers | — |
| `delete_ue` | Delete a UE container | `container_id_or_name` |
| `get_ue_logs` | Get logs from a UE container | `container_id_or_name`, `lines` |
| `attach_ue_to_gnb` | Start nr-ue and connect to gNB | `ue_container_id_or_name`, `gnb_container_id_or_name` |

#### Common

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `inspect_container_ip` | Get a container's IP address | `container_id_or_name` |
| `edit_exist_container` | Edit config in a running container | `container_id_or_name`, `config_type`, `config_value` |

### Kubernetes Tools

All Kubernetes tools mirror their Docker counterparts and default to the `ueransim` namespace.

#### gNB

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `k8s_create_gnb` | Create a gNB pod | `amf_address`, `amf_port`, `pod_name`, `namespace`, `gnb_image`, `image_pull_secret` |
| `k8s_list_gnbs` | List all gNB pods | `namespace` |
| `k8s_delete_gnb` | Delete a gNB pod | `pod_name`, `namespace` |
| `k8s_get_gnb_logs` | Get logs from a gNB pod | `pod_name`, `lines`, `namespace` |
| `k8s_attach_gnb_to_core` | Start nr-gnb and connect to AMF | `pod_name`, `amf_address`, `namespace` |

#### UE

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `k8s_create_ue` | Create a UE pod | `gnb_search_list`, `pod_name`, `namespace`, `ue_image`, `image_pull_secret` |
| `k8s_list_ues` | List all UE pods | `namespace` |
| `k8s_delete_ue` | Delete a UE pod | `pod_name`, `namespace` |
| `k8s_get_ue_logs` | Get logs from a UE pod | `pod_name`, `lines`, `namespace` |
| `k8s_attach_ue_to_gnb` | Start nr-ue and connect to gNB | `ue_pod_name`, `gnb_pod_name`, `namespace` |

#### Common

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `k8s_inspect_pod_ip` | Get a pod's IP address | `pod_name`, `namespace` |
| `k8s_edit_pod_config` | Edit config in a running pod | `pod_name`, `config_type`, `config_value`, `namespace` |

## Installation

### Prerequisites

- Python 3.8+
- [uv](https://docs.astral.sh/uv/) package manager
- **Docker** (for Docker tools)
- **kubectl** + access to a Kubernetes cluster (for Kubernetes tools)

### Install the MCP server

```bash
git clone https://github.com/APELGroup/MCP-UERANSIM.git
cd MCP-UERANSIM
uv run mcp install ueransim_mcp/server.py
```

Or for manual Claude Desktop configuration:

```json
{
  "mcpServers": {
    "ueransim": {
      "command": "uv",
      "args": ["run", "python", "ueransim_mcp/server.py"],
      "cwd": "/path/to/MCP-UERANSIM"
    }
  }
}
```

## Docker Setup

### Option A — Pull prebuilt images (recommended)

```bash
docker pull ghcr.io/apelgroup/mcp-ueransim-new/ueransim-gnb:latest
docker pull ghcr.io/apelgroup/mcp-ueransim-new/ueransim-ue:latest
```

> The images are private. You need a GitHub PAT with `read:packages` scope and must be logged in:
> ```bash
> echo <your-pat> | docker login ghcr.io -u <your-github-username> --password-stdin
> ```

### Option B — Build locally

```bash
# gNB (choose Ubuntu or Alpine)
docker build -f docker/gnb_ubuntu.Dockerfile -t ghcr.io/apelgroup/mcp-ueransim-new/ueransim-gnb:latest .
# OR
docker build -f docker/gnb_alpine.Dockerfile -t ghcr.io/apelgroup/mcp-ueransim-new/ueransim-gnb:latest .

# UE (choose Ubuntu or Alpine)
docker build -f docker/ue_ubuntu.Dockerfile -t ghcr.io/apelgroup/mcp-ueransim-new/ueransim-ue:latest .
# OR
docker build -f docker/ue_alpine.Dockerfile -t ghcr.io/apelgroup/mcp-ueransim-new/ueransim-ue:latest .
```

### Docker Workflow

```
create_gnb  ──►  attach_gnb_to_core  ──►  (gNB running, nr-gnb active)
create_ue   ──►  attach_ue_to_gnb    ──►  (UE running, nr-ue active)
```

**Important:** `attach_gnb_to_core` must be called before `attach_ue_to_gnb` — the gNB process must be up before the UE tries to connect.

#### Example

```python
# 1. Create nodes
gnb = create_gnb(amf_address="192.168.100.1")
ue  = create_ue(gnb_search_list="auto")   # auto-detects first gNB IP

# 2. Start processes
attach_gnb_to_core(container_id_or_name=gnb.container_name)
attach_ue_to_gnb(
    ue_container_id_or_name=ue.container_name,
    gnb_container_id_or_name=gnb.container_name
)

# 3. Monitor
get_gnb_logs(container_id_or_name=gnb.container_name, lines=50)
get_ue_logs(container_id_or_name=ue.container_name, lines=50)
```

## Kubernetes Setup

### 1. Create the namespace

```bash
kubectl apply -f k8s/namespace.yaml
```

### 2. Create an image pull secret

```bash
kubectl create secret docker-registry ghcr-pull-secret \
  --docker-server=ghcr.io \
  --docker-username=<your-github-username> \
  --docker-password=<your-pat-token> \
  --namespace=ueransim
```

### 3. Kubernetes Workflow

```
k8s_create_gnb  ──►  k8s_attach_gnb_to_core  ──►  (gNB pod running, nr-gnb active)
k8s_create_ue   ──►  k8s_attach_ue_to_gnb    ──►  (UE pod running, nr-ue active)
```

#### Example

```python
# 1. Create pods
gnb = k8s_create_gnb(amf_address="192.168.100.1", namespace="ueransim")
ue  = k8s_create_ue(gnb_search_list="auto", namespace="ueransim")

# 2. Start processes
k8s_attach_gnb_to_core(pod_name=gnb.container_name, amf_address="192.168.100.1")
k8s_attach_ue_to_gnb(
    ue_pod_name=ue.container_name,
    gnb_pod_name=gnb.container_name
)

# 3. Monitor
k8s_get_gnb_logs(pod_name=gnb.container_name, lines=50)
k8s_get_ue_logs(pod_name=ue.container_name, lines=50)
```

### Pod specifications

**gNB pod** — `NET_ADMIN` capability, regular pod networking.

**UE pod** — `privileged`, `NET_ADMIN`, `hostNetwork: true`, `/dev/net/tun` device mounted. Requires the cluster's admission policy to allow privileged pods (set `PodSecurity` to `privileged` profile on the namespace).

## Configuration

All tools configure UERANSIM by running `sed` inside the container/pod at creation time:

| Tool | File | Fields updated |
|------|------|----------------|
| `create_gnb` / `k8s_create_gnb` | `open5gs-gnb.yaml` | `linkIp`, `ngapIp`, `gtpIp`, `amfConfigs[0].address` |
| `attach_gnb_to_core` / `k8s_attach_gnb_to_core` | `open5gs-gnb.yaml` | `amfConfigs[0].address` |
| `create_ue` / `k8s_create_ue` | `open5gs-ue.yaml` | `gnbSearchList[0]` |
| `edit_exist_container` / `k8s_edit_pod_config` | both | Any of the above fields |

Config files inside the container/pod:
- gNB: `/etc/ueransim/open5gs-gnb.yaml`
- UE: `/etc/ueransim/open5gs-ue.yaml`

## Troubleshooting

### Docker

| Problem | Fix |
|---------|-----|
| Image not found | Pull or build the images (see Docker Setup) |
| Container not found | Use `list_gnbs` / `list_ues` to get exact names |
| UE can't connect to gNB | Ensure `attach_gnb_to_core` ran first; check gNB logs |
| Process not starting | Run `docker exec <name> ps aux \| grep nr-` to check |

### Kubernetes

| Problem | Fix |
|---------|-----|
| `ImagePullBackOff` | Check pull secret exists: `kubectl get secret ghcr-pull-secret -n ueransim` |
| Pod stuck in `Pending` | Check node resources: `kubectl describe pod <name> -n ueransim` |
| Exec fails | Pod must be in `Running` phase before exec commands work |
| UE TUN device error | Ensure cluster allows privileged pods on the `ueransim` namespace |

## Acknowledgments

- [UERANSIM](https://github.com/aligungr/UERANSIM) — Open source 5G UE and RAN simulator
- [Model Context Protocol](https://github.com/modelcontextprotocol/python-sdk) — MCP Python SDK
- [Claude Desktop](https://claude.ai/download)
