"""Qwen Cloud automated registration via Selenium.

Flow (fully automated — no CAPTCHA):
  1. Create disposable email (mail.tm)
  2. Selenium → Alibaba Cloud register page
  3. Auto-fill form → click "Send verification code"
  4. Poll mail.tm inbox for verification code
  5. Auto-fill code → submit registration
  6. OAuth redirect → Qwen Cloud
  7. Navigate to DashScope → create API key
  8. Extract cookies + API key

Usage:
    python qwen_selenium.py --count 5 --no-headless -v
"""
import sys
import os
import re
import json
import time
import argparse
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from providers.tempmail import create_account, get_messages, extract_links


# ── Config ────────────────────────────────────────────────────
REGISTER_URL = "https://account.alibabacloud.com/"
DASHSCOPE_URL = "https://dashscope.console.aliyun.com"
QWEN_HOME = "https://home.qwencloud.com"
DEFAULT_PASSWORD = "masuk123!"
VERIFY_POLL_INTERVAL = 3  # seconds
VERIFY_POLL_TIMEOUT = 120  # seconds


def create_driver(headless: bool = True):
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--lang=en-US,en")
    from chrome_detect import detect_chrome_version
    ver = detect_chrome_version()
    kwargs = {"options": opts}
    if ver:
        kwargs["version_main"] = ver
    return uc.Chrome(**kwargs)


def wait_for_email_code(email_token: str, timeout: int = VERIFY_POLL_TIMEOUT) -> str | None:
    """Poll mail.tm inbox for verification code email from Alibaba."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            messages = get_messages(email_token)
            for msg in messages:
                subject = msg.get("subject", "").lower()
                sender = msg.get("from", {}).get("address", "").lower()
                # Alibaba/aliyun sends verification codes
                if any(kw in subject for kw in ("verification", "verify", "code", "验证", "确认")):
                    # Get full message body
                    msg_detail = get_messages(email_token)  # already has text in list
                    # Extract 4-6 digit code from subject or preview
                    code_match = re.search(r'\b(\d{4,6})\b', msg.get("subject", "") + " " + msg.get("intro", ""))
                    if code_match:
                        return code_match.group(1)
                # Also check alibaba/aliyun sender
                if any(kw in sender for kw in ("alibaba", "aliyun", "alibabacloud", "aliyun.com")):
                    code_match = re.search(r'\b(\d{4,6})\b', msg.get("subject", "") + " " + msg.get("intro", ""))
                    if code_match:
                        return code_match.group(1)
        except Exception:
            pass
        time.sleep(VERIFY_POLL_INTERVAL)
    return None


def find_and_click(driver, selectors: list[str], timeout: int = 10) -> bool:
    """Try multiple selectors (CSS or XPath), click the first match."""
    for sel in selectors:
        try:
            by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
            el = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((by, sel))
            )
            el.click()
            return True
        except (TimeoutException, Exception):
            continue
    return False


def find_and_fill(driver, selectors: list[str], value: str, timeout: int = 10) -> bool:
    """Try multiple selectors (CSS or XPath), fill the first match."""
    for sel in selectors:
        try:
            by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, sel))
            )
            el.clear()
            el.send_keys(value)
            return True
        except (TimeoutException, Exception):
            continue
    return False


def register_account(driver, email: str, email_token: str, password: str, verbose: bool = False) -> dict:
    """Register one Qwen Cloud account. Returns {status, cookies, api_key, error}."""
    result = {"status": "failed", "cookies": {}, "api_keys": [], "error": None}

    # Step 1: Navigate to registration page
    if verbose:
        print(f"  [1/6] Loading registration page...")
    driver.get(REGISTER_URL)
    time.sleep(4)

    # Step 2: Fill email
    if verbose:
        print(f"  [2/6] Filling email: {email}")
    email_filled = find_and_fill(driver, [
        "input[name='email']",
        "input[name='loginId']",
        "input[type='email']",
        "input[placeholder*='mail']",
        "input[placeholder*='email']",
        "input[id*='email']",
        "input[id*='loginId']",
    ], email)

    if not email_filled:
        # Try finding all visible text inputs
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input:not([type])")
        for inp in inputs:
            if inp.is_displayed() and inp.get_attribute("value") == "":
                inp.send_keys(email)
                email_filled = True
                break

    if not email_filled:
        result["error"] = "cannot find email input"
        return result

    time.sleep(1)

    # Step 3: Fill password
    if verbose:
        print(f"  [3/6] Filling password...")
    pwd_filled = find_and_fill(driver, [
        "input[name='password']",
        "input[type='password']",
        "input[id*='password']",
    ], password)

    if not pwd_filled:
        pwds = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
        for p in pwds:
            if p.is_displayed():
                p.send_keys(password)
                pwd_filled = True
                break

    time.sleep(1)

    # Step 4: Click "Send verification code"
    if verbose:
        print(f"  [4/6] Sending verification code to {email}...")
    code_sent = find_and_click(driver, [
        "//button[contains(text(), 'Send')]",
        "//button[contains(text(), 'Get')]",
        "//button[contains(text(), 'Code')]",
        "//button[contains(text(), '发送')]",
        "//button[contains(text(), '获取')]",
        "//a[contains(text(), 'Send')]",
        "//a[contains(text(), 'Get')]",
        "//a[contains(text(), 'Code')]",
        "//a[contains(text(), '发送')]",
        "[class*='send']",
        "[class*='code'] button",
        "[class*='verify'] button",
        "[class*='captcha'] button",
    ], timeout=5)

    # Fallback: find any button near the verification code input
    if not code_sent:
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            text = btn.text.lower()
            if any(kw in text for kw in ("send", "get", "code", "发送", "获取", "验证")):
                btn.click()
                code_sent = True
                break

    if not code_sent:
        # Try clicking link elements
        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            text = link.text.lower()
            if any(kw in text for kw in ("send", "get", "code", "发送", "获取")):
                link.click()
                code_sent = True
                break

    if not code_sent:
        result["error"] = "cannot find 'send verification code' button"
        return result

    time.sleep(2)

    # Step 5: Poll mail.tm for verification code
    if verbose:
        print(f"  [5/6] Waiting for verification code email...")
    code = wait_for_email_code(email_token, timeout=VERIFY_POLL_TIMEOUT)

    if not code:
        result["error"] = "verification code email not received (timeout)"
        return result

    if verbose:
        print(f"  [5/6] Got code: {code}")

    # Fill verification code
    code_filled = find_and_fill(driver, [
        "input[name='verifyCode']",
        "input[name='code']",
        "input[name='verifyCode']",
        "input[name='verificationCode']",
        "input[placeholder*='code']",
        "input[placeholder*='Code']",
        "input[placeholder*='验证']",
        "input[id*='code']",
        "input[id*='verify']",
    ], code)

    if not code_filled:
        # Try all visible text inputs that are empty
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='number'], input:not([type])")
        for inp in inputs:
            if inp.is_displayed() and inp.get_attribute("value") == "":
                inp.send_keys(code)
                code_filled = True
                break

    if not code_filled:
        result["error"] = "cannot find verification code input"
        return result

    time.sleep(1)

    # Step 6: Submit registration
    if verbose:
        print(f"  [6/6] Submitting registration...")
    submitted = find_and_click(driver, [
        "button[type='submit']",
        "input[type='submit']",
        "//button[contains(text(), 'Register')]",
        "//button[contains(text(), 'Sign Up')]",
        "//button[contains(text(), 'Create')]",
        "//button[contains(text(), '注册')]",
        "//button[contains(text(), '创建')]",
        "[class*='submit']",
        "[class*='register'] button",
    ], timeout=5)

    if not submitted:
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            text = btn.text.lower()
            if any(kw in text for kw in ("register", "sign up", "create", "submit", "注册", "创建", "提交")):
                btn.click()
                submitted = True
                break

    time.sleep(8)

    # Extract cookies
    for c in driver.get_cookies():
        if c["name"] in ("SESSION", "cna", "cookie2", "sgcookie", "unb", "sn", "lid"):
            result["cookies"][c["name"]] = c["value"]

    # Check if registration succeeded (redirected to Qwen Cloud or logged in)
    current_url = driver.current_url
    page_text = driver.page_source[:2000]

    if "qwencloud" in current_url or "home" in current_url:
        result["status"] = "registered"
    elif "error" in page_text.lower() and "already" in page_text.lower():
        result["error"] = "email already registered"
        return result
    elif "success" in page_text.lower():
        result["status"] = "registered"
    else:
        # Still on register page — might need more steps or failed
        if "register" in current_url.lower():
            result["error"] = f"still on register page after submit (URL: {current_url[:80]})"
            return result
        result["status"] = "registered"  # assume success if redirected away

    # Step 7: Navigate to DashScope to create API key
    if verbose:
        print(f"  [+] Navigating to DashScope for API key...")
    try:
        driver.get(DASHSCOPE_URL)
        time.sleep(5)

        # Try to create API key via console
        driver.get(f"{DASHSCOPE_URL}/apikey")
        time.sleep(3)

        # Look for "Create API Key" button
        create_btn = find_and_click(driver, [
            "//button[contains(text(), 'Create')]",
            "//button[contains(text(), '新建')]",
            "//button[contains(text(), 'Generate')]",
            "//button[contains(text(), '创建')]",
            "[class*='create']",
            "[class*='add']",
        ], timeout=8)

        if create_btn:
            time.sleep(2)

            # If there's a name input, fill it
            find_and_fill(driver, [
                "input[name='name']",
                "input[name='keyName']",
                "input[placeholder*='name']",
                "input[placeholder*='Name']",
            ], f"auto-key-{int(time.time())}", timeout=3)

            # Confirm
            find_and_click(driver, [
                "//button[contains(text(), 'Confirm')]",
                "//button[contains(text(), 'OK')]",
                "//button[contains(text(), '确定')]",
                "//button[contains(text(), 'Create')]",
                "//button[contains(text(), 'Submit')]",
                "button[type='submit']",
            ], timeout=3)

            time.sleep(3)

            # Extract API key from page
            page_text = driver.page_source
            # Look for API key pattern (sk-xxx for DashScope)
            key_match = re.search(r'(sk-[a-zA-Z0-9]{20,})', page_text)
            if key_match:
                result["api_keys"].append(key_match.group(1))
                if verbose:
                    print(f"  [+] API Key: {key_match.group(1)[:20]}...")
            else:
                # Try to find it in a modal/popup
                modals = driver.find_elements(By.CSS_SELECTOR, "[class*='modal'], [class*='dialog'], [class*='popup']")
                for modal in modals:
                    text = modal.text
                    key_match = re.search(r'(sk-[a-zA-Z0-9]{20,})', text)
                    if key_match:
                        result["api_keys"].append(key_match.group(1))
                        break

        # Fallback: try API endpoint directly
        if not result["api_keys"]:
            cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
            try:
                s = requests.Session()
                for k, v in cookies.items():
                    s.cookies.set(k, v)
                r = s.post(f"{DASHSCOPE_URL}/api/apikey/create",
                          json={"name": f"auto-key-{int(time.time())}"},
                          timeout=10)
                if r.status_code in (200, 201):
                    data = r.json()
                    key = (data.get("apiKey") or data.get("data", {}).get("apiKey")
                           or data.get("data", {}).get("key"))
                    if key:
                        result["api_keys"].append(key)
            except Exception:
                pass

    except Exception as e:
        if verbose:
            print(f"  [!] API key creation error: {e}")

    if result["status"] == "registered":
        result["status"] = "success" if result["api_keys"] else "registered_no_key"

    return result


def batch_register(count: int, password: str = DEFAULT_PASSWORD,
                   headless: bool = False, verbose: bool = False) -> list[dict]:
    """Register multiple Qwen Cloud accounts."""
    results = []
    driver = create_driver(headless=headless)

    try:
        for i in range(count):
            print(f"\n{'='*50}")
            print(f"  Account {i+1}/{count}")
            print(f"{'='*50}")

            # Create disposable email
            if verbose:
                print(f"  [+] Creating disposable email...")
            try:
                email_data = create_account(password)
                email = email_data["email"]
                email_token = email_data["token"]
            except Exception as e:
                print(f"  ❌ Email creation failed: {e}")
                results.append({
                    "index": i + 1, "email": "", "password": password,
                    "status": "failed", "cookies": {}, "api_keys": [],
                    "error": f"email: {e}",
                })
                continue

            if verbose:
                print(f"  [+] Email: {email}")

            # Register
            result = register_account(driver, email, email_token, password, verbose)
            result["index"] = i + 1
            result["email"] = email
            result["password"] = password
            results.append(result)

            status_icon = "✅" if result["status"] == "success" else "⚠️" if result["status"] == "registered_no_key" else "❌"
            print(f"  {status_icon} {result['status']}: {email}", end="")
            if result["api_keys"]:
                print(f" | Key: {result['api_keys'][0][:20]}...")
            elif result["error"]:
                print(f" | Error: {result['error']}")
            else:
                print()

            time.sleep(3)

    finally:
        driver.quit()

    return results


def _next_batch_num(output_dir: str) -> int:
    existing = glob.glob(os.path.join(output_dir, "account*.json"))
    if not existing:
        return 1
    nums = []
    for f in existing:
        name = os.path.basename(f)
        if name.startswith("account") and name.endswith(".json"):
            try:
                nums.append(int(name[7:-5]))
            except ValueError:
                pass
    return max(nums, default=0) + 1


def save_batch(results: list[dict], output_dir: str = "output"):
    """Save batch results as accountN.json + accountN-api.txt."""
    os.makedirs(output_dir, exist_ok=True)
    batch = _next_batch_num(output_dir)

    json_path = os.path.join(output_dir, f"account{batch}.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)

    all_keys = []
    for r in results:
        all_keys.extend(r.get("api_keys", []))

    txt_path = os.path.join(output_dir, f"account{batch}-api.txt")
    with open(txt_path, "w") as f:
        for key in all_keys:
            f.write(key + "\n")

    return json_path, txt_path, batch, len(all_keys)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Qwen Cloud account generator (fully automated)")
    parser.add_argument("--count", "-c", type=int, default=1, help="Number of accounts")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Account password")
    parser.add_argument("--no-headless", action="store_true", help="Show browser")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("-o", "--output", default="output", help="Output directory")
    args = parser.parse_args()
