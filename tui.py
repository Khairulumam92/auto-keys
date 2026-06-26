#!/usr/bin/env python3
"""auto-keys TUI — Interactive Terminal User Interface.

Menu-driven TUI for managing Xiaomi MiMo account generation.
Navigate with number keys, configure settings, run batches.

Usage:
    python tui.py          # Interactive menu mode
    python tui.py --count 45  # Direct batch mode (old behavior)
"""
import sys
import os
import json
import time
import glob
import threading
import argparse
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.text import Text
from rich.live import Live
from rich import box

console = Console()

# ═══════════════════════════════════════════════════════════════
#  CONFIG — persistent settings
# ═══════════════════════════════════════════════════════════════
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "count": 45,
    "password": "***",
    "mode": "semi-auto",
    "headless": False,
    "output_dir": "output",
    "solver": None,
    "solver_key": None,
    "cookies_file": None,
    "timeout": 180,
}


def load_config() -> dict:
    """Load config from file, merge with defaults."""
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
            cfg.update(saved)
        except (json.JSONDecodeError, IOError):
            pass
    return cfg


def save_config(cfg: dict):
    """Save config to file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ═══════════════════════════════════════════════════════════════
#  DATA MODEL
# ═══════════════════════════════════════════════════════════════
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
    password: str = "***"
    cookies: dict = field(default_factory=dict)
    api_keys: list = field(default_factory=list)
    status: Status = Status.PENDING
    error: str = ""
    created_at: str = ""
    email_token: str = ""


# ═══════════════════════════════════════════════════════════════
#  OUTPUT HELPERS
# ═══════════════════════════════════════════════════════════════
def _next_batch_num(output_dir: str) -> int:
    """Find next batch number by scanning existing accountN.json files."""
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


def save_outputs(accounts: list[Account], output_dir: str):
    """Save 1 batch: accountN.json (all accounts) + accountN-api.txt (all keys)."""
    os.makedirs(output_dir, exist_ok=True)
    batch = _next_batch_num(output_dir)

    all_keys = []
    all_data = []
    for acc in accounts:
        entry = {
            "email": acc.email,
            "password": acc.password,
            "cookies": acc.cookies,
            "api_keys": acc.api_keys,
            "created_at": acc.created_at,
            "status": acc.status.value,
            "ultraspeed": acc.status == Status.SUCCESS,
            "error": acc.error or None,
        }
        all_data.append(entry)
        all_keys.extend(acc.api_keys)

    json_path = os.path.join(output_dir, f"account{batch}.json")
    with open(json_path, "w") as f:
        json.dump(all_data, f, indent=2)

    txt_path = os.path.join(output_dir, f"account{batch}-api.txt")
    with open(txt_path, "w") as f:
        for key in all_keys:
            f.write(key + "\n")

    return json_path, txt_path, batch, len(all_keys)


# ═══════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════
def build_stats_panel(accounts: list[Account], start_time: float) -> Panel:
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
    table = Table(box=box.SIMPLE_HEAVY, expand=True, show_lines=False)
    table.add_column("#", width=4, style="dim")
    table.add_column("Email", min_width=28)
    table.add_column("Status", width=12)
    table.add_column("API Keys", width=8, justify="center")
    table.add_column("Error", min_width=20)

    display = accounts[-max_rows:] if len(accounts) > max_rows else accounts
    for a in display:
        status_text = Text(a.status.value, style=STATUS_COLORS.get(a.status, "white"))
        keys_text = str(len(a.api_keys)) if a.api_keys else "-"
        error_text = (a.error[:40] + "...") if len(a.error) > 40 else a.error
        table.add_row(str(a.index), a.email or "-", status_text, keys_text, error_text)

    return Panel(table, title="📋 Accounts", border_style="green")


def build_dashboard(accounts: list[Account], start_time: float, header: str = ""):
    from rich.layout import Layout
    layout = Layout()
    layout.split_column(
        Layout(Panel(Text(header, style="bold cyan", justify="center"), border_style="cyan"), size=3),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(build_accounts_table(accounts), ratio=3),
        Layout(build_stats_panel(accounts, start_time), ratio=1),
    )
    return layout


# ═══════════════════════════════════════════════════════════════
#  PIPELINE STAGES
# ═══════════════════════════════════════════════════════════════
def stage_email(acc: Account, password: str):
    from providers.tempmail import create_account
    result = create_account(password)
    acc.email = result["email"]
    acc.email_token = result["token"]
    acc.password = password
    acc.created_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def stage_register_selenium(acc: Account, driver, timeout: int = 180):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    XIAOMI_REG = "https://account.xiaomi.com/pass/register?sid=api-platform&_json=true"
    driver.get(XIAOMI_REG)
    time.sleep(3)

    email_input = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='user'], input[name='email'], #email"))
    )
    email_input.clear()
    email_input.send_keys(acc.email)
    time.sleep(0.3)

    for pwd in driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
        pwd.clear()
        pwd.send_keys(acc.password)

    acc.status = Status.CAPTCHA
    deadline = time.time() + timeout
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
        acc.error = f"reCAPTCHA timeout ({timeout}s)"
        return

    time.sleep(1)
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit'], .register-btn")
        btn.click()
    except Exception:
        driver.execute_script("document.querySelector('form')?.submit()")
    time.sleep(5)

    for c in driver.get_cookies():
        if c["name"] in ("passToken", "cUserId", "userId", "serviceToken"):
            acc.cookies[c["name"]] = c["value"]

    if acc.cookies.get("passToken"):
        acc.status = Status.APIKEY
    else:
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

    for key, val in acc.cookies.items():
        s.cookies.set(key, val, domain=".xiaomimimo.com")
        s.cookies.set(key, val, domain="platform.xiaomimimo.com")

    try:
        s.get("https://platform.xiaomimimo.com/sts", params={
            "sign": "", "followup": "https://platform.xiaomimimo.com/api/v1/keys"
        }, timeout=15, allow_redirects=True)
    except Exception:
        pass

    r = s.post("https://platform.xiaomimimo.com/api/v1/keys",
               json={"name": f"auto-key-{int(time.time())}"}, timeout=15)

    if r.status_code in (200, 201):
        data = r.json()
        key = data.get("data", {}).get("key") or data.get("key") or data.get("data", {}).get("secret")
        if key:
            acc.api_keys.append(key)
            acc.status = Status.SUCCESS
            return
        # Try listing
        r2 = s.get("https://platform.xiaomimimo.com/api/v1/keys", timeout=15)
        if r2.status_code == 200:
            items = r2.json().get("data", [])
            if isinstance(items, list):
                for item in items:
                    k = item.get("key") or item.get("secret") if isinstance(item, dict) else item
                    if k:
                        acc.api_keys.append(k)
            if acc.api_keys:
                acc.status = Status.SUCCESS
                return
    acc.status = Status.FAILED
    acc.error = f"API key create failed (HTTP {r.status_code})"


# ═══════════════════════════════════════════════════════════════
#  PIPELINE RUNNERS
# ═══════════════════════════════════════════════════════════════
def run_pipeline_semi_auto(accounts: list[Account], cfg: dict, start_time: float):
    import undetected_chromedriver as uc

    opts = uc.ChromeOptions()
    if cfg.get("headless"):
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--lang=en-US,en")

    driver = uc.Chrome(options=opts)
    timeout = cfg.get("timeout", 180)

    try:
        for acc in accounts:
            acc.status = Status.EMAIL
            try:
                stage_email(acc, cfg["password"])
            except Exception as e:
                acc.status = Status.FAILED
                acc.error = f"email: {str(e)[:60]}"
                continue

            acc.status = Status.REGISTER
            try:
                stage_register_selenium(acc, driver, timeout)
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

            time.sleep(2)
    finally:
        driver.quit()


# ═══════════════════════════════════════════════════════════════
#  INTERACTIVE MENU
# ═══════════════════════════════════════════════════════════════
BANNER = r"""
   ╔═══════════════════════════════════════════════════════╗
   ║          auto-keys TUI  ·  Xiaomi MiMo               ║
   ║    Disposable Email → Account → API Key Generator     ║
   ╚═══════════════════════════════════════════════════════╝
"""


def show_banner():
    console.print(BANNER, style="bold cyan")


def show_main_menu(cfg: dict):
    """Display main menu with current settings."""
    console.print()
    console.print(Panel("[bold]Main Menu[/bold]", border_style="cyan"))

    # Current settings table
    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    tbl.add_column("Setting", style="bold")
    tbl.add_column("Value")
    tbl.add_row("Accounts", f"[cyan]{cfg['count']}[/cyan]")
    tbl.add_row("Password", f"[dim]{cfg['password']}[/dim]")
    tbl.add_row("Mode", f"[yellow]{cfg['mode']}[/yellow]")
    tbl.add_row("Headless", f"{'Yes' if cfg['headless'] else 'No'}")
    tbl.add_row("Output Dir", cfg["output_dir"])
    tbl.add_row("CAPTCHA Timeout", f"{cfg['timeout']}s")
    if cfg.get("solver"):
        tbl.add_row("Solver", f"{cfg['solver']} ({cfg.get('solver_key', 'N/A')[:10]}...)")
    console.print(Panel(tbl, title="⚙️  Current Settings", border_style="blue"))

    # Menu options
    console.print()
    menu = Table(box=None, show_header=False, padding=(0, 1))
    menu.add_column("#", style="bold cyan", width=3)
    menu.add_column("Action")
    menu.add_row("1", "🚀 Start batch generation")
    menu.add_row("2", "⚙️  Change account count")
    menu.add_row("3", "🔑 Change password")
    menu.add_row("4", "📦 Change mode (semi-auto / auto / cookies)")
    menu.add_row("5", "🖥️  Toggle headless browser")
    menu.add_row("6", "📁 Change output directory")
    menu.add_row("7", "⏱  Change CAPTCHA timeout")
    menu.add_row("8", "📊 View previous batches")
    menu.add_row("9", "📧 Generate disposable emails only")
    menu.add_row("0", "🚪 Exit")
    console.print(menu)
    console.print()


def setting_change_count(cfg: dict):
    console.print(f"\n[dim]Current: {cfg['count']}[/dim]")
    new_count = IntPrompt.ask("Number of accounts to generate", default=cfg["count"])
    cfg["count"] = int(new_count)
    save_config(cfg)
    console.print(f"[green]✅ Account count set to {cfg['count']}[/green]")


def setting_change_password(cfg: dict):
    console.print(f"\n[dim]Current: {cfg['password']}[/dim]")
    new_pass = Prompt.ask("Account password", default=cfg["password"])
    cfg["password"] = new_pass
    save_config(cfg)
    console.print(f"[green]✅ Password updated[/green]")


def setting_change_mode(cfg: dict):
    console.print(f"\n[dim]Current: {cfg['mode']}[/dim]")
    console.print("  [cyan]1[/cyan] semi-auto  — Selenium + manual reCAPTCHA (free)")
    console.print("  [cyan]2[/cyan] auto       — 2captcha/capsolver API (paid)")
    console.print("  [cyan]3[/cyan] cookies    — import existing cookies")
    choice = Prompt.ask("Select mode", choices=["1", "2", "3"], default="1")
    modes = {"1": "semi-auto", "2": "auto", "3": "cookies"}
    cfg["mode"] = modes[choice]

    if cfg["mode"] == "auto":
        cfg["solver"] = Prompt.ask("Solver (2captcha / capsolver)", choices=["2captcha", "capsolver"])
        cfg["solver_key"] = Prompt.ask("Solver API key")
    elif cfg["mode"] == "cookies":
        cfg["cookies_file"] = Prompt.ask("Path to cookies JSON file")

    save_config(cfg)
    console.print(f"[green]✅ Mode set to {cfg['mode']}[/green]")


def setting_toggle_headless(cfg: dict):
    cfg["headless"] = not cfg["headless"]
    save_config(cfg)
    state = "ON" if cfg["headless"] else "OFF"
    console.print(f"[green]✅ Headless: {state}[/green]")


def setting_change_output(cfg: dict):
    console.print(f"\n[dim]Current: {cfg['output_dir']}[/dim]")
    new_dir = Prompt.ask("Output directory", default=cfg["output_dir"])
    cfg["output_dir"] = new_dir
    save_config(cfg)
    console.print(f"[green]✅ Output dir: {cfg['output_dir']}[/green]")


def setting_change_timeout(cfg: dict):
    console.print(f"\n[dim]Current: {cfg['timeout']}s[/dim]")
    new_timeout = IntPrompt.ask("CAPTCHA timeout (seconds)", default=cfg["timeout"])
    cfg["timeout"] = int(new_timeout)
    save_config(cfg)
    console.print(f"[green]✅ Timeout: {cfg['timeout']}s[/green]")


def view_batches(cfg: dict):
    """Show existing batches in output dir."""
    output_dir = cfg["output_dir"]
    if not os.path.exists(output_dir):
        console.print("[yellow]No batches found — output directory doesn't exist yet.[/yellow]")
        return

    files = sorted(glob.glob(os.path.join(output_dir, "account*.json")))
    if not files:
        console.print("[yellow]No batches found yet.[/yellow]")
        return

    tbl = Table(box=box.ROUNDED, title="📊 Previous Batches")
    tbl.add_column("Batch", style="bold cyan")
    tbl.add_column("Accounts")
    tbl.add_column("Success")
    tbl.add_column("API Keys")
    tbl.add_column("File")

    for f in files:
        name = os.path.basename(f)
        batch_name = name.replace(".json", "")
        try:
            with open(f) as fp:
                data = json.load(fp)
            total = len(data)
            ok = sum(1 for a in data if a.get("status") == "success")
            keys = sum(len(a.get("api_keys", [])) for a in data)
            tbl.add_row(batch_name, str(total), f"[green]{ok}[/green]", f"[cyan]{keys}[/cyan]", name)
        except Exception:
            tbl.add_row(batch_name, "?", "?", "?", name)

    console.print(tbl)


def action_generate_emails(cfg: dict):
    """Generate disposable emails only."""
    count = IntPrompt.ask("How many emails?", default=5)
    console.print(f"\n📧 Generating {count} disposable emails...")

    from providers.tempmail import create_account
    results = []
    for i in range(count):
        try:
            r = create_account(cfg["password"])
            results.append(r)
            console.print(f"  [green]✅ {i+1}.[/green] {r['email']}")
            time.sleep(1)
        except Exception as e:
            console.print(f"  [red]❌ {i+1}.[/red] Error: {e}")

    # Save
    os.makedirs(cfg["output_dir"], exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(cfg["output_dir"], f"emails_{ts}.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    console.print(f"\n[green]✅ Saved {len(results)} emails → {path}[/green]")


def action_start_batch(cfg: dict):
    """Start batch generation with live dashboard."""
    count = cfg["count"]
    console.print(f"\n🚀 Starting batch: {count} accounts, mode: {cfg['mode']}")
    console.print(f"[dim]Output → {cfg['output_dir']}[/dim]\n")

    if cfg["mode"] == "semi-auto":
        console.print("[yellow]Browser will open — click 'I'm not a robot' for each account[/yellow]")
        console.print(f"[dim]Timeout: {cfg['timeout']}s per CAPTCHA[/dim]\n")

    if not Confirm.ask(f"Ready to generate {count} accounts?", default=True):
        console.print("[dim]Cancelled.[/dim]")
        return

    accounts = [Account(index=i + 1) for i in range(count)]
    start_time = time.time()

    with Live(build_dashboard(accounts, start_time, f"🚀 Generating {count} accounts..."),
              refresh_per_second=2, console=console) as live:

        def updater():
            while any(a.status not in (Status.SUCCESS, Status.FAILED, Status.SKIPPED) for a in accounts):
                live.update(build_dashboard(accounts, start_time,
                             f"🚀 Generating {count} accounts... ({cfg['mode']})"))
                time.sleep(0.5)
            live.update(build_dashboard(accounts, start_time, f"✅ Done — {count} accounts"))

        bg = threading.Thread(target=updater, daemon=True)
        bg.start()

        if cfg["mode"] == "semi-auto":
            run_pipeline_semi_auto(accounts, cfg, start_time)
        else:
            console.print("[red]Auto/cookies mode — use CLI directly: python cli.py generate -p xiaomi -c N[/red]")

        time.sleep(1)

    # Save
    json_path, txt_path, batch_num, key_count = save_outputs(accounts, cfg["output_dir"])

    ok = sum(1 for a in accounts if a.status == Status.SUCCESS)
    fail = sum(1 for a in accounts if a.status == Status.FAILED)
    elapsed = time.time() - start_time

    console.print()
    console.print(Panel(
        f"[green]✅ Success: {ok}[/green]  |  [red]❌ Failed: {fail}[/red]  |  [cyan]🔑 API Keys: {key_count}[/cyan]\n"
        f"[dim]⏱  {elapsed:.0f}s total[/dim]\n\n"
        f"📄 Batch {batch_num}: {json_path}\n"
        f"📝 API Keys: {txt_path}",
        title="📊 Batch Results",
        border_style="green" if ok > 0 else "red"
    ))

    if fail > 0:
        console.print(f"\n[red]Failed accounts:[/red]")
        for a in accounts:
            if a.status == Status.FAILED:
                console.print(f"  ❌ #{a.index} {a.email} — {a.error}")


# ═══════════════════════════════════════════════════════════════
#  MAIN LOOP
# ═══════════════════════════════════════════════════════════════
def interactive_menu():
    """Main interactive TUI loop."""
    cfg = load_config()
    show_banner()

    while True:
        show_main_menu(cfg)
        choice = Prompt.ask("Select option", choices=["0","1","2","3","4","5","6","7","8","9"], default="1")

        if choice == "1":
            action_start_batch(cfg)
        elif choice == "2":
            setting_change_count(cfg)
        elif choice == "3":
            setting_change_password(cfg)
        elif choice == "4":
            setting_change_mode(cfg)
        elif choice == "5":
            setting_toggle_headless(cfg)
        elif choice == "6":
            setting_change_output(cfg)
        elif choice == "7":
            setting_change_timeout(cfg)
        elif choice == "8":
            view_batches(cfg)
        elif choice == "9":
            action_generate_emails(cfg)
        elif choice == "0":
            console.print("\n[dim]👋 Bye![/dim]\n")
            break

        if choice != "0":
            Prompt.ask("\n[dim]Press Enter to continue...[/dim]", default="")


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="auto-keys TUI")
    parser.add_argument("-c", "--count", type=int, help="Direct batch mode: number of accounts")
    parser.add_argument("--password", default="masuk123!")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("-o", "--output", default="output")
    args = parser.parse_args()

    if args.count:
        # Direct mode (backward compatible)
        cfg = load_config()
        cfg["count"] = args.count
        cfg["password"] = args.password
        cfg["headless"] = args.headless
        cfg["output_dir"] = args.output
        action_start_batch(cfg)
    else:
        # Interactive TUI mode
        interactive_menu()


if __name__ == "__main__":
    main()
