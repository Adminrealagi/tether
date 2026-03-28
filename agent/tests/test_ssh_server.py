"""Tests for the SSH control server."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

import tether.ssh.server as ssh_server_module
from tether.api.emit import emit_output, emit_permission_request
from tether.models import SessionState
from tether.ssh.server import SSHControlServer


class FakeStream:
    """Minimal async stream for tests."""

    def __init__(self, lines: list[str] | None = None) -> None:
        self._lines = list(lines or [])

    async def readline(self) -> str:
        if not self._lines:
            return ""
        return self._lines.pop(0)


@dataclass
class FakeProcess:
    """Minimal AsyncSSH process stub."""

    command: str = ""
    stdin: FakeStream = field(default_factory=FakeStream)

    def __post_init__(self) -> None:
        self.output = ""

    def write(self, text: str) -> None:
        self.output += text


class StubCallbacks:
    """Fake callbacks used by the SSH server tests."""

    def __init__(self) -> None:
        self.inputs: list[tuple[str, str]] = []
        self.interrupts: list[str] = []
        self.permissions: list[tuple[str, str, bool, str | None]] = []
        self.sessions: list[dict] = []

    async def list_sessions(self) -> list[dict]:
        return self.sessions

    async def send_input(self, session_id: str, text: str) -> None:
        self.inputs.append((session_id, text))

    async def stop_session(self, session_id: str) -> None:
        self.interrupts.append(session_id)

    async def respond_to_permission(
        self, session_id: str, request_id: str, allow: bool, message: str | None
    ) -> bool:
        self.permissions.append((session_id, request_id, allow, message))
        return True


@pytest.fixture
def ssh_server() -> SSHControlServer:
    server = SSHControlServer()
    server._callbacks = StubCallbacks()  # noqa: SLF001 - test seam
    return server


@pytest.mark.anyio
async def test_list_command_outputs_sessions(
    ssh_server: SSHControlServer, fresh_store
) -> None:
    callbacks = ssh_server._callbacks  # noqa: SLF001 - test seam
    callbacks.sessions = [
        {
            "id": "sess_abc123",
            "state": "RUNNING",
            "platform": "discord",
            "name": "Fix tests",
            "directory": "/tmp/demo",
        }
    ]
    process = FakeProcess()

    result = await ssh_server.execute(process, "list")

    assert result.keep_running is True
    assert "sess_abc123" in process.output
    assert "RUNNING" in process.output
    assert "discord" in process.output


@pytest.mark.anyio
async def test_input_command_uses_session_prefix(
    ssh_server: SSHControlServer, fresh_store
) -> None:
    session = fresh_store.create_session("/tmp/demo", None)
    process = FakeProcess()

    await ssh_server.execute(process, f"input {session.id[:8]} continue please")

    callbacks = ssh_server._callbacks  # noqa: SLF001 - test seam
    assert callbacks.inputs == [(session.id, "continue please")]
    assert f"Sent input to {session.id}" in process.output


@pytest.mark.anyio
async def test_pending_command_lists_requests(
    ssh_server: SSHControlServer, fresh_store
) -> None:
    session = fresh_store.create_session("/tmp/demo", None)
    fresh_store.update_session(session)
    fresh_store.add_pending_permission(
        session.id,
        request_id="perm_1",
        tool_name="Write",
        tool_input={"path": "README.md"},
        future=asyncio.get_running_loop().create_future(),
    )
    process = FakeProcess()

    await ssh_server.execute(process, f"pending {session.id}")

    assert "perm_1" in process.output
    assert "Write" in process.output
    assert "README.md" in process.output


@pytest.mark.anyio
async def test_approve_command_resolves_permission(
    ssh_server: SSHControlServer, fresh_store
) -> None:
    session = fresh_store.create_session("/tmp/demo", None)
    process = FakeProcess()

    await ssh_server.execute(
        process,
        f"approve {session.id} perm_9 allow looks-good",
    )

    callbacks = ssh_server._callbacks  # noqa: SLF001 - test seam
    assert callbacks.permissions == [(session.id, "perm_9", True, "looks-good")]
    assert "allow sent for perm_9" in process.output


@pytest.mark.anyio
async def test_watch_streams_store_events(
    ssh_server: SSHControlServer, fresh_store
) -> None:
    session = fresh_store.create_session("/tmp/demo", None)
    session.state = SessionState.RUNNING
    fresh_store.update_session(session)
    process = FakeProcess()

    watch_task = asyncio.create_task(ssh_server.execute(process, f"watch {session.id}"))
    await asyncio.sleep(0)

    await emit_output(session, "hello over ssh", kind="step", is_final=False)
    await emit_permission_request(
        session,
        request_id="perm_2",
        tool_name="Bash",
        tool_input={"cmd": "ls"},
        suggestions=None,
    )
    await asyncio.sleep(0)
    watch_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watch_task

    assert "hello over ssh" in process.output
    assert "perm_2" in process.output


@pytest.mark.anyio
async def test_start_requires_authorized_keys(
    ssh_server: SSHControlServer, monkeypatch
) -> None:
    monkeypatch.setenv("TETHER_SSH_ENABLED", "1")
    monkeypatch.setenv("TETHER_SSH_AUTHORIZED_KEYS_PATH", "/tmp/does-not-exist")
    monkeypatch.setattr(
        ssh_server_module,
        "asyncssh",
        SimpleNamespace(listen=None),
    )

    with pytest.raises(RuntimeError, match="Authorized keys file not found"):
        await ssh_server.start()
