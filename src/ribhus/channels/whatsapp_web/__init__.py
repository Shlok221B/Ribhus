"""WhatsApp Web channel — browser automation of the user's existing session.

This is **not** the official WhatsApp Business API. It is subject to WhatsApp's
Terms of Service. Ribhus does not promise account safety.
"""

from ribhus.channels.whatsapp_web.navigator import WhatsAppNavigator
from ribhus.channels.whatsapp_web.policy import (
    CHANNEL_LABEL,
    TOS_WARNING,
    WhatsAppKilled,
    WhatsAppPolicy,
    WhatsAppPolicyError,
)
from ribhus.channels.whatsapp_web.reader import WhatsAppReader
from ribhus.channels.whatsapp_web.sender import WhatsAppSender
from ribhus.channels.whatsapp_web.session import WhatsAppSession

__all__ = [
    "CHANNEL_LABEL",
    "TOS_WARNING",
    "WhatsAppKilled",
    "WhatsAppNavigator",
    "WhatsAppPolicy",
    "WhatsAppPolicyError",
    "WhatsAppReader",
    "WhatsAppSender",
    "WhatsAppSession",
]
