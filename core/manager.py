"""Credential pool manager — generate, store, validate accounts."""
import json
import os
import time
from datetime import datetime, timezone

from providers.tempmail import create_account, get_messages, get_message, extract_links


OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")


def generate_account(platform: str = "xiaomi", password: str = "masuk123!") -> dict:
    """Full pipeline: disposable email → register → extract tokens → return account dict."""
    # Step 1: create disposable email
    email_data = create_account(password)
    result = {
        "email": email_data["email"],
        "password": password,
        "cookies": {},
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "pending",
        "ultraspeed": True,
        "error": None,
    }

    # Step 2: register on platform
    if platform == "xiaomi":
        from providers.xiaomi import register
    elif platform == "qwen":
        from providers.qwen import register
    else:
        result["status"] = "error"
        result["error"] = f"unknown platform: {platform}"
        return result

    reg = register(email_data["email"], password)
    result["cookies"] = reg.get("cookies", {})
    result["status"] = reg.get("status", "error")
    result["error"] = reg.get("error")

    # Step 3: try email verification if needed
    if result["status"] == "success" and not result["cookies"].get("passToken"):
        try:
            msgs = get_messages(email_data["token"], wait=15)
            if msgs:
                msg = get_message(email_data["token"], msgs[0]["id"])
                body = msg.get("text", "") or msg.get("html", [""])[0] if isinstance(msg.get("html"), list) else ""
                links = extract_links(body)
                if links:
                    # auto-click verification link
                    import requests
                    requests.get(links[0], timeout=10, allow_redirects=True)
        except Exception:
            pass  # verification optional

    return result


def batch_generate(count: int, platform: str = "xiaomi", password: str = "masuk123!",
                    delay: float = 1.0, verbose: bool = False) -> list[dict]:
    """Generate multiple accounts sequentially with delay."""
    results = []
    for i in range(count):
        if verbose:
            print(f"  [{i+1}/{count}] generating...", end=" ", flush=True)
        try:
            r = generate_account(platform, password)
            results.append(r)
            if verbose:
                print(r["status"], r.get("email", ""))
        except Exception as e:
            results.append({"status": "error", "error": str(e), "email": "", "cookies": {}})
            if verbose:
                print(f"ERROR: {e}")
        if i < count - 1:
            time.sleep(delay)
    return results


def save_results(results: list[dict], filename: str = None) -> str:
    """Save results to JSON file in output/ directory."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if filename is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"accounts_{ts}.json"
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w") as f:
        json.dump(results, f, indent=4)
    return path


def load_existing(path: str) -> list[dict]:
    """Load existing account JSON file."""
    with open(path) as f:
        return json.load(f)


def extract_api_keys_file(path: str) -> list[str]:
    """Parse api_keys.txt file — one sk-* key per line."""
    keys = []
    with open(path) as f:
        for line in f:
            key = line.strip()
            if key and key.startswith("sk-"):
                keys.append(key)
    return keys
