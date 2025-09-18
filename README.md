# MCP-UERANSIM

MCP tool to manage simulated gNB and UE resources using UERANSIM

## Overview

MCP-UERANSIM is a Model Context Protocol (MCP) server that provides tools for managing UERANSIM-based 5G network simulations. It allows you to create, manage, and interact with simulated gNodeB (gNB) and User Equipment (UE) containers through a standardized MCP interface.

## Available Tools

### gNB (gNodeB) Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `create_gnb` | Create a new gNB container | `amf_address`, `amf_port`, `container_name` |
| `list_gnbs` | List all gNB containers | None |
| `delete_gnb` | Delete a gNB container | `container_id_or_name` |
| `get_gnb_logs` | Get logs from a gNB container | `container_id_or_name`, `lines` |
| `attach_gnb_to_core` | Connect gNB to core network | `container_id_or_name`, `amf_address` |

### UE (User Equipment) Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `create_ue` | Create a new UE container | `gnb_search_list`, `container_name` |
| `list_ues` | List all UE containers | None |
| `delete_ue` | Delete a UE container | `container_id_or_name` |
| `get_ue_logs` | Get logs from a UE container | `container_id_or_name`, `lines` |
| `attach_ue_to_gnb` | Connect UE to gNB | `ue_container_id_or_name`, `gnb_container_id_or_name` |

### Additional Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `inspect_container_ip` | Get container IP address | `container_id_or_name` |
| `edit_exist_container` | Edit container configuration | `container_id_or_name`, `config_type`, `config_value` |

## Features

- **Container Management**: Create, list, delete gNB and UE containers
- **Dynamic Configuration**: Runtime configuration of network parameters
- **Network Attachment**: Connect UE to gNB and gNB to core network
- **Log Monitoring**: Retrieve container logs for debugging
- **Input Validation**: Comprehensive validation of IP addresses, container IDs, and names
- **Structured Output**: Pydantic models for type-safe responses

## Project Structure

```
MCP-UERANSIM/
├── README.md                 # This file
├── requirements.txt          # Python dependencies
├── main.py                   # Alternative server entry point
├── specification.md          # Technical specification
├── config/                   # UERANSIM configuration templates
│   ├── open5gs-gnb.yaml     # gNB configuration template
│   └── open5gs-ue.yaml      # UE configuration template
├── docker/                   # Docker build files
│   ├── gnb_ubuntu.Dockerfile # gNB container (Ubuntu-based)
│   ├── gnb_alpine.Dockerfile # gNB container (Alpine-based)
│   ├── ue_ubuntu.Dockerfile  # UE container (Ubuntu-based)
│   ├── ue_alpine.Dockerfile  # UE container (Alpine-based)
│   ├── gnb-entrypoint.sh     # gNB startup script
│   └── ue-entrypoint.sh      # UE startup script
└── ueransim_mcp/            # MCP server implementation
    └── server.py             # Main MCP server with all tools
```

## Installation

### Prerequisites

- Python 3.8 or higher
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker installed and running (NOT Nerdctl - this project is Docker-only)
- Git (for cloning)
- **Internet connection** (for downloading UERANSIM source during Docker build)

### Important Notes Before Starting

1. **Docker Images**: You MUST build the Docker images before using any MCP tools
2. **Container Runtime**: This project only supports Docker (nerdctl support removed)
3. **Network Requirements**: Containers need network access for 5G simulation
4. **System Resources**: Each container uses some CPU/memory - monitor your system

### Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/APELGroup/MCP-UERANSIM.git
   cd MCP-UERANSIM
   ```

2. **Install with Claude Desktop using uv**
   ```bash
   uv run mcp install ueransim_mcp/server.py
   ```
   
   This will automatically:
   - Install Python dependencies
   - Register the MCP server with Claude Desktop
   - Make the tools available in Claude

3. **Build Docker images** (REQUIRED before using MCP tools)
   ```bash
   # Build gNB image (choose Ubuntu or Alpine)
   docker build -f docker/gnb_ubuntu.Dockerfile -t ueransim-gnb:latest .
   # OR
   docker build -f docker/gnb_alpine.Dockerfile -t ueransim-gnb:latest .
   
   # Build UE image (choose Ubuntu or Alpine)  
   docker build -f docker/ue_ubuntu.Dockerfile -t ueransim-ue:latest .
   # OR
   docker build -f docker/ue_alpine.Dockerfile -t ueransim-ue:latest .
   
   # Verify images were built successfully
   docker images | grep ueransim
   ```

   **Note**: You MUST build these Docker images before the MCP tools will work. The tools expect images named exactly `ueransim-gnb:latest` and `ueransim-ue:latest`.

## Using Prebuilt Docker Images

If you prefer to use prebuilt Docker images instead of building them locally, you can pull them from either Harbor or GitHub Packages. After pulling the images, make sure to tag them as `ueransim-gnb:latest` and `ueransim-ue:latest` to ensure compatibility with the MCP tools.

### Harbor

The images are available in the following repository:

- `mcp-ueransim/ueransim-ue-alpine`
- `mcp-ueransim/ueransim-gnb-alpine`
- `mcp-ueransim/ueransim-ue-ubuntu`
- `mcp-ueransim/ueransim-gnb-ubuntu`

Example:
```bash
docker pull mcp-ueransim/ueransim-gnb-alpine
# Tag the image
docker tag mcp-ueransim/ueransim-gnb-alpine ueransim-gnb:latest

docker pull mcp-ueransim/ueransim-ue-alpine
# Tag the image
docker tag mcp-ueransim/ueransim-ue-alpine ueransim-ue:latest
```

### GitHub Packages

The images are available in the following repository:

- `mcp-ueransim-new/ueransim-gnb`
- `mcp-ueransim-new/ueransim-ue`
- `mcp-ueransim/ueransim-gnb-alpine`
- `mcp-ueransim/ueransim-ue-alpine`

Example:
```bash
docker pull ghcr.io/mcp-ueransim-new/ueransim-gnb
# Tag the image
docker tag ghcr.io/mcp-ueransim-new/ueransim-gnb ueransim-gnb:latest

docker pull ghcr.io/mcp-ueransim-new/ueransim-ue
# Tag the image
docker tag ghcr.io/mcp-ueransim-new/ueransim-ue ueransim-ue:latest
```

## Quick Start

**IMPORTANT**: You must build the Docker images BEFORE installing the MCP server, otherwise the tools won't work!

### Installation & Integration with Claude Desktop

The easiest way to use MCP-UERANSIM is through Claude Desktop with `uv`:

```bash
# Clone and install in one command
git clone https://github.com/APELGroup/MCP-UERANSIM.git
cd MCP-UERANSIM
uv run mcp install ueransim_mcp/server.py
```

This automatically integrates the tools with Claude Desktop without needing manual configuration.

### Manual Configuration (Alternative)

If you prefer manual setup or need custom configuration, you can also add the following to your Claude Desktop MCP configuration:

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

## Usage Examples

Here are complete examples showing both the Claude Desktop questions you can ask and the resulting MCP tool calls:

### Creating and Managing Containers

**Ask Claude Desktop:**
"Create a new gNB container with AMF at 192.168.1.5"

This will trigger:
```python
create_gnb(
    amf_address="192.168.1.5",
    amf_port="38412",
    container_name="gnb-a1b2"  # Auto-generated
)
```

**Ask Claude Desktop:**
"Create a UE container that will connect to the gNB at 192.168.1.100"

This will trigger:
```python
create_ue(
    gnb_search_list="192.168.1.100",
    container_name="ue-c3d4"  # Auto-generated
)
```

### Listing and Monitoring

**Ask Claude Desktop:**
"Show me all running gNB containers"

This will trigger:
```python
list_gnbs()
```

**Ask Claude Desktop:**
"List all UE containers and their status"

This will trigger:
```python
list_ues()
```

**Ask Claude Desktop:**
"Get the last 50 lines of logs from container gnb-a1b2"

This will trigger:
```python
get_gnb_logs(
    container_id_or_name="gnb-a1b2",
    lines=50
)
```

### Network Connections

**Ask Claude Desktop:**
"Connect UE container ue-c3d4 to gNB container gnb-a1b2"

This will trigger:
```python
attach_ue_to_gnb(
    ue_container_id_or_name="ue-c3d4",
    gnb_container_id_or_name="gnb-a1b2"
)
```

**Ask Claude Desktop:**
"Attach gNB gnb-a1b2 to the core network with AMF address 192.168.188.205"

This will trigger:
```python
attach_gnb_to_core(
    container_id_or_name="gnb-a1b2",
    amf_address="192.168.188.205"
)
```

### Cleanup Operations

**Ask Claude Desktop:**
"Delete the gNB container named gnb-a1b2"

This will trigger:
```python
delete_gnb(container_id_or_name="gnb-a1b2")
```

**Ask Claude Desktop:**
"Remove UE container ue-c3d4 and stop it first"

This will trigger:
```python
delete_ue(container_id_or_name="ue-c3d4")
```

### Complete Workflow Example

**Ask Claude Desktop:**
"Set up a complete 5G test environment: create a gNB with AMF at 192.168.100.1, create a UE, connect them together, and show me the logs"

This will trigger a sequence of operations:

**Step-by-step breakdown:**
1. `create_gnb(amf_address="192.168.100.1")` - Creates gNB container with configuration
2. `create_ue(gnb_search_list="auto")` - Creates UE container, auto-detects gNB IP
3. `attach_gnb_to_core()` - **IMPORTANT: Must happen FIRST** - Starts nr-gnb process  
4. `attach_ue_to_gnb()` - Starts nr-ue process and connects to gNB
5. `get_gnb_logs()` and `get_ue_logs()` - Shows connection status

**CRITICAL ORDER - You must follow this sequence:**
```python
# Step 1: Create containers (no processes started yet)
gnb_result = create_gnb(amf_address="192.168.100.1")
ue_result = create_ue(gnb_search_list="auto")  # Or specific gNB IP

# Step 2: FIRST attach gNB to core (starts nr-gnb process)
attach_gnb_to_core(container_id_or_name=gnb_result.container_name)

# Step 3: THEN attach UE to gNB (starts nr-ue process)
attach_ue_to_gnb(
    ue_container_id_or_name=ue_result.container_name, 
    gnb_container_id_or_name=gnb_result.container_name
)
```

**Why this order matters:**
- The gNB must be running (step 2) before the UE tries to connect to it (step 3)
- If you reverse the order, the UE won't find an active gNB to connect to

### Natural Language Examples

You can ask Claude Desktop in natural language:

- *"How many gNBs are currently running?"*
- *"Create a test setup with gNB and UE on the 10.0.0.x network"*
- *"Show me what went wrong with container gnb-test01"*
- *"Clean up all my test containers"*
- *"Connect my UE to a different gNB"*
- *"Reconfigure gNB to use new core network IPs"*

## Configuration

### gNB Configuration Changes

The MCP server automatically modifies the `/etc/ueransim/open5gs-gnb.yaml` file inside the container:

#### During `create_gnb`:
```yaml
# Original template values are replaced with actual container IP
linkIp: 172.17.0.2    # ← Updated to container's actual IP
ngapIp: 172.17.0.2    # ← Updated to container's actual IP  
gtpIp: 172.17.0.2     # ← Updated to container's actual IP

amfConfigs:
  - address: 127.0.0.5  # ← Updated to user-provided AMF address
    port: 38412
```

#### During `attach_gnb_to_core`:
```yaml
amfConfigs:
  - address: 192.168.188.205  # ← Updated to new AMF address (default or user-provided)
    port: 38412
```

**Note**: The `linkIp`, `ngapIp`, and `gtpIp` are **NOT** changed during `attach_gnb_to_core` - only the AMF address is updated.

### UE Configuration Changes

The MCP server automatically modifies the `/etc/ueransim/open5gs-ue.yaml` file inside the container:

#### During `create_ue`:
```yaml
gnbSearchList:
  - 127.0.0.1    # ← Original template value
```

Becomes:
```yaml
gnbSearchList:
  - 192.168.1.100  # ← Updated to user-provided or auto-detected gNB IP
```

#### Configuration File Locations:
- **gNB config**: `/etc/ueransim/open5gs-gnb.yaml` 
- **UE config**: `/etc/ueransim/open5gs-ue.yaml`

#### What Gets Modified:
| Function | File | Field Changed | Purpose |
|----------|------|---------------|---------|
| `create_gnb` | `open5gs-gnb.yaml` | `linkIp`, `ngapIp`, `gtpIp` | Set to container's IP |
| `create_gnb` | `open5gs-gnb.yaml` | `amfConfigs[0].address` | Set to provided AMF address |
| `attach_gnb_to_core` | `open5gs-gnb.yaml` | `amfConfigs[0].address` | Update AMF address only |
| `create_ue` | `open5gs-ue.yaml` | `gnbSearchList[0]` | Set gNB IP to connect to |

### Process Execution Workflow

The MCP server follows a specific workflow for when processes are started:

#### gNB Workflow:
1. **`create_gnb`**: Creates container + configures files (NO process started)
2. **`attach_gnb_to_core`**: Updates AMF address + starts `nr-gnb` process

#### UE Workflow:
1. **`create_ue`**: Creates container + configures gnbSearchList (NO process started) 
2. **`attach_ue_to_gnb`**: Starts `nr-ue` process only

#### Process Commands Executed:
```bash
# In gNB container (during attach_gnb_to_core):
/usr/local/bin/nr-gnb -c /etc/ueransim/open5gs-gnb.yaml

# In UE container (during attach_ue_to_gnb):
/usr/local/bin/nr-ue -c /etc/ueransim/open5gs-ue.yaml
```

**Important**: Each process starts only ONCE at the right time - no duplicate process execution.

## Input Validation

All tools include comprehensive input validation:

- **IP Addresses**: Must be in format "x.x.x.x" with valid octets (0-255)
- **Container IDs**: Must be alphanumeric (12 or 64 characters)
- **Container Names**: Must use only letters, numbers, underscores, and hyphens
- **Naming Convention**: gNB containers must start with "gnb-", UE containers with "ue-"

## Docker Images

### Image Labels

Both Docker images include labels for identification:

- gNB image: `ueransim.type=gnb`
- UE image: `ueransim.type=ue`

### Runtime Configuration

The MCP server creates containers with specific Docker flags and automatically configures the internal YAML files:

**gNB Container Creation:**
```bash
docker run -d --name gnb-xxxx ueransim-gnb:latest
# Then automatically configures /etc/ueransim/open5gs-gnb.yaml inside container
```

**UE Container Creation:**
```bash
docker run -d --name ue-xxxx \
  --cap-add=NET_ADMIN \
  --device /dev/net/tun \
  --network host \
  ueransim-ue:latest
# Then automatically configures /etc/ueransim/open5gs-ue.yaml inside container
```

**Note**: Configuration is done via `docker exec` commands to modify files inside the running containers, not through environment variables.

## Troubleshooting

### Common Issues and Solutions

#### 1. "Docker image not found" error
```bash
# Check if images exist
docker images | grep ueransim

# If empty, you need to build the images first:
docker build -f docker/gnb_ubuntu.Dockerfile -t ueransim-gnb:latest .
docker build -f docker/ue_ubuntu.Dockerfile -t ueransim-ue:latest .
```

#### 2. "Container not found" error
```bash
# List all containers to see what exists
docker ps -a | grep -E "(gnb-|ue-)"

# Use the exact container name shown in the list
```

#### 3. UE can't connect to gNB
- **Check order**: Did you run `attach_gnb_to_core` BEFORE `attach_ue_to_gnb`?
- **Check gNB status**: Use `get_gnb_logs` to see if nr-gnb process is running
- **Check IP addresses**: Verify the gNB IP in UE's gnbSearchList matches actual gNB IP

#### 4. Process not starting
```bash
# Check if process is actually running inside container
docker exec <container_name> ps aux | grep nr-

# Check container logs for errors
docker logs <container_name>
```

#### 5. Network connectivity issues
- **UE containers need special privileges**: They automatically get `--cap-add=NET_ADMIN --device /dev/net/tun --network host`
- **Check firewall**: Make sure Docker containers can communicate
- **Check AMF address**: Verify your AMF/core network is reachable

### Quick Verification Steps

1. **Verify Docker images exist:**
   ```bash
   docker images | grep ueransim
   # Should show: ueransim-gnb:latest and ueransim-ue:latest
   ```

2. **Test basic container creation:**
   ```bash
   # Try creating containers manually first
   docker run -d --name test-gnb ueransim-gnb:latest
   docker run -d --name test-ue --cap-add=NET_ADMIN --device /dev/net/tun --network host ueransim-ue:latest
   
   # Check they're running
   docker ps
   
   # Cleanup
   docker stop test-gnb test-ue && docker rm test-gnb test-ue
   ```

3. **Check MCP server is working:**
   ```bash
   # Run server directly to see any Python errors
   cd /path/to/MCP-UERANSIM
   python ueransim_mcp/server.py
   ```

## Testing

## Testing

### Pre-requisite Check

Before using any MCP tools, verify your setup:

```bash
# 1. Check Docker is running
docker --version
docker ps

# 2. Check images are built
docker images | grep ueransim
# Should show:
# ueransim-gnb    latest    <image_id>    <time>    <size>
# ueransim-ue     latest    <image_id>    <time>    <size>

# 3. Check MCP server can start
cd /path/to/MCP-UERANSIM
python ueransim_mcp/server.py
# Should show: "UERANSIM MCP Server initialized"
```

### Manual Testing Workflow

**Test the complete workflow manually:**

1. **Start MCP server in one terminal:**
   ```bash
   python ueransim_mcp/server.py
   ```

2. **Test in Claude Desktop or another terminal:**
   ```python
   # Ask Claude: "Create a gNB container"
   # Should create container successfully
   
   # Ask Claude: "List all gNB containers" 
   # Should show your new container
   
   # Ask Claude: "Attach the gNB to core network"
   # Should start nr-gnb process
   
   # Ask Claude: "Create a UE container"
   # Should create UE container
   
   # Ask Claude: "Connect UE to the gNB"
   # Should start nr-ue process and show connection status
   
   # Ask Claude: "Show me the gNB logs"
   # Should display process output and connection info
   ```

### Manual Container Testing (Alternative)

If MCP tools aren't working, test containers directly:

```bash
# Test gNB container
docker run -d --name manual-gnb ueransim-gnb:latest
docker exec manual-gnb ls -la /etc/ueransim/  # Should show config files
docker exec manual-gnb /usr/local/bin/nr-gnb --help  # Should show help

# Test UE container  
docker run -d --name manual-ue --cap-add=NET_ADMIN --device /dev/net/tun --network host ueransim-ue:latest
docker exec manual-ue ls -la /etc/ueransim/  # Should show config files
docker exec manual-ue /usr/local/bin/nr-ue --help  # Should show help

# Cleanup
docker stop manual-gnb manual-ue
docker rm manual-gnb manual-ue
```
## Acknowledgments

- [UERANSIM](https://github.com/aligungr/UERANSIM) - Open source 5G UE and RAN simulator
- [Model Context Protocol](https://github.com/modelcontextprotocol/python-sdk) - MCP Python SDK
- [Alpine Linux](https://alpinelinux.org/) - Minimal container base image
- [Claude Desktop](https://claude.ai/download)