"""Tether-local Discord bridge compatibility wrapper.

Keep the upstream ``agent_tether`` bridge as the source of truth for Discord
behavior, but override thread creation for text channels so new session threads
are public and discoverable in the configured control channel.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import socket
from typing import Any

import structlog
from agent_tether.discord.bot import DiscordBridge as UpstreamDiscordBridge
from agent_tether.discord.bot import DiscordConfig as UpstreamDiscordConfig
from agent_tether.discord.pairing_state import save as save_pairing_state

logger = structlog.get_logger(__name__)

_DISCORD_THREAD_NAME_LIMIT = 100
_DISCORD_STARTER_TEXT_LIMIT = 2000
_DISCORD_AUTO_ARCHIVE_MINUTES = 1440


def _hostname_slug() -> str:
    hostname = socket.gethostname().split(".", 1)[0].strip().lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", hostname).strip("-")
    return slug or "tether"


@dataclass
class DiscordConfig:
    """Tether-local Discord config compatibility shim."""

    require_pairing: bool = False
    allowed_user_ids: list[int] | None = None
    auto_pair_user_ids: list[int] | None = None
    pairing_code: str | None = None
    guild_id: int = 0


class DiscordBridge(UpstreamDiscordBridge):
    """Compatibility wrapper for the upstream Discord bridge.

    Upstream ``channel.create_thread(...)`` creates private threads when the
    configured control channel is a regular Discord text channel. Those private
    threads are effectively invisible in the machine channel, which makes the
    Discord surface look empty. Tether needs visible public threads there.

    For text channels, create a starter message and open the thread from that
    message so Discord treats it as a public thread. For any other channel type,
    fall back to upstream behavior unchanged.
    """

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
        raw_auto_pair_ids = getattr(local_config, "auto_pair_user_ids", None) or []
        auto_pair_user_ids: set[int] = set()
        for user_id in raw_auto_pair_ids:
            raw_user_id = str(user_id).strip()
            if not raw_user_id:
                continue
            try:
                auto_pair_user_ids.add(int(raw_user_id))
            except ValueError:
                continue
        self._auto_pair_user_ids = auto_pair_user_ids
        self._guild_id = int(getattr(local_config, "guild_id", 0) or 0)
        self._control_channel_name = f"🤖-{_hostname_slug()}"
        self._apply_auto_pair_users()

    async def create_thread(self, session_id: str, session_name: str) -> dict:
        if not self._client:
            raise RuntimeError("Discord client not initialized")

        channel = await self._ensure_control_channel()
        if not channel:
            raise RuntimeError(f"Discord channel {self._channel_id} not found")

        if hasattr(channel, "send"):
            return await self._create_public_thread_from_message(
                session_id=session_id,
                session_name=session_name,
                channel=channel,
            )

        logger.info(
            "Falling back to upstream Discord thread creation",
            session_id=session_id,
            channel_id=self._channel_id,
        )
        return await super().create_thread(session_id, session_name)

    def _persist_control_channel(self) -> None:
        self._ensure_pairing_state_loaded()
        if self._pairing_state is None:
            return
        self._pairing_state.control_channel_id = int(self._channel_id)
        self._pairing_state.paired_user_ids = set(self._paired_user_ids)
        save_pairing_state(path=self._pairing_state_path, state=self._pairing_state)

    def _apply_auto_pair_users(self) -> None:
        if not self._auto_pair_user_ids:
            return
        self._ensure_pairing_state_loaded()
        if self._pairing_state is None:
            return
        before = set(self._paired_user_ids)
        self._paired_user_ids.update(self._auto_pair_user_ids)
        if self._paired_user_ids == before:
            return
        self._pairing_state.paired_user_ids = set(self._paired_user_ids)
        save_pairing_state(path=self._pairing_state_path, state=self._pairing_state)
        logger.info(
            "Auto-paired Discord users from configuration",
            auto_pair_count=len(self._auto_pair_user_ids),
        )

    async def _resolve_bootstrap_guild(self) -> Any | None:
        if not self._client:
            return None

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
            channel = self._client.get_channel(self._channel_id)
            if channel is not None:
                return channel
            fetch_channel = getattr(self._client, "fetch_channel", None)
            if fetch_channel is not None:
                try:
                    channel = await fetch_channel(self._channel_id)
                except Exception:
                    logger.warning(
                        "Configured Discord control channel is not accessible; retrying bootstrap",
                        channel_id=self._channel_id,
                    )
                else:
                    return channel

        guild = await self._resolve_bootstrap_guild()
        if guild is None:
            return None

        for channel in getattr(guild, "text_channels", []) or []:
            if getattr(channel, "name", None) != self._control_channel_name:
                continue
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

    async def _create_public_thread_from_message(
        self,
        *,
        session_id: str,
        session_name: str,
        channel: Any,
    ) -> dict:
        try:
            self._reserve_thread_name(session_id, session_name)

            starter_text = (
                f"🧵 Tether session: **{session_name[:80]}**\n"
                "This starter message keeps the thread visible in this machine channel."
            )
            starter_message = await channel.send(
                starter_text[:_DISCORD_STARTER_TEXT_LIMIT]
            )
            thread = await starter_message.create_thread(
                name=session_name[:_DISCORD_THREAD_NAME_LIMIT],
                auto_archive_duration=_DISCORD_AUTO_ARCHIVE_MINUTES,
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
                "Created visible Discord thread",
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
            logger.exception(
                "Failed to create visible Discord thread", session_id=session_id
            )
            if self._thread_names.get(session_id) == session_name:
                self._release_thread_name(session_id)
            raise RuntimeError(f"Failed to create Discord thread: {exc}") from exc
