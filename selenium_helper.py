"""Selenium-based Xiaomi registration helper.

Automates browser registration to capture real cookies (passToken, cUserId, userId).
Falls back when API-only approach hits CAPTCHA or anti-bot.

Usage:
    python selenium_helper.py --count 5 --email-endpoint mail.tm

Requires: pip install selenium webdriver-manager
"""
import json
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from providers.tempmail import create_account

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False


REGISTER_URL = "https://account.xiaomi.com/pass/register?sid=mimovip&_json=true"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")


def create_driver(headless: bool = True) -> "webdriver.Chrome":
    """Create Chrome WebDriver with anti-detection options."""
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--lang=en-US")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver


def register_xiaomi(driver, email: str, password: str = "masuk123!", wait: int = 30) -> dict:
    """Register Xiaomi account via browser. Returns cookies dict."""
    result = {"email": email, "password": password, "cookies": {}, "status": "error", "error": None}

    try:
        driver.get(REGISTER_URL)
        time.sleep(2)

        # Fill email field
        email_input = WebDriverWait(driver, wait).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='user'], input[name='email'], #email"))
        )
        email_input.clear()
        email_input.send_keys(email)
        time.sleep(0.5)

        # Fill password
        pwd_input = driver.find_element(By.CSS_SELECTOR, "input[name='password'], input[type='password']")
        pwd_input.clear()
        pwd_input.send_keys(password)
        time.sleep(0.5)

        # Fill confirm password if exists
        try:
            pwd2 = driver.find_element(By.CSS_SELECTOR, "input[name='password2'], input[name='confirmPassword']")
            pwd2.clear()
            pwd2.send_keys(password)
        except Exception:
            pass  # Some flows don't have confirm password

        # Submit
        submit = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit'], .register-btn")
        submit.click()
        time.sleep(3)

        # Extract cookies
        all_cookies = driver.get_cookies()
        cookie_dict = {c["name"]: c["value"] for c in all_cookies}

        # Look for auth cookies
        for key in ["passToken", "cUserId", "userId", "serviceToken"]:
            if key in cookie_dict:
                result["cookies"][key] = cookie_dict[key]

        if result["cookies"].get("passToken"):
            result["status"] = "success"
        else:
            # Check if need email verification
            page = driver.page_source
            if "verify" in page.lower() or "activate" in page.lower():
                result["status"] = "need_verify"
                result["error"] = "email verification required"
            else:
                result["status"] = "error"
                result["error"] = "no passToken in cookies — may need manual CAPTCHA"

        result["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        result["ultraspeed"] = True

    except Exception as e:
        result["error"] = str(e)

    return result


def batch_register(count: int, headless: bool = True, password: str = "masuk123!", verbose: bool = False) -> list[dict]:
    """Register multiple accounts via browser."""
    if not HAS_SELENIUM:
        print("❌ selenium not installed. Run: pip install selenium webdriver-manager")
        return []

    results = []
    driver = create_driver(headless)

    try:
        for i in range(count):
            email_acc = create_account(password)
            email = email_acc["email"]
            if verbose:
                print(f"  [{i+1}/{count}] registering {email}...", end=" ", flush=True)

            r = register_xiaomi(driver, email, password)
            results.append(r)

            if verbose:
                print(r["status"], r.get("error") or "")
            time.sleep(2)  # rate limit
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
    parser = argparse.ArgumentParser(description="Selenium Xiaomi registration helper")
    parser.add_argument("--count", "-c", type=int, default=1, help="Number of accounts")
    parser.add_argument("--headless", action="store_true", default=True, help="Run headless")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--password", default="masuk123!", help="Account password")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    headless = not args.no_headless
    print(f"🚀 Registering {args.count} Xiaomi account(s) via Selenium...")
    results = batch_register(args.count, headless, args.password, args.verbose)

    if results:
        ok = sum(1 for r in results if r["status"] == "success")
        path = save_results(results)
        print(f"\n✅ {ok}/{len(results)} success → {path}")
    else:
        print("❌ No results generated")
