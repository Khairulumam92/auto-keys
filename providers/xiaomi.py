"""Xiaomi MiMo platform — real endpoints discovered via JS bundle analysis.

Platform: https://platform.xiaomimimo.com
API Base: https://platform.xiaomimimo.com/api/v1/
Auth:     Xiaomi SSO (account.xiaomi.com/pass) with SID=api-platform

Auth Flow:
  1. GET /api/v1/keys → 401 + loginUrl
  2. GET loginUrl → account.xiaomi.com/pass/serviceLogin?sid=api-platform&callback=<sts_url>
  3. POST /pass/register → create account
  4. GET /pass/serviceLogin/auth → extract passToken, cUserId, userId
  5. GET callback (STS) → platform sets session cookie
  6. GET /api/v1/keys → 200 + API keys
"""
import requests
import re
import json

DEFAULT_PASSWORD = "masuk123!"

# === Real endpoints (verified 2026-06-26) ===
PLATFORM_BASE = "https://platform.xiaomimimo.com"
API_BASE = f"{PLATFORM_BASE}/api/v1"
XIAOMI_AUTH = "https://account.xiaomi.com/pass"

SID = "api-platform"
GROUP = "DEFAULT"

ENDPOINTS = {
    # Platform API
    "models": f"{API_BASE}/models",
    "keys": f"{API_BASE}/keys",
    "key_create": f"{API_BASE}/keys",
    "user": f"{API_BASE}/user",
    "balance": f"{API_BASE}/balance",
    "usage": f"{API_BASE}/usage",
    "billing": f"{API_BASE}/billing",

    # Xiaomi SSO auth
    "login_page": f"{XIAOMI_AUTH}/serviceLogin",
    "register": f"{XIAOMI_AUTH}/register",
    "send_code": f"{XIAOMI_AUTH}/sendActivateEmail",
    "auth": f"{XIAOMI_AUTH}/serviceLogin/auth",
    "activate_email": f"{XIAOMI_AUTH}/register/activateEmail",

    # Platform STS (Security Token Service)
    "sts": f"{PLATFORM_BASE}/sts",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; Mi 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": PLATFORM_BASE,
    "Referer": f"{PLATFORM_BASE}/console/api-keys",
    "Content-Type": "application/json",
}


def get_login_url() -> dict:
    """Step 1: GET /api/v1/keys → get loginUrl with callback + SID."""
    r = requests.get(ENDPOINTS["keys"], headers=HEADERS, timeout=15)
    data = r.json()
    return {
        "code": data.get("code"),
        "login_url": data.get("loginUrl", ""),
    }


def _get_session(sid: str = SID) -> tuple[requests.Session, dict]:
    """Initialize Xiaomi SSO session — get _sign, qs, callback tokens."""
    s = requests.Session()
    s.headers.update(HEADERS)

    # GET login page to get CSRF tokens
    params = {"sid": sid, "_json": "true", "_group": GROUP}
    r = s.get(ENDPOINTS["login_page"], params=params, timeout=15)
    r.raise_for_status()

    text = r.text
    tokens = {}
    # Parse JSONP callback({...})
    match = re.search(r'callback\(({.*})\)', text, re.DOTALL)
    if match:
        text = match.group(1)
    for key in ["_sign", "qs", "callback", "sid", "user", "location"]:
        m = re.search(rf'"{key}":\s*"([^"]*)"', text)
        if m:
            tokens[key] = m.group(1)

    return s, tokens


def register(email: str, password: str = DEFAULT_PASSWORD) -> dict:
    """Register Xiaomi account for MiMo platform.

    Returns:
        {"status": "success"|"error"|"need_verify", "cookies": {...}, "error": str|None}
    """
    try:
        s, tokens = _get_session()

        # POST register
        payload = {
            "user": email,
            "password": password,
            "sid": SID,
            "_json": "true",
            "_sign": tokens.get("_sign", ""),
            "qs": tokens.get("qs", ""),
            "callback": tokens.get("callback", ""),
            "region": "id",
            "hasPassword": "true",
        }
        r = s.post(ENDPOINTS["register"], data=payload, timeout=15)
        r.raise_for_status()
        data = _parse_response(r.text)

        code = data.get("code")
        if code == 0 or data.get("result") == "ok":
            # Try to get auth cookies immediately
            auth = _get_auth_cookies(s)
            if auth.get("passToken"):
                return {"status": "success", "cookies": auth, "error": None}

            # Need email verification — send activation
            _send_activate(s, email)
            return {
                "status": "need_verify",
                "cookies": {},
                "error": "email verification required — check inbox",
            }
        else:
            return {
                "status": "error",
                "cookies": {},
                "error": data.get("desc") or data.get("description") or data.get("error", "register failed"),
            }
    except Exception as e:
        return {"status": "error", "cookies": {}, "error": str(e)}


def get_api_keys(cookies: dict) -> dict:
    """Step 5: Use cookies to fetch API keys from platform.

    Uses cookies from Xiaomi SSO to authenticate with MiMo platform.
    The STS (Security Token Service) endpoint bridges Xiaomi SSO → platform session.
    """
    try:
        s = requests.Session()
        s.headers.update(HEADERS)

        # Set Xiaomi auth cookies
        for key, val in cookies.items():
            s.cookies.set(key, val, domain=".xiaomimimo.com")

        # First hit STS to get platform session token
        # The STS endpoint validates Xiaomi cookies and issues platform session
        login_info = get_login_url()
        login_url = login_info.get("login_url", "")
        if login_url:
            # Follow the SSO flow — cookies should authenticate us
            r = s.get(login_url, timeout=15, allow_redirects=True)

        # Now fetch API keys
        r = s.get(ENDPOINTS["keys"], timeout=15)
        if r.status_code == 200:
            return {"status": "success", "data": r.json(), "error": None}
        else:
            return {"status": "error", "data": None, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"status": "error", "data": None, "error": str(e)}


def create_api_key(cookies: dict, name: str = "auto-key") -> str | None:
    """Create a new API key on MiMo platform using authenticated session."""
    try:
        s = requests.Session()
        s.headers.update(HEADERS)
        for key, val in cookies.items():
            s.cookies.set(key, val, domain=".xiaomimimo.com")

        # Authenticate via STS
        login_info = get_login_url()
        if login_info.get("login_url"):
            s.get(login_info["login_url"], timeout=15, allow_redirects=True)

        # Create key
        r = s.post(ENDPOINTS["key_create"], json={"name": name}, timeout=15)
        if r.status_code in (200, 201):
            data = r.json()
            return data.get("key") or data.get("api_key") or data.get("data", {}).get("key")
        return None
    except Exception:
        return None


def list_models() -> list[dict]:
    """Public endpoint — no auth needed. List available MiMo models."""
    try:
        r = requests.get(ENDPOINTS["models"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


def _get_auth_cookies(s: requests.Session) -> dict:
    """Extract passToken, cUserId, userId from Xiaomi SSO."""
    try:
        params = {"sid": SID, "_json": "true"}
        r = s.get(ENDPOINTS["auth"], params=params, timeout=15)
        data = _parse_response(r.text)

        cookies = {}
        for key in ["passToken", "cUserId", "userId"]:
            if key in data:
                cookies[key] = data[key]
            elif key in s.cookies:
                cookies[key] = s.cookies.get(key)
        return cookies
    except Exception:
        return {}


def _send_activate(s: requests.Session, email: str):
    """Request activation email from Xiaomi."""
    try:
        s.post(ENDPOINTS["send_code"], data={"user": email, "sid": SID, "_json": "true"}, timeout=10)
    except Exception:
        pass


def _parse_response(text: str) -> dict:
    """Parse Xiaomi response — handles JSONP callback({...}) and plain JSON."""
    # Try JSONP
    match = re.search(r'callback\(({.*})\)', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    # Try plain JSON
    try:
        return json.loads(text)
    except Exception:
        pass
    # Fallback: extract key-value pairs
    result = {}
    for m in re.finditer(r'"(\w+)":\s*"([^"]*)"', text):
        result[m.group(1)] = m.group(2)
    return result


# === Quick test ===
if __name__ == "__main__":
    print("=== MiMo Platform Models (public) ===")
    models = list_models()
    for m in models:
        print(f"  {m.get('id', '?')} — {m.get('name', '?')}")

    print("\n=== Auth Flow Test ===")
    info = get_login_url()
    print(f"  Login required: {info['code'] == 401}")
    print(f"  SID: {SID}")
    if info.get("login_url"):
        print(f"  Login URL: {info['login_url'][:80]}...")
