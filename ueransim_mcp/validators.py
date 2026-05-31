import re
from typing import Optional


def validate_ip(ip: str) -> bool:
    """Validate IPv4 address format and octet range. Raises ValueError on failure."""
    match = re.match(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$', ip)
    if not match:
        raise ValueError(f"Invalid IP format: {ip}. Must be x.x.x.x with numbers only.")
    for octet in match.groups():
        if int(octet) > 255:
            raise ValueError(f"Invalid IP: {ip}. Each octet must be 0-255.")
    return True


def validate_container_id(container_id: str) -> bool:
    """Validate that a string is a hexadecimal Docker container ID. Raises ValueError on failure."""
    if not re.match(r'^[0-9a-fA-F]+$', container_id):
        raise ValueError(f"Invalid container ID: {container_id}. Must be a hexadecimal string.")
    return True


def validate_container_name(name: str, prefix: Optional[str] = None) -> bool:
    """Validate a container/pod name (alphanumeric, hyphens, underscores).

    Args:
        name: Name to validate.
        prefix: If given, name must start with '{prefix}-'.

    Raises:
        ValueError: If the name is invalid or missing the required prefix.
    """
    if not name:
        raise ValueError("Container name cannot be empty.")
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        raise ValueError(
            f"Invalid container name: {name}. Use only letters, numbers, underscores and hyphens."
        )
    if prefix and not name.startswith(f"{prefix}-"):
        raise ValueError(f"Container name must start with '{prefix}-', got: {name}")
    return True
