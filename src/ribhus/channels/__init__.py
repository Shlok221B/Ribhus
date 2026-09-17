"""User-facing channels. The agent runtime does not care which one originated a task."""

from ribhus.channels.whatsapp_web.policy import CHANNEL_LABEL, TOS_WARNING

__all__ = ["CHANNEL_LABEL", "TOS_WARNING"]
