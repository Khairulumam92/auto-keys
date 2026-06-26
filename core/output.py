"""Output formatting — JSON accounts + api_keys.txt parser."""
import json
from datetime import datetime


def format_account(entry: dict) -> dict:
    """Normalize account entry to standard output format."""
    return {
        "email": entry.get("email", ""),
        "password": entry.get("password", "masuk123!"),
        "cookies": entry.get("cookies", {}),
        "created_at": entry.get("created_at", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")),
        "status": entry.get("status", "unknown"),
        "ultraspeed": entry.get("ultraspeed", True),
        "error": entry.get("error"),
    }


def format_batch(entries: list[dict]) -> list[dict]:
    """Format batch of accounts."""
    return [format_account(e) for e in entries]


def print_table(entries: list[dict], verbose: bool = False):
    """Print accounts as readable table to stdout."""
    ok = sum(1 for e in entries if e.get("status") == "success")
    fail = len(entries) - ok
    print(f"\n{'='*60}")
    print(f" Results: {ok} success / {fail} failed / {len(entries)} total")
    print(f"{'='*60}")
    for i, e in enumerate(entries, 1):
        status = "✅" if e.get("status") == "success" else "❌"
        email = e.get("email", "N/A")
        err = f" ({e['error']})" if e.get("error") else ""
        print(f"  {status} {i:>3}. {email}{err}")
        if verbose and e.get("cookies"):
            for k, v in e["cookies"].items():
                val = str(v)[:40] + "..." if len(str(v)) > 40 else v
                print(f"       {k}: {val}")
    print()


def parse_api_keys_file(path: str) -> list[str]:
    """Parse api_keys.txt — one sk-* key per line."""
    keys = []
    with open(path) as f:
        for line in f:
            key = line.strip()
            if key and key.startswith("sk-"):
                keys.append(key)
    return keys


def save_as_keys_txt(keys: list[str], path: str):
    """Save API keys to txt file (one per line)."""
    with open(path, "w") as f:
        f.write("\n".join(keys) + "\n")
