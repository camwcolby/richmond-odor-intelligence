from __future__ import annotations

import asyncio
import os

import httpx


class SonomaAuthorizationError(RuntimeError):
    pass


class SonomaAuthConfigurationError(RuntimeError):
    pass


_TOKEN: str | None = None
_LOCK = asyncio.Lock()


def _login_url() -> str:
    return os.getenv(
        "SONOMA_LOGIN_URL",
        "https://insightdms.sonomatech.com/api/Auth/User/login",
    ).strip()


def _public_credentials() -> tuple[str, str] | None:
    username = os.getenv("SONOMA_PUBLIC_USERNAME", "").strip()
    password = os.getenv("SONOMA_PUBLIC_PASSWORD", "").strip()
    if username and password:
        return username, password
    return None


def configured_static_token() -> str | None:
    token = os.getenv("SONOMA_DMS_TOKEN", "").strip()
    return token or None


async def get_sonoma_token(*, verify=True, force_refresh: bool = False) -> str:
    """
    Return a cached temporary Sonoma token.

    Preferred path: use the public Richmond site's application credentials to
    obtain the same temporary token the public site obtains. A configured
    SONOMA_DMS_TOKEN remains available as a migration/fallback path.
    """
    global _TOKEN

    if _TOKEN and not force_refresh:
        return _TOKEN

    creds = _public_credentials()
    if creds is None:
        static = configured_static_token()
        if static:
            _TOKEN = static
            return static
        raise SonomaAuthConfigurationError(
            "Configure SONOMA_PUBLIC_USERNAME and SONOMA_PUBLIC_PASSWORD "
            "(preferred) or SONOMA_DMS_TOKEN (fallback)."
        )

    async with _LOCK:
        if _TOKEN and not force_refresh:
            return _TOKEN

        username, password = creds
        async with httpx.AsyncClient(
            timeout=30.0,
            verify=verify,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                _login_url(),
                data={"username": username, "password": password},
                headers={
                    "Accept": "*/*",
                    "Origin": "https://richmondwpcp-h2s.org",
                    "Referer": "https://richmondwpcp-h2s.org/",
                },
            )

        response.raise_for_status()

        try:
            payload = response.json()
        except Exception:
            payload = response.text

        token = payload.strip() if isinstance(payload, str) else None
        if not token:
            raise SonomaAuthorizationError(
                "Sonoma public-app login did not return a temporary token."
            )

        _TOKEN = token
        return token


def invalidate_sonoma_token() -> None:
    global _TOKEN
    _TOKEN = None


def raise_for_sonoma_application_error(payload):
    """
    Sonoma sometimes returns HTTP 200 for application-level authorization
    failures. Detect those explicitly so callers can refresh and retry.
    """
    if not isinstance(payload, dict):
        return

    messages = payload.get("messages") or []
    if isinstance(messages, str):
        messages = [messages]

    text = " | ".join(str(x) for x in messages)
    restricted = (
        payload.get("error") is True
        and "access restricted" in text.lower()
    )

    if restricted:
        raise SonomaAuthorizationError(
            "Sonoma temporary authorization is expired or access is restricted."
        )
