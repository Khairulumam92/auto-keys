#!/usr/bin/env python3
"""auto-keys — CLI tool for disposable email + AI platform account generation.

Usage:
    python cli.py generate --platform xiaomi --count 10
    python cli.py generate --platform qwen --count 5 --verbose
    python cli.py parse api_keys.txt
    python cli.py email --count 3
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

import json
import click
from datetime import datetime

from core.manager import batch_generate, save_results, load_existing, extract_api_keys_file
from core.output import format_batch, print_table, parse_api_keys_file, save_as_keys_txt
from providers.tempmail import create_account


@click.group()
@click.version_option("0.1.0")
def cli():
    """auto-keys — disposable email + AI platform account generator."""
    pass


@cli.command()
@click.option("-p", "--platform", type=click.Choice(["xiaomi", "qwen"]), default="xiaomi",
              help="Target platform (default: xiaomi)")
@click.option("-c", "--count", default=1, help="Number of accounts to generate")
@click.option("-d", "--delay", default=2.0, help="Delay between requests (seconds)")
@click.option("--password", default="masuk123!", help="Account password")
@click.option("-v", "--verbose", is_flag=True, help="Show details per account")
@click.option("-o", "--output", default=None, help="Output filename (auto-generated if omitted)")
def generate(platform, count, delay, password, verbose, output):
    """Generate accounts on target platform."""
    click.echo(f"🚀 Generating {count} account(s) on {platform}...")
    results = batch_generate(count, platform, password, delay, verbose)

    formatted = format_batch(results)
    print_table(formatted, verbose)

    path = save_results(formatted, output)
    ok = sum(1 for r in results if r.get("status") == "success")
    click.echo(f"💾 Saved {ok}/{count} accounts → {path}")


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("-v", "--verbose", is_flag=True, help="Show cookie details")
def show(file, verbose):
    """Display accounts from existing JSON file."""
    data = load_existing(file)
    formatted = format_batch(data)
    print_table(formatted, verbose)


@cli.command()
@click.argument("file", type=click.Path(exists=True))
def keys(file):
    """Extract API keys from api_keys.txt file."""
    if file.endswith(".txt"):
        klist = parse_api_keys_file(file)
    else:
        klist = extract_api_keys_file(file)
    click.echo(f"🔑 Found {len(klist)} API keys")
    for i, k in enumerate(klist, 1):
        masked = k[:8] + "..." + k[-4:]
        click.echo(f"  {i:>3}. {masked}")
    if klist:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = f"output/parsed_keys_{ts}.txt"
        os.makedirs("output", exist_ok=True)
        save_as_keys_txt(klist, out)
        click.echo(f"💾 Saved → {out}")


@cli.command()
@click.option("-c", "--count", default=1, help="Number of emails to create")
@click.option("-v", "--verbose", is_flag=True, help="Show token details")
def email(count, verbose):
    """Create disposable email accounts (no platform registration)."""
    from providers.tempmail import get_domains
    domains = get_domains()
    click.echo(f"📧 Available domains: {', '.join(domains[:5])}...")
    results = []
    for i in range(count):
        acc = create_account()
        results.append(acc)
        click.echo(f"  {i+1}. {acc['email']}")
        if verbose:
            click.echo(f"     token: {acc['token'][:30]}...")

    # Save
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"output/emails_{ts}.json"
    os.makedirs("output", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    click.echo(f"💾 Saved → {out_path}")


@cli.command()
@click.option("-p", "--platform", type=click.Choice(["xiaomi", "qwen"]), default="xiaomi")
def endpoints(platform):
    """Show current registration endpoints (for RE reference)."""
    if platform == "xiaomi":
        from providers.xiaomi import ENDPOINTS, PLATFORM_BASE, SID
        click.echo(f"📌 Xiaomi/MiMo endpoints:")
        click.echo(f"  Platform:  {PLATFORM_BASE}")
        click.echo(f"  SID:       {SID}")
        for name, url in ENDPOINTS.items():
            click.echo(f"  {name}: {url}")
    elif platform == "qwen":
        from providers.qwen import BASE_URL, REGISTER_URL, APIKEY_URL
        click.echo(f"📌 DashScope/Qwen endpoints:")
        click.echo(f"  Base:     {BASE_URL}")
        click.echo(f"  Register: {REGISTER_URL}")
        click.echo(f"  API Key:  {APIKEY_URL}")


@cli.command()
@click.option("-c", "--count", default=1, help="Number of accounts to register")
@click.option("--headless-off", is_flag=True, help="Show browser window (click CAPTCHA visible)")
@click.option("-v", "--verbose", is_flag=True)
def register(count, headless_off, verbose):
    """Register Xiaomi accounts — auto-fill + manual reCAPTCHA click."""
    from selenium_recaptcha import batch_register, save_results
    headless = not headless_off
    click.echo(f"🚀 Registering {count} Xiaomi account(s) via Selenium...")
    click.echo(f"   {'Browser window visible — klik reCAPTCHA manual' if not headless else 'Headless mode'}")
    click.echo()
    results = batch_register(count, headless=headless, verbose=verbose)
    ok = sum(1 for r in results if r["status"] == "success")
    path = save_results(results)
    click.echo(f"\n{'='*50}")
    click.echo(f"✅ {ok}/{count} registered → {path}")
    for r in results:
        icon = "✅" if r["status"] == "success" else "⚠️" if r["status"] == "need_verify" else "❌"
        click.echo(f"  {icon} {r['email']} — {r['status']}")


if __name__ == "__main__":
    cli()
