#!/usr/bin/env python3
"""auto-keys TUI — Full pipeline: email → register → API key.

Single TUI dashboard for batch generating Xiaomi MiMo accounts.
Supports 3 modes:
  1. semi-auto: Selenium + manual reCAPTCHA click (free, recommended)
  2. auto: 2captcha/capsolver API (costs ~$3/1000)
  3. cookies: import existing cookies, just create API keys

Usage:
    python3 tui.py --count 45                     # semi-auto mode
    python3 tui.py --count 45 --solver 2captcha --key YOUR_KEY
    python3 tui.py --count 45 --cookies cookies.json
"""
import sys
import os
import json
import time
import argparse
import threading
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

sys.path.insert(0, os.path.dirname(__file__))

# ── Rich imports ──────────────────────────────────────────────
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.text import Text
from rich import box

console = Console()


# ── Data model ────────────────────────────────────────────────
class Status(Enum):
    PENDING = "pending"
    EMAIL = "email"
    REGISTER = "register"
    CAPTCHA = "captcha"
    VERIFY = "verify"
    APIKEY = "apikey"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


STATUS_COLORS = {
    Status.PENDING: "dim",
    Status.EMAIL: "cyan",
    Status.REGISTER: "yellow",
    Status.CAPTCHA: "magenta",
    Status.VERIFY: "blue",
    Status.APIKEY: "bright_yellow",
    Status.SUCCESS: "bold green",
    Status.FAILED: "bold red",
    Status.SKIPPED: "dim red",
}


@dataclass
class Account:
    index: int
    email: str = ""
    password: str = "masuk123!"
    cookies: dict = field(default_factory=dict)
    api_keys: list = field(default_factory=list)
    status: Status = Status.PENDING
    error: str = ""
    created_at: str = ""
    email_token: str = ""


# ── Dashboard ─────────────────────────────────────────────────
def build_stats_panel(accounts: list[Account], start_time: float) -> Panel:
    """Stats summary panel."""
    total = len(accounts)
    ok = sum(1 for a in accounts if a.status == Status.SUCCESS)
    fail = sum(1 for a in accounts if a.status == Status.FAILED)
    active = sum(1 for a in accounts if a.status not in (Status.PENDING, Status.SUCCESS, Status.FAILED, Status.SKIPPED))
    pending = sum(1 for a in accounts if a.status == Status.PENDING)
    elapsed = time.time() - start_time
    keys_total = sum(len(a.api_keys) for a in accounts)

    stats = Text()
    stats.append(f"  Total:     {total}\n", style="bold")
    stats.append(f"  ✅ Success: {ok}\n", style="green")
    stats.append(f"  ❌ Failed:  {fail}\n", style="red")
    stats.append(f"  ⏳ Active:  {active}\n", style="yellow")
    stats.append(f"  ⬚  Pending: {pending}\n", style="dim")
    stats.append(f"  🔑 Keys:    {keys_total}\n", style="cyan")
    stats.append(f"  ⏱  Elapsed: {elapsed:.0f}s\n", style="dim")

    return Panel(stats, title="📊 Stats", border_style="blue", width=30)


def build_accounts_table(accounts: list[Account], max_rows: int = 15) -> Table:
    """Accounts status table."""
    table = Table(box=box.SIMPLE_HEAVY, expand=True, show_lines=False)
    table.add_column("#", width=4, style="dim")
    table.add_column("Email", min_width=28)
    table.add_column("Status", width=12)
    table.add_column("API Keys", width=8, justify="center")
    table.add_column("Error", min_width=20)

    # Show most recent entries (last N)
    display = accounts[-max_rows:] if len(accounts) > max_rows else accounts
    for a in display:
        status_text = Text(a.status.value, style=STATUS_COLORS.get(a.status, "white"))
        keys_text = str(len(a.api_keys)) if a.api_keys else "-"
        error_text = (a.error[:40] + "...") if len(a.error) > 40 else a.error
        table.add_row(str(a.index), a.email or "-", status_text, keys_text, error_text)

    return Panel(table, title="📋 Accounts", border_style="green")


def build_dashboard(accounts: list[Account], start_time: float, header: str = "") -> Layout:
    """Full TUI dashboard layout."""
    layout = Layout()
    layout.split_column(
        Layout(build_header(header), size=3),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(build_accounts_table(accounts), ratio=3),
        Layout(build_stats_panel(accounts, start_time), ratio=1),
    )
    return layout


def build_header(text: str) -> Panel:
    return Panel(Text(text, style="bold cyan", justify="center"), border_style="cyan")


# ── Pipeline stages ───────────────────────────────────────────
def stage_email(acc: Account, password: str = "masuk123!"):
    """Create disposable email via mail.tm."""
    from providers.tempmail import create_account
    result = create_account(password)
    acc.email = result["email"]
    acc.email_token = result["token"]
    acc.password = password
    acc.created_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def stage_register_selenium(acc: Account, driver):
    """Register via Selenium browser — auto-fill + wait for reCAPTCHA."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    XIAOMI_REGISTER = "https://account.xiaomi.com/pass/register?sid=api-platform&_json=true"

    driver.get(XIAOMI_REGISTER)
    time.sleep(3)

    # Fill email
    email_input = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='user'], input[name='email'], #email"))
    )
    email_input.clear()
    email_input.send_keys(acc.email)
    time.sleep(0.3)

    # Fill password
    for pwd in driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
        pwd.clear()
        pwd.send_keys(acc.password)

    # Wait for reCAPTCHA
    acc.status = Status.CAPTCHA
    deadline = time.time() + 180
    captcha_solved = False
    while time.time() < deadline:
        response = driver.execute_script(
            "return document.getElementById('g-recaptcha-response')?.value || ''"
        )
        if response and len(response) > 50:
            captcha_solved = True
            break
        time.sleep(1)

    if not captcha_solved:
        acc.status = Status.FAILED
        acc.error = "reCAPTCHA timeout (180s)"
        return

    # Submit
    time.sleep(1)
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit'], .register-btn")
        btn.click()
    except Exception:
        driver.execute_script("document.querySelector('form')?.submit()")
    time.sleep(5)

    # Extract cookies
    for c in driver.get_cookies():
        if c["name"] in ("passToken", "cUserId", "userId", "serviceToken"):
            acc.cookies[c["name"]] = c["value"]

    if acc.cookies.get("passToken"):
        acc.status = Status.APIKEY
    elif "verify" in driver.page_source.lower() or "激活" in driver.page_source:
        acc.status = Status.VERIFY
        acc.error = "email verification required"
    else:
        # Try auth endpoint
        driver.get("https://account.xiaomi.com/pass/serviceLogin/auth?sid=api-platform&_json=true")
        time.sleep(2)
        import re
        text = driver.page_source
        for key in ("passToken", "cUserId", "userId"):
            match = re.search(rf'"{key}":"([^"]+)"', text)
            if match:
                acc.cookies[key] = match.group(1)
        if acc.cookies.get("passToken"):
            acc.status = Status.APIKEY
        else:
            acc.status = Status.FAILED
            acc.error = "no passToken after register"


def stage_create_apikey(acc: Account):
    """Create API key on platform.xiaomimimo.com using session cookies."""
    import requests

    if not acc.cookies.get("passToken"):
        acc.status = Status.FAILED
        acc.error = "no cookies available"
        return

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 14; Mi 14) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://platform.xiaomimimo.com/console/api-keys",
    })

    # Set cookies on platform domain
    for key, val in acc.cookies.items():
        s.cookies.set(key, val, domain=".xiaomimimo.com")
        s.cookies.set(key, val, domain="platform.xiaomimimo.com")

    # First visit STS to establish session
    try:
        s.get("https://platform.xiaomimimo.com/sts", params={
            "sign": "", "followup": "https://platform.xiaomimimo.com/api/v1/keys"
        }, timeout=15, allow_redirects=True)
    except Exception:
        pass

    # Create new API key
    r = s.post("https://platform.xiaomimimo.com/api/v1/keys", json={
        "name": f"auto-key-{int(time.time())}",
    }, timeout=15)

    if r.status_code in (200, 201):
        data = r.json()
        key = data.get("data", {}).get("key") or data.get("key") or data.get("data", {}).get("secret")
        if key:
            acc.api_keys.append(key)
            acc.status = Status.SUCCESS
        else:
            # Try listing existing keys
            r2 = s.get("https://platform.xiaomimimo.com/api/v1/keys", timeout=15)
            if r2.status_code == 200:
                keys_data = r2.json()
                items = keys_data.get("data", [])
                if isinstance(items, list):
                    for item in items:
                        k = item.get("key") or item.get("secret") if isinstance(item, dict) else item
                        if k:
                            acc.api_keys.append(k)
                if acc.api_keys:
                    acc.status = Status.SUCCESS
                else:
                    acc.status = Status.FAILED
                    acc.error = "no keys in response"
            else:
                acc.status = Status.FAILED
                acc.error = f"keys list HTTP {r2.status_code}"
    elif r.status_code == 401:
        acc.status = Status.FAILED
        acc.error = "401 unauthorized — STS auth failed"
    else:
        acc.status = Status.FAILED
        acc.error = f"key create HTTP {r.status_code}"


def stage_import_cookies(acc: Account, cookies: dict):
    """Import pre-existing cookies."""
    acc.cookies = cookies
    acc.status = Status.APIKEY


# ── Main pipeline ─────────────────────────────────────────────
def run_pipeline_semi_auto(accounts: list[Account], password: str, start_time: float, headless: bool = False):
    """Semi-auto mode: Selenium + manual reCAPTCHA."""
    import undetected_chromedriver as uc

    opts = uc.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--lang=en-US,en")

    driver = uc.Chrome(options=opts)

    try:
        for acc in accounts:
            # Stage 1: Email
            acc.status = Status.EMAIL
            try:
                stage_email(acc, password)
            except Exception as e:
                acc.status = Status.FAILED
                acc.error = f"email: {str(e)[:60]}"
                continue

            # Stage 2: Register + CAPTCHA
            acc.status = Status.REGISTER
            try:
                stage_register_selenium(acc, driver)
            except Exception as e:
                acc.status = Status.FAILED
                acc.error = f"register: {str(e)[:60]}"
                continue

            # Stage 3: API Key
            if acc.status == Status.APIKEY:
                try:
                    stage_create_apikey(acc)
                except Exception as e:
                    acc.status = Status.FAILED
                    acc.error = f"apikey: {str(e)[:60]}"

            time.sleep(2)  # rate limit
    finally:
        driver.quit()


def run_pipeline_auto(accounts: list[Account], password: str, solver: str, solver_key: str):
    """Auto mode: API-based CAPTCHA solving."""
    from captcha_solver import fetch_captcha, solve_with_2captcha, solve_with_capsolver
    from full_pipeline import auto_register

    for acc in accounts:
        acc.status = Status.EMAIL
        try:
            stage_email(acc, password)
        except Exception as e:
            acc.status = Status.FAILED
            acc.error = f"email: {str(e)[:60]}"
            continue

        acc.status = Status.REGISTER
        try:
            result = auto_register(acc.email, password, verbose=False)
            acc.cookies = result.get("cookies", {})
            acc.error = result.get("error", "")
            if result["status"] in ("success", "success_partial"):
                acc.status = Status.APIKEY
            else:
                acc.status = Status.FAILED
                continue
        except Exception as e:
            acc.status = Status.FAILED
            acc.error = f"register: {str(e)[:60]}"
            continue

        if acc.status == Status.APIKEY:
            try:
                stage_create_apikey(acc)
            except Exception as e:
                acc.status = Status.FAILED
                acc.error = f"apikey: {str(e)[:60]}"

        time.sleep(3)


def run_pipeline_cookies(accounts: list[Account], cookies_file: str):
    """Cookie import mode: just create API keys."""
    with open(cookies_file) as f:
        all_cookies = json.load(f)

    if isinstance(all_cookies, dict):
        all_cookies = [all_cookies]

    for i, acc in enumerate(accounts):
        if i < len(all_cookies):
            cookies = all_cookies[i] if isinstance(all_cookies[i], dict) else all_cookies[i].get("cookies", {})
            acc.email = all_cookies[i].get("email", f"imported-{i+1}") if isinstance(all_cookies[i], dict) else f"imported-{i+1}"
            acc.cookies = cookies
            acc.status = Status.APIKEY
            try:
                stage_create_apikey(acc)
            except Exception as e:
                acc.status = Status.FAILED
                acc.error = f"apikey: {str(e)[:60]}"
        else:
            acc.status = Status.SKIPPED
            acc.error = "no cookie data"


# ── Output ────────────────────────────────────────────────────
def save_outputs(accounts: list[Account], output_dir: str):
    """Save per-account JSON + TXT + combined summary."""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    saved_json = []
    saved_txt = []
    all_keys = []
    all_data = []

    for acc in accounts:
        if acc.status != Status.SUCCESS:
            # Still save failed accounts in combined, but skip per-account
            all_data.append({
                "email": acc.email,
                "password": acc.password,
                "cookies": acc.cookies,
                "api_keys": acc.api_keys,
                "created_at": acc.created_at,
                "status": acc.status.value,
                "ultraspeed": acc.status == Status.SUCCESS,
                "error": acc.error or None,
            })
            all_keys.extend(acc.api_keys)
            continue

        entry = {
            "email": acc.email,
            "password": acc.password,
            "cookies": acc.cookies,
            "api_keys": acc.api_keys,
            "created_at": acc.created_at,
            "status": acc.status.value,
            "ultraspeed": True,
            "error": None,
        }
        all_data.append(entry)

        # Per-account JSON
        json_path = os.path.join(output_dir, f"account{acc.index}.json")
        with open(json_path, "w") as f:
            json.dump(entry, f, indent=2)
        saved_json.append(json_path)

        # Per-account API key TXT
        if acc.api_keys:
            txt_path = os.path.join(output_dir, f"account-api{acc.index}.txt")
            with open(txt_path, "w") as f:
                for key in acc.api_keys:
                    f.write(key + "\n")
            saved_txt.append(txt_path)
            all_keys.extend(acc.api_keys)

    # Combined summary
    summary_path = os.path.join(output_dir, f"summary_{ts}.json")
    with open(summary_path, "w") as f:
        json.dump(all_data, f, indent=2)

    all_keys_path = os.path.join(output_dir, f"all_api_keys_{ts}.txt")
    with open(all_keys_path, "w") as f:
        for key in all_keys:
            f.write(key + "\n")

    return saved_json, saved_txt, summary_path, all_keys_path, len(all_keys)


# ── Entry point ───────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="auto-keys TUI — batch Xiaomi MiMo account generator")
    parser.add_argument("-c", "--count", type=int, default=45, help="Number of accounts (default: 45)")
    parser.add_argument("--password", default="masuk123!", help="Account password")
    parser.add_argument("--mode", choices=["semi-auto", "auto", "cookies"], default="semi-auto",
                        help="Registration mode (default: semi-auto)")
    parser.add_argument("--solver", choices=["2captcha", "capsolver"], help="CAPTCHA solver (auto mode)")
    parser.add_argument("--key", help="API key for CAPTCHA solver")
    parser.add_argument("--cookies", help="Path to cookies JSON (cookies mode)")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--no-wait", action="store_true", help="Don't wait for reCAPTCHA (debug)")
    parser.add_argument("-o", "--output", default="output", help="Output directory")
    args = parser.parse_args()

    # Validate mode
    if args.mode == "auto" and not (args.solver and args.key):
        console.print("[red]Error: --mode auto requires --solver and --key[/red]")
        sys.exit(1)
    if args.mode == "cookies" and not args.cookies:
        console.print("[red]Error: --mode cookies requires --cookies[/red]")
        sys.exit(1)

    # Create accounts
    accounts = [Account(index=i + 1) for i in range(args.count)]
    start_time = time.time()

    # Print header
    console.print()
    console.print(Panel(
        f"[bold cyan]auto-keys TUI[/bold cyan]\n"
        f"Count: {args.count} | Mode: {args.mode} | Password: {args.password}",
        title="🚀 Xiaomi MiMo Account Generator",
        border_style="cyan"
    ))
    console.print()

    # Run pipeline with live dashboard
    with Live(build_dashboard(accounts, start_time, f"🚀 Generating {args.count} accounts..."),
              refresh_per_second=2, console=console) as live:

        def update_loop():
            while any(a.status not in (Status.SUCCESS, Status.FAILED, Status.SKIPPED) for a in accounts):
                live.update(build_dashboard(accounts, start_time,
                             f"🚀 Generating {args.count} accounts... ({args.mode})"))
                time.sleep(0.5)
            live.update(build_dashboard(accounts, start_time, f"✅ Done — {args.count} accounts"))

        # Start dashboard updater in background
        updater = threading.Thread(target=update_loop, daemon=True)
        updater.start()

        # Run pipeline
        if args.mode == "semi-auto":
            console.print("[yellow]Browser will open — click 'I'm not a robot' for each account[/yellow]")
            console.print(f"[dim]Timeout: 180s per CAPTCHA[/dim]")
            run_pipeline_semi_auto(accounts, args.password, start_time, args.headless)
        elif args.mode == "auto":
            run_pipeline_auto(accounts, args.password, args.solver, args.key)
        elif args.mode == "cookies":
            run_pipeline_cookies(accounts, args.cookies)

        # Wait for dashboard to settle
        time.sleep(1)

    # Save outputs
    saved_json, saved_txt, summary_path, all_keys_path, key_count = save_outputs(accounts, args.output)

    # Final summary
    console.print()
    ok = sum(1 for a in accounts if a.status == Status.SUCCESS)
    fail = sum(1 for a in accounts if a.status == Status.FAILED)
    elapsed = time.time() - start_time

    console.print(Panel(
        f"[green]✅ Success: {ok}[/green]  |  [red]❌ Failed: {fail}[/red]  |  [cyan]🔑 API Keys: {key_count}[/cyan]\n"
        f"[dim]⏱  {elapsed:.0f}s total[/dim]\n\n"
        f"📄 Per-account: {len(saved_json)} JSON + {len(saved_txt)} TXT\n"
        f"📋 Summary: {summary_path}\n"
        f"📝 All keys: {all_keys_path}",
        title="📊 Final Results",
        border_style="green" if ok > 0 else "red"
    ))

    # Show failed accounts
    if fail > 0:
        console.print(f"\n[red]Failed accounts:[/red]")
        for a in accounts:
            if a.status == Status.FAILED:
                console.print(f"  ❌ #{a.index} {a.email} — {a.error}")


if __name__ == "__main__":
    main()
