"""Alibaba Cloud / Qwen Cloud account registration.

Auth flow (discovered via probing):
  1. Register → account.alibabacloud.com/sso/register.htm
  2. Login   → account.alibabacloud.com/sso/login.htm?client_id=qwencloud
  3. OAuth   → account.qwencloud.com/sso/ssoLogin (code callback)
  4. DashScope → dashscope.console.aliyun.com (API keys)

Platform: https://home.qwencloud.com
Auth:     Alibaba Cloud SSO (OAuth2, client_id=qwencloud)
"""
import requests

# ponytail: OAuth flow complex — Selenium may be needed for SSO registration
ALIBABA_SSO = "https://account.alibabacloud.com"
QWEN_CLOUD = "https://home.qwencloud.com"
QWEN_ACCOUNT = "https://account.qwencloud.com"
DASHSCOPE = "https://dashscope.console.aliyun.com"

ENDPOINTS = {
    "register": f"{ALIBABA_SSO}/sso/register.htm",
    "login": f"{ALIBABA_SSO}/sso/login.htm",
    "oauth_login": f"{ALIBABA_SSO}/sso/login.htm?response_type=code&client_id=qwencloud&scope=openid&redirect_uri=https%3A%2F%2Faccount.qwencloud.com%2Fsso%2FssoLogin",
    "oauth_callback": f"{QWEN_ACCOUNT}/sso/ssoLogin",
    "dashscope": DASHSCOPE,
    "apikey_create": f"{DASHSCOPE}/api/apikey/create",
    "apikey_list": f"{DASHSCOPE}/api/apikey/list",
    "models": f"{DASHSCOPE}/api/models",
}

DEFAULT_PASSWORD = "masuk123!"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def register(email: str, password: str = DEFAULT_PASSWORD) -> dict:
    """Register Alibaba Cloud account (which grants Qwen Cloud access).

    ponytail: SSO registration likely needs CAPTCHA or SMS verification.
    If automated registration fails, use Selenium to fill the form manually.
    """
    s = requests.Session()
    s.headers.update(HEADERS)

    # Step 1: Get registration page (extract CSRF tokens)
    try:
        r = s.get(ENDPOINTS["register"], timeout=15)
        r.raise_for_status()
    except Exception as e:
        return {"status": "error", "cookies": {}, "error": f"page load: {e}"}

    # Step 2: Submit registration form
    # ponytail: exact payload fields unknown — needs RE of registration API
    # Typical Alibaba Cloud registration needs: email, password, verification code
    payload = {
        "email": email,
        "password": password,
        "confirmPassword": password,
        "region": "intl",
        "accountType": "individual",
    }

    try:
        # Try common Alibaba registration API endpoint
        r = s.post(
            f"{ALIBABA_SSO}/sso/api/register",
            json=payload,
            timeout=15,
        )
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code in (200, 201) and data.get("success"):
            cookies = dict(s.cookies)
            return {"status": "success", "cookies": cookies, "error": None}
        return {"status": "error", "cookies": {}, "error": data.get("message", f"HTTP {r.status_code}")}
    except Exception as e:
        return {"status": "error", "cookies": {}, "error": str(e)}


def login(email: str, password: str = DEFAULT_PASSWORD) -> dict:
    """Login via Alibaba Cloud SSO with Qwen Cloud OAuth redirect.

    Returns session cookies valid for DashScope console.
    """
    s = requests.Session()
    s.headers.update(HEADERS)

    try:
        r = s.get(ENDPOINTS["oauth_login"], timeout=15)
        r.raise_for_status()
    except Exception as e:
        return {"status": "error", "cookies": {}, "error": f"login page: {e}"}

    # ponytail: SSO login form fields need RE — typical: loginId, password, _csrf
    payload = {
        "loginId": email,
        "password": password,
    }

    try:
        r = s.post(
            f"{ALIBABA_SSO}/sso/api/login",
            json=payload,
            timeout=15,
            allow_redirects=True,
        )
        cookies = dict(s.cookies)
        if cookies.get("SESSION") or cookies.get("cna") or "qwencloud" in r.url:
            return {"status": "success", "cookies": cookies, "error": None}
        return {"status": "error", "cookies": cookies, "error": f"login failed (HTTP {r.status_code})"}
    except Exception as e:
        return {"status": "error", "cookies": {}, "error": str(e)}


def create_api_key(cookies: dict) -> str | None:
    """Create API key on DashScope console using session cookies.

    ponytail: exact endpoint params unknown — needs RE of DashScope API.
    """
    s = requests.Session()
    s.headers.update(HEADERS)
    for key, val in cookies.items():
        s.cookies.set(key, val, domain=".aliyun.com")
        s.cookies.set(key, val, domain="dashscope.console.aliyun.com")

    try:
        r = s.post(
            ENDPOINTS["apikey_create"],
            json={"name": f"auto-key-{__import__('time').time():.0f}"},
            timeout=15,
        )
        if r.status_code in (200, 201):
            data = r.json()
            return data.get("apiKey") or data.get("data", {}).get("apiKey")
    except Exception:
        pass
    return None


if __name__ == "__main__":
    print("📌 Qwen Cloud / Alibaba Cloud endpoints:")
    for name, url in ENDPOINTS.items():
        print(f"  {name:20s} {url}")
