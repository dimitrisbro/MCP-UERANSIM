"""K8s gNB/UE tools: pods run nr-gnb/nr-ue as PID 1 and take config from a ConfigMap;
attach/edit change the ConfigMap and recreate the pod (MCP-UERANSIM#2)."""

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
from ueransim_mcp.k8s_utils import MANAGED_BY, pod_config_map

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


@pytest.fixture
def v1():
    api = MagicMock()
    with patch.object(k8s_tools, "get_k8s_client", return_value=api), \
         patch.object(k8s_tools, "wait_for_pod_running", return_value=True), \
         patch.object(k8s_tools.time, "sleep"):
        yield api


def test_create_gnb_runs_nr_gnb_from_its_own_config_map(v1) -> None:
    v1.read_namespaced_pod.return_value = _pod("gnb-x", GNB_CFG, "gnb-x-config")

    result = k8s_tools.k8s_create_gnb(amf_address="10.0.0.5", pod_name="gnb-x",
                                      namespace="net-demo")

    assert result.status == "success"
    _, cm = v1.create_namespaced_config_map.call_args.args
    assert cm.metadata.name == "gnb-x-config" and cm.metadata.labels == MANAGED_BY
    assert yaml.safe_load(cm.data["open5gs-gnb.yaml"])["amfConfigs"][0]["address"] == "10.0.0.5"
    pod = v1.create_namespaced_pod.call_args.kwargs["body"]
    container = pod.spec.containers[0]
    assert container.command == gnb_pod_command()
    assert (container.volume_mounts[0].mount_path, container.volume_mounts[0].sub_path) == (
        GNB_CFG, "open5gs-gnb.yaml")
    assert pod.spec.volumes[0].config_map.name == "gnb-x-config"
    v1.connect_get_namespaced_pod_exec.assert_not_called()


def test_create_ue_runs_nr_ue_from_its_own_config_map(v1) -> None:
    result = k8s_tools.k8s_create_ue(gnb_search_list="10.0.0.9", pod_name="ue-x",
                                     namespace="net-demo")

    assert result.status == "success"
    _, cm = v1.create_namespaced_config_map.call_args.args
    assert yaml.safe_load(cm.data["open5gs-ue.yaml"])["gnbSearchList"] == ["10.0.0.9"]
    spec = v1.create_namespaced_pod.call_args.kwargs["body"].spec
    container = spec.containers[0]
    assert not spec.host_network
    assert container.security_context.privileged
    assert "/dev/net/tun" in [m.mount_path for m in container.volume_mounts]
    assert container.command == ue_pod_command()
    assert UE_CFG in [m.mount_path for m in container.volume_mounts]


def test_attach_gnb_patches_the_config_map_and_recreates_the_pod(v1) -> None:
    pod = _pod("gnb-1a", GNB_CFG, "gnb-1a-config")
    # read #1: the tool reads the pod; read #2: wait_for_pod_deleted sees it gone.
    v1.read_namespaced_pod.side_effect = [pod, ApiException(status=404)]
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        data={"open5gs-gnb.yaml": yaml.safe_dump(build_gnb_config(**GNB_ARGS))})

    with patch.object(k8s_tools, "exec_in_pod",
                      return_value=("nr-gnb is running", "")) as exec_mock, \
         patch("ueransim_mcp.k8s_utils.wait_for_pod_running", return_value=True):
        result = k8s_tools.k8s_attach_gnb_to_core("gnb-1a", amf_address="10.9.9.9",
                                                  namespace="net-demo")

    assert result.status == "success"
    name, ns, body = v1.patch_namespaced_config_map.call_args.args
    assert (name, ns) == ("gnb-1a-config", "net-demo")
    assert yaml.safe_load(body["data"]["open5gs-gnb.yaml"])["amfConfigs"][0]["address"] == "10.9.9.9"
    v1.delete_namespaced_pod.assert_called_once()
    recreated = v1.create_namespaced_pod.call_args.kwargs["body"]
    assert recreated.metadata.name == "gnb-1a" and recreated.spec is pod.spec
    assert "pgrep -x nr-gnb" in exec_mock.call_args.args[3][-1]


def test_attach_gnb_reports_a_stopped_process(v1) -> None:
    v1.read_namespaced_pod.side_effect = [_pod("gnb-1a", GNB_CFG, "gnb-1a-config"),
                                          ApiException(status=404)]
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        data={"open5gs-gnb.yaml": yaml.safe_dump(build_gnb_config(**GNB_ARGS))})

    with patch.object(k8s_tools, "exec_in_pod", return_value=("nr-gnb not found", "")), \
         patch("ueransim_mcp.k8s_utils.wait_for_pod_running", return_value=True):
        result = k8s_tools.k8s_attach_gnb_to_core("gnb-1a", amf_address="10.9.9.9")

    assert result.status == "warning"


def test_attach_refuses_a_pod_without_a_config_map(v1) -> None:
    v1.read_namespaced_pod.return_value = _pod("gnb-old", GNB_CFG, None)

    result = k8s_tools.k8s_attach_gnb_to_core("gnb-old", amf_address="10.9.9.9")

    assert result.status == "error" and "ConfigMap" in result.message
    v1.delete_namespaced_pod.assert_not_called()


def test_edit_rejects_an_unsupported_field_before_touching_the_pod(v1) -> None:
    result = k8s_tools.k8s_edit_pod_config("gnb-1a", config_type="supi", config_value="x")

    assert result.status == "error"
    v1.read_namespaced_pod.assert_not_called()


@pytest.mark.parametrize("labels, deleted", [(MANAGED_BY, True), ({}, False)])
def test_delete_gnb_removes_only_config_maps_the_tools_created(v1, labels, deleted) -> None:
    v1.read_namespaced_pod.return_value = _pod("gnb-x", GNB_CFG, "gnb-x-config")
    v1.read_namespaced_config_map.return_value = SimpleNamespace(
        metadata=SimpleNamespace(labels=labels))

    k8s_tools.k8s_delete_gnb("gnb-x", namespace="net-demo", confirm=True)

    assert v1.delete_namespaced_config_map.called is deleted


def test_pod_config_map_finds_the_subpath_mount() -> None:
    assert pod_config_map(_pod("gnb-1a", GNB_CFG, "gnb-1a-config"), GNB_CFG) == (
        "gnb-1a-config", "open5gs-gnb.yaml")


def test_get_gnb_logs_returns_decoded_text(v1) -> None:
    v1.read_namespaced_pod_log.return_value = SimpleNamespace(data=b"NG Setup ok\n")

    result = k8s_tools.k8s_get_gnb_logs("gnb-1a", lines=5, namespace="net-demo")

    assert result.logs == "NG Setup ok\n"
    assert v1.read_namespaced_pod_log.call_args.kwargs["_preload_content"] is False
