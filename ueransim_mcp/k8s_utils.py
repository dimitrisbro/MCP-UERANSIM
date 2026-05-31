import time
from typing import List


def get_k8s_client():
    """Return a CoreV1Api client, trying in-cluster config then local kubeconfig."""
    from kubernetes import client, config
    from kubernetes.config.config_exception import ConfigException

    try:
        config.load_incluster_config()
    except ConfigException:
        config.load_kube_config()

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
