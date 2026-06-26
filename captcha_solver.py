"""Xiaomi CAPTCHA handler — dual approach: Selenium manual + 2captcha API.

Xiaomi CAPTCHA flow:
  1. GET /pass/getCode?icodeType=register → gambar CAPTCHA (base64)
  2. Solve → dapat code
  3. POST /pass/register + icode + callback → register success
"""
import requests
import base64
import time
import json

DEFAULT_PASSWORD = "masuk123!"
CAPTCHA_URL = "https://account.xiaomi.com/pass/getCode"
REGISTER_URL = "https://account.xiaomi.com/pass/register"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; Mi 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://account.xiaomi.com/pass/register",
}


def fetch_captcha(session: requests.Session, icode_type: str = "register") -> dict:
    """Fetch CAPTCHA image from Xiaomi.

    Returns:
        {"image_base64": str, "cookies": dict, "error": str|None}
    """
    try:
        params = {"icodeType": icode_type, "_dc": str(int(time.time() * 1000))}
        r = session.get(CAPTCHA_URL, params=params, headers=HEADERS, timeout=15)

        content_type = r.headers.get("content-type", "")
        if "image" in content_type or "octet-stream" in content_type:
            img_b64 = base64.b64encode(r.content).decode()
            return {"image_base64": img_b64, "cookies": dict(session.cookies), "error": None}
        else:
            # Sometimes returns JSON with captcha URL
            try:
                data = r.json()
                return {"image_base64": None, "cookies": dict(session.cookies), "error": data.get("desc", "not image")}
            except Exception:
                return {"image_base64": None, "cookies": dict(session.cookies), "error": f"unexpected content-type: {content_type}"}
    except Exception as e:
        return {"image_base64": None, "cookies": {}, "error": str(e)}


def solve_with_2captcha(api_key: str, image_base64: str, timeout: int = 120) -> str | None:
    """Solve image CAPTCHA using 2captcha API.

    Cost: ~$2.99/1000 solves. Speed: ~10-30s per solve.
    Requires: pip install 2captcha-python
    """
    try:
        from twocaptcha import TwoCaptcha
        solver = TwoCaptcha(api_key)
        result = solver.normal(image_base64)
        return result.get("code")
    except ImportError:
        return None
    except Exception:
        return None


def solve_with_capsolver(api_key: str, image_base64: str, timeout: int = 120) -> str | None:
    """Solve image CAPTCHA using Capsolver API.

    Cost: ~$0.4/1000 solves. Speed: ~5-15s per solve.
    """
    try:
        payload = {
            "clientKey": api_key,
            "task": {
                "type": "ImageToTextTask",
                "body": image_base64,
            }
        }
        r = requests.post("https://api.capsolver.com/createTask", json=payload, timeout=15)
        data = r.json()
        task_id = data.get("taskId")
        if not task_id:
            return None

        # Poll for result
        deadline = time.time() + timeout
        while time.time() < deadline:
            r2 = requests.post("https://api.capsolver.com/getTaskResult", json={"clientKey": api_key, "taskId": task_id}, timeout=15)
            result = r2.json()
            if result.get("status") == "ready":
                return result.get("solution", {}).get("text")
            time.sleep(3)
        return None
    except Exception:
        return None


def register_with_captcha(
    email: str,
    password: str = DEFAULT_PASSWORD,
    solver: str = "manual",
    solver_key: str = None,
    sid: str = "api-platform",
) -> dict:
    """Full register flow with CAPTCHA solving.

    Args:
        solver: "manual" (print base64 to stdout, user types), "2captcha", "capsolver"
        solver_key: API key for 2captcha or capsolver

    Returns:
        {"status": "success"|"error", "cookies": {...}, "error": str|None}
    """
    s = requests.Session()
    s.headers.update(HEADERS)

    # Step 1: GET login page for tokens
    r = s.get(f"https://account.xiaomi.com/pass/serviceLogin?sid={sid}&_json=true&_group=DEFAULT", timeout=15)
    import re
    text = r.text
    match = re.search(r'&&&START&&&({.*})', text, re.DOTALL)
    if not match:
        match = re.search(r'callback\(({.*})\)', text, re.DOTALL)
    if match:
        data = json.loads(match.group(1))
    else:
        return {"status": "error", "cookies": {}, "error": "failed to parse login page"}

    sign = data.get("_sign", "")
    qs = data.get("qs", "")
    callback = data.get("callback", "")

    # Step 2: Fetch CAPTCHA
    captcha_result = fetch_captcha(s)
    if captcha_result.get("error") and not captcha_result.get("image_base64"):
        return {"status": "error", "cookies": {}, "error": f"CAPTCHA fetch failed: {captcha_result['error']}"}

    # Step 3: Solve CAPTCHA
    icode = None
    if solver == "manual":
        img = captcha_result.get("image_base64", "")
        print(f"\n🔑 CAPTCHA image (base64, first 100 chars): {img[:100]}...")
        print(f"   Full base64 length: {len(img)}")
        print(f"   Paste base64 into browser: data:image/png;base64,{img[:50]}...")
        icode = input("   Enter CAPTCHA code: ").strip()
    elif solver == "2captcha" and solver_key:
        icode = solve_with_2captcha(solver_key, captcha_result["image_base64"])
    elif solver == "capsolver" and solver_key:
        icode = solve_with_capsolver(solver_key, captcha_result["image_base64"])

    if not icode:
        return {"status": "error", "cookies": {}, "error": "CAPTCHA not solved"}

    # Step 4: POST register with CAPTCHA code
    payload = {
        "user": email,
        "password": password,
        "sid": sid,
        "_json": "true",
        "_sign": sign,
        "qs": qs,
        "callback": callback,
        "region": "id",
        "hasPassword": "true",
        "icode": icode,
    }
    r2 = s.post(REGISTER_URL, data=payload, timeout=15)
    text2 = r2.text

    match2 = re.search(r'&&&START&&&({.*})', text2, re.DOTALL)
    if not match2:
        match2 = re.search(r'callback\(({.*})\)', text2, re.DOTALL)
    if match2:
        result = json.loads(match2.group(1))
    else:
        return {"status": "error", "cookies": {}, "error": f"unexpected response: {text2[:200]}"}

    if result.get("code") == 0 or result.get("result") == "ok":
        # Extract cookies
        auth_cookies = {}
        for key in ["passToken", "cUserId", "userId"]:
            if key in result:
                auth_cookies[key] = result[key]
            elif key in s.cookies:
                auth_cookies[key] = s.cookies.get(key)

        if not auth_cookies.get("passToken"):
            # Try auth endpoint
            r3 = s.get(f"https://account.xiaomi.com/pass/serviceLogin/auth?sid={sid}&_json=true", timeout=15)
            match3 = re.search(r'&&&START&&&({.*})', r3.text, re.DOTALL)
            if match3:
                auth_data = json.loads(match3.group(1))
                for key in ["passToken", "cUserId", "userId"]:
                    if key in auth_data:
                        auth_cookies[key] = auth_data[key]

        return {"status": "success", "cookies": auth_cookies, "error": None}
    else:
        return {
            "status": "error",
            "cookies": {},
            "error": result.get("desc") or result.get("description") or result.get("reason", "register failed"),
        }


if __name__ == "__main__":
    import sys
    from providers.tempmail import create_account

    solver = sys.argv[1] if len(sys.argv) > 1 else "manual"
    solver_key = sys.argv[2] if len(sys.argv) > 2 else None

    acc = create_account()
    print(f"📧 Email: {acc['email']}")

    result = register_with_captcha(acc["email"], solver=solver, solver_key=solver_key)
    print(f"Status: {result['status']}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    if result.get("cookies"):
        print(f"Cookies: {json.dumps(result['cookies'], indent=2)}")
