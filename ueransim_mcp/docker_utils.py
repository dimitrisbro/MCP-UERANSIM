import os
import re
import subprocess
import sys
from typing import List

from .validators import validate_container_id


def get_container_runtime() -> str:
    """Verify Docker is available and return the runtime name ('docker')."""
    try:
        result = subprocess.run(["docker", "version"], capture_output=True, text=True)
        if result.returncode == 0:
            return "docker"
        print(f"docker error: {result.stderr}", file=sys.stderr)
        raise RuntimeError("Docker is not available")
    except FileNotFoundError:
        print("docker not found", file=sys.stderr)
        raise RuntimeError("Docker is not installed or not in PATH")


def run_container_command(command: List[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a Docker command, ensuring standard bin directories are in PATH."""
    env = os.environ.copy()
    if 'PATH' not in env:
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
    else:
        for directory in ['/usr/local/bin', '/usr/bin', '/bin']:
            if directory not in env['PATH'].split(':'):
                env['PATH'] = f"{directory}:{env['PATH']}"
    kwargs.setdefault('env', env)
    return subprocess.run(command, **kwargs)


def detect_image_os(image_name: str) -> str:
    """Return 'alpine', 'ubuntu', or 'unknown' for the given Docker image."""
    runtime = get_container_runtime()
    result = run_container_command(
        [runtime, "run", "--rm", image_name, "cat", "/etc/os-release"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        output = result.stdout.lower()
        if "alpine" in output:
            return "alpine"
        if "ubuntu" in output:
            return "ubuntu"
    return "unknown"


def get_container_name(container_id_or_name: str) -> str:
    """Resolve a container ID or name to its plain name (strips leading slash)."""
    runtime = get_container_runtime()
    r = run_container_command(
        [runtime, "inspect", "-f", "{{.Name}}", container_id_or_name],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        return r.stdout.strip().lstrip("/")
    return container_id_or_name


def validate_existing_container(container_id_or_name: str) -> bool:
    """Check that a container exists in Docker. Raises ValueError if not found."""
    try:
        if (re.match(r'^[0-9a-fA-F]+$', container_id_or_name)
                and len(container_id_or_name) in (12, 64)):
            validate_container_id(container_id_or_name)
        else:
            if not re.match(r'^[a-zA-Z0-9_-]+$', container_id_or_name):
                raise ValueError(f"Invalid container name format: {container_id_or_name}")

        runtime = get_container_runtime()
        result = run_container_command(
            [runtime, "inspect", container_id_or_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise ValueError(f"Container {container_id_or_name} not found or not accessible")
        return True

    except subprocess.SubprocessError as e:
        raise ValueError(f"Failed to validate container {container_id_or_name}: {e}")
    except FileNotFoundError:
        raise ValueError("Container runtime (Docker) not found")
