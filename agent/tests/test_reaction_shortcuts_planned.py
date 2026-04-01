from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="planned checkmark-reaction shortcut coverage stays disabled until the bridge handlers exist"
)


def test_planned_discord_checkmark_reaction_creates_and_starts_session_from_control_channel_message() -> None:
    """Planned: reacting with `✅` to a top-level control-channel message like `!new codex /repo` plus a prompt body creates a Discord-bound session and sends the prompt as the first input."""


def test_planned_discord_checkmark_reaction_ignores_threads_unauthorized_users_and_duplicate_events() -> None:
    """Planned: Discord ignores checkmark reactions inside threads, from unauthorized users, or for already-processed message ids."""


def test_planned_slack_checkmark_reaction_creates_and_starts_session_from_control_channel_message() -> None:
    """Planned: reacting with `✅` to a top-level Slack control-channel message like `!new codex /repo` plus a prompt body creates a Slack-bound session and sends the prompt as the first input."""


def test_planned_slack_checkmark_reaction_ignores_non_checkmark_reactions_and_thread_messages() -> None:
    """Planned: Slack ignores non-checkmark reactions and thread-scoped reaction events for the shortcut flow."""
