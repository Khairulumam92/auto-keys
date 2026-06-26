"""Alibaba/DashScope (Qwen) account registration framework.

Uses DashScope API console endpoints.
Endpoints are proprietary — replace after RE current DashScope auth flow.
"""
import requests

# ponytail: placeholder — replace after RE
BASE_URL = "https://dashscope.console.aliyun.com"
REGISTER_URL = f"{BASE_URL}/api/account/register"
APIKEY_URL = f"{BASE_URL}/api/apikey/create"
DEFAULT_PASSWORD = "masuk123!"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14)",
    "Content-Type": "application/json",
}


def register(email: str, password: str = DEFAULT_PASSWORD) -> dict:
    """Register DashScope account.

    Returns:
        {"status": "success"|"error", "cookies": {...}, "error": str|None}
    """
    payload = {
        "email": email,
        "password": password,
        "region": "cn",
    }
    try:
        r = requests.post(REGISTER_URL, json=payload, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("Code") and data["Code"] != "200":
            return {"status": "error", "cookies": {}, "error": data.get("Message", "register failed")}

        cookies = {
            "session": data.get("Session", ""),
            "csrfToken": data.get("CsrfToken", ""),
            "accountId": data.get("AccountId", ""),
        }
        return {"status": "success", "cookies": cookies, "error": None}
    except Exception as e:
        return {"status": "error", "cookies": {}, "error": str(e)}


def create_api_key(cookies: dict) -> str | None:
    """Create API key using authenticated session.

    ponytail: endpoint/params unknown — implement after RE DashScope console.
    """
    # Placeholder: POST to APIKEY_URL with session cookies
    return None
