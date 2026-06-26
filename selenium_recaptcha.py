"""Semi-auto Xiaomi registration via Selenium + undetected-chromedriver.

Flow:
  1. Browser kebuka → halaman register Xiaomi
  2. Tool auto-fill email + password
  3. User klik "I'm not a robot" checkbox (reCAPTCHA v2)
  4. Tool detect CAPTCHA solved → auto-submit
  5. Extract cookies (passToken, cUserId, userId)
  6. Navigate ke platform.xiaomimimo.com → STS redirect → cookies valid
  7. Fetch API keys dari /api/v1/keys

Usage:
    python selenium_recaptcha.py [--count 5] [--headless-off]
"""
import json
import time
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from providers.tempmail import create_account

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

XIAOMI_REGISTER = "https://account.xiaomi.com/pass/register?sid=api-platform&_json=true"
PLATFORM_KEYS = "https://platform.xiaomimimo.com/console/api-keys"
PLATFORM_API = "https://platform.xiaomimimo.com/api/v1/keys"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def create_driver(headless: bool = True) -> uc.Chrome:
    """Create undetected Chrome driver."""
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


def wait_for_recaptcha(driver, timeout: int = 120) -> bool:
    """Wait for user to solve reCAPTCHA checkbox. Returns True when solved."""
    print("  ⏳ Klik 'I'm not a robot' di browser...")
    print(f"  (timeout: {timeout}s)")

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            # Check reCAPTCHA response textarea
            response = driver.execute_script(
                "return document.getElementById('g-recaptcha-response')?.value || "
                "document.querySelector('[name=\"g-recaptcha-response\"]')?.value || ''"
            )
            if response and len(response) > 50:
                print("  ✅ reCAPTCHA solved!")
                return True

            # Alternative: check iframe checkbox state
            frames = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='recaptcha']")
            for frame in frames:
                driver.switch_to.frame(frame)
                try:
                    checkbox = driver.find_element(By.CSS_SELECTOR, ".recaptcha-checkbox-checked")
                    if checkbox:
                        driver.switch_to.default_content()
                        print("  ✅ reCAPTCHA checkbox checked!")
                        return True
                except Exception:
                    pass
                driver.switch_to.default_content()
        except Exception:
            pass
        time.sleep(1)

    print("  ❌ Timeout — reCAPTCHA not solved")
    return False


def register_account(driver, email: str, password: str = "masuk123!", verbose: bool = False) -> dict:
    """Register one Xiaomi account. Returns cookies dict."""
    result = {
        "email": email,
        "password": password,
        "cookies": {},
        "status": "error",
        "error": None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ultraspeed": True,
    }

    try:
        # Step 1: Load register page
        if verbose:
            print(f"  [1/5] Loading register page...")
        driver.get(XIAOMI_REGISTER)
        time.sleep(3)

        # Step 2: Fill email
        if verbose:
            print(f"  [2/5] Filling email: {email}")
        email_input = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='user'], input[name='email'], #email"))
        )
        email_input.clear()
        email_input.send_keys(email)
        time.sleep(0.5)

        # Step 3: Fill password
        if verbose:
            print(f"  [3/5] Filling password...")
        pwd_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
        for i, pwd_input in enumerate(pwd_inputs):
            pwd_input.clear()
            pwd_input.send_keys(password)
            time.sleep(0.3)

        # Step 4: Solve reCAPTCHA
        if verbose:
            print(f"  [4/5] Waiting for reCAPTCHA...")
        captcha_ok = wait_for_recaptcha(driver, timeout=120)
        if not captcha_ok:
            result["error"] = "reCAPTCHA timeout"
            return result

        # Step 5: Submit
        if verbose:
            print(f"  [5/5] Submitting registration...")
        time.sleep(1)
        try:
            submit = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit'], .register-btn, #register-button")
            submit.click()
        except Exception:
            # Try form submit via JS
            driver.execute_script("document.querySelector('form')?.submit()")

        time.sleep(5)

        # Extract cookies
        all_cookies = driver.get_cookies()
        cookie_dict = {c["name"]: c["value"] for c in all_cookies}
        for key in ["passToken", "cUserId", "userId", "serviceToken"]:
            if key in cookie_dict:
                result["cookies"][key] = cookie_dict[key]

        # Check page for errors
        page = driver.page_source.lower()
        if "error" in page or "错误" in page or "验证码" in page:
            # Try to get specific error
            try:
                err_el = driver.find_element(By.CSS_SELECTOR, ".error-msg, .err-msg, .alert, .tip-error")
                result["error"] = err_el.text[:200]
            except Exception:
                result["error"] = "register page shows error"
            result["status"] = "error"
        elif result["cookies"].get("passToken"):
            result["status"] = "success"
            if verbose:
                print(f"  ✅ passToken: {result['cookies']['passToken'][:30]}...")
        elif "verify" in page or "activate" in page or "验证" in page:
            result["status"] = "need_verify"
            result["error"] = "email verification required"
        else:
            result["status"] = "unknown"
            result["error"] = "no passToken found — check browser manually"

    except Exception as e:
        result["error"] = str(e)[:300]

    return result


def fetch_api_keys(driver) -> list:
    """Navigate to platform and fetch API keys using existing session."""
    try:
        driver.get(PLATFORM_KEYS)
        time.sleep(5)

        # Try to get keys from page
        keys = []
        try:
            # Look for API key elements in the page
            key_elements = driver.find_elements(By.CSS_SELECTOR, "[class*='key'], [class*='api-key'], .key-value, code, pre")
            for el in key_elements:
                text = el.text.strip()
                if text.startswith("sk-") or text.startswith("key-"):
                    keys.append(text)
        except Exception:
            pass

        # Also try API endpoint
        try:
            driver.get(PLATFORM_API)
            time.sleep(2)
            body = driver.find_element(By.TAG_NAME, "body").text
            data = json.loads(body)
            if isinstance(data, dict) and "data" in data:
                for item in data["data"]:
                    if isinstance(item, dict) and "key" in item:
                        keys.append(item["key"])
                    elif isinstance(item, str):
                        keys.append(item)
        except Exception:
            pass

        return keys
    except Exception:
        return []


def batch_register(count: int, headless: bool = False, verbose: bool = False) -> list[dict]:
    """Register multiple accounts via Selenium."""
    results = []
    driver = create_driver(headless=headless)

    try:
        for i in range(count):
            email_acc = create_account()
            email = email_acc["email"]

            if verbose:
                print(f"\n{'='*50}")
                print(f"Account [{i+1}/{count}] — {email}")
                print(f"{'='*50}")

            r = register_account(driver, email, verbose=verbose)
            results.append(r)

            if verbose:
                status_icon = "✅" if r["status"] == "success" else "⚠️" if r["status"] == "need_verify" else "❌"
                print(f"  {status_icon} Status: {r['status']}")
                if r.get("error"):
                    print(f"  Error: {r['error']}")

            if i < count - 1:
                time.sleep(3)
    finally:
        driver.quit()

    return results


def save_results(results: list[dict], filename: str = None) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if filename is None:
        filename = f"selenium_accounts_{int(time.time())}.json"
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    return path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Semi-auto Xiaomi registration via Selenium")
    parser.add_argument("-c", "--count", type=int, default=1, help="Number of accounts")
    parser.add_argument("--headless-off", action="store_true", help="Show browser window (default: headless)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    headless = not args.headless_off
    print(f"🚀 Semi-auto Xiaomi registration — {args.count} account(s)")
    print(f"   Browser: {'visible' if not headless else 'headless'}")
    print(f"   reCAPTCHA: manual click required")
    print()

    results = batch_register(args.count, headless=headless, verbose=args.verbose)

    ok = sum(1 for r in results if r["status"] == "success")
    path = save_results(results)
    print(f"\n{'='*50}")
    print(f"✅ {ok}/{len(results)} registered → {path}")

    for r in results:
        status = "✅" if r["status"] == "success" else "⚠️" if r["status"] == "need_verify" else "❌"
        print(f"  {status} {r['email']} — {r['status']}")
