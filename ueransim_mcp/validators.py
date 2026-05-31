import re
from typing import Optional

_VALID_CELL_ACCESS_TYPES = {"nr", "nr-leo", "nr-meo", "nr-geo", "nr-othersat"}
_VALID_OP_TYPES           = {"OP", "OPC"}
_VALID_SESSION_TYPES      = {"IPv4", "IPv6", "IPv4v6"}


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


def validate_mcc(mcc: str) -> bool:
    """Validate MCC: exactly 3 decimal digits."""
    if not re.match(r'^\d{3}$', mcc):
        raise ValueError(f"Invalid MCC: {mcc}. Must be exactly 3 decimal digits.")
    return True


def validate_mnc(mnc: str) -> bool:
    """Validate MNC: 2 or 3 decimal digits."""
    if not re.match(r'^\d{2,3}$', mnc):
        raise ValueError(f"Invalid MNC: {mnc}. Must be 2 or 3 decimal digits.")
    return True


def validate_nci(nci: str) -> bool:
    """Validate NR Cell Identity: hex value fitting in 36 bits (max 0xFFFFFFFFF)."""
    try:
        val = int(nci, 16)
    except ValueError:
        raise ValueError(f"Invalid NCI: {nci}. Must be a hex string (e.g. 0x000000010).")
    if val < 0 or val > 0xFFFFFFFFF:
        raise ValueError(f"NCI {nci} exceeds 36-bit range (max 0xFFFFFFFFF).")
    return True


def validate_cell_access_type(cat: str) -> bool:
    """Validate cellAccessType value."""
    if cat not in _VALID_CELL_ACCESS_TYPES:
        raise ValueError(
            f"Invalid cellAccessType: '{cat}'. Must be one of: {sorted(_VALID_CELL_ACCESS_TYPES)}"
        )
    return True


def validate_op_type(op_type: str) -> bool:
    """Validate opType: must be 'OP' or 'OPC'."""
    if op_type not in _VALID_OP_TYPES:
        raise ValueError(f"Invalid opType: '{op_type}'. Must be 'OP' or 'OPC'.")
    return True


def validate_session_type(session_type: str) -> bool:
    """Validate PDU session type."""
    if session_type not in _VALID_SESSION_TYPES:
        raise ValueError(
            f"Invalid session type: '{session_type}'. Must be one of: {sorted(_VALID_SESSION_TYPES)}"
        )
    return True


def validate_supi(supi: str) -> bool:
    """Validate SUPI: imsi- followed by exactly 15 digits."""
    if not re.match(r'^imsi-\d{15}$', supi):
        raise ValueError(
            f"Invalid SUPI: '{supi}'. Must be 'imsi-' followed by exactly 15 digits."
        )
    return True


def validate_hex_key(value: str, name: str = "key") -> bool:
    """Validate a 128-bit key expressed as 32 hexadecimal characters."""
    if not re.match(r'^[0-9a-fA-F]{32}$', value):
        raise ValueError(
            f"Invalid {name}: '{value}'. Must be exactly 32 hexadecimal characters."
        )
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
