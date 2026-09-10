
from __future__ import annotations


class SonomaAuthorizationError(RuntimeError):
    pass


def raise_for_sonoma_application_error(payload):
    """
    Sonoma sometimes returns HTTP 200 for application-level authorization
    failures. Detect those explicitly so callers do not misread them as an
    empty observation set.
    """
    if not isinstance(payload, dict):
        return

    messages = payload.get("messages") or []

    if isinstance(messages, str):
        messages = [messages]

    text = " | ".join(
        str(x)
        for x in messages
    )

    restricted = (
        payload.get("error") is True
        and "access restricted" in text.lower()
    )

    if restricted:
        raise SonomaAuthorizationError(
            "Sonoma authorization expired or access is restricted. "
            "Refresh the browser-session token or use a sanctioned API credential."
        )
