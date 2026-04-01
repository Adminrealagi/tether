"""Repo-owned Discord bridge wrapper with control-channel bootstrap."""

from __future__ import annotations

import asyncio
import re
import socket
from dataclasses import dataclass
from typing import Any

import structlog
from agent_tether.discord.bot import DiscordBridge as UpstreamDiscordBridge
from agent_tether.discord.bot import DiscordConfig as UpstreamDiscordConfig

logger = structlog.get_logger(__name__)

_CONTROL_CHANNEL_EMOJI = "🤖"


def _hostname_slug() -> str:
    hostname = socket.gethostname().split(".", 1)[0].strip().lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", hostname).strip("-")
    return slug or "tether"


@dataclass
class DiscordConfig:
    """Discord-specific configuration owned by the Tether repo."""

    require_pairing: bool = False
    allowed_user_ids: list[int] | None = None
    pairing_code: str | None = None
    guild_id: int = 0


class DiscordBridge(UpstreamDiscordBridge):
    """Discord bridge with automatic host-named control channel bootstrap."""

    def __init__(
        self,
        bot_token: str,
        channel_id: int,
        discord_config: DiscordConfig | UpstreamDiscordConfig | None = None,
        **kwargs: Any,
    ) -> None:
        local_config = discord_config or DiscordConfig()
        upstream_config = UpstreamDiscordConfig(
            require_pairing=getattr(local_config, "require_pairing", False),
            allowed_user_ids=getattr(local_config, "allowed_user_ids", None),
            pairing_code=getattr(local_config, "pairing_code", None),
        )
        super().__init__(
            bot_token=bot_token,
            channel_id=channel_id,
            discord_config=upstream_config,
            **kwargs,
        )
        self._guild_id = int(getattr(local_config, "guild_id", 0) or 0)
        self._control_channel_name = f"{_CONTROL_CHANNEL_EMOJI}-{_hostname_slug()}"

    def _persist_control_channel(self) -> None:
        self._ensure_pairing_state_loaded()
        if self._pairing_state is None:
            return
        self._pairing_state.control_channel_id = int(self._channel_id)
        self._pairing_state.paired_user_ids = set(self._paired_user_ids)
        from agent_tether.discord.pairing_state import save as save_pairing_state

        save_pairing_state(path=self._pairing_state_path, state=self._pairing_state)

    async def _resolve_bootstrap_guild(self) -> Any | None:
        guilds = list(getattr(self._client, "guilds", []) or [])
        if self._guild_id:
            guild = self._client.get_guild(self._guild_id)
            if guild is None:
                logger.warning(
                    "Configured Discord guild not found for control channel bootstrap",
                    guild_id=self._guild_id,
                    guild_count=len(guilds),
                )
            return guild
        if len(guilds) == 1:
            return guilds[0]
        if len(guilds) > 1:
            logger.warning(
                "Discord control channel bootstrap needs DISCORD_GUILD_ID when the bot is in multiple guilds",
                guild_count=len(guilds),
            )
            return None
        logger.warning("Discord control channel bootstrap found no accessible guilds")
        return None

    async def _ensure_control_channel(self) -> Any | None:
        if not self._client:
            return None

        if self._channel_id:
            cached = self._client.get_channel(self._channel_id)
            if cached is not None:
                return cached
            try:
                fetched = await self._client.fetch_channel(self._channel_id)
            except Exception:
                logger.warning(
                    "Configured Discord control channel is not accessible; retrying bootstrap",
                    channel_id=self._channel_id,
                )
                self._channel_id = 0
            else:
                return fetched

        guild = await self._resolve_bootstrap_guild()
        if guild is None:
            return None

        for channel in getattr(guild, "text_channels", []) or []:
            if getattr(channel, "name", None) == self._control_channel_name:
                self._channel_id = int(channel.id)
                self._persist_control_channel()
                logger.info(
                    "Using existing Discord control channel",
                    guild_id=getattr(guild, "id", 0),
                    channel_id=self._channel_id,
                    channel_name=self._control_channel_name,
                )
                return channel

        topic = (
            f"Tether control channel for {socket.gethostname().split('.', 1)[0]}. "
            "Session threads are created from here automatically."
        )
        channel = await guild.create_text_channel(
            name=self._control_channel_name,
            topic=topic[:1024],
        )
        self._channel_id = int(channel.id)
        self._persist_control_channel()
        logger.info(
            "Created Discord control channel",
            guild_id=getattr(guild, "id", 0),
            channel_id=self._channel_id,
            channel_name=self._control_channel_name,
        )
        return channel

    async def start(self) -> None:
        """Initialize and start the Discord client with channel bootstrap."""
        try:
            import discord
        except ImportError:
            logger.error("discord.py not installed. Install with: pip install discord.py")
            return

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready() -> None:
            logger.info("Discord client ready", user=self._client.user)
            try:
                await self._ensure_control_channel()
            except Exception:
                logger.exception("Failed to bootstrap Discord control channel")

        @self._client.event
        async def on_message(message: Any) -> None:
            await self._handle_message(message)

        asyncio.create_task(self._client.start(self._bot_token))

        logger.info(
            "Discord bridge initialized and starting",
            channel_id=self._channel_id,
            guild_id=self._guild_id,
        )
        if not self._channel_id and self._guild_id:
            logger.info(
                "Discord bridge will auto-create or reuse the hostname control channel",
                guild_id=self._guild_id,
                channel_name=self._control_channel_name,
            )
        elif not self._channel_id and self._pairing_code:
            logger.warning(
                "Discord bridge not configured with a control channel. Run !setup <code> in the desired channel.",
                code=self._pairing_code,
            )
        elif self._pairing_required and self._pairing_code:
            logger.warning(
                "Discord pairing enabled. DM the bot: !pair <code>",
                code=self._pairing_code,
            )

    async def create_thread(self, session_id: str, session_name: str) -> dict:
        """Create a Discord thread, bootstrapping the control channel if needed."""
        if not self._client:
            raise RuntimeError("Discord client not initialized")

        channel = await self._ensure_control_channel()
        if channel is None:
            raise RuntimeError("Discord control channel is not configured")

        try:
            self._reserve_thread_name(session_id, session_name)

            thread = await channel.create_thread(
                name=session_name[:100],
                auto_archive_duration=1440,
            )

            thread_id = thread.id
            self._thread_ids[session_id] = thread_id
            try:
                await thread.send(
                    "Tether session thread.\n"
                    "Send a message here to provide input. Use `!stop` to interrupt, `!usage` for token usage."
                )
            except Exception:
                pass

            logger.info(
                "Created Discord thread",
                session_id=session_id,
                thread_id=thread_id,
                name=session_name,
                channel_id=self._channel_id,
            )

            return {
                "thread_id": str(thread_id),
                "platform": "discord",
            }
        except Exception as exc:
            logger.exception("Failed to create Discord thread", session_id=session_id)
            if self._thread_names.get(session_id) == session_name:
                self._release_thread_name(session_id)
            raise RuntimeError(f"Failed to create Discord thread: {exc}")
