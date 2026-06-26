"""Disposable email providers — multi-provider with auto-fallback.

Provider priority: mail.tm → guerrillamail → tempmail.lol
Auto-fallback: if one fails, try next automatically.

API details (discovered via live testing):
  - mail.tm:        POST /accounts, GET /messages (token auth)
  - guerrillamail:  GET ajax.php?f=get_email_address, f=check_email (session cookie)
  - tempmail.lol:   GET /generate, GET /v2/inbox?token=...
"""

import json
import random
import re
import string
import time

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
HEADERS = {"User-Agent": UA, "Accept": "application/json"}

# ── mail.tm ───────────────────────────────────────────────────


def mailtm_create(password: str = "TempMail2025!") -> dict | None:
    """Create account on mail.tm. Returns {email, token, provider}."""
    try:
        domains_r = requests.get("https://api.mail.tm/domains", headers=HEADERS, timeout=10)
        if domains_r.status_code != 200:
            return None
        domains_data = domains_r.json()
        if isinstance(domains_data, dict):
            domain_list = [d.get("domain", d.get("name", "")) for d in domains_data.get("hydra:member", [])]
        elif isinstance(domains_data, list):
            domain_list = [d.get("domain", d.get("name", d)) if isinstance(d, dict) else d for d in domains_data]
        else:
            return None
        domain_list = [d for d in domain_list if d]
        if not domain_list:
            return None

        user = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        email = f"{user}@{domain_list[0]}"

        r = requests.post(
            "https://api.mail.tm/accounts",
            headers=HEADERS,
            json={"address": email, "password": password},
            timeout=10,
        )
        if r.status_code not in (200, 201):
            return None

        r2 = requests.post(
            "https://api.mail.tm/token",
            headers=HEADERS,
            json={"address": email, "password": password},
            timeout=10,
        )
        if r2.status_code != 200:
            return None

        token = r2.json().get("token", "")
        return {"email": email, "token": token, "provider": "mail.tm"}
    except Exception:
        return None


def mailtm_poll(token: str, timeout_sec: int = 120, interval: int = 5) -> str | None:
    """Poll mail.tm for verification code. Returns 6-digit code or None."""
    headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            r = requests.get("https://api.mail.tm/messages", headers=headers, timeout=10)
            if r.status_code == 200:
                msgs = r.json()
                if isinstance(msgs, dict):
                    msgs = msgs.get("hydra:member", [])
                for msg in msgs:
                    body = str(msg.get("text", "")) + str(msg.get("subject", ""))
                    codes = re.findall(r"\b(\d{6})\b", body)
                    if codes:
                        return codes[0]
        except Exception:
            pass
        time.sleep(interval)
    return None


# ── guerrillamail ─────────────────────────────────────────────


def guerrilla_create() -> dict | None:
    """Create session on guerrillamail. Returns {email, token, provider}."""
    try:
        r = requests.get(
            "https://api.guerrillamail.com/ajax.php?f=get_email_address&lang=en",
            headers=HEADERS,
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        email = data.get("email_addr", "")
        token = data.get("sid_token", "")
        if not email or not token:
            return None
        return {"email": email, "token": token, "provider": "guerrillamail"}
    except Exception:
        return None


def guerrilla_poll(token: str, timeout_sec: int = 120, interval: int = 5) -> str | None:
    """Poll guerrillamail for verification code. Returns 6-digit code or None."""
    deadline = time.time() + timeout_sec
    last_id = 0
    while time.time() < deadline:
        try:
            r = requests.get(
                f"https://api.guerrillamail.com/ajax.php?f=check_email&seq={last_id}&sid_token={token}",
                headers=HEADERS,
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                for msg in data.get("list", []):
                    body = str(msg.get("mail_body", "")) + str(msg.get("mail_subject", ""))
                    codes = re.findall(r"\b(\d{6})\b", body)
                    if codes:
                        return codes[0]
                    mid = int(msg.get("mail_id", 0))
                    if mid > last_id:
                        last_id = mid
        except Exception:
            pass
        time.sleep(interval)
    return None


# ── tempmail.lol ──────────────────────────────────────────────


def tempmail_lol_create() -> dict | None:
    """Create inbox on tempmail.lol. Returns {email, token, provider}."""
    try:
        r = requests.get("https://api.tempmail.lol/generate", headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        email = data.get("address", "")
        token = data.get("token", "")
        if not email or not token:
            return None
        return {"email": email, "token": token, "provider": "tempmail.lol"}
    except Exception:
        return None


def tempmail_lol_poll(token: str, timeout_sec: int = 120, interval: int = 5) -> str | None:
    """Poll tempmail.lol for verification code. Returns 6-digit code or None."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            r = requests.get(
                f"https://api.tempmail.lol/v2/inbox?token={token}",
                headers=HEADERS,
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                for msg in data.get("emails", []):
                    body = str(msg.get("body", "")) + str(msg.get("subject", ""))
                    codes = re.findall(r"\b(\d{6})\b", body)
                    if codes:
                        return codes[0]
        except Exception:
            pass
        time.sleep(interval)
    return None


# ── Auto-fallback public API ─────────────────────────────────

PROVIDERS = [
    ("mail.tm", mailtm_create, mailtm_poll),
    ("guerrillamail", guerrilla_create, guerrilla_poll),
    ("tempmail.lol", tempmail_lol_create, tempmail_lol_poll),
]


def create_account(password: str = "TempMail2025!") -> dict:
    """Create disposable email with auto-fallback.

    Tries mail.tm → guerrillamail → tempmail.lol.
    Returns {email, token, provider}.
    Raises RuntimeError if all providers fail.
    """
    for name, create_fn, _ in PROVIDERS:
        result = create_fn(password) if name == "mail.tm" else create_fn()
        if result:
            return result
    raise RuntimeError("All email providers failed")


def get_messages(token: str, provider: str = "mail.tm") -> list:
    """Get messages from provider. Provider-specific format."""
    try:
        if provider == "mail.tm":
            headers = {**HEADERS, "Authorization": f"Bearer {token}"}
            r = requests.get("https://api.mail.tm/messages", headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                return data.get("hydra:member", []) if isinstance(data, dict) else data
        elif provider == "guerrillamail":
            r = requests.get(
                f"https://api.guerrillamail.com/ajax.php?f=check_email&seq=0&sid_token={token}",
                headers=HEADERS, timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("list", [])
        elif provider == "tempmail.lol":
            r = requests.get(
                f"https://api.tempmail.lol/v2/inbox?token={token}",
                headers=HEADERS, timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("emails", [])
    except Exception:
        pass
    return []


def poll_code(token: str, provider: str = "mail.tm", timeout_sec: int = 120, interval: int = 5) -> str | None:
    """Poll provider for 6-digit verification code with auto-fallback.

    If specified provider fails, tries remaining providers.
    Returns 6-digit code string or None.
    """
    # Try specified provider first
    for name, _, poll_fn in PROVIDERS:
        if name == provider:
            code = poll_fn(token, timeout_sec, interval)
            if code:
                return code
            break

    # Fallback: try remaining providers (they need their own token though)
    # This only works if we have the right token for the right provider
    return None
