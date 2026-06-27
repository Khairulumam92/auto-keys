#!/usr/bin/env python3
"""Gmail OAuth-based OTP reader — polls Gmail API for verification codes.

More reliable than disposable email polling:
- No disposable email domain blocking
- Instant delivery (Gmail push)
- No rate limiting on personal accounts

Setup:
1. Create OAuth 2.0 credentials at console.cloud.google.com
2. Enable Gmail API
3. Download client_secret.json to this directory
4. Run: python3 gmail_otp.py --authorize user@gmail.com
"""
import base64
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

TOKEN_FILE = Path(__file__).parent / "gmail_tokens.json"
CLIENT_SECRET_FILE = Path(__file__).parent / "client_secret.json"
REDIRECT_URI = "http://localhost:8085/callback"


def _load_tokens() -> dict:
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return {"default_client": {}, "accounts": {}}


def _save_tokens(data: dict):
    tmp = TOKEN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(TOKEN_FILE)


def _client_creds(data: dict, email: str) -> tuple:
    acc = data["accounts"].setdefault(email, {})
    cid = acc.get("client_id") or data.get("default_client", {}).get("client_id", "")
    csec = acc.get("client_secret") or data.get("default_client", {}).get("client_secret", "")
    return cid, csec


def _refresh_token(email: str, data: dict) -> str:
    acc = data["accounts"][email]
    rt = acc.get("refresh_token")
    if not rt:
        raise RuntimeError(f"No refresh_token for {email}. Run: python3 gmail_otp.py --authorize {email}")

    cid, csec = _client_creds(data, email)
    body = urllib.parse.urlencode({
        "client_id": cid,
        "client_secret": csec,
        "refresh_token": rt,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    acc["access_token"] = resp["access_token"]
    acc["expires_at"] = int(time.time()) + resp.get("expires_in", 3600)
    _save_tokens(data)
    return acc["access_token"]


def get_access_token(email: str) -> str:
    data = _load_tokens()
    acc = data["accounts"].get(email, {})
    if acc.get("access_token") and acc.get("expires_at", 0) > time.time() + 60:
        return acc["access_token"]
    if acc.get("refresh_token"):
        return _refresh_token(email, data)
    raise RuntimeError(f"No token for {email}. Run: python3 gmail_otp.py --authorize {email}")


def normalize_gmail(email: str) -> str:
    """Map Gmail alias (dots/plus) to real inbox address."""
    local, domain = email.rsplit("@", 1)
    if domain.lower() in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
        if "+" in local:
            local = local.split("+", 1)[0]
    return f"{local}@{domain}"


def poll_otp(email: str, sender: str = "system_sg@notice.qwencloud.com",
             timeout_sec: int = 90, interval: float = 2.0,
             min_date_ms: int = 0) -> Optional[str]:
    """Poll Gmail API for 6-digit verification code from Qwen Cloud.

    Args:
        email: Gmail address (dot aliases OK — routes to real inbox)
        sender: Email sender to filter (default: Qwen Cloud)
        timeout_sec: Max wait time
        interval: Poll interval in seconds
        min_date_ms: Ignore emails before this timestamp (ms)

    Returns:
        6-digit code string or None on timeout
    """
    access_token = get_access_token(normalize_gmail(email))
    q = urllib.parse.quote(f"from:{sender}")
    list_url = f"https://www.googleapis.com/gmail/v1/users/me/messages?q={q}&maxResults=10"
    deadline = time.time() + timeout_sec

    def _extract_code(payload: dict, mime: str) -> str:
        if payload.get("mimeType") == mime and "data" in payload.get("body", {}):
            text = base64.urlsafe_b64decode(payload["body"]["data"]).decode(errors="ignore")
            m = re.search(r"\b(\d{6})\b", text)
            if m:
                return m.group(1)
        for p in payload.get("parts", []):
            code = _extract_code(p, mime)
            if code:
                return code
        return ""

    while time.time() < deadline:
        try:
            req = urllib.request.Request(list_url, headers={"Authorization": f"Bearer {access_token}"})
            data = json.loads(urllib.request.urlopen(req, timeout=30).read())
            for m in data.get("messages", []):
                r = urllib.request.Request(
                    f"https://www.googleapis.com/gmail/v1/users/me/messages/{m['id']}?format=full",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                d = json.loads(urllib.request.urlopen(r, timeout=30).read())
                if min_date_ms and int(d.get("internalDate", 0)) < min_date_ms:
                    continue
                headers = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
                to = headers.get("To", "").replace("<", "").replace(">", "")
                if normalize_gmail(email) not in normalize_gmail(to):
                    continue
                code = _extract_code(d.get("payload", {}), "text/plain")
                if not code:
                    code = _extract_code(d.get("payload", {}), "text/html")
                if code:
                    return code
        except Exception:
            pass
        time.sleep(interval)
    return None


def authorize(email: str):
    """Interactive OAuth authorization flow."""
    data = _load_tokens()
    if not CLIENT_SECRET_FILE.exists():
        print(f"Error: {CLIENT_SECRET_FILE} not found.")
        print("Download from console.cloud.google.com -> APIs -> Credentials -> OAuth 2.0")
        sys.exit(1)

    creds = json.loads(CLIENT_SECRET_FILE.read_text())
    client = creds.get("installed") or creds.get("web", {})
    cid = client["client_id"]
    csec = client["client_secret"]

    data.setdefault("default_client", {"client_id": cid, "client_secret": csec})

    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={cid}&redirect_uri={REDIRECT_URI}"
        f"&response_type=code&scope=https://www.googleapis.com/auth/gmail.readonly"
        f"&access_type=offline&prompt=consent"
    )
    print(f"\nOpen this URL in a browser:\n\n  {auth_url}\n")
    code = input("Paste the authorization code: ").strip()

    body = urllib.parse.urlencode({
        "code": code,
        "client_id": cid,
        "client_secret": csec,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())

    acc = data["accounts"].setdefault(normalize_gmail(email), {})
    acc.update(resp)
    acc["client_id"] = cid
    acc["client_secret"] = csec
    acc["expires_at"] = int(time.time()) + resp.get("expires_in", 3600)
    _save_tokens(data)
    print(f"\n✅ Authorized {email}. Token saved to {TOKEN_FILE}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorize", metavar="EMAIL", help="Authorize Gmail account")
    parser.add_argument("--test", metavar="EMAIL", help="Test OTP poll")
    args = parser.parse_args()

    if args.authorize:
        authorize(args.authorize)
    elif args.test:
        print(f"Polling for OTP for {args.test}...")
        code = poll_otp(args.test, timeout_sec=120)
        if code:
            print(f"✅ Code: {code}")
        else:
            print("❌ No code found in 120s")
    else:
        print("Usage:")
        print("  python3 gmail_otp.py --authorize user@gmail.com")
        print("  python3 gmail_otp.py --test user@gmail.com")
