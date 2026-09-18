"""Gmail Web channel — browser automation of the user's Gmail session.

This is **not** the Gmail API. It is subject to Google's Terms of Service.
"""

from ribhus.channels.gmail_web.policy import CHANNEL_LABEL, TOS_WARNING, EmailPolicy
from ribhus.channels.gmail_web.session import GmailSession
from ribhus.channels.gmail_web.tools import resolve_email_send_mode

__all__ = [
    "CHANNEL_LABEL",
    "TOS_WARNING",
    "EmailPolicy",
    "GmailSession",
    "resolve_email_send_mode",
]
