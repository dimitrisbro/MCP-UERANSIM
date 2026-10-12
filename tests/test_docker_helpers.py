"""Trailing-newline rejection in the Docker container id/name checks (no Docker needed)."""

import subprocess
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from ueransim_mcp import docker_utils
from ueransim_mcp.docker_tools import _is_container_id


class TestIsContainerId:
    @pytest.mark.parametrize("value", ["abcdef012345", "a" * 64, "ABCDEF012345"])
    def test_valid_ids_still_pass(self, value):
        assert _is_container_id(value)

    def test_trailing_newline_is_not_a_container_id(self):
        # 11 hex digits + "\n" is 12 characters; `$` used to match before the newline.
        assert not _is_container_id("abcdef01234\n")


class TestValidateExistingContainer:
    @staticmethod
    @contextmanager
    def _runtime(returncode=0):
        """Mock the container runtime; yields the run_container_command mock."""
        run = MagicMock(return_value=subprocess.CompletedProcess([], returncode, "", ""))
        with patch.multiple(
            docker_utils,
            get_container_runtime=MagicMock(return_value="docker"),
            run_container_command=run,
        ):
            yield run

    @pytest.mark.parametrize("value", ["abcdef012345", "ueransim-gnb", "ue_1"])
    def test_valid_values_still_pass(self, value):
        with self._runtime():
            assert docker_utils.validate_existing_container(value) is True

    def test_trailing_newline_hex_id_is_rejected_before_reaching_the_runtime(self):
        with self._runtime() as run:
            with pytest.raises(ValueError):
                docker_utils.validate_existing_container("abcdef01234\n")
        run.assert_not_called()

    def test_trailing_newline_container_name_is_rejected_before_reaching_the_runtime(self):
        with self._runtime() as run:
            with pytest.raises(ValueError, match="Invalid container name format"):
                docker_utils.validate_existing_container("ueransim-gnb\n")
        run.assert_not_called()
