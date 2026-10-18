import time
from types import SimpleNamespace
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
from .k8s_utils import (
    MANAGED_BY, build_deployment, exec_in_pod, get_apps_client,
    get_k8s_client, pod_config_map, read_deployment, read_pod_log, recreate_pod,
    resolve_pod_name, rollout_restart, wait_for_deployment_deleted, wait_for_deployment_ready,
    workload_name, WORKLOAD_LABEL,
)
from .config_ops import (
    apply_config_edit, build_gnb_config, build_ue_config, dump_config, load_template,
    gnb_pod_command, ue_pod_command, GNB_CFG, UE_CFG,
)

_GNB_IMAGE = "ghcr.io/dimitrisbro/mcp-ueransim/ueransim-gnb:3.3.0"
_UE_IMAGE  = "ghcr.io/dimitrisbro/mcp-ueransim/ueransim-ue:3.3.0"


def _pod_type(pod_name: str) -> str:
    if pod_name.startswith("gnb-"):
        return "gnb"
    if pod_name.startswith("ue-"):
        return "ue"
    return "unknown"


def _config_map(name: str, namespace: str, filename: str, cfg: dict):
    from kubernetes import client

    return client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name=name, namespace=namespace, labels=dict(MANAGED_BY)),
        data={filename: dump_config(cfg)},
    )


def _config_mount(cfg_path: str):
    """Mount the pod's ConfigMap at cfg_path (read-only subPath), as infra/ does."""
    from kubernetes import client

    return client.V1VolumeMount(
        name="config", mount_path=cfg_path, sub_path=cfg_path.rsplit("/", 1)[1]
    )


def _edit_pod_config(v1, apps, name: str, namespace: str, cfg_path: str, edit) -> bool:
    """Apply edit(cfg) to the YAML in the workload's ConfigMap, then restart it.

    A Deployment (made by the create tools) gets a rollout restart, never a pod delete; a bare
    pod (from infra/ or an older version) is recreated. Returns True once the new pod is up.
    """
    import yaml

    deployment = read_deployment(apps, name, namespace)
    pod = _template_pod(deployment) if deployment else v1.read_namespaced_pod(name, namespace)
    cm_name, key = pod_config_map(pod, cfg_path)
    cm = v1.read_namespaced_config_map(cm_name, namespace)
    cfg = yaml.safe_load(cm.data[key])
    edit(cfg)
    v1.patch_namespaced_config_map(cm_name, namespace, {"data": {key: dump_config(cfg)}})
    if deployment is None:
        return recreate_pod(v1, pod)
    rollout_restart(apps, name, namespace)
    return wait_for_deployment_ready(apps, name, namespace)


def _template_pod(deployment):
    """The Deployment's pod template shaped like a pod (spec + metadata) for pod_config_map."""
    return SimpleNamespace(
        spec=deployment.spec.template.spec,
        metadata=SimpleNamespace(
            name=deployment.metadata.name, namespace=deployment.metadata.namespace
        ),
    )


def _process_running(v1, pod_name: str, namespace: str, binary: str) -> tuple:
    """(running, output) for an exact process-name match (pgrep -f matched its own sh -c)."""
    out, _ = exec_in_pod(
        v1, pod_name, namespace,
        ["sh", "-c", f"pgrep -x {binary} >/dev/null && echo '{binary} is running'"
                     f" || echo '{binary} not found'"],
    )
    return f"{binary} is running" in out, out


def _delete_managed_config_map(v1, pod, cfg_path: str) -> None:
    """Delete the pod's ConfigMap only if the create tools made it (infra/ owns its own)."""
    from kubernetes.client.rest import ApiException

    try:
        cm_name, _ = pod_config_map(pod, cfg_path)
    except ValueError:
        return
    cm = v1.read_namespaced_config_map(cm_name, pod.metadata.namespace)
    if (cm.metadata.labels or {}).items() >= MANAGED_BY.items():
        try:
            v1.delete_namespaced_config_map(cm_name, pod.metadata.namespace)
        except ApiException as e:
            if e.status != 404:
                raise


def _radio_service_name(gnb: str) -> str:
    return f"{gnb}-radio"


def _radio_service(gnb: str, namespace: str):
    """Headless Service that resolves to the gNB pod's current IP (UDP 4997, the gNB's radio-link
    port), so a UE's gnbSearchList survives a gNB rollout restart."""
    from kubernetes import client

    return client.V1Service(
        metadata=client.V1ObjectMeta(
            name=_radio_service_name(gnb), namespace=namespace, labels=dict(MANAGED_BY)
        ),
        spec=client.V1ServiceSpec(
            cluster_ip="None",
            selector={"gnb": gnb},
            publish_not_ready_addresses=True,
            ports=[client.V1ServicePort(name="radio", protocol="UDP", port=4997,
                                        target_port=4997)],
        ),
    )


def _read_radio_service(v1, gnb: str, namespace: str):
    """The gNB's ``<gnb>-radio`` Service, or None if there is none (a bare gNB, or one made
    before the tools created it)."""
    from kubernetes.client.rest import ApiException

    try:
        return v1.read_namespaced_service(_radio_service_name(gnb), namespace)
    except ApiException as e:
        if e.status == 404:
            return None
        raise


def _delete_managed_radio_service(v1, gnb: str, namespace: str) -> None:
    """Delete the gNB's radio Service only if the create tools made it (infra/ owns its own)."""
    from kubernetes.client.rest import ApiException

    svc = _read_radio_service(v1, gnb, namespace)
    if svc is not None and (svc.metadata.labels or {}).items() >= MANAGED_BY.items():
        try:
            v1.delete_namespaced_service(_radio_service_name(gnb), namespace)
        except ApiException as e:
            if e.status != 404:
                raise


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
    """Create a new gNB in Kubernetes: a one-replica Deployment (strategy Recreate) plus its ConfigMap.

    Args:
        amf_address: AMF IP address
        amf_port: AMF port
        pod_name: Optional name of the gNB (Deployment and ConfigMap prefix; auto-generated if omitted)
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

        cfg = build_gnb_config(
            amf_address=amf_address, amf_port=amf_port,
            mcc=mcc, mnc=mnc, tac=tac, nci=nci, id_length=id_length,
            slice_sst=slice_sst, slice_sd=slice_sd,
            cell_access_type=cell_access_type,
            gtp_advertise_ip=gtp_advertise_ip,
            ignore_stream_ids=ignore_stream_ids,
        )
        v1 = get_k8s_client(kubeconfig=kubeconfig)
        apps = get_apps_client(kubeconfig=kubeconfig)
        v1.create_namespaced_config_map(
            namespace, _config_map(f"{pod_name}-config", namespace, "open5gs-gnb.yaml", cfg)
        )
        try:
            v1.create_namespaced_service(namespace, _radio_service(pod_name, namespace))
        except ApiException:
            v1.delete_namespaced_config_map(f"{pod_name}-config", namespace)  # a retry must not 409
            raise
        pod_spec = (
            client.V1PodSpec(
                image_pull_secrets=[client.V1LocalObjectReference(name=image_pull_secret)],
                containers=[client.V1Container(
                    name="gnb", image=gnb_image, image_pull_policy="IfNotPresent",
                    command=gnb_pod_command(),
                    security_context=client.V1SecurityContext(
                        capabilities=client.V1Capabilities(add=["NET_ADMIN"])
                    ),
                    volume_mounts=[_config_mount(GNB_CFG)],
                )],
                volumes=[client.V1Volume(
                    name="config",
                    config_map=client.V1ConfigMapVolumeSource(name=f"{pod_name}-config"),
                )],
            )
        )
        try:
            apps.create_namespaced_deployment(
                namespace=namespace,
                body=build_deployment(
                    pod_name, namespace, {"app": "ueransim", "type": "gnb", "gnb": pod_name},
                    pod_spec,
                ),
            )
        except ApiException:
            v1.delete_namespaced_service(_radio_service_name(pod_name), namespace)
            v1.delete_namespaced_config_map(f"{pod_name}-config", namespace)  # a retry must not 409
            raise

        if not wait_for_deployment_ready(apps, pod_name, namespace):
            return GnbCreateResponse(
                status="error", container_id=pod_name, container_name=pod_name,
                configuration=_empty_cfg(),
                message=f"Deployment {pod_name} did not become ready within 60s",
            )

        # The pod command replaces the __POD_IP__ placeholders with this IP.
        live_pod = resolve_pod_name(v1, apps, pod_name, namespace)
        pod_ip = v1.read_namespaced_pod(live_pod, namespace).status.pod_ip or ""

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
    """List all gNB pods in the given Kubernetes namespace (name is the Deployment name
    for pods the create tools made, id the current pod name).

    Args:
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        v1 = get_k8s_client(kubeconfig=kubeconfig)
        pods = v1.list_namespaced_pod(namespace, label_selector="type=gnb").items
        containers = [
            GnbContainer(id=p.metadata.name,
                         name=(p.metadata.labels or {}).get(WORKLOAD_LABEL, p.metadata.name),
                         status=p.status.phase or "Unknown",
                         created=str(p.metadata.creation_timestamp))
            for p in pods
            if not p.metadata.deletion_timestamp
        ]
        return GnbListResponse(status="success", containers=containers, count=len(containers))
    except ApiException as e:
        return GnbListResponse(status="error", containers=[], count=0,
                               message=f"Kubernetes API error: {e.reason} (status {e.status})")
    except Exception as e:
        return GnbListResponse(status="error", containers=[], count=0, message=str(e))


@mcp.tool()
def k8s_delete_gnb(pod_name: str, namespace: str = "ueransim", kubeconfig: str = "", confirm: bool = False) -> GnbOperationResponse:
    """Delete a gNB pod from Kubernetes.

    Args:
        pod_name: Name of the gNB/UE (its Deployment; a bare pod name also works)
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
        confirm: must be True to authorise the delete operation.
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException
    try:
        if not confirm:
            return GnbOperationResponse(
                status="error",
                message="Refusing to delete without explicit confirmation. Pass confirm=True to proceed.",
                container=pod_name,
            )
        validate_container_name(pod_name, "gnb")
        v1 = get_k8s_client(kubeconfig=kubeconfig)
        apps = get_apps_client(kubeconfig=kubeconfig)
        pod_name = workload_name(v1, apps, pod_name, namespace)
        deployment = read_deployment(apps, pod_name, namespace)
        if deployment is not None:
            apps.delete_namespaced_deployment(
                pod_name, namespace, body=client.V1DeleteOptions(propagation_policy="Foreground")
            )
            # Until it is gone, creating one with the same name gets a 409.
            if not wait_for_deployment_deleted(apps, pod_name, namespace):
                return GnbOperationResponse(
                    status="error", container=pod_name,
                    message=f"Deployment {pod_name} was still being deleted after 60s",
                )
            _delete_managed_config_map(v1, _template_pod(deployment), GNB_CFG)
            _delete_managed_radio_service(v1, pod_name, namespace)
            kind_name = "Deployment"
        else:
            pod = v1.read_namespaced_pod(pod_name, namespace)
            v1.delete_namespaced_pod(pod_name, namespace,
                                     body=client.V1DeleteOptions(grace_period_seconds=0))
            _delete_managed_config_map(v1, pod, GNB_CFG)
            _delete_managed_radio_service(v1, pod_name, namespace)
            kind_name = "Pod"
        return GnbOperationResponse(
            status="success",
            message=f"{kind_name} {pod_name} deleted from namespace {namespace}",
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
        pod_name: Name of the gNB/UE (its Deployment; a bare pod name also works)
        lines: Number of log lines to retrieve (default: 100)
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        validate_container_name(pod_name, "gnb")
        v1 = get_k8s_client(kubeconfig=kubeconfig)
        apps = get_apps_client(kubeconfig=kubeconfig)
        logs = read_pod_log(v1, resolve_pod_name(v1, apps, pod_name, namespace), namespace, lines)
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
    """Point a gNB at an AMF: update its ConfigMap and restart its Deployment (rollout restart).

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
        apps = get_apps_client(kubeconfig=kubeconfig)
        pod_name = workload_name(v1, apps, pod_name, namespace)

        def set_amf(cfg: dict) -> None:
            cfg["amfConfigs"][0]["address"] = amf_address

        if not _edit_pod_config(v1, apps, pod_name, namespace, GNB_CFG, set_amf):
            return GnbOperationResponse(
                status="error", container=pod_name,
                message=f"{pod_name} did not reach Running state after the restart",
            )
        time.sleep(2)
        running, status_out = _process_running(
            v1, resolve_pod_name(v1, apps, pod_name, namespace), namespace, "nr-gnb"
        )

        return GnbOperationResponse(
            status="success" if running else "warning",
            message=(f"Pod {pod_name} connected to core with AMF {amf_address}. "
                     f"{'nr-gnb restarted.' if running else 'nr-gnb is not running.'}"),
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
        pod_name: Name of the gNB/UE (its Deployment; a bare pod name also works)
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        v1 = get_k8s_client(kubeconfig=kubeconfig)
        apps = get_apps_client(kubeconfig=kubeconfig)
        pod_ip = v1.read_namespaced_pod(
            resolve_pod_name(v1, apps, pod_name, namespace), namespace
        ).status.pod_ip
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
    """Create a new UE in Kubernetes: a one-replica Deployment (strategy Recreate) plus its ConfigMap.

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

        cfg = build_ue_config(
            gnb_search_list=gnb_search_list, supi=supi, mcc=mcc, mnc=mnc,
            key=key, op=op, op_type=op_type,
            slice_sst=slice_sst, slice_sd=slice_sd,
            session_apn=session_apn, session_type=session_type,
            tun_netmask=tun_netmask,
        )
        v1 = get_k8s_client(kubeconfig=kubeconfig)
        apps = get_apps_client(kubeconfig=kubeconfig)
        v1.create_namespaced_config_map(
            namespace, _config_map(f"{pod_name}-config", namespace, "open5gs-ue.yaml", cfg)
        )
        pod_spec = (
            client.V1PodSpec(
                # Own network namespace, as the infra/ UE pools: with hostNetwork the UE's
                # uesimtun address lives on the node, and a UPF on the same node drops/keeps
                # the replies locally (no user-plane traffic) and its ip rules leak.
                image_pull_secrets=[client.V1LocalObjectReference(name=image_pull_secret)],
                containers=[client.V1Container(
                    name="ue", image=ue_image, image_pull_policy="IfNotPresent",
                    command=ue_pod_command(),
                    security_context=client.V1SecurityContext(
                        privileged=True,
                        capabilities=client.V1Capabilities(add=["NET_ADMIN"]),
                    ),
                    volume_mounts=[
                        client.V1VolumeMount(name="tun-device", mount_path="/dev/net/tun"),
                        _config_mount(UE_CFG),
                    ],
                )],
                volumes=[
                    client.V1Volume(
                        name="tun-device",
                        host_path=client.V1HostPathVolumeSource(
                            path="/dev/net/tun", type="CharDevice"
                        ),
                    ),
                    client.V1Volume(
                        name="config",
                        config_map=client.V1ConfigMapVolumeSource(name=f"{pod_name}-config"),
                    ),
                ],
            )
        )
        try:
            apps.create_namespaced_deployment(
                namespace=namespace,
                body=build_deployment(
                    pod_name, namespace, {"app": "ueransim", "type": "ue"}, pod_spec
                ),
            )
        except ApiException:
            v1.delete_namespaced_config_map(f"{pod_name}-config", namespace)  # a retry must not 409
            raise

        if not wait_for_deployment_ready(apps, pod_name, namespace):
            return UeCreateResponse(
                status="error", container_id=pod_name, container_name=pod_name,
                configuration=_empty_cfg(gnb_search_list),
                message=f"Deployment {pod_name} did not become ready within 60s",
            )

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
    """List all UE pods in the given Kubernetes namespace (name is the Deployment name
    for pods the create tools made, id the current pod name).

    Args:
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        v1 = get_k8s_client(kubeconfig=kubeconfig)
        pods = v1.list_namespaced_pod(namespace, label_selector="type=ue").items
        containers = [
            UeContainer(id=p.metadata.name,
                        name=(p.metadata.labels or {}).get(WORKLOAD_LABEL, p.metadata.name),
                        status=p.status.phase or "Unknown",
                        created=str(p.metadata.creation_timestamp))
            for p in pods
            if not p.metadata.deletion_timestamp
        ]
        return UeListResponse(status="success", containers=containers, count=len(containers))
    except ApiException as e:
        return UeListResponse(status="error", containers=[], count=0,
                              message=f"Kubernetes API error: {e.reason} (status {e.status})")
    except Exception as e:
        return UeListResponse(status="error", containers=[], count=0, message=str(e))


@mcp.tool()
def k8s_delete_ue(pod_name: str, namespace: str = "ueransim", kubeconfig: str = "", confirm: bool = False) -> UeOperationResponse:
    """Delete a UE pod from Kubernetes.

    Args:
        pod_name: Name of the gNB/UE (its Deployment; a bare pod name also works)
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
        confirm: must be True to authorise the delete operation.
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException
    try:
        if not confirm:
            return UeOperationResponse(
                status="error",
                message="Refusing to delete without explicit confirmation. Pass confirm=True to proceed.",
                container=pod_name,
            )
        validate_container_name(pod_name, "ue")
        v1 = get_k8s_client(kubeconfig=kubeconfig)
        apps = get_apps_client(kubeconfig=kubeconfig)
        pod_name = workload_name(v1, apps, pod_name, namespace)
        deployment = read_deployment(apps, pod_name, namespace)
        if deployment is not None:
            apps.delete_namespaced_deployment(
                pod_name, namespace, body=client.V1DeleteOptions(propagation_policy="Foreground")
            )
            # Until it is gone, creating one with the same name gets a 409.
            if not wait_for_deployment_deleted(apps, pod_name, namespace):
                return UeOperationResponse(
                    status="error", container=pod_name,
                    message=f"Deployment {pod_name} was still being deleted after 60s",
                )
            _delete_managed_config_map(v1, _template_pod(deployment), UE_CFG)
            kind_name = "Deployment"
        else:
            pod = v1.read_namespaced_pod(pod_name, namespace)
            v1.delete_namespaced_pod(pod_name, namespace,
                                     body=client.V1DeleteOptions(grace_period_seconds=0))
            _delete_managed_config_map(v1, pod, UE_CFG)
            kind_name = "Pod"
        return UeOperationResponse(
            status="success",
            message=f"{kind_name} {pod_name} deleted from namespace {namespace}",
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
        pod_name: Name of the gNB/UE (its Deployment; a bare pod name also works)
        lines: Number of log lines to retrieve (default: 100)
        namespace: Kubernetes namespace (default: ueransim)
        kubeconfig: path to a kubeconfig file. If omitted, uses the current kubectl context.
    """
    from kubernetes.client.rest import ApiException
    try:
        validate_container_name(pod_name, "ue")
        v1 = get_k8s_client(kubeconfig=kubeconfig)
        apps = get_apps_client(kubeconfig=kubeconfig)
        logs = read_pod_log(v1, resolve_pod_name(v1, apps, pod_name, namespace), namespace, lines)
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
    """Point a UE at a gNB: update its ConfigMap and restart its Deployment (rollout restart).

    The UE gets the gNB's ``<gnb>-radio.<namespace>.svc.cluster.local`` name when that Service
    exists (gNBs made by k8s_create_gnb), so it follows the gNB across restarts; else the pod IP.

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
        apps = get_apps_client(kubeconfig=kubeconfig)
        ue_pod_name = workload_name(v1, apps, ue_pod_name, namespace)

        gnb_ip_result = k8s_inspect_pod_ip(gnb_pod_name, namespace, kubeconfig=kubeconfig)
        if gnb_ip_result.status != "success" or not gnb_ip_result.logs:
            return UeOperationResponse(
                status="error",
                message=f"Could not determine IP for gNB pod {gnb_pod_name}: {gnb_ip_result.message}",
                container=ue_pod_name,
            )
        gnb_ip = gnb_ip_result.logs.strip()
        gnb_name = workload_name(v1, apps, gnb_pod_name, namespace)
        if _read_radio_service(v1, gnb_name, namespace) is not None:
            gnb_addr = f"{_radio_service_name(gnb_name)}.{namespace}.svc.cluster.local"
        else:
            gnb_addr = gnb_ip

        def set_gnb(cfg: dict) -> None:
            cfg["gnbSearchList"] = [gnb_addr]

        if not _edit_pod_config(v1, apps, ue_pod_name, namespace, UE_CFG, set_gnb):
            return UeOperationResponse(
                status="error", container=ue_pod_name,
                message=f"{ue_pod_name} did not reach Running state after the restart",
            )
        time.sleep(3)

        gnb_ok, gnb_out = _process_running(
            v1, resolve_pod_name(v1, apps, gnb_pod_name, namespace), namespace, "nr-gnb"
        )
        ue_ok, ue_out = _process_running(
            v1, resolve_pod_name(v1, apps, ue_pod_name, namespace), namespace, "nr-ue"
        )
        details = [
            "gNB: nr-gnb active" if gnb_ok else "gNB: nr-gnb not running",
            "UE: nr-ue active"   if ue_ok  else "UE: nr-ue not running",
        ]

        return UeOperationResponse(
            status="success" if (gnb_ok and ue_ok) else "warning",
            message=(f"UE pod {ue_pod_name} attached to gNB pod {gnb_pod_name}"
                     f" (gNB address: {gnb_addr}). {'; '.join(details)}"),
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
    """Edit one configuration field of a gNB/UE: update its ConfigMap and restart its Deployment.

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
        apps = get_apps_client(kubeconfig=kubeconfig)
        ctype = _pod_type(pod_name)
        # Dry-run on the template to reject an unsupported field before touching the pod.
        if ctype == "unknown" or not apply_config_edit(load_template(ctype), ctype,
                                                       config_type, config_value):
            return UeOperationResponse(
                status="error",
                message=(f"Unsupported config_type '{config_type}' for pod type '{ctype}'."
                         " Check the docstring for valid types."),
                container=pod_name,
            )

        cfg_path = GNB_CFG if ctype == "gnb" else UE_CFG
        pod_name = workload_name(v1, apps, pod_name, namespace)
        running = _edit_pod_config(
            v1, apps, pod_name, namespace, cfg_path,
            lambda cfg: apply_config_edit(cfg, ctype, config_type, config_value),
        )
        return UeOperationResponse(
            status="success" if running else "error",
            message=(f"Pod {pod_name} updated: {config_type}={config_value}"
                     if running else f"{pod_name} did not reach Running state after the restart"),
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

