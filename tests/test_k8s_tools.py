"""K8s gNB/UE tools: nr-gnb/nr-ue run as PID 1 in a one-replica Deployment (strategy Recreate) and
take config from a ConfigMap; attach/edit change the ConfigMap and roll the Deployment (#4).
A bare pod (made by infra/ or an older version) is still recreated."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml
from kubernetes import client
from kubernetes.client.rest import ApiException

from ueransim_mcp import k8s_tools
from ueransim_mcp.config_ops import (
    GNB_CFG, POD_IP_PLACEHOLDER, UE_CFG, apply_config_edit, build_gnb_config,
    build_ue_config, gnb_pod_command, load_template, ue_pod_command,
)
from ueransim_mcp.k8s_utils import (
    MANAGED_BY, RESTARTED_AT, WORKLOAD_LABEL, deployment_pod_name, pod_config_map,
    resolve_pod_name, wait_for_deployment_deleted, wait_for_deployment_ready,
)

GNB_ARGS = dict(
    amf_address="10.0.0.5", amf_port="30412", mcc="001", mnc="01", tac=100,
    nci="0x000000001", id_length=32, slice_sst=1, slice_sd=None, cell_access_type="nr",
    gtp_advertise_ip=None, ignore_stream_ids=True,
)
UE_ARGS = dict(
    gnb_search_list="10.0.0.9", supi="imsi-001010000000001", mcc="001", mnc="01",
    key=None, op=None, op_type="OPC", slice_sst=2, slice_sd=None,
    session_apn="internet", session_type="IPv4", tun_netmask="255.255.255.0",
)


# ── pod commands ──────────────────────────────────────────────────────────────

def test_gnb_command_renders_pod_ip_then_execs_nr_gnb() -> None:
    script = gnb_pod_command()[-1]
    assert gnb_pod_command()[:2] == ["sh", "-c"]
    assert f"s/{POD_IP_PLACEHOLDER}/$(hostname -i)/g" in script
    assert script.endswith("exec /usr/local/bin/nr-gnb -c /tmp/gnb.yaml")
    assert "tail" not in script


def test_ue_command_runs_nr_ue_on_the_mounted_config() -> None:
    assert ue_pod_command() == ["/usr/local/bin/nr-ue", "-c", UE_CFG]


# ── config building and edits ─────────────────────────────────────────────────

def test_gnb_config_uses_pod_ip_placeholders_and_keeps_string_codes() -> None:
    cfg = yaml.safe_load(yaml.safe_dump(build_gnb_config(**GNB_ARGS)))
    assert cfg["linkIp"] == cfg["ngapIp"] == cfg["gtpIp"] == POD_IP_PLACEHOLDER
    assert cfg["amfConfigs"] == [{"address": "10.0.0.5", "port": 30412}]
    assert cfg["mcc"] == "001" and cfg["mnc"] == "01"
    assert cfg["slices"] == [{"sst": 1}]
    assert "gtpAdvertiseIp" not in cfg


def test_gnb_config_sets_sd_and_gtp_advertise_ip_when_given() -> None:
    cfg = build_gnb_config(**{**GNB_ARGS, "slice_sd": 5, "gtp_advertise_ip": "1.2.3.4"})
    assert cfg["slices"] == [{"sst": 1, "sd": 5}]
    assert cfg["gtpAdvertiseIp"] == "1.2.3.4"


def test_ue_config_sets_the_slice_in_every_section() -> None:
    cfg = build_ue_config(**UE_ARGS)
    assert cfg["gnbSearchList"] == ["10.0.0.9"]
    assert cfg["sessions"][0]["slice"] == {"sst": 2}
    assert cfg["configured-nssai"] == cfg["default-nssai"] == [{"sst": 2}]
    assert cfg["supi"] == "imsi-001010000000001"


@pytest.mark.parametrize(
    "ctype, config_type, value, path, expected",
    [
        ("gnb", "amf_ip", "10.1.1.1", ("amfConfigs", 0, "address"), "10.1.1.1"),
        ("gnb", "tac", "7", ("tac",), 7),
        ("gnb", "ignore_stream_ids", "false", ("ignoreStreamIds",), False),
        ("gnb", "slice", "3,9", ("slices",), [{"sst": 3, "sd": 9}]),
        ("ue", "gnb_search_list", "10.2.2.2", ("gnbSearchList",), ["10.2.2.2"]),
        ("ue", "session_apn", "ims", ("sessions", 0, "apn"), "ims"),
        ("ue", "slice", "3", ("default-nssai",), [{"sst": 3}]),
    ],
)
def test_apply_config_edit(ctype, config_type, value, path, expected) -> None:
    cfg = load_template(ctype)
    assert apply_config_edit(cfg, ctype, config_type, value)
    for step in path:
        cfg = cfg[step]
    assert cfg == expected


def test_apply_config_edit_rejects_fields_of_the_other_pod_type() -> None:
    assert not apply_config_edit(load_template("gnb"), "gnb", "supi", "imsi-1")
    assert not apply_config_edit(load_template("ue"), "ue", "amf_ip", "10.0.0.1")


# ── tools against a mocked Kubernetes API ─────────────────────────────────────

def _pod(name: str, cfg_path: str, cm_name: str | None):
    mounts, volumes = [], []
    if cm_name:
        mounts = [client.V1VolumeMount(name="config", mount_path=cfg_path,
                                       sub_path=cfg_path.rsplit("/", 1)[1])]
        volumes = [client.V1Volume(name="config",
                                   config_map=client.V1ConfigMapVolumeSource(name=cm_name))]
    return client.V1Pod(
        metadata=client.V1ObjectMeta(name=name, namespace="net-demo", labels={"type": "gnb"}),
        spec=client.V1PodSpec(containers=[client.V1Container(name="c", volume_mounts=mounts)],
                              volumes=volumes),
        status=client.V1PodStatus(phase="Running", pod_ip="10.0.0.20"),
    )


def _deployment(name: str, cfg_path: str, cm_name: str, ns: str = "net-demo"):
    pod = _pod(name, cfg_path, cm_name)
    return client.V1Deployment(
        metadata=client.V1ObjectMeta(name=name, namespace=ns),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={WORKLOAD_LABEL: name}),
            template=client.V1PodTemplateSpec(spec=pod.spec),
        ),
    )


@pytest.fixture
def v1():
    api = MagicMock()
    api.read_namespaced_service.side_effect = ApiException(status=404)  # no <gnb>-radio Service
    with patch.object(k8s_tools, "get_k8s_client", return_value=api), \
         patch.object(k8s_tools.time, "sleep"):
        yield api


@pytest.fixture
def apps():
    """AppsV1Api: no Deployment exists unless a test sets read_namespaced_deployment."""
    api = MagicMock()
    api.read_namespaced_deployment.side_effect = ApiException(status=404)
    with patch.object(k8s_tools, "get_apps_client", return_value=api), \
         patch.object(k8s_tools, "wait_for_deployment_ready", return_value=True), \
         patch.object(k8s_tools, "wait_for_deployment_deleted", return_value=True):
        yield api


def _live_pod(v1, name: str, pod_name: str) -> None:
    """The Deployment's current pod: found by label selector, name carries a hash suffix."""
    pod = _pod(pod_name, GNB_CFG, f"{name}-config")
    v1.list_namespaced_pod.return_value = SimpleNamespace(items=[pod])
    v1.read_namespaced_pod.return_value = pod


def test_create_gnb_makes_a_recreate_deployment_from_its_own_config_map(v1, apps) -> None:
    apps.read_namespaced_deployment.side_effect = None
    apps.read_namespaced_deployment.return_value = _deployment("gnb-x", GNB_CFG, "gnb-x-config")
    _live_pod(v1, "gnb-x", "gnb-x-7d9f-abcde")

    result = k8s_tools.k8s_create_gnb(amf_address="10.0.0.5", pod_name="gnb-x",
                                      namespace="net-demo")

    assert result.status == "success"
    assert result.configuration.gtp_ip == "10.0.0.20"
    _, cm = v1.create_namespaced_config_map.call_args.args
    assert cm.metadata.name == "gnb-x-config" and cm.metadata.labels == MANAGED_BY
    assert yaml.safe_load(cm.data["open5gs-gnb.yaml"])["amfConfigs"][0]["address"] == "10.0.0.5"
    deployment = apps.create_namespaced_deployment.call_args.kwargs["body"]
    assert deployment.metadata.name == "gnb-x"
    assert deployment.spec.replicas == 1
    assert deployment.spec.strategy.type == "Recreate"
    assert deployment.spec.selector.match_labels == {WORKLOAD_LABEL: "gnb-x"}
    labels = deployment.spec.template.metadata.labels
    assert labels == {"app": "ueransim", "type": "gnb", "gnb": "gnb-x", WORKLOAD_LABEL: "gnb-x"}
    container = deployment.spec.template.spec.containers[0]
    assert container.command == gnb_pod_command()
    assert (container.volume_mounts[0].mount_path, container.volume_mounts[0].sub_path) == (
        GNB_CFG, "open5gs-gnb.yaml")
    assert deployment.spec.template.spec.volumes[0].config_map.name == "gnb-x-config"
    ns, svc = v1.create_namespaced_service.call_args.args
    assert ns == "net-demo"
    assert svc.metadata.name == "gnb-x-radio" and svc.metadata.labels == MANAGED_BY
    assert svc.spec.cluster_ip == "None" and svc.spec.publish_not_ready_addresses is True
    assert svc.spec.selector == {"gnb": "gnb-x"}
    assert (svc.spec.ports[0].protocol, svc.spec.ports[0].port) == ("UDP", 4997)
    v1.create_namespaced_pod.assert_not_called()
    v1.connect_get_namespaced_pod_exec.assert_not_called()


def test_create_ue_makes_a_recreate_deployment_from_its_own_config_map(v1, apps) -> None:
    result = k8s_tools.k8s_create_ue(gnb_search_list="10.0.0.9", pod_name="ue-x",
                                     namespace="net-demo")

    assert result.status == "success"
    _, cm = v1.create_namespaced_config_map.call_args.args
    assert yaml.safe_load(cm.data["open5gs-ue.yaml"])["gnbSearchList"] == ["10.0.0.9"]
    deployment = apps.create_namespaced_deployment.call_args.kwargs["body"]
    assert deployment.spec.strategy.type == "Recreate" and deployment.spec.replicas == 1
    assert deployment.spec.template.metadata.labels["type"] == "ue"
    spec = deployment.spec.template.spec
    container = spec.containers[0]
    assert not spec.host_network
    assert container.security_context.privileged
    assert "/dev/net/tun" in [m.mount_path for m in container.volume_mounts]
    assert container.command == ue_pod_command()
    assert UE_CFG in [m.mount_path for m in container.volume_mounts]
    v1.create_namespaced_pod.assert_not_called()


def test_create_reports_a_deployment_that_never_gets_ready(v1, apps) -> None:
    with patch.object(k8s_tools, "wait_for_deployment_ready", return_value=False):
        result = k8s_tools.k8s_create_ue(gnb_search_list="10.0.0.9", pod_name="ue-x")

    assert result.status == "error" and "ue-x" in result.message


def test_attach_gnb_patches_the_config_map_and_rolls_the_deployment(v1, apps) -> None:
    apps.read_namespaced_deployment.side_effect = None
    apps.read_namespaced_deployment.return_value = _deployment("gnb-1a", GNB_CFG, "gnb-1a-config")
    _live_pod(v1, "gnb-1a", "gnb-1a-6c7d-xyz12")
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        data={"open5gs-gnb.yaml": yaml.safe_dump(build_gnb_config(**GNB_ARGS))})

    with patch.object(k8s_tools, "exec_in_pod",
                      return_value=("nr-gnb is running", "")) as exec_mock:
        result = k8s_tools.k8s_attach_gnb_to_core("gnb-1a", amf_address="10.9.9.9",
                                                  namespace="net-demo")

    assert result.status == "success"
    name, ns, body = v1.patch_namespaced_config_map.call_args.args
    assert (name, ns) == ("gnb-1a-config", "net-demo")
    assert yaml.safe_load(body["data"]["open5gs-gnb.yaml"])["amfConfigs"][0]["address"] == "10.9.9.9"
    name, ns, patch_body = apps.patch_namespaced_deployment.call_args.args
    assert (name, ns) == ("gnb-1a", "net-demo")
    assert RESTARTED_AT in patch_body["spec"]["template"]["metadata"]["annotations"]
    v1.delete_namespaced_pod.assert_not_called()
    v1.create_namespaced_pod.assert_not_called()
    assert exec_mock.call_args.args[1] == "gnb-1a-6c7d-xyz12"
    assert "pgrep -x nr-gnb" in exec_mock.call_args.args[3][-1]


def test_attach_ue_rolls_the_ue_deployment_with_the_gnb_pod_ip(v1, apps) -> None:
    ue_dep = _deployment("ue-1", UE_CFG, "ue-1-config")
    gnb_dep = _deployment("gnb-1a", GNB_CFG, "gnb-1a-config")
    apps.read_namespaced_deployment.side_effect = lambda n, ns: {"ue-1": ue_dep,
                                                                  "gnb-1a": gnb_dep}[n]
    v1.list_namespaced_pod.return_value = SimpleNamespace(items=[_pod("p-x", UE_CFG, "ue-1-config")])
    v1.read_namespaced_pod.return_value = _pod("p-x", UE_CFG, "ue-1-config")
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        data={"open5gs-ue.yaml": yaml.safe_dump(build_ue_config(**UE_ARGS))})

    with patch.object(k8s_tools, "exec_in_pod", side_effect=[
        ("nr-gnb is running", ""), ("nr-ue is running", ""),
    ]):
        result = k8s_tools.k8s_attach_ue_to_gnb("ue-1", "gnb-1a", namespace="net-demo")

    assert result.status == "success"
    _, _, body = v1.patch_namespaced_config_map.call_args.args
    assert yaml.safe_load(body["data"]["open5gs-ue.yaml"])["gnbSearchList"] == ["10.0.0.20"]
    assert apps.patch_namespaced_deployment.call_args.args[0] == "ue-1"
    v1.delete_namespaced_pod.assert_not_called()


def test_edit_pod_config_rolls_the_deployment(v1, apps) -> None:
    apps.read_namespaced_deployment.side_effect = None
    apps.read_namespaced_deployment.return_value = _deployment("gnb-1a", GNB_CFG, "gnb-1a-config")
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        data={"open5gs-gnb.yaml": yaml.safe_dump(build_gnb_config(**GNB_ARGS))})

    result = k8s_tools.k8s_edit_pod_config("gnb-1a", "tac", "7", namespace="net-demo")

    assert result.status == "success"
    apps.patch_namespaced_deployment.assert_called_once()
    v1.delete_namespaced_pod.assert_not_called()


def test_attach_gnb_still_recreates_a_bare_pod(v1, apps) -> None:
    pod = _pod("gnb-1a", GNB_CFG, "gnb-1a-config")
    # reads: workload_name (no owning Deployment), the tool, wait_for_pod_deleted sees it gone.
    v1.read_namespaced_pod.side_effect = [pod, pod, ApiException(status=404)]
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        data={"open5gs-gnb.yaml": yaml.safe_dump(build_gnb_config(**GNB_ARGS))})

    with patch.object(k8s_tools, "exec_in_pod", return_value=("nr-gnb is running", "")), \
         patch("ueransim_mcp.k8s_utils.wait_for_pod_running", return_value=True):
        result = k8s_tools.k8s_attach_gnb_to_core("gnb-1a", amf_address="10.9.9.9",
                                                  namespace="net-demo")

    assert result.status == "success"
    v1.delete_namespaced_pod.assert_called_once()
    apps.patch_namespaced_deployment.assert_not_called()
    recreated = v1.create_namespaced_pod.call_args.kwargs["body"]
    assert recreated.metadata.name == "gnb-1a" and recreated.spec is pod.spec


def test_attach_gnb_reports_a_stopped_process(v1, apps) -> None:
    apps.read_namespaced_deployment.side_effect = None
    apps.read_namespaced_deployment.return_value = _deployment("gnb-1a", GNB_CFG, "gnb-1a-config")
    _live_pod(v1, "gnb-1a", "gnb-1a-x")
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        data={"open5gs-gnb.yaml": yaml.safe_dump(build_gnb_config(**GNB_ARGS))})

    with patch.object(k8s_tools, "exec_in_pod", return_value=("nr-gnb not found", "")):
        result = k8s_tools.k8s_attach_gnb_to_core("gnb-1a", amf_address="10.9.9.9")

    assert result.status == "warning"


def test_attach_refuses_a_pod_without_a_config_map(v1, apps) -> None:
    v1.read_namespaced_pod.return_value = _pod("gnb-old", GNB_CFG, None)

    result = k8s_tools.k8s_attach_gnb_to_core("gnb-old", amf_address="10.9.9.9")

    assert result.status == "error" and "ConfigMap" in result.message
    v1.delete_namespaced_pod.assert_not_called()


def test_edit_rejects_an_unsupported_field_before_touching_the_pod(v1, apps) -> None:
    result = k8s_tools.k8s_edit_pod_config("gnb-1a", config_type="supi", config_value="x")

    assert result.status == "error"
    v1.read_namespaced_pod.assert_not_called()


def test_attach_ue_writes_the_gnb_radio_service_name_when_it_exists(v1, apps) -> None:
    v1.read_namespaced_service.side_effect = None
    ue_dep = _deployment("ue-1", UE_CFG, "ue-1-config")
    gnb_dep = _deployment("gnb-1a", GNB_CFG, "gnb-1a-config")
    apps.read_namespaced_deployment.side_effect = lambda n, ns: {"ue-1": ue_dep,
                                                                  "gnb-1a": gnb_dep}[n]
    v1.list_namespaced_pod.return_value = SimpleNamespace(items=[_pod("p-x", UE_CFG, "ue-1-config")])
    v1.read_namespaced_pod.return_value = _pod("p-x", UE_CFG, "ue-1-config")
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        data={"open5gs-ue.yaml": yaml.safe_dump(build_ue_config(**UE_ARGS))})

    with patch.object(k8s_tools, "exec_in_pod", side_effect=[
        ("nr-gnb is running", ""), ("nr-ue is running", ""),
    ]):
        result = k8s_tools.k8s_attach_ue_to_gnb("ue-1", "gnb-1a", namespace="net-demo")

    assert result.status == "success"
    v1.read_namespaced_service.assert_called_with("gnb-1a-radio", "net-demo")
    _, _, body = v1.patch_namespaced_config_map.call_args.args
    assert yaml.safe_load(body["data"]["open5gs-ue.yaml"])["gnbSearchList"] == [
        "gnb-1a-radio.net-demo.svc.cluster.local"]


def test_attach_ue_by_radio_service_needs_no_gnb_pod_ip(v1, apps) -> None:
    v1.read_namespaced_service.side_effect = None
    ue_dep = _deployment("ue-1", UE_CFG, "ue-1-config")
    gnb_dep = _deployment("gnb-1a", GNB_CFG, "gnb-1a-config")
    apps.read_namespaced_deployment.side_effect = lambda n, ns: {"ue-1": ue_dep,
                                                                  "gnb-1a": gnb_dep}[n]
    v1.list_namespaced_pod.return_value = SimpleNamespace(items=[_pod("p-x", UE_CFG, "ue-1-config")])
    v1.read_namespaced_pod.return_value = _pod("p-x", UE_CFG, "ue-1-config")
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        data={"open5gs-ue.yaml": yaml.safe_dump(build_ue_config(**UE_ARGS))})

    with patch.object(k8s_tools, "k8s_inspect_pod_ip") as inspect, \
         patch.object(k8s_tools, "exec_in_pod", side_effect=[
             ("nr-gnb is running", ""), ("nr-ue is running", ""),
         ]):
        result = k8s_tools.k8s_attach_ue_to_gnb("ue-1", "gnb-1a", namespace="net-demo")

    assert result.status == "success"
    inspect.assert_not_called()


@pytest.mark.parametrize("labels, deleted", [(MANAGED_BY, True), ({}, False)])
def test_delete_gnb_removes_only_a_tool_made_radio_service(v1, apps, labels, deleted) -> None:
    apps.read_namespaced_deployment.side_effect = None
    apps.read_namespaced_deployment.return_value = _deployment("gnb-x", GNB_CFG, "gnb-x-config")
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        metadata=SimpleNamespace(labels={}))
    v1.read_namespaced_service.side_effect = None
    v1.read_namespaced_service.return_value = SimpleNamespace(
        metadata=SimpleNamespace(labels=labels))

    result = k8s_tools.k8s_delete_gnb("gnb-x", namespace="net-demo", confirm=True)

    assert result.status == "success"
    assert v1.delete_namespaced_service.called is deleted
    if deleted:
        v1.delete_namespaced_service.assert_called_once_with("gnb-x-radio", "net-demo")


@pytest.mark.parametrize("labels, deleted", [(MANAGED_BY, True), ({}, False)])
def test_delete_gnb_removes_the_deployment_and_only_config_maps_the_tools_created(
    v1, apps, labels, deleted
) -> None:
    apps.read_namespaced_deployment.side_effect = None
    apps.read_namespaced_deployment.return_value = _deployment("gnb-x", GNB_CFG, "gnb-x-config")
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        metadata=SimpleNamespace(labels=labels))

    result = k8s_tools.k8s_delete_gnb("gnb-x", namespace="net-demo", confirm=True)

    assert result.status == "success"
    assert apps.delete_namespaced_deployment.call_args.args[:2] == ("gnb-x", "net-demo")
    v1.delete_namespaced_pod.assert_not_called()
    assert v1.delete_namespaced_config_map.called is deleted


def test_delete_ue_removes_the_deployment(v1, apps) -> None:
    apps.read_namespaced_deployment.side_effect = None
    apps.read_namespaced_deployment.return_value = _deployment("ue-x", UE_CFG, "ue-x-config")
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        metadata=SimpleNamespace(labels=MANAGED_BY))

    result = k8s_tools.k8s_delete_ue("ue-x", namespace="net-demo", confirm=True)

    assert result.status == "success"
    apps.delete_namespaced_deployment.assert_called_once()
    v1.delete_namespaced_config_map.assert_called_once()


def test_delete_still_removes_a_bare_pod(v1, apps) -> None:
    v1.read_namespaced_pod.return_value = _pod("gnb-old", GNB_CFG, "gnb-old-config")
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        metadata=SimpleNamespace(labels={}))

    result = k8s_tools.k8s_delete_gnb("gnb-old", namespace="net-demo", confirm=True)

    assert result.status == "success"
    v1.delete_namespaced_pod.assert_called_once()
    apps.delete_namespaced_deployment.assert_not_called()


def _owned_pod(pod_name: str, workload: str, cfg_path: str = GNB_CFG):
    """A pod of a tool-made Deployment, as a pod name (hash suffix) finds it."""
    pod = _pod(pod_name, cfg_path, f"{workload}-config")
    pod.metadata.labels = {"type": "gnb", WORKLOAD_LABEL: workload}
    return pod


def _only_deployment(dep):
    """read_namespaced_deployment: ``dep`` by its name, 404 for anything else (a pod name)."""
    def read(name, namespace):
        if name != dep.metadata.name:
            raise ApiException(status=404)
        return dep
    return read


def test_delete_by_pod_name_removes_the_deployment_not_the_pod(v1, apps) -> None:
    dep = _deployment("gnb-x", GNB_CFG, "gnb-x-config")
    apps.read_namespaced_deployment.side_effect = _only_deployment(dep)
    v1.read_namespaced_pod.return_value = _owned_pod("gnb-x-7d9f-abcde", "gnb-x")
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        metadata=SimpleNamespace(labels=MANAGED_BY))

    result = k8s_tools.k8s_delete_gnb("gnb-x-7d9f-abcde", namespace="net-demo", confirm=True)

    assert result.status == "success"
    assert apps.delete_namespaced_deployment.call_args.args[:2] == ("gnb-x", "net-demo")
    v1.delete_namespaced_pod.assert_not_called()


def test_attach_by_pod_name_rolls_the_deployment_and_never_recreates_the_pod(v1, apps) -> None:
    dep = _deployment("gnb-1a", GNB_CFG, "gnb-1a-config")
    apps.read_namespaced_deployment.side_effect = _only_deployment(dep)
    pod = _owned_pod("gnb-1a-6c7d-xyz12", "gnb-1a")
    v1.read_namespaced_pod.return_value = pod
    v1.list_namespaced_pod.return_value = SimpleNamespace(items=[pod])
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        data={"open5gs-gnb.yaml": yaml.safe_dump(build_gnb_config(**GNB_ARGS))})

    with patch.object(k8s_tools, "exec_in_pod", return_value=("nr-gnb is running", "")):
        result = k8s_tools.k8s_attach_gnb_to_core("gnb-1a-6c7d-xyz12", amf_address="10.9.9.9",
                                                  namespace="net-demo")

    assert result.status == "success"
    assert apps.patch_namespaced_deployment.call_args.args[:2] == ("gnb-1a", "net-demo")
    v1.delete_namespaced_pod.assert_not_called()
    v1.create_namespaced_pod.assert_not_called()


def test_delete_reports_a_deployment_still_being_deleted(v1, apps) -> None:
    apps.read_namespaced_deployment.side_effect = None
    apps.read_namespaced_deployment.return_value = _deployment("gnb-x", GNB_CFG, "gnb-x-config")

    with patch.object(k8s_tools, "wait_for_deployment_deleted", return_value=False):
        result = k8s_tools.k8s_delete_gnb("gnb-x", namespace="net-demo", confirm=True)

    assert result.status == "error" and "still being deleted" in result.message
    v1.delete_namespaced_config_map.assert_not_called()


def test_wait_for_deployment_deleted_waits_for_the_404() -> None:
    apps = MagicMock()
    apps.read_namespaced_deployment.side_effect = [
        _deployment("gnb-x", GNB_CFG, "c"), ApiException(status=404)]
    with patch("ueransim_mcp.k8s_utils.time.sleep"):
        assert wait_for_deployment_deleted(apps, "gnb-x", "net-demo", timeout=5)
    assert apps.read_namespaced_deployment.call_count == 2


def test_failed_deployment_create_removes_its_config_map(v1, apps) -> None:
    apps.create_namespaced_deployment.side_effect = ApiException(status=409, reason="Conflict")

    result = k8s_tools.k8s_create_gnb(amf_address="10.0.0.5", pod_name="gnb-x",
                                      namespace="net-demo")

    assert result.status == "error" and "409" in result.message
    v1.delete_namespaced_config_map.assert_called_once_with("gnb-x-config", "net-demo")
    v1.delete_namespaced_service.assert_not_called()  # the fixture has no <gnb>-radio Service

    v1.read_namespaced_service.side_effect = None
    v1.read_namespaced_service.return_value = SimpleNamespace(
        metadata=SimpleNamespace(labels=dict(MANAGED_BY)))
    k8s_tools.k8s_create_gnb(amf_address="10.0.0.5", pod_name="gnb-x", namespace="net-demo")
    v1.delete_namespaced_service.assert_called_once_with("gnb-x-radio", "net-demo")


def test_failed_radio_service_delete_still_removes_the_config_map(v1, apps) -> None:
    apps.create_namespaced_deployment.side_effect = ApiException(status=409, reason="Conflict")
    v1.read_namespaced_service.side_effect = ApiException(status=403, reason="Forbidden")

    result = k8s_tools.k8s_create_gnb(amf_address="10.0.0.5", pod_name="gnb-x",
                                      namespace="net-demo")

    assert result.status == "error"
    v1.delete_namespaced_config_map.assert_called_once_with("gnb-x-config", "net-demo")


@pytest.mark.parametrize("labels, reused", [(MANAGED_BY, True), ({}, False)])
def test_create_gnb_reuses_only_a_tool_made_leftover_radio_service(v1, apps, labels,
                                                                   reused) -> None:
    v1.create_namespaced_service.side_effect = ApiException(status=409, reason="Conflict")
    v1.read_namespaced_service.side_effect = None
    v1.read_namespaced_service.return_value = SimpleNamespace(
        metadata=SimpleNamespace(labels=dict(labels)))

    k8s_tools.k8s_create_gnb(amf_address="10.0.0.5", pod_name="gnb-x", namespace="net-demo")

    assert apps.create_namespaced_deployment.called is reused
    assert v1.delete_namespaced_config_map.called is not reused


def test_wait_for_deployment_ready_surfaces_api_errors() -> None:
    apps = MagicMock()
    apps.read_namespaced_deployment_status.side_effect = ApiException(status=403)

    with pytest.raises(ApiException):
        wait_for_deployment_ready(apps, "gnb-x", "net-demo", timeout=5)


def test_list_gnbs_skips_terminating_pods(v1, apps) -> None:
    old, new = _owned_pod("gnb-1a-old", "gnb-1a"), _owned_pod("gnb-1a-new", "gnb-1a")
    old.metadata.deletion_timestamp = "now"
    v1.list_namespaced_pod.return_value = SimpleNamespace(items=[old, new])

    result = k8s_tools.k8s_list_gnbs(namespace="net-demo")

    assert [c.id for c in result.containers] == ["gnb-1a-new"]


def test_list_gnbs_reports_the_deployment_name_for_hash_suffixed_pods(v1, apps) -> None:
    pod = _pod("gnb-1a-6c7d-xyz12", GNB_CFG, "gnb-1a-config")
    pod.metadata.labels = {"type": "gnb", WORKLOAD_LABEL: "gnb-1a"}
    pod.metadata.creation_timestamp = "t"
    v1.list_namespaced_pod.return_value = SimpleNamespace(items=[pod])

    result = k8s_tools.k8s_list_gnbs(namespace="net-demo")

    assert [(c.id, c.name) for c in result.containers] == [("gnb-1a-6c7d-xyz12", "gnb-1a")]
    assert v1.list_namespaced_pod.call_args.kwargs["label_selector"] == "type=gnb"


def test_pod_config_map_finds_the_subpath_mount() -> None:
    assert pod_config_map(_pod("gnb-1a", GNB_CFG, "gnb-1a-config"), GNB_CFG) == (
        "gnb-1a-config", "open5gs-gnb.yaml")


def test_get_gnb_logs_reads_the_deployments_current_pod(v1, apps) -> None:
    apps.read_namespaced_deployment.side_effect = None
    apps.read_namespaced_deployment.return_value = _deployment("gnb-1a", GNB_CFG, "gnb-1a-config")
    _live_pod(v1, "gnb-1a", "gnb-1a-6c7d-xyz12")
    v1.read_namespaced_pod_log.return_value = SimpleNamespace(data=b"NG Setup ok\n")

    result = k8s_tools.k8s_get_gnb_logs("gnb-1a", lines=5, namespace="net-demo")

    assert result.logs == "NG Setup ok\n"
    assert v1.read_namespaced_pod_log.call_args.args[0] == "gnb-1a-6c7d-xyz12"
    assert v1.read_namespaced_pod_log.call_args.kwargs["_preload_content"] is False


def test_get_gnb_logs_of_a_bare_pod(v1, apps) -> None:
    v1.read_namespaced_pod_log.return_value = SimpleNamespace(data=b"ok")

    k8s_tools.k8s_get_gnb_logs("gnb-1a", namespace="net-demo")

    assert v1.read_namespaced_pod_log.call_args.args[0] == "gnb-1a"


def test_resolve_pod_name_prefers_a_running_pod_over_a_terminating_one() -> None:
    v1, apps = MagicMock(), MagicMock()
    apps.read_namespaced_deployment.return_value = _deployment("gnb-1a", GNB_CFG, "c")
    old, new = _pod("old", GNB_CFG, "c"), _pod("new", GNB_CFG, "c")
    old.metadata.deletion_timestamp = "now"
    old.metadata.creation_timestamp = new.metadata.creation_timestamp = "t"
    v1.list_namespaced_pod.return_value = SimpleNamespace(items=[old, new])

    assert resolve_pod_name(v1, apps, "gnb-1a", "net-demo") == "new"
    assert v1.list_namespaced_pod.call_args.kwargs["label_selector"] == f"{WORKLOAD_LABEL}=gnb-1a"


def test_wait_for_deployment_ready_needs_a_finished_rollout() -> None:
    apps = MagicMock()

    def status(replicas, updated, ready, observed=2):
        return SimpleNamespace(
            metadata=SimpleNamespace(generation=2),
            spec=SimpleNamespace(replicas=1),
            status=SimpleNamespace(observed_generation=observed, replicas=replicas,
                                   updated_replicas=updated, ready_replicas=ready),
        )

    apps.read_namespaced_deployment_status.side_effect = [
        status(2, 1, 1),  # old pod still there
        status(1, 1, 0),  # new pod not ready
        status(1, 1, 1, observed=1),  # controller has not seen the new generation
        status(1, 1, 1),
    ]
    with patch("ueransim_mcp.k8s_utils.time.sleep"):
        assert wait_for_deployment_ready(apps, "gnb-1a", "net-demo", timeout=10)
    assert apps.read_namespaced_deployment_status.call_count == 4


def test_deployment_pod_name_is_none_without_pods() -> None:
    v1 = MagicMock()
    v1.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    assert deployment_pod_name(v1, _deployment("gnb-1a", GNB_CFG, "c")) is None
