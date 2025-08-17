# MCP-UERANSIM

MCP tool to manage simulated gNB and UE resources using UERANSIM

## Overview

MCP-UERANSIM is a Model Context Protocol (MCP) server that provides tools for managing UERANSIM-based 5G network simulations. It allows you to create, manage, and interact with simulated gNodeB (gNB) and User Equipment (UE) containers through a standardized MCP interface.

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
├── config/                   # UERANSIM configuration templates
│   ├── open5gs-gnb.yaml     # gNB configuration template
│   └── open5gs-ue.yaml      # UE configuration template
├── docker/                   # Docker build files
│   ├── gnb.Dockerfile        # gNB container image
│   ├── ue.Dockerfile         # UE container image
│   ├── gnb-entrypoint.sh     # gNB startup script
│   └── ue-entrypoint.sh      # UE startup script
└── ueransim_mcp/            # MCP server implementation
    └── server.py             # Main MCP server with all tools
```

## Installation

### Prerequisites

- Python 3.8 or higher
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker/Nerdctl installed and running
- Git (for cloning)

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

3. **Build Docker images**
   ```bash
   # Build gNB image
   docker build -f docker/gnb.Dockerfile -t ueransim-gnb:latest .
   
   # Build UE image
   docker build -f docker/ue.Dockerfile -t ueransim-ue:latest .
   ```

## Quick Start

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

## Available Tools

### gNB (gNodeB) Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `create_gnb` | Create a new gNB container | `link_ip`, `ngap_ip`, `gtp_ip`, `amf_address`, `amf_port`, `container_name` |
| `list_gnbs` | List all gNB containers | None |
| `delete_gnb` | Delete a gNB container | `container_id_or_name` |
| `get_gnb_logs` | Get logs from a gNB container | `container_id_or_name`, `lines` |
| `attach_gnb_to_core` | Connect gNB to core network | `container_id_or_name`, `ngap_ip`, `gtp_ip` |

### UE (User Equipment) Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `create_ue` | Create a new UE container | `gnb_search_list`, `container_name` |
| `list_ues` | List all UE containers | None |
| `delete_ue` | Delete a UE container | `container_id_or_name` |
| `get_ue_logs` | Get logs from a UE container | `container_id_or_name`, `lines` |
| `attach_ue_to_gnb` | Connect UE to gNB | `ue_container_id_or_name`, `gnb_container_id_or_name` |

## Usage Examples

Here are complete examples showing both the Claude Desktop questions you can ask and the resulting MCP tool calls:

### Creating and Managing Containers

**Ask Claude Desktop:**
"Create a new gNB container with IP 192.168.1.100 for all interfaces and AMF at 192.168.1.5"

This will trigger:
```python
create_gnb(
    link_ip="192.168.1.100",
    ngap_ip="192.168.1.100", 
    gtp_ip="192.168.1.100",
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
"Attach gNB gnb-a1b2 to the core network with NGAP IP 10.0.1.10 and GTP IP 10.0.1.11"

This will trigger:
```python
attach_gnb_to_core(
    container_id_or_name="gnb-a1b2",
    ngap_ip="10.0.1.10",
    gtp_ip="10.0.1.11"
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
"Set up a complete 5G test environment: create a gNB with IP 192.168.100.10, create a UE, connect them together, and show me the logs"

This will trigger a sequence of operations:
1. `create_gnb()` with specified IP
2. `create_ue()` with matching gNB search list
3. `attach_ue_to_gnb()` to connect them
4. `get_gnb_logs()` and `get_ue_logs()` to show status

### Natural Language Examples

You can ask Claude Desktop in natural language:

- *"How many gNBs are currently running?"*
- *"Create a test setup with gNB and UE on the 10.0.0.x network"*
- *"Show me what went wrong with container gnb-test01"*
- *"Clean up all my test containers"*
- *"Connect my UE to a different gNB"*
- *"Reconfigure gNB to use new core network IPs"*

## Configuration

### gNB Configuration

The gNB containers expose the following configurable parameters:

- **linkIp**: gNB's local IP address for Radio Link Simulation
- **ngapIp**: gNB's local IP address for N2 Interface  
- **gtpIp**: gNB's local IP address for N3 Interface
- **amf_address**: AMF IP address
- **amf_port**: AMF port number

### UE Configuration

The UE containers expose:

- **gnbSearchList**: List of gNB IP addresses for connection

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

Containers are configured through environment variables:

**gNB Container:**
```bash
docker run -d \
  -e LINK_IP=192.168.1.100 \
  -e NGAP_IP=192.168.1.100 \
  -e GTP_IP=192.168.1.100 \
  -e AMF_ADDRESS=192.168.1.5 \
  -e AMF_PORT=38412 \
  --name gnb-example \
  ueransim-gnb:latest
```

**UE Container:**
```bash
docker run -d \
  -e GNB_SEARCH_LIST=192.168.1.100 \
  --name ue-example \
  ueransim-ue:latest
```

## Testing

### Manual Testing

1. Start the MCP server:
   ```bash
   python main.py
   ```

2. Test container creation:
   ```bash
   # Verify images exist
   docker images | grep ueransim
   
   # Test manual container creation
   docker run -d --name test-gnb ueransim-gnb:latest
   docker run -d --name test-ue ueransim-ue:latest
   
   # Check containers are running
   docker ps
   
   # Cleanup
   docker stop test-gnb test-ue
   docker rm test-gnb test-ue
   ```

## Acknowledgments

- [UERANSIM](https://github.com/aligungr/UERANSIM) - Open source 5G UE and RAN simulator
- [Model Context Protocol](https://github.com/modelcontextprotocol/python-sdk) - MCP Python SDK
- [Alpine Linux](https://alpinelinux.org/) - Minimal container base image
- [Claude Desktop](https://claude.ai/download)
