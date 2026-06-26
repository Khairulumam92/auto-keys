"""Full auto pipeline: disposable email → Xiaomi register → MiMo API keys.

Flow:
  1. Create disposable email (mail.tm)
  2. Register at account.xiaomi.com (CAPTCHA via ddddocr)
  3. Email verification (auto-click link from mail.tm inbox)
  4. Login → account.xiaomi.com/pass/serviceLogin?sid=api-platform
  5. Redirect → platform.xiaomimimo.com/sts → cookies set
  6. Fetch API keys → platform.xiaomimimo.com/api/v1/keys
"""
import requests
import re
import json
import time
import base64

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from providers.tempmail import create_account, get_messages, get_message, extract_links

DEFAULT_PASSWORD = "masuk123!"
PLATFORM_BASE = "https://platform.xiaomimimo.com"
API_BASE = f"{PLATFORM_BASE}/api/v1"
SID = "api-platform"
GROUP = "DEFAULT"

XIAOMI_BASE = "https://account.xiaomi.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; Mi 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{XIAOMI_BASE}/pass/serviceLogin",
}


def _parse_xiaomi_response(text: str) -> dict:
    """Parse Xiaomi response — handles &&&START&&&{...}, JSONP callback({...}), and plain JSON."""
    # &&&START&&& format (most common from Xiaomi)
    match = re.search(r'&&&START&&&({.*})', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    # JSONP
    match = re.search(r'callback\(({.*})\)', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    # Plain JSON
    try:
        return json.loads(text)
    except Exception:
        pass
    # Fallback
    result = {}
    for m in re.finditer(r'"(\w+)":\s*"([^"]*)"', text):
        result[m.group(1)] = m.group(2)
    return result


def solve_captcha(session: requests.Session, max_retries: int = 5) -> str | None:
    """Fetch + solve Xiaomi CAPTCHA with ddddocr. Retry with fresh CAPTCHA on each attempt.

    Each retry fetches a NEW CAPTCHA image (new ick cookie) to avoid stale token.
    """
    try:
        import ddddocr
    except ImportError:
        return None

    ocr = ddddocr.DdddOcr(show_ad=False)

    for attempt in range(1, max_retries + 1):
        # Fresh CAPTCHA each attempt — ick cookie must match the image
        params = {"icodeType": "register", "_dc": str(int(time.time() * 1000))}
        r = session.get(f"{XIAOMI_BASE}/pass/getCode", params=params, timeout=15)
        if r.status_code != 200 or len(r.content) < 100:
            continue

        # Preprocessing: denoise + threshold for better OCR accuracy
        img_bytes = r.content
        try:
            from PIL import Image, ImageFilter
            import io
            img = Image.open(io.BytesIO(img_bytes))
            img = img.convert("L")  # grayscale
            img = img.point(lambda x: 0 if x < 140 else 255)  # binary threshold
            img = img.filter(ImageFilter.MedianFilter(3))  # denoise
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            img_bytes = buf.getvalue()
        except ImportError:
            pass  # no PIL, use raw image

        code = ocr.classification(img_bytes)

        # Validate: Xiaomi CAPTCHA is 4-6 alphanumeric chars
        if code and 3 <= len(code) <= 8 and code.isalnum():
            return code
        # If weird result, try raw image (sometimes preprocessing hurts)
        if attempt <= 2:
            code_raw = ocr.classification(r.content)
            if code_raw and 3 <= len(code_raw) <= 8 and code_raw.isalnum():
                return code_raw

    return None


def auto_register(email: str, password: str = DEFAULT_PASSWORD, verbose: bool = False) -> dict:
    """Full auto register + login + get API keys.

    Returns:
        {"status": "success"|"error", "email": str, "cookies": {...}, "api_keys": [...], "error": str|None}
    """
    result = {
        "email": email,
        "password": password,
        "cookies": {},
        "api_keys": [],
        "status": "error",
        "error": None,
    }

    s = requests.Session()
    s.headers.update(HEADERS)

    # ========== STEP 1: GET login page (get _sign, qs, callback) ==========
    if verbose:
        print("  [1/5] Getting login page tokens...")
    r = s.get(f"{XIAOMI_BASE}/pass/serviceLogin?sid={SID}&_json=true&_group={GROUP}", timeout=15)
    data = _parse_xiaomi_response(r.text)
    sign = data.get("_sign", "")
    qs = data.get("qs", "")
    callback = data.get("callback", "")

    if not sign:
        result["error"] = f"failed to get _sign: {data.get('description', data.get('code', 'unknown'))}"
        return result

    if verbose:
        print(f"  [1/5] OK — _sign={sign[:20]}...")

    # ========== STEP 2: Solve CAPTCHA ==========
    if verbose:
        print("  [2/5] Solving CAPTCHA with ddddocr...")
    icode = solve_captcha(s)
    if not icode:
        result["error"] = "CAPTCHA solve failed"
        return result
    if verbose:
        print(f"  [2/5] Solved: \"{icode}\"")

    # ========== STEP 3: Register ==========
    if verbose:
        print(f"  [3/5] Registering {email}...")
    payload = {
        "user": email,
        "password": password,
        "sid": SID,
        "_json": "true",
        "_sign": sign,
        "qs": qs,
        "callback": callback,
        "region": "id",
        "hasPassword": "true",
        "icode": icode,
    }
    r2 = s.post(f"{XIAOMI_BASE}/pass/register", data=payload, timeout=15)
    reg_data = _parse_xiaomi_response(r2.text)

    if reg_data.get("code") not in (0, None) and reg_data.get("result") != "ok":
        err_code = reg_data.get("code")
        err_desc = reg_data.get("desc") or reg_data.get("description") or reg_data.get("reason", "unknown")

        # If CAPTCHA wrong, retry once
        if err_code == 87001 or "CAPTCHA" in str(err_desc).upper() or "验证码" in str(err_desc):
            if verbose:
                print(f"  [3/5] CAPTCHA wrong, retrying...")
            icode = solve_captcha(s)
            if icode:
                payload["icode"] = icode
                r2 = s.post(f"{XIAOMI_BASE}/pass/register", data=payload, timeout=15)
                reg_data = _parse_xiaomi_response(r2.text)
                if reg_data.get("code") == 0 or reg_data.get("result") == "ok":
                    pass  # success on retry
                else:
                    result["error"] = f"register failed after retry: {reg_data.get('desc', reg_data.get('code'))}"
                    return result
            else:
                result["error"] = "CAPTCHA retry failed"
                return result
        else:
            result["error"] = f"register failed: {err_desc} (code={err_code})"
            return result

    if verbose:
        print(f"  [3/5] Register OK")

    # ========== STEP 4: Get auth cookies (passToken, cUserId, userId) ==========
    if verbose:
        print("  [4/5] Getting auth cookies...")
    auth_cookies = {}

    # Method A: Check cookies already in session
    for key in ["passToken", "cUserId", "userId"]:
        if key in s.cookies:
            auth_cookies[key] = s.cookies.get(key)

    # Method B: Hit auth endpoint
    if not auth_cookies.get("passToken"):
        r3 = s.get(f"{XIAOMI_BASE}/pass/serviceLogin/auth?sid={SID}&_json=true", timeout=15)
        auth_data = _parse_xiaomi_response(r3.text)
        for key in ["passToken", "cUserId", "userId"]:
            if key in auth_data:
                auth_cookies[key] = auth_data[key]

    # Method C: Email verification flow
    if not auth_cookies.get("passToken"):
        if verbose:
            print("  [4/5] No passToken — trying email verification...")
        try:
            msgs = get_messages(s.cookies.get("_email_token", ""), wait=20)
            if msgs:
                msg = get_message(s.cookies.get("_email_token", ""), msgs[0]["id"])
                body = msg.get("text", "") or ""
                links = extract_links(body)
                if links:
                    requests.get(links[0], timeout=10, allow_redirects=True)
                    # Retry auth
                    r4 = s.get(f"{XIAOMI_BASE}/pass/serviceLogin/auth?sid={SID}&_json=true", timeout=15)
                    auth_data = _parse_xiaomi_response(r4.text)
                    for key in ["passToken", "cUserId", "userId"]:
                        if key in auth_data:
                            auth_cookies[key] = auth_data[key]
        except Exception:
            pass

    result["cookies"] = auth_cookies

    if not auth_cookies.get("passToken"):
        result["error"] = "no passToken — may need manual email verification"
        result["status"] = "need_verify"
        return result

    if verbose:
        print(f"  [4/5] OK — passToken={auth_cookies['passToken'][:20]}...")

    # ========== STEP 5: Login to platform + get API keys ==========
    if verbose:
        print("  [5/5] Fetching API keys from platform...")

    # Set cookies on platform domain
    s2 = requests.Session()
    s2.headers.update({
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "application/json",
        "Referer": f"{PLATFORM_BASE}/console/api-keys",
    })
    for key, val in auth_cookies.items():
        s2.cookies.set(key, val, domain=".xiaomimimo.com")
        s2.cookies.set(key, val, domain="platform.xiaomimimo.com")

    # Hit STS endpoint to get platform session
    try:
        r5 = s2.get(f"{PLATFORM_BASE}/sts", params={"sign": "", "followup": f"{API_BASE}/keys"}, timeout=15, allow_redirects=True)
    except Exception:
        pass

    # Fetch API keys
    r6 = s2.get(f"{API_BASE}/keys", timeout=15)
    if r6.status_code == 200:
        keys_data = r6.json()
        if isinstance(keys_data, dict) and "data" in keys_data:
            result["api_keys"] = keys_data["data"]
        elif isinstance(keys_data, list):
            result["api_keys"] = keys_data
        else:
            result["api_keys"] = [keys_data]
        result["status"] = "success"
        if verbose:
            print(f"  [5/5] OK — {len(result['api_keys'])} API key(s) found")
    elif r6.status_code == 401:
        # Cookies didn't work for platform — need STS bridge
        result["status"] = "success_partial"
        result["error"] = "cookies valid but platform STS auth failed — manual /sts redirect needed"
        if verbose:
            print(f"  [5/5] 401 — STS redirect needed")
    else:
        result["error"] = f"API keys fetch failed: HTTP {r6.status_code}"
        if verbose:
            print(f"  [5/5] Error: HTTP {r6.status_code}")

    return result


def batch_auto_register(count: int, password: str = DEFAULT_PASSWORD, verbose: bool = False) -> list[dict]:
    """Register multiple accounts with full auto pipeline."""
    results = []
    for i in range(count):
        if verbose:
            print(f"\n{'='*50}")
            print(f"Account [{i+1}/{count}]")
            print(f"{'='*50}")

        # Create disposable email
        email_acc = create_account(password)
        email = email_acc["email"]
        email_token = email_acc["token"]

        # Store email token for verification step
        r = auto_register(email, password, verbose)
        r["email_token"] = email_token
        results.append(r)

        if i < count - 1:
            time.sleep(3)  # rate limit

    return results


if __name__ == "__main__":
    import sys
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    print(f"🚀 Auto-registering {count} Xiaomi account(s) for MiMo platform...")
    print(f"   Flow: mail.tm → ddddocr CAPTCHA → account.xiaomi.com → platform.xiaomimimo.com")
    print()

    results = batch_auto_register(count, verbose=True)

    # Summary
    ok = sum(1 for r in results if r["status"] in ("success", "success_partial"))
    print(f"\n{'='*50}")
    print(f"✅ {ok}/{count} registered successfully")

    # Save
    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"auto_accounts_{ts}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"💾 Saved → {out_path}")

    for r in results:
        status = "✅" if r["status"] == "success" else "⚠️" if r["status"] == "success_partial" else "❌"
        print(f"  {status} {r['email']} — {r['status']} — {r.get('error') or 'OK'}")
