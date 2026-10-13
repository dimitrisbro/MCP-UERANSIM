import time
from typing import List, Optional


def _load_k8s_config(kubeconfig: str = "") -> None:
    from kubernetes import config
    from kubernetes.config.config_exception import ConfigException

    if kubeconfig:
        config.load_kube_config(config_file=kubeconfig)
        return
    try:
        config.load_incluster_config()
    except ConfigException:
        config.load_kube_config()


def get_k8s_client(kubeconfig: str = ""):
    """Return a CoreV1Api client. kubeconfig overrides in-cluster/default context."""
    from kubernetes import client

    _load_k8s_config(kubeconfig)
    return client.CoreV1Api()


def get_apps_client(kubeconfig: str = ""):
    """Return an AppsV1Api client (same config resolution as get_k8s_client)."""
    from kubernetes import client

    _load_k8s_config(kubeconfig)
    return client.AppsV1Api()


def exec_in_pod(v1, pod_name: str, namespace: str, command: List[str]) -> tuple:
    """Execute a command inside a running pod and return (stdout, stderr)."""
    from kubernetes.stream import stream

    resp = stream(
        v1.connect_get_namespaced_pod_exec,
        pod_name,
        namespace,
        command=command,
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
    )
    return resp, ""


def wait_for_pod_running(v1, pod_name: str, namespace: str, timeout: int = 60) -> bool:
    """Poll until the pod is Running or timeout (seconds) expires."""
    for _ in range(timeout):
        try:
            pod = v1.read_namespaced_pod(pod_name, namespace)
            if pod.status.phase == "Running":
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


MANAGED_BY = {"app.kubernetes.io/managed-by": "ueransim-mcp"}
# Selects the pods of one tool-created gNB/UE Deployment (pod names carry a hash suffix).
WORKLOAD_LABEL = "ueransim-mcp/workload"
RESTARTED_AT = "kubectl.kubernetes.io/restartedAt"


def pod_config_map(pod, cfg_path: str) -> tuple:
    """Return (ConfigMap name, key) behind the pod's config file at cfg_path.

    Raises ValueError if cfg_path isn't mounted from a ConfigMap with a subPath.
    """
    mount = next(
        (m for c in pod.spec.containers for m in (c.volume_mounts or [])
         if m.mount_path == cfg_path and m.sub_path),
        None,
    )
    volume = mount and next((v for v in pod.spec.volumes or [] if v.name == mount.name), None)
    if not volume or not volume.config_map:
        raise ValueError(
            f"Pod {pod.metadata.name} does not mount {cfg_path} from a ConfigMap; "
            "recreate it with k8s_create_gnb/k8s_create_ue."
        )
    return volume.config_map.name, mount.sub_path


def wait_for_pod_deleted(v1, pod_name: str, namespace: str, timeout: int = 60) -> bool:
    """Poll until the pod no longer exists or timeout (seconds) expires."""
    from kubernetes.client.rest import ApiException

    for _ in range(timeout):
        try:
            v1.read_namespaced_pod(pod_name, namespace)
        except ApiException as e:
            if e.status == 404:
                return True
            raise
        time.sleep(1)
    return False


def recreate_pod(v1, pod, timeout: int = 60) -> bool:
    """Delete a bare pod and create it again with the same spec, so it re-reads its
    ConfigMap (subPath mounts never pick up ConfigMap changes in place).
    Returns True once the new pod is Running.
    """
    from kubernetes import client

    name, namespace = pod.metadata.name, pod.metadata.namespace
    body = client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=name, namespace=namespace,
            labels=pod.metadata.labels, annotations=pod.metadata.annotations,
        ),
        spec=pod.spec,
    )
    v1.delete_namespaced_pod(name, namespace, body=client.V1DeleteOptions(grace_period_seconds=0))
    if not wait_for_pod_deleted(v1, name, namespace, timeout):
        raise TimeoutError(f"Pod {name} was not deleted within {timeout}s")
    v1.create_namespaced_pod(namespace=namespace, body=body)
    return wait_for_pod_running(v1, name, namespace, timeout)


def read_pod_log(v1, pod_name: str, namespace: str, lines: int) -> str:
    """Return the pod's last log lines as text.

    The kubernetes client (36.x) returns str(bytes), i.e. "b'...'", for preloaded
    log content, so read the raw response and decode it.
    """
    resp = v1.read_namespaced_pod_log(
        pod_name, namespace, tail_lines=lines, _preload_content=False
    )
    return resp.data.decode("utf-8", errors="replace")


def build_deployment(name: str, namespace: str, labels: dict, pod_spec):
    """A one-replica Deployment named ``name`` for a gNB/UE pod spec.

    ``strategy: Recreate`` stops the old pod before the new one starts, so two gNBs with the
    same NCI never connect to the AMF at once. ``labels`` (e.g. app, type) go on the pod
    template, plus WORKLOAD_LABEL=name, which is the Deployment's selector.
    """
    from kubernetes import client

    pod_labels = {**labels, WORKLOAD_LABEL: name}
    return client.V1Deployment(
        metadata=client.V1ObjectMeta(name=name, namespace=namespace, labels=dict(MANAGED_BY)),
        spec=client.V1DeploymentSpec(
            replicas=1,
            strategy=client.V1DeploymentStrategy(type="Recreate"),
            selector=client.V1LabelSelector(match_labels={WORKLOAD_LABEL: name}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=pod_labels), spec=pod_spec
            ),
        ),
    )


def read_deployment(apps, name: str, namespace: str):
    """The Deployment ``name``, or None if there is none (a bare pod made by infra/ or an
    older tool version)."""
    from kubernetes.client.rest import ApiException

    try:
        return apps.read_namespaced_deployment(name, namespace)
    except ApiException as e:
        if e.status == 404:
            return None
        raise


def deployment_pod_name(v1, deployment) -> Optional[str]:
    """The newest live pod behind a Deployment's label selector, or None."""
    selector = ",".join(f"{k}={v}" for k, v in deployment.spec.selector.match_labels.items())
    pods = v1.list_namespaced_pod(deployment.metadata.namespace, label_selector=selector).items
    live = [p for p in pods if not p.metadata.deletion_timestamp]
    live.sort(key=lambda p: (p.status.phase == "Running", str(p.metadata.creation_timestamp)))
    return live[-1].metadata.name if live else None


def resolve_pod_name(v1, apps, name: str, namespace: str) -> str:
    """Map a tool's ``pod_name`` to a real pod: the Deployment's current pod, else ``name``."""
    deployment = read_deployment(apps, name, namespace)
    if deployment is None:
        return name
    return deployment_pod_name(v1, deployment) or name


def wait_for_deployment_ready(apps, name: str, namespace: str, timeout: int = 60) -> bool:
    """Poll until the Deployment's rollout is done (one updated, ready replica, no old ones)."""
    for _ in range(timeout):
        try:
            d = apps.read_namespaced_deployment_status(name, namespace)
            want = d.spec.replicas
            st = d.status
            if (
                (st.observed_generation or 0) >= (d.metadata.generation or 0)
                and (st.updated_replicas or 0) == want
                and (st.ready_replicas or 0) == want
                and (st.replicas or 0) == want
            ):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def rollout_restart(apps, name: str, namespace: str) -> None:
    """``kubectl rollout restart``: stamp the pod template so the Deployment replaces its pod,
    which re-reads its ConfigMap (subPath mounts never pick up ConfigMap changes in place)."""
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).isoformat()
    apps.patch_namespaced_deployment(
        name, namespace,
        {"spec": {"template": {"metadata": {"annotations": {RESTARTED_AT: stamp}}}}},
    )
