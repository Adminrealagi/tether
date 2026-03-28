"""AsyncSSH-backed control server for Tether sessions."""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from dataclasses import dataclass

import structlog

from tether.bridges.glue import make_bridge_callbacks
from tether.settings import settings

try:  # pragma: no cover - exercised indirectly in startup tests
    import asyncssh
except ImportError:  # pragma: no cover - exercised indirectly in startup tests
    asyncssh = None


logger = structlog.get_logger(__name__)


HELP_TEXT = """Available commands:
  help
  list
  pending <session-id-prefix>
  input <session-id-prefix> <text>
  interrupt <session-id-prefix>
  approve <session-id-prefix> <request-id> <allow|deny> [message]
  watch <session-id-prefix>
  exit
"""


@dataclass
class CommandResult:
    """Outcome of a command invocation."""

    keep_running: bool = True


class SSHControlServer:
    """Serve Tether control commands over SSH."""

    def __init__(self) -> None:
        self._callbacks = make_bridge_callbacks()
        self._server = None

    async def start(self) -> None:
        """Start the SSH server if configuration is valid."""
        if asyncssh is None:
            raise RuntimeError(
                "AsyncSSH is not installed. Install with `pip install tether-ai[ssh]`."
            )

        host_key_path = settings.ssh_host_key_path()
        authorized_keys_path = settings.ssh_authorized_keys_path()
        self._validate_paths(host_key_path, authorized_keys_path)
        await asyncio.to_thread(self._ensure_host_key, host_key_path)

        self._server = await asyncssh.listen(
            settings.ssh_host(),
            settings.ssh_port(),
            server_host_keys=[host_key_path],
            authorized_client_keys=authorized_keys_path,
            process_factory=self._handle_process,
        )
        logger.info(
            "SSH control server started",
            host=settings.ssh_host(),
            port=settings.ssh_port(),
            authorized_keys_path=authorized_keys_path,
        )

    async def stop(self) -> None:
        """Stop the SSH server."""
        if self._server is None:
            return
        self._server.close()
        wait_closed = getattr(self._server, "wait_closed", None)
        if wait_closed is not None:
            await wait_closed()
        self._server = None

    def _validate_paths(self, host_key_path: str, authorized_keys_path: str) -> None:
        if not authorized_keys_path:
            raise RuntimeError("TETHER_SSH_AUTHORIZED_KEYS_PATH must be set")
        if not os.path.exists(authorized_keys_path):
            raise RuntimeError(
                f"Authorized keys file not found: {authorized_keys_path}"
            )
        os.makedirs(os.path.dirname(host_key_path), exist_ok=True)

    def _ensure_host_key(self, host_key_path: str) -> None:
        """Create an ed25519 host key if one does not already exist."""
        if os.path.exists(host_key_path):
            return
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", host_key_path],
            check=True,
        )

    async def _handle_process(self, process) -> None:
        command = (getattr(process, "command", None) or "").strip()
        if command:
            await self.execute(process, command)
            return

        self._write(
            process,
            "Tether SSH control\n",
            "Type `help` for commands. Ctrl+C disconnects a watch stream.\n\n",
        )
        while True:
            self._write(process, "tether> ")
            line = await process.stdin.readline()
            if not line:
                break
            result = await self.execute(process, line)
            if not result.keep_running:
                break

    async def execute(self, process, line: str) -> CommandResult:
        """Parse and execute one SSH command."""
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            self._write(process, f"Parse error: {exc}\n")
            return CommandResult()

        if not parts:
            return CommandResult()

        command = parts[0].lower()
        args = parts[1:]

        try:
            if command in {"exit", "quit"}:
                self._write(process, "Bye.\n")
                return CommandResult(keep_running=False)
            if command == "help":
                self._write(process, HELP_TEXT)
                return CommandResult()
            if command == "list":
                await self._list_sessions(process)
                return CommandResult()
            if command == "pending":
                await self._show_pending(process, args)
                return CommandResult()
            if command == "input":
                await self._send_input(process, args)
                return CommandResult()
            if command == "interrupt":
                await self._interrupt(process, args)
                return CommandResult()
            if command == "approve":
                await self._approve(process, args)
                return CommandResult()
            if command == "watch":
                await self._watch(process, args)
                return CommandResult()
        except RuntimeError as exc:
            self._write(process, f"{exc}\n")
            return CommandResult()

        self._write(process, f"Unknown command: {command}\n")
        self._write(process, "Run `help` for the supported command set.\n")
        return CommandResult()

    async def _list_sessions(self, process) -> None:
        sessions = await self._callbacks.list_sessions()
        if not sessions:
            self._write(process, "No sessions.\n")
            return

        lines = []
        for session in sessions:
            session_id = session.get("id", "")
            state = session.get("state", "")
            platform = session.get("platform") or "-"
            name = session.get("name") or "Untitled"
            directory = session.get("directory") or "-"
            lines.append(
                f"{session_id}  {state:<16}  {platform:<8}  {name}  [{directory}]"
            )
        self._write(process, "\n".join(lines) + "\n")

    async def _show_pending(self, process, args: list[str]) -> None:
        if len(args) != 1:
            self._write(process, "Usage: pending <session-id-prefix>\n")
            return
        session = self._resolve_session(args[0])
        pending = _store().get_all_pending_permissions(session.id)
        if not pending:
            self._write(process, f"No pending permissions for {session.id}.\n")
            return

        lines = []
        for item in pending:
            lines.append(f"{item.request_id}  {item.tool_name}  {item.tool_input}")
        self._write(process, "\n".join(lines) + "\n")

    async def _send_input(self, process, args: list[str]) -> None:
        if len(args) < 2:
            self._write(process, "Usage: input <session-id-prefix> <text>\n")
            return
        session = self._resolve_session(args[0])
        text = " ".join(args[1:]).strip()
        if not text:
            self._write(process, "Input text cannot be empty.\n")
            return
        await self._callbacks.send_input(session.id, text)
        self._write(process, f"Sent input to {session.id}.\n")

    async def _interrupt(self, process, args: list[str]) -> None:
        if len(args) != 1:
            self._write(process, "Usage: interrupt <session-id-prefix>\n")
            return
        session = self._resolve_session(args[0])
        await self._callbacks.stop_session(session.id)
        self._write(process, f"Interrupt requested for {session.id}.\n")

    async def _approve(self, process, args: list[str]) -> None:
        if len(args) < 3:
            self._write(
                process,
                "Usage: approve <session-id-prefix> <request-id> <allow|deny> [message]\n",
            )
            return
        session = self._resolve_session(args[0])
        request_id = args[1]
        decision = args[2].lower()
        if decision not in {"allow", "deny"}:
            self._write(process, "Decision must be `allow` or `deny`.\n")
            return
        message = " ".join(args[3:]).strip() or None
        await self._callbacks.respond_to_permission(
            session.id,
            request_id,
            decision == "allow",
            message,
        )
        self._write(process, f"{decision} sent for {request_id} on {session.id}.\n")

    async def _watch(self, process, args: list[str]) -> None:
        if len(args) != 1:
            self._write(process, "Usage: watch <session-id-prefix>\n")
            return
        session = self._resolve_session(args[0])
        queue = _store().new_subscriber(session.id)
        self._write(process, f"Watching {session.id}. Ctrl+C disconnects.\n")
        try:
            while True:
                event = await queue.get()
                text = self._format_event(event)
                if text:
                    self._write(process, text)
        finally:
            _store().remove_subscriber(session.id, queue)

    def _resolve_session(self, session_prefix: str):
        session = _store().get_session(session_prefix)
        if session is not None:
            return session

        matches = [
            candidate
            for candidate in _store().list_sessions()
            if candidate.id.startswith(session_prefix)
        ]
        if not matches:
            raise RuntimeError(f"No session matches `{session_prefix}`.")
        if len(matches) > 1:
            options = ", ".join(match.id for match in matches[:5])
            raise RuntimeError(
                f"Session prefix `{session_prefix}` is ambiguous: {options}"
            )
        return matches[0]

    def _format_event(self, event: dict) -> str:
        event_type = event.get("type")
        data = event.get("data") or {}

        if event_type == "output":
            return data.get("text", "")
        if event_type == "session_state":
            return f"\n[session] {data.get('state', 'unknown')}\n"
        if event_type == "permission_request":
            return (
                "\n[approval] "
                f"{data.get('request_id')} {data.get('tool_name')} {data.get('tool_input')}\n"
            )
        if event_type == "permission_resolved":
            return (
                "\n[approval] "
                f"{data.get('request_id')} resolved allow={data.get('allowed')}\n"
            )
        if event_type == "error":
            return f"\n[error] {data.get('message', '')}\n"
        if event_type == "warning":
            return f"\n[warning] {data.get('message', '')}\n"
        return ""

    def _write(self, process, *parts: str) -> None:
        for part in parts:
            if not part:
                continue
            process.write(part)


def _store():
    from tether.store import store

    return store
