"""Tests for OpenCode managed sidecar helpers."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from tether.runner.base import RunnerUnavailableError


def test_resolve_uses_custom_cmd_when_set(monkeypatch):
    from tether.runner.opencode_sidecar_manager import _resolve_sidecar_command

    monkeypatch.setattr(
        "tether.settings.settings.opencode_sidecar_cmd",
        staticmethod(lambda: "my-cmd --flag"),
    )
    assert _resolve_sidecar_command() == ["my-cmd", "--flag"]


def test_resolve_uses_bundled_mjs_when_no_custom_cmd(monkeypatch, tmp_path):
    from tether.runner.opencode_sidecar_manager import _resolve_sidecar_command

    monkeypatch.setattr(
        "tether.settings.settings.opencode_sidecar_cmd",
        staticmethod(lambda: ""),
    )

    fake_mjs = tmp_path / "opencode-sidecar.mjs"
    fake_mjs.write_text("// fake")

    with patch(
        "tether.runner.opencode_sidecar_manager.bundle_path",
        return_value=fake_mjs,
    ):
        result = _resolve_sidecar_command()

    node = shutil.which("node")
    assert result == [node, str(fake_mjs)]


def test_resolve_raises_when_no_node(monkeypatch, tmp_path):
    from tether.runner.opencode_sidecar_manager import _resolve_sidecar_command

    monkeypatch.setattr(
        "tether.settings.settings.opencode_sidecar_cmd",
        staticmethod(lambda: ""),
    )

    fake_mjs = tmp_path / "opencode-sidecar.mjs"
    fake_mjs.write_text("// fake")

    with patch(
        "tether.runner.opencode_sidecar_manager.bundle_path",
        return_value=fake_mjs,
    ), patch("tether.runner.opencode_sidecar_manager.shutil") as mock_shutil:
        mock_shutil.which.return_value = None
        with pytest.raises(RunnerUnavailableError, match="Node.js is required"):
            _resolve_sidecar_command()


def test_resolve_falls_back_to_source_tree(monkeypatch):
    from tether.runner.opencode_sidecar_manager import _resolve_sidecar_command

    monkeypatch.setattr(
        "tether.settings.settings.opencode_sidecar_cmd",
        staticmethod(lambda: ""),
    )

    # No bundle available, fall back to source tree walk.
    with patch(
        "tether.runner.opencode_sidecar_manager.bundle_path",
        side_effect=FileNotFoundError,
    ):
        result = _resolve_sidecar_command()

    # In the dev layout, opencode-sdk-sidecar/ exists in the repo.
    assert "--prefix" in result
    assert "start" in result


def test_resolve_managed_xdg_data_home_preserves_default_when_writable(
    monkeypatch, tmp_path
):
    from tether.runner.opencode_sidecar_manager import _resolve_managed_xdg_data_home

    monkeypatch.setattr(
        "tether.runner.opencode_sidecar_manager.Path.home",
        lambda: tmp_path,
    )

    data_home = tmp_path / ".local" / "share"
    data_home.mkdir(parents=True)

    assert _resolve_managed_xdg_data_home({}) is None


def test_resolve_managed_xdg_data_home_preserves_configured_value_when_writable(
    tmp_path,
):
    from tether.runner.opencode_sidecar_manager import _resolve_managed_xdg_data_home

    data_home = tmp_path / "custom-data"
    data_home.mkdir()

    assert _resolve_managed_xdg_data_home({"XDG_DATA_HOME": str(data_home)}) is None


def test_resolve_managed_xdg_data_home_falls_back_when_default_not_usable(
    monkeypatch, tmp_path
):
    from tether.runner.opencode_sidecar_manager import _resolve_managed_xdg_data_home

    blocked_home = tmp_path / "blocked-home"
    blocked_home.mkdir()

    monkeypatch.setattr(
        "tether.runner.opencode_sidecar_manager.Path.home",
        lambda: blocked_home,
    )
    monkeypatch.setattr(
        "tether.settings.settings.data_dir",
        staticmethod(lambda: str(tmp_path / "tether-data")),
    )
    monkeypatch.setattr(
        "tether.runner.opencode_sidecar_manager.os.access",
        lambda _path, _mode: False,
    )

    fallback = _resolve_managed_xdg_data_home({})

    assert fallback == str(tmp_path / "tether-data" / "opencode_managed")
    assert Path(fallback).is_dir()
