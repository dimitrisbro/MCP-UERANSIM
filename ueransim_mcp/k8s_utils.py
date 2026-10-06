import time
from typing import List


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
