import time
from typing import Optional

from .app import mcp
from .models import (
    GnbConfiguration, GnbContainer, GnbCreateResponse, GnbListResponse, GnbOperationResponse,
    UeConfiguration, UeContainer, UeCreateResponse, UeListResponse, UeOperationResponse,
)
from .utils import generate_random_suffix
from .validators import validate_ip, validate_container_name
from .k8s_utils import get_k8s_client, exec_in_pod, wait_for_pod_running

_GNB_IMAGE = "ghcr.io/apelgroup/mcp-ueransim-new/ueransim-gnb:latest"
_UE_IMAGE  = "ghcr.io/apelgroup/mcp-ueransim-new/ueransim-ue:latest"


# ── gNB tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def k8s_create_gnb(
    amf_address: str = "127.0.0.5",
    amf_port: str = "38412",
    pod_name: Optional[str] = None,
    namespace: str = "ueransim",
    gnb_image: str = _GNB_IMAGE,
    image_pull_secret: str = "ghcr-pull-secret",
) -> GnbCreateResponse:
    """Create a new gNB Pod in Kubernetes.

    Args:
        amf_address: AMF IP address
        amf_port: AMF port
        pod_name: Optional pod name (auto-generated if omitted)
        namespace: Kubernetes namespace (default: ueransim)
        gnb_image: Container image for the gNB
        image_pull_secret: Name of the K8s docker-registry secret for pulling the image
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    _empty_cfg = lambda: GnbConfiguration(link_ip="", ngap_ip="", gtp_ip="",
                                          amf_address=amf_address, amf_port=amf_port)
    try:
        validate_ip(amf_address)
        if pod_name:
            validate_container_name(pod_name, "gnb")
        else:
            pod_name = f"gnb-{generate_random_suffix()}"

        v1 = get_k8s_client()
        pod_body = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=pod_name, namespace=namespace,
                labels={"app": "ueransim", "type": "gnb"},
            ),
            spec=client.V1PodSpec(
                image_pull_secrets=[client.V1LocalObjectReference(name=image_pull_secret)],
                containers=[client.V1Container(
                    name="gnb", image=gnb_image, image_pull_policy="IfNotPresent",
                    command=["tail", "-f", "/dev/null"],
                    security_context=client.V1SecurityContext(
                        capabilities=client.V1Capabilities(add=["NET_ADMIN"])
                    ),
                )],
            ),
        )
        v1.create_namespaced_pod(namespace=namespace, body=pod_body)

        if not wait_for_pod_running(v1, pod_name, namespace):
            return GnbCreateResponse(
                status="error", container_id=pod_name, container_name=pod_name,
                configuration=_empty_cfg(),
                message=f"Pod {pod_name} did not reach Running state within 60s",
            )

        pod_ip = v1.read_namespaced_pod(pod_name, namespace).status.pod_ip or ""

        for pattern in [
            f"s/linkIp: .*/linkIp: {pod_ip}/",
            f"s/ngapIp: .*/ngapIp: {pod_ip}/",
            f"s/gtpIp: .*/gtpIp: {pod_ip}/",
        ]:
            exec_in_pod(v1, pod_name, namespace,
                        ["sed", "-i", pattern, "/etc/ueransim/open5gs-gnb.yaml"])

        exec_in_pod(v1, pod_name, namespace,
                    ["sed", "-i", f"s/- address: .*/- address: {amf_address}/",
                     "/etc/ueransim/open5gs-gnb.yaml"])

        return GnbCreateResponse(
            status="success", container_id=pod_name, container_name=pod_name,
            configuration=GnbConfiguration(link_ip=pod_ip, ngap_ip=pod_ip, gtp_ip=pod_ip,
                                           amf_address=amf_address, amf_port=amf_port),
        )

    except ValueError as e:
        return GnbCreateResponse(status="error", container_id="", container_name="",
                                 configuration=_empty_cfg(), message=str(e))
    except ApiException as e:
        return GnbCreateResponse(
            status="error", container_id="", container_name="", configuration=_empty_cfg(),
            message=f"Kubernetes API error: {e.reason} (status {e.status})",
        )
    except Exception as e:
        return GnbCreateResponse(status="error", container_id="", container_name="",
                                 configuration=_empty_cfg(), message=str(e))


@mcp.tool()
def k8s_list_gnbs(namespace: str = "ueransim") -> GnbListResponse:
    """List all gNB pods in the given Kubernetes namespace.

    Args:
        namespace: Kubernetes namespace (default: ueransim)
    """
    from kubernetes.client.rest import ApiException

    try:
        v1 = get_k8s_client()
        pods = v1.list_namespaced_pod(namespace, label_selector="type=gnb").items
        containers = [
            GnbContainer(id=p.metadata.name, name=p.metadata.name,
                         status=p.status.phase or "Unknown",
                         created=str(p.metadata.creation_timestamp))
            for p in pods
        ]
        return GnbListResponse(status="success", containers=containers, count=len(containers))

    except ApiException as e:
        return GnbListResponse(status="error", containers=[], count=0,
                               message=f"Kubernetes API error: {e.reason} (status {e.status})")
    except Exception as e:
        return GnbListResponse(status="error", containers=[], count=0, message=str(e))


@mcp.tool()
def k8s_delete_gnb(pod_name: str, namespace: str = "ueransim") -> GnbOperationResponse:
    """Delete a gNB pod from Kubernetes.

    Args:
        pod_name: Pod name
        namespace: Kubernetes namespace (default: ueransim)
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    try:
        validate_container_name(pod_name, "gnb")
        v1 = get_k8s_client()
        v1.delete_namespaced_pod(pod_name, namespace,
                                 body=client.V1DeleteOptions(grace_period_seconds=0))
        return GnbOperationResponse(
            status="success",
            message=f"Pod {pod_name} deleted from namespace {namespace}",
            container=pod_name,
        )

    except ValueError as e:
        return GnbOperationResponse(status="error", message=str(e), container=pod_name)
    except ApiException as e:
        return GnbOperationResponse(
            status="error",
            message=f"Kubernetes API error: {e.reason} (status {e.status})",
            container=pod_name,
        )
    except Exception as e:
        return GnbOperationResponse(status="error", message=str(e), container=pod_name)


@mcp.tool()
def k8s_get_gnb_logs(
    pod_name: str, lines: int = 100, namespace: str = "ueransim"
) -> GnbOperationResponse:
    """Get logs from a gNB pod.

    Args:
        pod_name: Pod name
        lines: Number of log lines to retrieve (default: 100)
        namespace: Kubernetes namespace (default: ueransim)
    """
    from kubernetes.client.rest import ApiException

    try:
        validate_container_name(pod_name, "gnb")
        v1 = get_k8s_client()
        logs = v1.read_namespaced_pod_log(pod_name, namespace, tail_lines=lines)
        return GnbOperationResponse(status="success", message="Logs retrieved successfully",
                                    container=pod_name, logs=logs)

    except ValueError as e:
        return GnbOperationResponse(status="error", message=str(e), container=pod_name)
    except ApiException as e:
        return GnbOperationResponse(
            status="error",
            message=f"Kubernetes API error: {e.reason} (status {e.status})",
            container=pod_name,
        )
    except Exception as e:
        return GnbOperationResponse(status="error", message=str(e), container=pod_name)


@mcp.tool()
def k8s_attach_gnb_to_core(
    pod_name: str, amf_address: str = "127.0.0.5", namespace: str = "ueransim"
) -> GnbOperationResponse:
    """Update AMF address and start the nr-gnb process inside a gNB pod.

    Args:
        pod_name: gNB pod name
        amf_address: AMF IP address (default: 127.0.0.5)
        namespace: Kubernetes namespace (default: ueransim)
    """
    from kubernetes.client.rest import ApiException

    try:
        validate_ip(amf_address)
        validate_container_name(pod_name, "gnb")
        v1 = get_k8s_client()

        exec_in_pod(v1, pod_name, namespace,
                    ["sed", "-i", f"s/- address: .*/- address: {amf_address}/",
                     "/etc/ueransim/open5gs-gnb.yaml"])

        exec_in_pod(v1, pod_name, namespace,
                    ["sh", "-c",
                     "nohup /usr/local/bin/nr-gnb -c /etc/ueransim/open5gs-gnb.yaml"
                     " > /proc/1/fd/1 2>&1 &"])

        time.sleep(2)

        status_out, _ = exec_in_pod(
            v1, pod_name, namespace,
            ["sh", "-c", "pgrep -f nr-gnb && echo 'gNB process is running'"
                         " || echo 'gNB process not found'"],
        )
        running = "process is running" in status_out

        return GnbOperationResponse(
            status="success" if running else "warning",
            message=(f"Pod {pod_name} connected to core with AMF {amf_address}. "
                     f"{'nr-gnb started.' if running else 'nr-gnb may not be running.'}"),
            container=pod_name, logs=status_out,
        )

    except ValueError as e:
        return GnbOperationResponse(status="error", message=str(e), container=pod_name)
    except ApiException as e:
        return GnbOperationResponse(
            status="error",
            message=f"Kubernetes API error: {e.reason} (status {e.status})",
            container=pod_name,
        )
    except Exception as e:
        return GnbOperationResponse(status="error", message=str(e), container=pod_name)


# ── Common tools ──────────────────────────────────────────────────────────────

@mcp.tool()
def k8s_inspect_pod_ip(pod_name: str, namespace: str = "ueransim") -> GnbOperationResponse:
    """Return the IP address of a Kubernetes pod.

    Args:
        pod_name: Pod name
        namespace: Kubernetes namespace (default: ueransim)
    """
    from kubernetes.client.rest import ApiException

    try:
        v1 = get_k8s_client()
        pod_ip = v1.read_namespaced_pod(pod_name, namespace).status.pod_ip
        if not pod_ip:
            return GnbOperationResponse(
                status="error", message=f"No IP found for pod {pod_name}", container=pod_name
            )
        return GnbOperationResponse(
            status="success", message=f"Pod {pod_name} IP: {pod_ip}",
            container=pod_name, logs=pod_ip,
        )

    except ApiException as e:
        return GnbOperationResponse(
            status="error",
            message=f"Kubernetes API error: {e.reason} (status {e.status})",
            container=pod_name,
        )
    except Exception as e:
        return GnbOperationResponse(status="error", message=str(e), container=pod_name)


# ── UE tools ──────────────────────────────────────────────────────────────────

@mcp.tool()
def k8s_create_ue(
    gnb_search_list: str = "127.0.0.1",
    pod_name: Optional[str] = None,
    namespace: str = "ueransim",
    ue_image: str = _UE_IMAGE,
    image_pull_secret: str = "ghcr-pull-secret",
) -> UeCreateResponse:
    """Create a new UE Pod in Kubernetes.

    Args:
        gnb_search_list: gNB IP for Radio Link Simulation, or 'auto' to use first available gNB
        pod_name: Optional pod name (auto-generated if omitted)
        namespace: Kubernetes namespace (default: ueransim)
        ue_image: Container image for the UE
        image_pull_secret: Name of the K8s docker-registry secret for pulling the image
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    try:
        if gnb_search_list == "auto":
            gnb_list = k8s_list_gnbs(namespace)
            if gnb_list.status == "success" and gnb_list.count > 0:
                ip_result = k8s_inspect_pod_ip(gnb_list.containers[0].name, namespace)
                gnb_search_list = ip_result.logs if ip_result.status == "success" else "127.0.0.1"
            else:
                gnb_search_list = "127.0.0.1"

        validate_ip(gnb_search_list)
        if pod_name:
            validate_container_name(pod_name, "ue")
        else:
            pod_name = f"ue-{generate_random_suffix()}"

        v1 = get_k8s_client()
        pod_body = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=pod_name, namespace=namespace,
                labels={"app": "ueransim", "type": "ue"},
            ),
            spec=client.V1PodSpec(
                host_network=True,
                image_pull_secrets=[client.V1LocalObjectReference(name=image_pull_secret)],
                containers=[client.V1Container(
                    name="ue", image=ue_image, image_pull_policy="IfNotPresent",
                    command=["tail", "-f", "/dev/null"],
                    security_context=client.V1SecurityContext(
                        privileged=True,
                        capabilities=client.V1Capabilities(add=["NET_ADMIN"]),
                    ),
                    volume_mounts=[client.V1VolumeMount(
                        name="tun-device", mount_path="/dev/net/tun"
                    )],
                )],
                volumes=[client.V1Volume(
                    name="tun-device",
                    host_path=client.V1HostPathVolumeSource(
                        path="/dev/net/tun", type="CharDevice"
                    ),
                )],
            ),
        )
        v1.create_namespaced_pod(namespace=namespace, body=pod_body)

        if not wait_for_pod_running(v1, pod_name, namespace):
            return UeCreateResponse(
                status="error", container_id=pod_name, container_name=pod_name,
                configuration=UeConfiguration(gnb_search_list=gnb_search_list),
                message=f"Pod {pod_name} did not reach Running state within 60s",
            )

        exec_in_pod(v1, pod_name, namespace,
                    ["sed", "-i", f"s/- .*/- {gnb_search_list}/",
                     "/etc/ueransim/open5gs-ue.yaml"])

        return UeCreateResponse(
            status="success", container_id=pod_name, container_name=pod_name,
            configuration=UeConfiguration(gnb_search_list=gnb_search_list),
        )

    except ValueError as e:
        return UeCreateResponse(
            status="error", container_id="", container_name="",
            configuration=UeConfiguration(gnb_search_list=gnb_search_list), message=str(e),
        )
    except ApiException as e:
        return UeCreateResponse(
            status="error", container_id="", container_name="",
            configuration=UeConfiguration(gnb_search_list=gnb_search_list),
            message=f"Kubernetes API error: {e.reason} (status {e.status})",
        )
    except Exception as e:
        return UeCreateResponse(
            status="error", container_id="", container_name="",
            configuration=UeConfiguration(
                gnb_search_list=gnb_search_list if 'gnb_search_list' in locals() else "127.0.0.1"
            ),
            message=str(e),
        )


@mcp.tool()
def k8s_list_ues(namespace: str = "ueransim") -> UeListResponse:
    """List all UE pods in the given Kubernetes namespace.

    Args:
        namespace: Kubernetes namespace (default: ueransim)
    """
    from kubernetes.client.rest import ApiException

    try:
        v1 = get_k8s_client()
        pods = v1.list_namespaced_pod(namespace, label_selector="type=ue").items
        containers = [
            UeContainer(id=p.metadata.name, name=p.metadata.name,
                        status=p.status.phase or "Unknown",
                        created=str(p.metadata.creation_timestamp))
            for p in pods
        ]
        return UeListResponse(status="success", containers=containers, count=len(containers))

    except ApiException as e:
        return UeListResponse(status="error", containers=[], count=0,
                              message=f"Kubernetes API error: {e.reason} (status {e.status})")
    except Exception as e:
        return UeListResponse(status="error", containers=[], count=0, message=str(e))


@mcp.tool()
def k8s_delete_ue(pod_name: str, namespace: str = "ueransim") -> UeOperationResponse:
    """Delete a UE pod from Kubernetes.

    Args:
        pod_name: Pod name
        namespace: Kubernetes namespace (default: ueransim)
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    try:
        validate_container_name(pod_name, "ue")
        v1 = get_k8s_client()
        v1.delete_namespaced_pod(pod_name, namespace,
                                 body=client.V1DeleteOptions(grace_period_seconds=0))
        return UeOperationResponse(
            status="success",
            message=f"Pod {pod_name} deleted from namespace {namespace}",
            container=pod_name,
        )

    except ValueError as e:
        return UeOperationResponse(status="error", message=str(e), container=pod_name)
    except ApiException as e:
        return UeOperationResponse(
            status="error",
            message=f"Kubernetes API error: {e.reason} (status {e.status})",
            container=pod_name,
        )
    except Exception as e:
        return UeOperationResponse(status="error", message=str(e), container=pod_name)


@mcp.tool()
def k8s_get_ue_logs(
    pod_name: str, lines: int = 100, namespace: str = "ueransim"
) -> UeOperationResponse:
    """Get logs from a UE pod.

    Args:
        pod_name: Pod name
        lines: Number of log lines to retrieve (default: 100)
        namespace: Kubernetes namespace (default: ueransim)
    """
    from kubernetes.client.rest import ApiException

    try:
        validate_container_name(pod_name, "ue")
        v1 = get_k8s_client()
        logs = v1.read_namespaced_pod_log(pod_name, namespace, tail_lines=lines)
        return UeOperationResponse(status="success", message="Logs retrieved successfully",
                                   container=pod_name, logs=logs)

    except ValueError as e:
        return UeOperationResponse(status="error", message=str(e), container=pod_name)
    except ApiException as e:
        return UeOperationResponse(
            status="error",
            message=f"Kubernetes API error: {e.reason} (status {e.status})",
            container=pod_name,
        )
    except Exception as e:
        return UeOperationResponse(status="error", message=str(e), container=pod_name)


@mcp.tool()
def k8s_attach_ue_to_gnb(
    ue_pod_name: str, gnb_pod_name: str, namespace: str = "ueransim"
) -> UeOperationResponse:
    """Update the UE's gnbSearchList with the gNB pod IP and start the nr-ue process.

    Args:
        ue_pod_name: UE pod name
        gnb_pod_name: gNB pod name
        namespace: Kubernetes namespace (default: ueransim)
    """
    from kubernetes.client.rest import ApiException

    try:
        validate_container_name(ue_pod_name, "ue")
        validate_container_name(gnb_pod_name, "gnb")
        v1 = get_k8s_client()

        gnb_ip_result = k8s_inspect_pod_ip(gnb_pod_name, namespace)
        if gnb_ip_result.status != "success" or not gnb_ip_result.logs:
            return UeOperationResponse(
                status="error",
                message=f"Could not determine IP for gNB pod {gnb_pod_name}: {gnb_ip_result.message}",
                container=ue_pod_name,
            )
        gnb_ip = gnb_ip_result.logs.strip()

        exec_in_pod(v1, ue_pod_name, namespace,
                    ["sed", "-i", f"s/- .*/- {gnb_ip}/", "/etc/ueransim/open5gs-ue.yaml"])

        exec_in_pod(v1, ue_pod_name, namespace,
                    ["sh", "-c",
                     "nohup /usr/local/bin/nr-ue -c /etc/ueransim/open5gs-ue.yaml"
                     " > /proc/1/fd/1 2>&1 &"])

        time.sleep(3)

        gnb_out, _ = exec_in_pod(v1, gnb_pod_name, namespace,
                                  ["sh", "-c",
                                   "pgrep -f nr-gnb && echo 'gNB process is running'"
                                   " || echo 'gNB process not found'"])
        ue_out, _ = exec_in_pod(v1, ue_pod_name, namespace,
                                 ["sh", "-c",
                                  "pgrep -f nr-ue && echo 'UE process is running'"
                                  " || echo 'UE process not found'"])

        gnb_ok = "process is running" in gnb_out
        ue_ok  = "process is running" in ue_out
        both   = gnb_ok and ue_ok
        details = [
            "gNB: nr-gnb active" if gnb_ok else "gNB: nr-gnb not running",
            "UE: nr-ue active"   if ue_ok  else "UE: nr-ue not running",
        ]

        return UeOperationResponse(
            status="success" if both else "warning",
            message=(f"UE pod {ue_pod_name} attached to gNB pod {gnb_pod_name}"
                     f" (gNB IP: {gnb_ip}). {'; '.join(details)}"),
            container=ue_pod_name,
            logs=f"gNB check:\n{gnb_out}\n\nUE check:\n{ue_out}",
        )

    except ValueError as e:
        return UeOperationResponse(status="error", message=str(e), container=ue_pod_name)
    except ApiException as e:
        return UeOperationResponse(
            status="error",
            message=f"Kubernetes API error: {e.reason} (status {e.status})",
            container=ue_pod_name,
        )
    except Exception as e:
        return UeOperationResponse(status="error", message=str(e), container=ue_pod_name)


@mcp.tool()
def k8s_edit_pod_config(
    pod_name: str,
    config_type: str = "gnb_search_list",
    config_value: str = "127.0.0.1",
    namespace: str = "ueransim",
) -> UeOperationResponse:
    """Edit a configuration field inside an existing pod.

    Args:
        pod_name: Pod name
        config_type: One of gnb_search_list, ngap_ip, gtp_ip, amf_ip
        config_value: New value (IP address)
        namespace: Kubernetes namespace (default: ueransim)
    """
    from kubernetes.client.rest import ApiException

    try:
        v1 = get_k8s_client()
        v1.read_namespaced_pod(pod_name, namespace)

        if config_type in ("gnb_search_list", "ngap_ip", "gtp_ip", "amf_ip"):
            validate_ip(config_value)

        patterns = {
            "gnb_search_list": (f"s/- .*/- {config_value}/",
                                "/etc/ueransim/open5gs-ue.yaml"),
            "ngap_ip":         (f"s/ngapIp: .*/ngapIp: {config_value}/",
                                "/etc/ueransim/open5gs-gnb.yaml"),
            "gtp_ip":          (f"s/gtpIp: .*/gtpIp: {config_value}/",
                                "/etc/ueransim/open5gs-gnb.yaml"),
            "amf_ip":          (f"s/- address: .*/- address: {config_value}/",
                                "/etc/ueransim/open5gs-gnb.yaml"),
        }
        if config_type not in patterns:
            return UeOperationResponse(
                status="error", message=f"Unsupported config type: {config_type}",
                container=pod_name,
            )

        sed_pattern, config_file = patterns[config_type]
        exec_in_pod(v1, pod_name, namespace, ["sed", "-i", sed_pattern, config_file])

        return UeOperationResponse(
            status="success",
            message=f"Pod {pod_name} configuration updated: {config_type}={config_value}",
            container=pod_name,
        )

    except ValueError as e:
        return UeOperationResponse(status="error", message=str(e), container=pod_name)
    except ApiException as e:
        return UeOperationResponse(
            status="error",
            message=f"Kubernetes API error: {e.reason} (status {e.status})",
            container=pod_name,
        )
    except Exception as e:
        return UeOperationResponse(status="error", message=str(e), container=pod_name)
