#!/usr/bin/env python3
"""Qwen Cloud registration — Selenium-based, fully automated.

Real flow discovered via testing on live site:
  1. Navigate → account.alibabacloud.com/register/intl_register.htm
  2. Switch to iframe (passport.alibabacloud.com)
  3. Click "Individual Account" → "Next"
  4. Fill email + password (must be Strong) + confirmPwd
  5. Click "Sign Up (Step 1 of 2)" → triggers email verification
  6. Poll mail.tm inbox → extract 6-digit code
  7. Fill code → submit (Step 2 of 2)
  8. Follow OAuth redirect → Qwen Cloud logged in
  9. Navigate to DashScope console → create API key

NOTE: Alibaba Cloud WAF (fireyejs) blocks headless browsers on server.
      Must run on Windows with real Chrome + display. --no-headless mode.
"""

import argparse
import json
import os
import re
import sys
import time

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from providers.tempmail import create_account, get_messages

# ── Config ────────────────────────────────────────────────────
REGISTER_URL = "https://account.alibabacloud.com/register/intl_register.htm"
IFRAME_SRC_CONTAINS = "passport.alibabacloud.com"
DASHSCOPE_APIKEY_URL = "https://dashscope.console.aliyun.com/apiKey"

DEFAULT_PASSWORD = "AutoKey$2025Xyz"  # Strong: upper+lower+num+symbol

# ── Helpers ───────────────────────────────────────────────────


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
        except Exception:
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
        except Exception:
            continue
    return False


def click_by_js(driver, text_contains: str, tag_filter: str = "*") -> bool:
    """Click element by visible text via JavaScript."""
    result = driver.execute_script(f"""
        for (const el of document.querySelectorAll("{tag_filter}")) {{
            if (el.textContent.trim().includes("{text_contains}") && el.offsetParent !== null) {{
                el.click();
                return true;
            }}
        }}
        return false;
    """)
    return bool(result)


def click_next_btn_primary(driver, text_contains: str = "Sign Up") -> bool:
    """Click Alibaba Cloud's next-btn-primary div (not a real <button>)."""
    result = driver.execute_script(f"""
        for (const el of document.querySelectorAll("div[class*='next-btn-primary']")) {{
            if (el.textContent.includes("{text_contains}") && el.offsetParent !== null) {{
                el.click();
                return true;
            }}
        }}
        return false;
    """)
    return bool(result)


# ── Chrome Launch ─────────────────────────────────────────────


def launch_chrome(headless: bool = False) -> uc.Chrome:
    """Launch Chrome with anti-detection patches."""
    opts = uc.ChromeOptions()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1366,768")
    opts.add_argument("--lang=en-US,en")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-infobars")
    if headless:
        opts.add_argument("--headless=new")

    from chrome_detect import detect_chrome_version

    ver = detect_chrome_version()
    kwargs = {"options": opts}
    if ver:
        kwargs["version_main"] = ver

    driver = uc.Chrome(**kwargs)

    # Anti-detection patches
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = {runtime: {}};
            """
        },
    )
    return driver


# ── Core Registration Flow ────────────────────────────────────


def register_account(
    password: str = DEFAULT_PASSWORD,
    headless: bool = False,
    verbose: bool = False,
    timeout: int = 180,
) -> dict:
    """Register one Qwen Cloud account. Returns dict with email, cookies, etc."""
    result = {
        "email": "",
        "password": password,
        "cookies": {},
        "api_keys": [],
        "status": "failed",
        "error": "",
    }

    # Step 0: Create disposable email
    if verbose:
        print("  [0/7] Creating disposable email...")
    try:
        email_data = create_account(password)
        email = email_data["email"]
        mail_token = email_data["token"]
        result["email"] = email
    except Exception as e:
        result["error"] = f"mail.tm failed: {e}"
        return result

    if verbose:
        print(f"  Email: {email}")

    # Step 0b: Launch Chrome
    driver = None
    try:
        driver = launch_chrome(headless=headless)
        if verbose:
            print("  Chrome launched")

        # Step 1: Navigate to registration page
        if verbose:
            print("  [1/7] Navigating to registration page...")
        driver.get(REGISTER_URL)
        time.sleep(8)

        # Step 2: Switch to iframe
        if verbose:
            print("  [2/7] Switching to iframe...")
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        found_iframe = False
        for frame in iframes:
            src = frame.get_attribute("src") or ""
            if IFRAME_SRC_CONTAINS in src:
                driver.switch_to.frame(frame)
                found_iframe = True
                break
        if not found_iframe and iframes:
            driver.switch_to.frame(iframes[0])
            found_iframe = True
        if not found_iframe:
            result["error"] = "cannot find registration iframe"
            return result

        time.sleep(2)

        # Step 3: Select "Individual Account"
        if verbose:
            print("  [3/7] Selecting Individual Account...")
        click_by_js(driver, "Individual Account", "h4")
        time.sleep(2)

        # Step 4: Click "Next"
        if verbose:
            print("  [4/7] Clicking Next...")
        click_by_js(driver, "Next", "*")
        time.sleep(5)

        # Step 5: Fill registration form
        if verbose:
            print(f"  [5/7] Filling form (email={email})...")

        email_filled = find_and_fill(driver, ["input[name='email']"], email)
        if not email_filled:
            result["error"] = "cannot find email input"
            return result

        pwd_filled = find_and_fill(driver, ["input[name='password']"], password)
        if not pwd_filled:
            result["error"] = "cannot find password input"
            return result

        confirm_filled = find_and_fill(driver, ["input[name='confirmPwd']"], password)
        if not confirm_filled:
            result["error"] = "cannot find confirm password input"
            return result

        time.sleep(2)

        # Step 6: Click "Sign Up (Step 1 of 2)"
        if verbose:
            print("  [6/7] Submitting Step 1...")
        submitted = click_next_btn_primary(driver, "Sign Up")
        if not submitted:
            # Fallback: Enter key on confirmPwd
            driver.find_element(By.NAME, "confirmPwd").send_keys(Keys.RETURN)

        # Wait for Step 2 (verification code form)
        time.sleep(10)

        # Check if we're on Step 2
        visible_inputs = [
            i for i in driver.find_elements(By.CSS_SELECTOR, "input") if i.is_displayed()
        ]
        has_code_input = any(
            i.get_attribute("name") in ("code", "verifyCode", "verificationCode", "captcha")
            for i in visible_inputs
        )

        if not has_code_input:
            driver.save_screenshot("/tmp/qwen_step2_debug.png")
            result["error"] = "did not reach Step 2 (verification code). Screenshot: /tmp/qwen_step2_debug.png"
            return result

        # Step 7: Poll mail.tm for verification code + fill + submit
        if verbose:
            print("  [7/7] Waiting for verification code...")

        code = None
        for attempt in range(24):  # 2 minutes max
            msgs = get_messages(mail_token)
            if msgs:
                for msg in msgs:
                    body = str(msg.get("body", ""))
                    subject = str(msg.get("subject", ""))
                    codes = re.findall(r"\b(\d{6})\b", body + subject)
                    if codes:
                        code = codes[0]
                        if verbose:
                            print(f"  Got code: {code}")
                        break
                if code:
                    break
            time.sleep(5)
            if verbose and attempt % 4 == 3:
                print(f"  Waiting... ({attempt + 1}/24)")

        if not code:
            result["error"] = "no verification code received (2 min timeout)"
            return result

        # Fill code
        code_input = find_and_fill(driver, ["input[name='code']"], code)
        if not code_input:
            code_input = find_and_fill(driver, ["input[name='verifyCode']"], code)
        if not code_input:
            result["error"] = "cannot find verification code input"
            return result

        time.sleep(2)

        # Submit Step 2
        click_next_btn_primary(driver, "Sign Up")
        time.sleep(10)

        # Extract cookies
        cookies = {}
        for c in driver.get_cookies():
            cookies[c["name"]] = c["value"]
        result["cookies"] = cookies

        # Check if registration succeeded
        if "home" in driver.current_url or "qwencloud" in driver.current_url:
            result["status"] = "success"
        elif "error" in driver.current_url.lower():
            result["error"] = f"registration error: {driver.current_url}"
        else:
            # May have succeeded even if URL doesn't change
            result["status"] = "success"

    except Exception as e:
        result["error"] = str(e)
    finally:
        if driver:
            driver.quit()

    return result


# ── DashScope API Key ─────────────────────────────────────────


def create_api_key(driver, verbose: bool = False) -> str | None:
    """Navigate to DashScope console and create an API key."""
    try:
        driver.get(DASHSCOPE_APIKEY_URL)
        time.sleep(8)

        # Click "Create API Key" button
        created = click_next_btn_primary(driver, "Create")
        if not created:
            created = click_by_js(driver, "Create", "button")
        if not created:
            created = click_by_js(driver, "新建", "button")

        time.sleep(5)

        # Click confirm in dialog
        click_next_btn_primary(driver, "Confirm")
        time.sleep(3)

        # Extract API key from page
        body_text = driver.find_element(By.TAG_NAME, "body").text
        keys = re.findall(r"sk-[a-zA-Z0-9]{20,}", body_text)
        if keys:
            return keys[0]

    except Exception as e:
        if verbose:
            print(f"  API key error: {e}")

    return None


# ── Batch Registration ────────────────────────────────────────


def batch_register(
    count: int = 1,
    password: str = DEFAULT_PASSWORD,
    headless: bool = False,
    verbose: bool = True,
    output_dir: str = "output",
) -> list[dict]:
    """Register multiple accounts. Returns list of results."""
    results = []
    os.makedirs(output_dir, exist_ok=True)

    for i in range(1, count + 1):
        if verbose:
            print(f"\n{'=' * 50}")
            print(f"  Account {i}/{count}")
            print(f"{'=' * 50}")

        result = register_account(
            password=password,
            headless=headless,
            verbose=verbose,
        )
        results.append(result)

        status_icon = "✅" if result["status"] == "success" else "❌"
        if verbose:
            print(f"  {status_icon} {result['email']} — {result['status']}")
            if result["error"]:
                print(f"  Error: {result['error']}")

        time.sleep(3)  # Delay between registrations

    # Save batch output
    if results:
        # Find next batch number
        existing = [f for f in os.listdir(output_dir) if f.startswith("account") and f.endswith(".json")]
        batch_nums = []
        for f in existing:
            m = re.match(r"account(\d+)\.json", f)
            if m:
                batch_nums.append(int(m.group(1)))
        batch_num = max(batch_nums, default=0) + 1

        json_path = os.path.join(output_dir, f"account{batch_num}.json")
        txt_path = os.path.join(output_dir, f"account{batch_num}-api.txt")

        with open(json_path, "w") as f:
            json.dump(results, f, indent=2)
        if verbose:
            print(f"\n💾 {json_path}")

        api_keys = []
        for r in results:
            api_keys.extend(r.get("api_keys", []))
        if api_keys:
            with open(txt_path, "w") as f:
                f.write("\n".join(api_keys) + "\n")
            if verbose:
                print(f"💾 {txt_path}")

    return results


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Qwen Cloud account registration")
    parser.add_argument("-c", "--count", type=int, default=1, help="Number of accounts")
    parser.add_argument("-p", "--password", default=DEFAULT_PASSWORD, help="Password")
    parser.add_argument("--headless", action="store_true", help="Run headless (server mode)")
    parser.add_argument("--no-headless", action="store_true", help="Show browser (Windows)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("-o", "--output", default="output", help="Output directory")
    args = parser.parse_args()

    headless = args.headless and not args.no_headless

    results = batch_register(
        count=args.count,
        password=args.password,
        headless=headless,
        verbose=args.verbose or True,
        output_dir=args.output,
    )

    success = sum(1 for r in results if r["status"] == "success")
    print(f"\n{'=' * 50}")
    print(f"  Results: {success}/{len(results)} successful")
    print(f"{'=' * 50}")
