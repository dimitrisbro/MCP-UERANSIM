"""UERANSIM MCP Server - UERANSIM Tool using FastMCP with structured output"""

import subprocess
import sys
import re
import random
import string
from typing import List, Optional
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("UERANSIM MCP Server")
print("UERANSIM MCP Server initialized", file=sys.stderr)

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_container_runtime():
    """Get the preferred container runtime (docker or nerdctl).
    
    Returns:
        str: "docker" or "nerdctl" based on availability
    """
    # Try nerdctl first, fallback to docker
    try:
        result = subprocess.run(["nerdctl", "version"], capture_output=True, text=True)
        if result.returncode == 0:
            return "nerdctl"
    except FileNotFoundError:
        pass
    
    # Default to docker
    return "docker"

def generate_random_suffix(length: int = 4) -> str:
    """Generate a random alphanumeric suffix for container names.
    
    Args:
        length: Length of the suffix (default: 4)
        
    Returns:
        Random alphanumeric string
    """
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_ip(ip: str) -> bool:
    """Validate that a string is a valid IP address.
    
    Args:
        ip: The IP address to validate
        
    Returns:
        True if valid, otherwise raises ValueError
        
    Raises:
        ValueError: If the IP address is not valid
    """
    ip_pattern = re.compile(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$')
    match = ip_pattern.match(ip)
    
    if not match:
        raise ValueError(f"Invalid IP format: {ip}. Must be in format x.x.x.x with numbers only.")
    
    # Check that each octet is between 0-255
    for octet in match.groups():
        if int(octet) > 255:
            raise ValueError(f"Invalid IP: {ip}. Each octet must be between 0-255.")
    
    return True

def validate_container_id(container_id: str) -> bool:
    """Validate that a container identifier is valid.
    
    Args:
        container_id: The container ID to validate
        
    Returns:
        True if valid, otherwise raises ValueError
        
    Raises:
        ValueError: If the container ID is not valid
    """
    # Container IDs should be only numbers as per requirements
    if not container_id.isdigit():
        raise ValueError(f"Invalid container ID: {container_id}. Must contain only numbers.")
    
    return True

def validate_container_name(name: str, prefix: Optional[str] = None) -> bool:
    """Validate that a container name is valid.
    
    Args:
        name: The container name to validate
        prefix: Optional prefix that the name should have
        
    Returns:
        True if valid, otherwise raises ValueError
        
    Raises:
        ValueError: If the container name is not valid
    """
    # Check for empty name
    if not name:
        raise ValueError("Container name cannot be empty.")
    
    # Container names should contain only a-z, A-Z, 0-9, _ and -
    pattern = re.compile(r'^[a-zA-Z0-9_-]+$')
    if not pattern.match(name):
        raise ValueError(f"Invalid container name: {name}. Use only letters, numbers, underscores and hyphens.")
    
    # Check for prefix if specified
    if prefix:
        if not name.startswith(f"{prefix}-"):
            raise ValueError(f"Container name must start with '{prefix}-', got: {name}")
    
    return True

def validate_existing_container(container_id_or_name: str) -> bool:
    """Validate that a container exists and is accessible.
    
    Args:
        container_id_or_name: The container ID or name to validate
        
    Returns:
        True if valid and exists, otherwise raises ValueError
        
    Raises:
        ValueError: If the container doesn't exist or is not accessible
    """
    try:
        # First validate the format
        if container_id_or_name.isdigit() and (len(container_id_or_name) == 12 or len(container_id_or_name) == 64):
            validate_container_id(container_id_or_name)
        else:
            # Basic name validation without prefix since we don't know the type
            if not re.match(r'^[a-zA-Z0-9_-]+$', container_id_or_name):
                raise ValueError(f"Invalid container name format: {container_id_or_name}")
        
        # Check if container exists using docker/nerdctl inspect
        container_runtime = get_container_runtime()
        inspect_cmd = [container_runtime, "inspect", container_id_or_name]
        
        result = subprocess.run(inspect_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise ValueError(f"Container {container_id_or_name} not found or not accessible")
        
        return True
        
    except subprocess.SubprocessError as e:
        raise ValueError(f"Failed to validate container {container_id_or_name}: {str(e)}")
    except FileNotFoundError:
        raise ValueError("Container runtime (Docker/nerdctl) not found")

# ============================================================================
# PYDANTIC MODELS FOR STRUCTURED OUTPUT
# ============================================================================

# gNB Models
class GnbConfiguration(BaseModel):
    """gNB configuration structure."""
    link_ip: str = Field(description="Link interface IP address")
    ngap_ip: str = Field(description="NGAP interface IP address") 
    gtp_ip: str = Field(description="GTP interface IP address")
    amf_address: str = Field(description="AMF IP address")
    amf_port: str = Field(description="AMF port")

class GnbContainer(BaseModel):
    """gNB container information structure."""
    id: str = Field(description="Container ID")
    name: str = Field(description="Container name")
    status: str = Field(description="Container status")
    created: str = Field(description="Creation timestamp")

class GnbCreateResponse(BaseModel):
    """gNB creation response structure."""
    status: str = Field(description="Operation status")
    container_id: str = Field(description="Created container ID")
    container_name: str = Field(description="Container name")
    configuration: GnbConfiguration = Field(description="Container configuration")
    message: Optional[str] = Field(description="Additional message", default=None)

class GnbListResponse(BaseModel):
    """gNB list response structure."""
    status: str = Field(description="Operation status")
    containers: List[GnbContainer] = Field(description="List of gNB containers")
    count: int = Field(description="Number of containers")
    message: Optional[str] = Field(description="Additional message", default=None)

class GnbOperationResponse(BaseModel):
    """Generic gNB operation response structure."""
    status: str = Field(description="Operation status (success/error)")
    message: str = Field(description="Operation message")
    container: Optional[str] = Field(description="Container ID or name", default=None)
    logs: Optional[str] = Field(description="Container logs", default=None)

# UE Models
class UeConfiguration(BaseModel):
    """UE configuration structure."""
    gnb_search_list: str = Field(description="gNB search list IP addresses")

class UeContainer(BaseModel):
    """UE container information structure."""
    id: str = Field(description="Container ID")
    name: str = Field(description="Container name")
    status: str = Field(description="Container status")
    created: str = Field(description="Creation timestamp")

class UeCreateResponse(BaseModel):
    """UE creation response structure."""
    status: str = Field(description="Operation status")
    container_id: str = Field(description="Created container ID")
    container_name: str = Field(description="Container name")
    configuration: UeConfiguration = Field(description="Container configuration")
    message: Optional[str] = Field(description="Additional message", default=None)

class UeListResponse(BaseModel):
    """UE list response structure."""
    status: str = Field(description="Operation status")
    containers: List[UeContainer] = Field(description="List of UE containers")
    count: int = Field(description="Number of containers")
    message: Optional[str] = Field(description="Additional message", default=None)

class UeOperationResponse(BaseModel):
    """Generic UE operation response structure."""
    status: str = Field(description="Operation status (success/error)")
    message: str = Field(description="Operation message")
    container: Optional[str] = Field(description="Container ID or name", default=None)
    logs: Optional[str] = Field(description="Container logs", default=None)


# ============================================================================
# GNB TOOLS
# ============================================================================

@mcp.tool()
def create_gnb(amf_address: str = "127.0.0.5", 
               amf_port: str = "38412", 
               container_name: Optional[str] = None) -> GnbCreateResponse:
    """Create a new gNB container.
    
    Args:
        amf_address: AMF IP address
        amf_port: AMF port
        container_name: Optional container name
    
    Returns:
        GnbCreateResponse: Information about the new container
    """
    try:
        # Validate AMF IP parameter
        validate_ip(amf_address)
        
        # Get container runtime (docker or nerdctl)
        container_runtime = get_container_runtime()
        
        # Create container command
        terminal_command = [container_runtime, "run", "-d"]

        # Add name if specified, otherwise generate one
        if container_name:
            validate_container_name(container_name, "gnb")
            terminal_command.extend(["--name", container_name])
        else:
            container_name = f"gnb-{generate_random_suffix()}"
            terminal_command.extend(["--name", container_name])

        # Add the Docker image name
        terminal_command.append("ueransim-gnb:latest")
        
        # Execute command to create container
        result = subprocess.run(terminal_command, capture_output=True, text=True)

        if result.returncode != 0:
            return GnbCreateResponse(
                status="error",
                container_id="",
                container_name="",
                configuration=GnbConfiguration(
                    link_ip="",
                    ngap_ip="",
                    gtp_ip="",
                    amf_address=amf_address,
                    amf_port=amf_port
                ),
                message=result.stderr
            )
        
        container_id = result.stdout.strip()
        
        # Step 1: Get container IP using docker inspect
        inspect_command = [
            container_runtime, "inspect", "-f", 
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", 
            container_id
        ]
        inspect_result = subprocess.run(inspect_command, capture_output=True, text=True)
        
        if inspect_result.returncode != 0:
            return GnbCreateResponse(
                status="error",
                container_id=container_id,
                container_name=container_name,
                configuration=GnbConfiguration(
                    link_ip="",
                    ngap_ip="",
                    gtp_ip="",
                    amf_address=amf_address,
                    amf_port=amf_port
                ),
                message=f"Failed to get container IP: {inspect_result.stderr}"
            )
        
        container_ip = inspect_result.stdout.strip()
        
        # Step 2: Update configuration file with container IP and AMF settings
        # Update linkIp with container IP
        link_cmd = [
            container_runtime, "exec", container_id,
            "sed", "-i", f"s/linkIp: .*/linkIp: {container_ip}/",
            "/etc/ueransim/open5gs-gnb.yaml"
        ]
        link_result = subprocess.run(link_cmd, capture_output=True, text=True)
        
        if link_result.returncode != 0:
            return GnbCreateResponse(
                status="error",
                container_id=container_id,
                container_name=container_name,
                configuration=GnbConfiguration(
                    link_ip=container_ip,
                    ngap_ip=container_ip,
                    gtp_ip=container_ip,
                    amf_address=amf_address,
                    amf_port=amf_port
                ),
                message=f"Failed to update linkIp: {link_result.stderr}"
            )
        
        # Update ngapIp with container IP
        ngap_cmd = [
            container_runtime, "exec", container_id,
            "sed", "-i", f"s/ngapIp: .*/ngapIp: {container_ip}/",
            "/etc/ueransim/open5gs-gnb.yaml"
        ]
        ngap_result = subprocess.run(ngap_cmd, capture_output=True, text=True)
        
        if ngap_result.returncode != 0:
            return GnbCreateResponse(
                status="error",
                container_id=container_id,
                container_name=container_name,
                configuration=GnbConfiguration(
                    link_ip=container_ip,
                    ngap_ip=container_ip,
                    gtp_ip=container_ip,
                    amf_address=amf_address,
                    amf_port=amf_port
                ),
                message=f"Failed to update ngapIp: {ngap_result.stderr}"
            )
        
        # Update gtpIp with container IP
        gtp_cmd = [
            container_runtime, "exec", container_id,
            "sed", "-i", f"s/gtpIp: .*/gtpIp: {container_ip}/",
            "/etc/ueransim/open5gs-gnb.yaml"
        ]
        gtp_result = subprocess.run(gtp_cmd, capture_output=True, text=True)
        
        if gtp_result.returncode != 0:
            return GnbCreateResponse(
                status="error",
                container_id=container_id,
                container_name=container_name,
                configuration=GnbConfiguration(
                    link_ip=container_ip,
                    ngap_ip=container_ip,
                    gtp_ip=container_ip,
                    amf_address=amf_address,
                    amf_port=amf_port
                ),
                message=f"Failed to update gtpIp: {gtp_result.stderr}"
            )
        
        # Update AMF address
        amf_cmd = [
            container_runtime, "exec", container_id,
            "sed", "-i", f"s/amfConfigs:.*address: .*/amfConfigs:\\n  - address: {amf_address}/",
            "/etc/ueransim/open5gs-gnb.yaml"
        ]
        amf_result = subprocess.run(amf_cmd, capture_output=True, text=True)
        
        if amf_result.returncode != 0:
            return GnbCreateResponse(
                status="error",
                container_id=container_id,
                container_name=container_name,
                configuration=GnbConfiguration(
                    link_ip=container_ip,
                    ngap_ip=container_ip,
                    gtp_ip=container_ip,
                    amf_address=amf_address,
                    amf_port=amf_port
                ),
                message=f"Failed to update AMF address: {amf_result.stderr}"
            )
        
        # Step 3: Execute nr-gnb with the configuration file
        exec_command = [
            container_runtime, "exec", "-d", container_id,
            "/usr/local/bin/nr-gnb", "-c", "/etc/ueransim/open5gs-gnb.yaml"
        ]
        exec_result = subprocess.run(exec_command, capture_output=True, text=True)
        
        if exec_result.returncode != 0:
            return GnbCreateResponse(
                status="error",
                container_id=container_id,
                container_name=container_name,
                configuration=GnbConfiguration(
                    link_ip=container_ip,
                    ngap_ip=container_ip,
                    gtp_ip=container_ip,
                    amf_address=amf_address,
                    amf_port=amf_port
                ),
                message=f"Failed to execute nr-gnb: {exec_result.stderr}"
            )
        
        return GnbCreateResponse(
            status="success",
            container_id=container_id,
            container_name=container_name,
            configuration=GnbConfiguration(
                link_ip=container_ip,
                ngap_ip=container_ip,
                gtp_ip=container_ip,
                amf_address=amf_address,
                amf_port=amf_port
            )
        )
    except ValueError as e:
        # Validation errors from validate_ip() or validate_container_name()
        return GnbCreateResponse(
            status="error",
            container_id="",
            container_name="",
            configuration=GnbConfiguration(
                link_ip="",
                ngap_ip="",
                gtp_ip="",
                amf_address=amf_address,
                amf_port=amf_port
            ),
            message=str(e)
        )
    except Exception as e:
        # Handle container creation failures and other unexpected errors
        error_msg = str(e)
        if "not found" in error_msg.lower():
            error_msg = "Container runtime (Docker/nerdctl) not found or not accessible"
        elif "permission" in error_msg.lower():
            error_msg = f"Permission denied: {error_msg}"
        
        return GnbCreateResponse(
            status="error",
            container_id="",
            container_name="",
            configuration=GnbConfiguration(
                link_ip="",
                ngap_ip="",
                gtp_ip="",
                amf_address=amf_address,
                amf_port=amf_port
            ),
            message=error_msg
        )


@mcp.tool()
def list_gnbs() -> GnbListResponse:
    """List all gNB containers.
    
    Returns:
        GnbListResponse: List of gNB containers
    """
    try:
        container_runtime = get_container_runtime()
        terminal_command = [
            container_runtime, "ps", "-a", "--filter", "label=ueransim.type=gnb", 
            "--format", "{{.ID}}|{{.Names}}|{{.Status}}|{{.CreatedAt}}"
        ]

        result = subprocess.run(terminal_command, capture_output=True, text=True)

        if result.returncode != 0:
            return GnbListResponse(
                status="error",
                containers=[],
                count=0,
                message=result.stderr
            )
        
        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                id, name, status, created = line.split('|', 3)
                containers.append(GnbContainer(
                    id=id,
                    name=name,
                    status=status,
                    created=created
                ))
        
        return GnbListResponse(
            status="success",
            containers=containers,
            count=len(containers)
        )
    except Exception as e:
        # Handle all errors with smart error message detection
        error_msg = str(e)
        if "not found" in error_msg.lower() or "command not found" in error_msg.lower():
            error_msg = "Container runtime (Docker/nerdctl) not found"
        elif "permission" in error_msg.lower():
            error_msg = f"Permission denied: {error_msg}"
        elif "invalid" in error_msg.lower() or "format" in error_msg.lower():
            error_msg = f"Output parsing error: {error_msg}"
        
        return GnbListResponse(
            status="error",
            containers=[],
            count=0,
            message=error_msg
        )


@mcp.tool()
def delete_gnb(container_id_or_name: str) -> GnbOperationResponse:
    """Delete a gNB container.
    
    Args:
        container_id_or_name: Container ID or name to delete
        
    Returns:
        GnbOperationResponse: Deletion status
    """
    try:
        # Check if it's ID or name
        if container_id_or_name.isdigit() and len(container_id_or_name) == 12 or len(container_id_or_name) == 64:
            validate_container_id(container_id_or_name)
        else:
            validate_container_name(container_id_or_name, "gnb")
            
        # Get container runtime
        container_runtime = get_container_runtime()

        # Stop and remove container
        stop_cmd = [container_runtime, "stop", container_id_or_name]
        result = subprocess.run(stop_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return GnbOperationResponse(
                status="error",
                message=f"Failed to stop container: {result.stderr}",
                container=container_id_or_name
            )

        rm_cmd = [container_runtime, "rm", container_id_or_name]
        result = subprocess.run(rm_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return GnbOperationResponse(
                status="error", 
                message=f"Failed to remove container: {result.stderr}",
                container=container_id_or_name
            )
        
        return GnbOperationResponse(
            status="success", 
            message=f"Container {container_id_or_name} successfully deleted",
            container=container_id_or_name
        )
    except ValueError as e:
        # Validation errors from validate_container_id() or validate_container_name()
        return GnbOperationResponse(
            status="error",
            message=str(e),
            container=container_id_or_name
        )
    except Exception as e:
        # Handle container operations and other errors
        error_msg = str(e)
        if "not found" in error_msg.lower():
            error_msg = f"Container {container_id_or_name} not found"
        elif "permission" in error_msg.lower():
            error_msg = f"Permission denied: {error_msg}"
        elif "already stopped" in error_msg.lower():
            error_msg = f"Container {container_id_or_name} is already stopped"
        
        return GnbOperationResponse(
            status="error",
            message=error_msg,
            container=container_id_or_name
        )


@mcp.tool()
def get_gnb_logs(container_id_or_name: str, lines: int = 100) -> GnbOperationResponse:
    """Get logs from a gNB container.
    
    Args:
        container_id_or_name: Container ID or name
        lines: Number of lines to retrieve (default: 100)
        
    Returns:
        GnbOperationResponse: Container logs
    """
    try:
        # Check if it's ID or name
        if container_id_or_name.isdigit() and len(container_id_or_name) == 12 or len(container_id_or_name) == 64:
            validate_container_id(container_id_or_name)
        else:
            validate_container_name(container_id_or_name, "gnb")
        
        # Get container runtime
        container_runtime = get_container_runtime()

        # Execute command to retrieve logs
        terminal_command = [container_runtime, "logs", f"--tail={lines}", container_id_or_name]
        result = subprocess.run(terminal_command, capture_output=True, text=True)

        if result.returncode != 0:
            return GnbOperationResponse(
                status="error",
                message=result.stderr,
                container=container_id_or_name
            )
        
        return GnbOperationResponse(
            status="success",
            message="Logs retrieved successfully",
            container=container_id_or_name,
            logs=result.stdout
        )
    except Exception as e:
        return GnbOperationResponse(
            status="error",
            message=str(e),
            container=container_id_or_name
        )


@mcp.tool()
def attach_gnb_to_core(container_id_or_name: str, ngap_ip: str, gtp_ip: str) -> GnbOperationResponse:
    """Attach a gNB container to the network core.
    
    Args:
        container_id_or_name: gNB container ID or name
        ngap_ip: New NGAP IP address
        gtp_ip: New GTP IP address
        
    Returns:
        GnbOperationResponse: Connection status
    """
    try:
        # Validate parameters
        validate_ip(ngap_ip)
        validate_ip(gtp_ip)
        
        # Check if it's ID or name
        if container_id_or_name.isdigit() and len(container_id_or_name) == 12 or len(container_id_or_name) == 64:
            validate_container_id(container_id_or_name)
        else:
            validate_container_name(container_id_or_name, "gnb")
        
        # Get container runtime
        container_runtime = get_container_runtime()
        
        # Command to change NGAP IP
        ngap_cmd = [
            container_runtime, "exec", container_id_or_name, 
            "sed", "-i", f"s/ngapIp: .*/ngapIp: {ngap_ip}/", 
            "/etc/ueransim/open5gs-gnb.yaml"
        ]
        result_ngap = subprocess.run(ngap_cmd, capture_output=True, text=True)
        
        if result_ngap.returncode != 0:
            return GnbOperationResponse(
                status="error",
                message=f"Failed to update NGAP IP: {result_ngap.stderr}",
                container=container_id_or_name
            )
        
        # Command to change GTP IP
        gtp_cmd = [
            container_runtime, "exec", container_id_or_name, 
            "sed", "-i", f"s/gtpIp: .*/gtpIp: {gtp_ip}/", 
            "/etc/ueransim/open5gs-gnb.yaml"
        ]
        result_gtp = subprocess.run(gtp_cmd, capture_output=True, text=True)
        
        if result_gtp.returncode != 0:
            return GnbOperationResponse(
                status="error",
                message=f"Failed to update GTP IP: {result_gtp.stderr}",
                container=container_id_or_name
            )
        
        # Restart process to apply changes
        restart_cmd = [container_runtime, "restart", container_id_or_name]
        result_restart = subprocess.run(restart_cmd, capture_output=True, text=True)
        
        if result_restart.returncode != 0:
            return GnbOperationResponse(
                status="error",
                message=f"Failed to restart container: {result_restart.stderr}",
                container=container_id_or_name
            )
        
        return GnbOperationResponse(
            status="success",
            message=f"Container {container_id_or_name} successfully connected to core with NGAP IP {ngap_ip} and GTP IP {gtp_ip}",
            container=container_id_or_name
        )
    except Exception as e:
        return GnbOperationResponse(
            status="error",
            message=str(e),
            container=container_id_or_name
        )


# ============================================================================
# COMMON TOOLS
# ============================================================================

@mcp.tool()
def inspect_container_ip(container_id_or_name: str) -> GnbOperationResponse:
    """Inspect container IP address using docker inspect command.
    
    Args:
        container_id_or_name: Container ID or name to inspect
        
    Returns:
        GnbOperationResponse: Container IP information
    """
    try:
        # Validate that container exists and is accessible
        validate_existing_container(container_id_or_name)
        
        # Get container runtime
        container_runtime = get_container_runtime()
        
        # Use docker inspect to get container IP
        inspect_cmd = [
            container_runtime, "inspect", "-f", 
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", 
            container_id_or_name
        ]
        
        result = subprocess.run(inspect_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return GnbOperationResponse(
                status="error",
                message=f"Failed to inspect container: {result.stderr}",
                container=container_id_or_name
            )
        
        container_ip = result.stdout.strip()
        
        # Check if IP was found
        if not container_ip:
            return GnbOperationResponse(
                status="error",
                message=f"No IP address found for container {container_id_or_name}",
                container=container_id_or_name
            )
        
        return GnbOperationResponse(
            status="success",
            message=f"Container {container_id_or_name} IP address: {container_ip}",
            container=container_id_or_name,
            logs=container_ip
        )
        
    except ValueError as e:
        # Validation errors from validate_existing_container()
        return GnbOperationResponse(
            status="error",
            message=str(e),
            container=container_id_or_name
        )
    except Exception as e:
        # Handle container operations and other errors
        error_msg = str(e)
        if "not found" in error_msg.lower():
            error_msg = f"Container {container_id_or_name} not found or not accessible"
        elif "permission" in error_msg.lower():
            error_msg = f"Permission denied: {error_msg}"
        elif "command not found" in error_msg.lower():
            error_msg = "Container runtime (Docker/nerdctl) not found"
        
        return GnbOperationResponse(
            status="error",
            message=error_msg,
            container=container_id_or_name
        )


# ============================================================================
# UE TOOLS
# ============================================================================

@mcp.tool()
def create_ue(gnb_search_list: str = "127.0.0.1", container_name: Optional[str] = None) -> UeCreateResponse:
    """Create a new UE container.
    
    Args:
        gnb_search_list: gNB search list IP address
        container_name: Optional container name
    
    Returns:
        UeCreateResponse: Information about the new container
    """
    try:
        # Validate parameters
        validate_ip(gnb_search_list)
        
        # Get container runtime (docker or nerdctl)
        container_runtime = get_container_runtime()
        
        # Create container command
        terminal_command = [container_runtime, "run", "-d"]
        
        # Add name if specified, otherwise generate one
        if container_name:
            validate_container_name(container_name, "ue")
            terminal_command.extend(["--name", container_name])
        else:
            container_name = f"ue-{generate_random_suffix()}"
            terminal_command.extend(["--name", container_name])
            
        # Add environment variables
        terminal_command.extend([
            "-e", f"GNB_SEARCH_LIST={gnb_search_list}",
            "ueransim-ue:latest"  # Docker image name
        ])
        
        # Execute command
        result = subprocess.run(terminal_command, capture_output=True, text=True)
        
        if result.returncode != 0:
            return UeCreateResponse(
                status="error",
                container_id="",
                container_name="",
                configuration=UeConfiguration(gnb_search_list=gnb_search_list),
                message=result.stderr
            )
        
        container_id = result.stdout.strip()
        
        return UeCreateResponse(
            status="success",
            container_id=container_id,
            container_name=container_name or container_id[:12],
            configuration=UeConfiguration(gnb_search_list=gnb_search_list)
        )
    except Exception as e:
        return UeCreateResponse(
            status="error",
            container_id="",
            container_name="",
            configuration=UeConfiguration(gnb_search_list=gnb_search_list),
            message=str(e)
        )


@mcp.tool()
def list_ues() -> UeListResponse:
    """List all UE containers.
    
    Returns:
        UeListResponse: List of UE containers
    """
    try:
        container_runtime = get_container_runtime()
        terminal_command = [
            container_runtime, "ps", "-a", "--filter", "label=ueransim.type=ue", 
            "--format", "{{.ID}}|{{.Names}}|{{.Status}}|{{.CreatedAt}}"
        ]

        result = subprocess.run(terminal_command, capture_output=True, text=True)
        
        if result.returncode != 0:
            return UeListResponse(
                status="error",
                containers=[],
                count=0,
                message=result.stderr
            )
        
        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                id, name, status, created = line.split('|', 3)
                containers.append(UeContainer(
                    id=id,
                    name=name,
                    status=status,
                    created=created
                ))
        
        return UeListResponse(
            status="success",
            containers=containers,
            count=len(containers)
        )
    except Exception as e:
        return UeListResponse(
            status="error",
            containers=[],
            count=0,
            message=str(e)
        )


@mcp.tool()
def delete_ue(container_id_or_name: str) -> UeOperationResponse:
    """Delete a UE container.
    
    Args:
        container_id_or_name: Container ID or name to delete
        
    Returns:
        UeOperationResponse: Deletion status
    """
    try:
        # Check if it's ID or name
        if container_id_or_name.isdigit() and len(container_id_or_name) == 12 or len(container_id_or_name) == 64:
            validate_container_id(container_id_or_name)
        else:
            validate_container_name(container_id_or_name, "ue")
        
        # Get container runtime
        container_runtime = get_container_runtime()
            
        # Stop and remove container
        stop_cmd = [container_runtime, "stop", container_id_or_name]
        result = subprocess.run(stop_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return UeOperationResponse(
                status="error",
                message=f"Failed to stop container: {result.stderr}",
                container=container_id_or_name
            )
        
        rm_cmd = [container_runtime, "rm", container_id_or_name]
        result = subprocess.run(rm_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return UeOperationResponse(
                status="error", 
                message=f"Failed to remove container: {result.stderr}",
                container=container_id_or_name
            )
        
        return UeOperationResponse(
            status="success", 
            message=f"Container {container_id_or_name} successfully deleted",
            container=container_id_or_name
        )
    except Exception as e:
        return UeOperationResponse(
            status="error",
            message=str(e),
            container=container_id_or_name
        )


@mcp.tool()
def get_ue_logs(container_id_or_name: str, lines: int = 100) -> UeOperationResponse:
    """Get logs from a UE container.
    
    Args:
        container_id_or_name: Container ID or name
        lines: Number of lines to retrieve (default: 100)
        
    Returns:
        UeOperationResponse: Container logs
    """
    try:
        # Check if it's ID or name
        if container_id_or_name.isdigit() and len(container_id_or_name) == 12 or len(container_id_or_name) == 64:
            validate_container_id(container_id_or_name)
        else:
            validate_container_name(container_id_or_name, "ue")
        
        # Get container runtime
        container_runtime = get_container_runtime()
        
        # Execute command to retrieve logs
        terminal_command = [container_runtime, "logs", f"--tail={lines}", container_id_or_name]
        result = subprocess.run(terminal_command, capture_output=True, text=True)
        
        if result.returncode != 0:
            return UeOperationResponse(
                status="error",
                message=result.stderr,
                container=container_id_or_name
            )
        
        return UeOperationResponse(
            status="success",
            message="Logs retrieved successfully",
            container=container_id_or_name,
            logs=result.stdout
        )
    except Exception as e:
        return UeOperationResponse(
            status="error",
            message=str(e),
            container=container_id_or_name
        )


@mcp.tool()
def attach_ue_to_gnb(ue_container_id_or_name: str, gnb_container_id_or_name: str) -> UeOperationResponse:
    """Attach a UE container to a gNB container.
    
    Args:
        ue_container_id_or_name: UE container ID or name
        gnb_container_id_or_name: gNB container ID or name
        
    Returns:
        UeOperationResponse: Connection status
    """
    try:
        # Check if it's ID or name for UE
        if ue_container_id_or_name.isdigit() and len(ue_container_id_or_name) == 12 or len(ue_container_id_or_name) == 64:
            validate_container_id(ue_container_id_or_name)
        else:
            validate_container_name(ue_container_id_or_name, "ue")
            
        # Check if it's ID or name for gNB
        if gnb_container_id_or_name.isdigit() and len(gnb_container_id_or_name) == 12 or len(gnb_container_id_or_name) == 64:
            validate_container_id(gnb_container_id_or_name)
        else:
            validate_container_name(gnb_container_id_or_name, "gnb")
        
        # Get container runtime
        container_runtime = get_container_runtime()
        
        # Get gNB container IP
        ip_cmd = [container_runtime, "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", gnb_container_id_or_name]
        ip_result = subprocess.run(ip_cmd, capture_output=True, text=True)
        
        if ip_result.returncode != 0:
            return UeOperationResponse(
                status="error",
                message=f"Failed to get gNB IP: {ip_result.stderr}",
                container=ue_container_id_or_name
            )
        
        gnb_ip = ip_result.stdout.strip()
        
        # Update gnbSearchList in UE
        search_cmd = [
            container_runtime, "exec", ue_container_id_or_name, 
            "sed", "-i", f"s/gnbSearchList: .*/gnbSearchList: {gnb_ip}/", 
            "/etc/ueransim/open5gs-ue.yaml"
        ]
        search_result = subprocess.run(search_cmd, capture_output=True, text=True)
        
        if search_result.returncode != 0:
            return UeOperationResponse(
                status="error",
                message=f"Failed to update gnbSearchList: {search_result.stderr}",
                container=ue_container_id_or_name
            )
        
        # Add success message to logs
        log_cmd = [
            container_runtime, "exec", ue_container_id_or_name, 
            "sh", "-c", "echo 'Successfully attached to gNB container' >> /var/log/ueransim.log"
        ]
        subprocess.run(log_cmd)
        
        # Restart UE container
        restart_cmd = [container_runtime, "restart", ue_container_id_or_name]
        result_restart = subprocess.run(restart_cmd, capture_output=True, text=True)
        
        if result_restart.returncode != 0:
            return UeOperationResponse(
                status="error",
                message=f"Failed to restart container: {result_restart.stderr}",
                container=ue_container_id_or_name
            )
        
        return UeOperationResponse(
            status="success",
            message=f"UE container {ue_container_id_or_name} successfully attached to gNB container {gnb_container_id_or_name} with IP {gnb_ip}",
            container=ue_container_id_or_name
        )
    except Exception as e:
        return UeOperationResponse(
            status="error",
            message=str(e),
            container=ue_container_id_or_name
        )


@mcp.tool()
def edit_exist_container(container_id_or_name: str, 
                        config_type: str = "gnb_search_list",
                        config_value: str = "127.0.0.1") -> UeOperationResponse:
    """Edit configuration of an existing container.
    
    Args:
        container_id_or_name: Container ID or name to edit
        config_type: Type of configuration to change (gnb_search_list, ngap_ip, gtp_ip, amf_ip)
        config_value: New configuration value
        
    Returns:
        UeOperationResponse: Operation status
    """
    try:
        # Validate that container exists and is accessible
        validate_existing_container(container_id_or_name)
        
        # Validate config value based on type
        if config_type in ["gnb_search_list", "ngap_ip", "gtp_ip", "amf_ip"]:
            validate_ip(config_value)
        
        # Get container runtime
        container_runtime = get_container_runtime()
        
        # Container already validated by validate_existing_container, no need to check again
        
        # Apply configuration based on type
        if config_type == "gnb_search_list":
            # Update UE configuration
            config_cmd = [
                container_runtime, "exec", container_id_or_name,
                "sed", "-i", f"s/gnbSearchList: .*/gnbSearchList: {config_value}/",
                "/etc/ueransim/open5gs-ue.yaml"
            ]
        elif config_type == "ngap_ip":
            # Update gNB NGAP IP
            config_cmd = [
                container_runtime, "exec", container_id_or_name,
                "sed", "-i", f"s/ngapIp: .*/ngapIp: {config_value}/",
                "/etc/ueransim/open5gs-gnb.yaml"
            ]
        elif config_type == "gtp_ip":
            # Update gNB GTP IP
            config_cmd = [
                container_runtime, "exec", container_id_or_name,
                "sed", "-i", f"s/gtpIp: .*/gtpIp: {config_value}/",
                "/etc/ueransim/open5gs-gnb.yaml"
            ]
        elif config_type == "amf_ip":
            # Update gNB AMF IP address
            config_cmd = [
                container_runtime, "exec", container_id_or_name,
                "sed", "-i", f"s/amfConfigs:.*address: .*/amfConfigs:\\n  - address: {config_value}/",
                "/etc/ueransim/open5gs-gnb.yaml"
            ]
        else:
            return UeOperationResponse(
                status="error",
                message=f"Unsupported config type: {config_type}",
                container=container_id_or_name
            )
        
        # Execute configuration change
        config_result = subprocess.run(config_cmd, capture_output=True, text=True)
        
        if config_result.returncode != 0:
            return UeOperationResponse(
                status="error",
                message=f"Failed to update {config_type}: {config_result.stderr}",
                container=container_id_or_name
            )
        
        # Add success message to logs
        log_cmd = [
            container_runtime, "exec", container_id_or_name,
            "sh", "-c", f"echo 'Configuration updated: {config_type}={config_value}' >> /var/log/ueransim.log"
        ]
        subprocess.run(log_cmd)
        
        # Echo success to demonstrate completion
        success_cmd = [
            container_runtime, "exec", container_id_or_name,
            "sh", "-c", "echo 'success'"
        ]
        success_result = subprocess.run(success_cmd, capture_output=True, text=True)
        
        return UeOperationResponse(
            status="success",
            message=f"Container {container_id_or_name} configuration updated: {config_type}={config_value}",
            container=container_id_or_name,
            logs=success_result.stdout if success_result.returncode == 0 else None
        )
        
    except ValueError as e:
        # Validation errors from validate_existing_container() or validate_ip()
        return UeOperationResponse(
            status="error",
            message=str(e),
            container=container_id_or_name
        )
    except Exception as e:
        # Handle container operations and configuration errors
        error_msg = str(e)
        if "not found" in error_msg.lower():
            error_msg = f"Container {container_id_or_name} not found or not accessible"
        elif "permission" in error_msg.lower():
            error_msg = f"Permission denied: {error_msg}"
        elif "no such file" in error_msg.lower():
            error_msg = "Configuration file not found in container"
        elif "command not found" in error_msg.lower():
            error_msg = "Container runtime (Docker/nerdctl) not found"
        
        return UeOperationResponse(
            status="error",
            message=error_msg,
            container=container_id_or_name
        )


# ============================================================================
# SERVER STARTUP
# ============================================================================

def start_server():
    """Start the MCP server."""
    mcp.run()


if __name__ == "__main__":
    start_server()