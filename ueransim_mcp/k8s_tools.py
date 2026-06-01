import time
from typing import Optional

from .app import mcp
from .models import (
    GnbConfiguration, GnbContainer, GnbCreateResponse, GnbListResponse, GnbOperationResponse,
    UeConfiguration, UeContainer, UeCreateResponse, UeListResponse, UeOperationResponse,
)
from .utils import generate_random_suffix
from .validators import (
    validate_ip, validate_container_name,
    validate_mcc, validate_mnc, validate_nci, validate_cell_access_type,
    validate_op_type, validate_session_type, validate_supi, validate_hex_key,
)
from .k8s_utils import get_k8s_client, exec_in_pod, wait_for_pod_running
from .config_ops import (
    gnb_config_cmds, ue_config_cmds,
    gnb_slice_cmds, ue_slice_cmds, gnb_gtp_advertise_cmds,
    GNB_CFG, UE_CFG,
)

_GNB_IMAGE = "ghcr.io/apelgroup/mcp-ueransim-new/ueransim-gnb:latest"
_UE_IMAGE  = "ghcr.io/apelgroup/mcp-ueransim-new/ueransim-ue:latest"


def _pod_type(pod_name: str) -> str:
    if pod_name.startswith("gnb-"):
        return "gnb"
    if pod_name.startswith("ue-"):
        return "ue"
    return "unknown"


# ── gNB tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def k8s_create_gnb(
    amf_address: str = "127.0.0.5",
    amf_port: str = "38412",
    pod_name: Optional[str] = None,
    namespace: str = "ueransim",
    gnb_image: str = _GNB_IMAGE,
    image_pull_secret: str = "ghcr-pull-secret",
    mcc: str = "999",
    mnc: str = "70",
    tac: int = 1,
    nci: str = "0x000000010",
    id_length: int = 32,
    slice_sst: int = 1,
    slice_sd: Optional[int] = None,
    cell_access_type: str = "nr",
    gtp_advertise_ip: Optional[str] = None,
    ignore_stream_ids: bool = True,
    kubeconfig: str = "",
) -> GnbCreateResponse:
    """Create a new gNB Pod in Kubernetes.

    Args:
        amf_address: AMF IP address
        amf_port: AMF port
        pod_name: Optional pod name (auto-generated if omitted)
        namespace: Kubernetes namespace (default: ueransim)
        gnb_image: Container image for the gNB
        image_pull_secret: Name of the K8s docker-registry secret
        mcc: Mobile Country Code (3 digits)
        mnc: Mobile Network Code (2-3 digits)
        tac: Tracking Area Code
        nci: NR Cell Identity (36-bit hex, e.g. 0x000000010)
        id_length: NR gNB ID length in bits [22..32]
        slice_sst: Primary slice SST
        slice_sd: Primary slice SD (optional)
        cell_access_type: nr | nr-leo | nr-meo | nr-geo | nr-othersat
        gtp_advertise_ip: GTP advertise IP override (for NAT scenarios)
        ignore_stream_ids: Whether to ignore SCTP stream ID errors
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    _empty_cfg = lambda: GnbConfiguration(
        link_ip="", ngap_ip="", gtp_ip="",
        amf_address=amf_address, amf_port=amf_port,
        mcc=mcc, mnc=mnc, tac=tac, nci=nci, id_length=id_length,
        slice_sst=slice_sst, slice_sd=slice_sd,
        cell_access_type=cell_access_type,
        gtp_advertise_ip=gtp_advertise_ip,
        ignore_stream_ids=ignore_stream_ids,
    )
    try:
        validate_ip(amf_address)
        validate_mcc(mcc)
        validate_mnc(mnc)
        validate_nci(nci)
        validate_cell_access_type(cell_access_type)
        if gtp_advertise_ip is not None:
            validate_ip(gtp_advertise_ip)

        if pod_name:
            validate_container_name(pod_name, "gnb")
        else:
            pod_name = f"gnb-{generate_random_suffix()}"

        v1 = get_k8s_client(kubeconfig=kubeconfig)
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

        # Update interface IPs and AMF address
        for pattern in [
            f"s/linkIp: .*/linkIp: {pod_ip}/",
            f"s/ngapIp: .*/ngapIp: {pod_ip}/",
            f"s/gtpIp: .*/gtpIp: {pod_ip}/",
        ]:
            exec_in_pod(v1, pod_name, namespace, ["sed", "-i", pattern, GNB_CFG])

        exec_in_pod(v1, pod_name, namespace,
                    ["sed", "-i", f"s/- address: .*/- address: {amf_address}/", GNB_CFG])

        # Apply additional parametric config
        for cmd in gnb_config_cmds(
            mcc=mcc, mnc=mnc, tac=tac, nci=nci, id_length=id_length,
            slice_sst=slice_sst, slice_sd=slice_sd,
            cell_access_type=cell_access_type,
            gtp_advertise_ip=gtp_advertise_ip,
            ignore_stream_ids=ignore_stream_ids,
            amf_port=amf_port,
        ):
            exec_in_pod(v1, pod_name, namespace, cmd)

        return GnbCreateResponse(
            status="success", container_id=pod_name, container_name=pod_name,
            configuration=GnbConfiguration(
                link_ip=pod_ip, ngap_ip=pod_ip, gtp_ip=pod_ip,
                amf_address=amf_address, amf_port=amf_port,
                mcc=mcc, mnc=mnc, tac=tac, nci=nci, id_length=id_length,
                slice_sst=slice_sst, slice_sd=slice_sd,
                cell_access_type=cell_access_type,
                gtp_advertise_ip=gtp_advertise_ip,
                ignore_stream_ids=ignore_stream_ids,
            ),
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
def k8s_list_gnbs(namespace: str = "ueransim", kubeconfig: str = "") -> GnbListResponse:
    """List all gNB pods in the given Kubernetes namespace.

    Args:
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        v1 = get_k8s_client(kubeconfig=kubeconfig)
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
def k8s_delete_gnb(pod_name: str, namespace: str = "ueransim", kubeconfig: str = "") -> GnbOperationResponse:
    """Delete a gNB pod from Kubernetes.

    Args:
        pod_name: Pod name
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException
    try:
        validate_container_name(pod_name, "gnb")
        v1 = get_k8s_client(kubeconfig=kubeconfig)
        v1.delete_namespaced_pod(pod_name, namespace,
                                 body=client.V1DeleteOptions(grace_period_seconds=0))
        return GnbOperationResponse(
            status="success", message=f"Pod {pod_name} deleted from namespace {namespace}",
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
    pod_name: str, lines: int = 100, namespace: str = "ueransim", kubeconfig: str = ""
) -> GnbOperationResponse:
    """Get logs from a gNB pod.

    Args:
        pod_name: Pod name
        lines: Number of log lines to retrieve (default: 100)
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        validate_container_name(pod_name, "gnb")
        v1 = get_k8s_client(kubeconfig=kubeconfig)
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
    pod_name: str, amf_address: str = "127.0.0.5", namespace: str = "ueransim",
    kubeconfig: str = "",
) -> GnbOperationResponse:
    """Update AMF address and start the nr-gnb process in a gNB pod.

    Args:
        pod_name: gNB pod name
        amf_address: AMF IP address (default: 127.0.0.5)
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        validate_ip(amf_address)
        validate_container_name(pod_name, "gnb")
        v1 = get_k8s_client(kubeconfig=kubeconfig)

        exec_in_pod(v1, pod_name, namespace,
                    ["sed", "-i", f"s/- address: .*/- address: {amf_address}/", GNB_CFG])
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
def k8s_inspect_pod_ip(pod_name: str, namespace: str = "ueransim", kubeconfig: str = "") -> GnbOperationResponse:
    """Return the IP address of a Kubernetes pod.

    Args:
        pod_name: Pod name
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        v1 = get_k8s_client(kubeconfig=kubeconfig)
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
    supi: Optional[str] = None,
    mcc: str = "999",
    mnc: str = "70",
    key: Optional[str] = None,
    op: Optional[str] = None,
    op_type: str = "OPC",
    slice_sst: int = 1,
    slice_sd: Optional[int] = None,
    session_apn: str = "internet",
    session_type: str = "IPv4",
    tun_netmask: str = "255.255.255.0",
    kubeconfig: str = "",
) -> UeCreateResponse:
    """Create a new UE Pod in Kubernetes.

    Args:
        gnb_search_list: gNB IP for Radio Link Simulation, or 'auto' to use first gNB
        pod_name: Optional pod name (auto-generated if omitted)
        namespace: Kubernetes namespace (default: ueransim)
        ue_image: Container image for the UE
        image_pull_secret: Name of the K8s docker-registry secret
        supi: SUPI in imsi-MCCMNCMSISDN format (15 digits after imsi-)
        mcc: Mobile Country Code (3 digits)
        mnc: Mobile Network Code (2-3 digits)
        key: Permanent subscription key (32 hex chars)
        op: Operator code (32 hex chars)
        op_type: OP or OPC
        slice_sst: Primary slice SST
        slice_sd: Primary slice SD (optional)
        session_apn: PDU session APN
        session_type: IPv4 | IPv6 | IPv4v6
        tun_netmask: TUN interface netmask
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    _empty_cfg = lambda gsl: UeConfiguration(
        gnb_search_list=gsl, supi=supi, mcc=mcc, mnc=mnc,
        key=key, op=op, op_type=op_type,
        slice_sst=slice_sst, slice_sd=slice_sd,
        session_apn=session_apn, session_type=session_type,
        tun_netmask=tun_netmask,
    )
    try:
        if gnb_search_list == "auto":
            gnb_list = k8s_list_gnbs(namespace, kubeconfig=kubeconfig)
            if gnb_list.status == "success" and gnb_list.count > 0:
                ip_result = k8s_inspect_pod_ip(gnb_list.containers[0].name, namespace, kubeconfig=kubeconfig)
                gnb_search_list = ip_result.logs if ip_result.status == "success" else "127.0.0.1"
            else:
                gnb_search_list = "127.0.0.1"

        validate_ip(gnb_search_list)
        validate_mcc(mcc)
        validate_mnc(mnc)
        validate_op_type(op_type)
        validate_session_type(session_type)
        if supi is not None:
            validate_supi(supi)
        if key is not None:
            validate_hex_key(key, "key")
        if op is not None:
            validate_hex_key(op, "op")

        if pod_name:
            validate_container_name(pod_name, "ue")
        else:
            pod_name = f"ue-{generate_random_suffix()}"

        v1 = get_k8s_client(kubeconfig=kubeconfig)
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
                configuration=_empty_cfg(gnb_search_list),
                message=f"Pod {pod_name} did not reach Running state within 60s",
            )

        # Update gnbSearchList
        exec_in_pod(v1, pod_name, namespace,
                    ["sh", "-c",
                     f"sed -i '/^gnbSearchList:/{{n; s/  - .*/  - {gnb_search_list}/;}}' {UE_CFG}"])

        # Apply additional parametric config
        for cmd in ue_config_cmds(
            supi=supi, mcc=mcc, mnc=mnc, key=key, op=op, op_type=op_type,
            slice_sst=slice_sst, slice_sd=slice_sd,
            session_apn=session_apn, session_type=session_type,
            tun_netmask=tun_netmask,
        ):
            exec_in_pod(v1, pod_name, namespace, cmd)

        return UeCreateResponse(
            status="success", container_id=pod_name, container_name=pod_name,
            configuration=_empty_cfg(gnb_search_list),
        )

    except ValueError as e:
        gsl = gnb_search_list if 'gnb_search_list' in locals() else "127.0.0.1"
        return UeCreateResponse(
            status="error", container_id="", container_name="",
            configuration=_empty_cfg(gsl), message=str(e),
        )
    except ApiException as e:
        gsl = gnb_search_list if 'gnb_search_list' in locals() else "127.0.0.1"
        return UeCreateResponse(
            status="error", container_id="", container_name="",
            configuration=_empty_cfg(gsl),
            message=f"Kubernetes API error: {e.reason} (status {e.status})",
        )
    except Exception as e:
        gsl = gnb_search_list if 'gnb_search_list' in locals() else "127.0.0.1"
        return UeCreateResponse(
            status="error", container_id="", container_name="",
            configuration=_empty_cfg(gsl), message=str(e),
        )


@mcp.tool()
def k8s_list_ues(namespace: str = "ueransim", kubeconfig: str = "") -> UeListResponse:
    """List all UE pods in the given Kubernetes namespace.

    Args:
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        v1 = get_k8s_client(kubeconfig=kubeconfig)
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
def k8s_delete_ue(pod_name: str, namespace: str = "ueransim", kubeconfig: str = "") -> UeOperationResponse:
    """Delete a UE pod from Kubernetes.

    Args:
        pod_name: Pod name
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException
    try:
        validate_container_name(pod_name, "ue")
        v1 = get_k8s_client(kubeconfig=kubeconfig)
        v1.delete_namespaced_pod(pod_name, namespace,
                                 body=client.V1DeleteOptions(grace_period_seconds=0))
        return UeOperationResponse(
            status="success", message=f"Pod {pod_name} deleted from namespace {namespace}",
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
    pod_name: str, lines: int = 100, namespace: str = "ueransim", kubeconfig: str = ""
) -> UeOperationResponse:
    """Get logs from a UE pod.

    Args:
        pod_name: Pod name
        lines: Number of log lines to retrieve (default: 100)
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        validate_container_name(pod_name, "ue")
        v1 = get_k8s_client(kubeconfig=kubeconfig)
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
    ue_pod_name: str, gnb_pod_name: str, namespace: str = "ueransim", kubeconfig: str = "",
) -> UeOperationResponse:
    """Update the UE's gnbSearchList with the gNB pod IP and start nr-ue.

    Args:
        ue_pod_name: UE pod name
        gnb_pod_name: gNB pod name
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        validate_container_name(ue_pod_name, "ue")
        validate_container_name(gnb_pod_name, "gnb")
        v1 = get_k8s_client(kubeconfig=kubeconfig)

        gnb_ip_result = k8s_inspect_pod_ip(gnb_pod_name, namespace, kubeconfig=kubeconfig)
        if gnb_ip_result.status != "success" or not gnb_ip_result.logs:
            return UeOperationResponse(
                status="error",
                message=f"Could not determine IP for gNB pod {gnb_pod_name}: {gnb_ip_result.message}",
                container=ue_pod_name,
            )
        gnb_ip = gnb_ip_result.logs.strip()

        exec_in_pod(v1, ue_pod_name, namespace,
                    ["sh", "-c",
                     f"sed -i '/^gnbSearchList:/{{n; s/  - .*/  - {gnb_ip}/;}}' {UE_CFG}"])
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
        details = [
            "gNB: nr-gnb active" if gnb_ok else "gNB: nr-gnb not running",
            "UE: nr-ue active"   if ue_ok  else "UE: nr-ue not running",
        ]

        return UeOperationResponse(
            status="success" if (gnb_ok and ue_ok) else "warning",
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
    kubeconfig: str = "",
) -> UeOperationResponse:
    """Edit a configuration field inside an existing pod.

    Args:
        pod_name: Pod name (gnb-* or ue-*)
        config_type: Field to change. GNB types: ngap_ip, gtp_ip, amf_ip, mcc, mnc,
            tac, nci, id_length, cell_access_type, ignore_stream_ids, gtp_advertise_ip,
            slice (value: "sst" or "sst,sd").
            UE types: gnb_search_list, supi, key, op, op_type, mcc, mnc, session_apn,
            session_type, tun_netmask, slice (value: "sst" or "sst,sd").
        config_value: New value as a string
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        v1 = get_k8s_client(kubeconfig=kubeconfig)
        v1.read_namespaced_pod(pod_name, namespace)  # verify pod exists

        ctype = _pod_type(pod_name)
        cmds = _k8s_edit_commands(config_type, config_value, ctype)
        if cmds is None:
            return UeOperationResponse(
                status="error",
                message=(f"Unsupported config_type '{config_type}' for pod type '{ctype}'."
                         " Check the docstring for valid types."),
                container=pod_name,
            )

        for cmd in cmds:
            exec_in_pod(v1, pod_name, namespace, cmd)

        return UeOperationResponse(
            status="success",
            message=f"Pod {pod_name} updated: {config_type}={config_value}",
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


def _k8s_edit_commands(config_type: str, config_value: str, ctype: str):
    """Mirror of docker_tools._edit_commands for K8s (pod names always known)."""
    f_gnb, f_ue = GNB_CFG, UE_CFG

    if config_type == "slice":
        parts = config_value.split(",")
        sst = int(parts[0])
        sd = int(parts[1]) if len(parts) > 1 else None
        if ctype == "gnb":
            return gnb_slice_cmds(sst, sd)
        if ctype == "ue":
            return ue_slice_cmds(sst, sd)
        return None

    if config_type in ("mcc", "mnc"):
        target = f_gnb if ctype == "gnb" else f_ue if ctype == "ue" else None
        if target is None:
            return None
        return [["sed", "-i", f"s/^{config_type}: .*/{config_type}: '{config_value}'/", target]]

    _gnb_map = {
        "ngap_ip":          [["sed", "-i", f"s/ngapIp: .*/ngapIp: {config_value}/", f_gnb]],
        "gtp_ip":           [["sed", "-i", f"s/gtpIp: .*/gtpIp: {config_value}/", f_gnb]],
        "amf_ip":           [["sed", "-i", f"s/- address: .*/- address: {config_value}/", f_gnb]],
        "tac":              [["sed", "-i", f"s/^tac: .*/tac: {config_value}/", f_gnb]],
        "nci":              [["sed", "-i", f"s/^nci: .*/nci: '{config_value}'/", f_gnb]],
        "id_length":        [["sed", "-i", f"s/^idLength: .*/idLength: {config_value}/", f_gnb]],
        "cell_access_type": [["sed", "-i",
                               f"s/^cellAccessType: .*/cellAccessType: {config_value}/", f_gnb]],
        "ignore_stream_ids":[["sed", "-i",
                               f"s/^ignoreStreamIds: .*/ignoreStreamIds: {config_value}/", f_gnb]],
        "gtp_advertise_ip": gnb_gtp_advertise_cmds(config_value),
    }
    _ue_map = {
        "gnb_search_list":  [["sh", "-c",
                               f"sed -i '/^gnbSearchList:/{{n; s/  - .*/  - {config_value}/;}}' {f_ue}"]],
        "supi":             [["sed", "-i", f"s/^supi: .*/supi: '{config_value}'/", f_ue]],
        "key":              [["sed", "-i", f"s/^key: .*/key: '{config_value}'/", f_ue]],
        "op":               [["sed", "-i", f"s/^op: .*/op: '{config_value}'/", f_ue]],
        "op_type":          [["sed", "-i", f"s/^opType: .*/opType: '{config_value}'/", f_ue]],
        "session_apn":      [["sed", "-i",
                               f"s/^    apn: .*/    apn: '{config_value}'/", f_ue]],
        "session_type":     [["sed", "-i",
                               f"s/^  - type: .*/  - type: '{config_value}'/", f_ue]],
        "tun_netmask":      [["sed", "-i",
                               f"s/^tunNetmask: .*/tunNetmask: '{config_value}'/", f_ue]],
    }

    if config_type in _gnb_map:
        return _gnb_map[config_type]
    if config_type in _ue_map:
        return _ue_map[config_type]
    return None
