"""Disposable email provider via mail.tm API (free, no auth required)."""
import time
import random
import string
import requests

BASE = "https://api.mail.tm"

DOMAINS_CACHE = None


def get_domains():
    global DOMAINS_CACHE
    if DOMAINS_CACHE is None:
        r = requests.get(f"{BASE}/domains", timeout=10)
        r.raise_for_status()
        DOMAINS_CACHE = [d["domain"] for d in r.json()["hydra:member"]]
    return DOMAINS_CACHE


def random_local(length=12):
    chars = string.ascii_lowercase + string.digits
    parts = [random.choice(string.ascii_lowercase)]
    for _ in range(length - 1):
        parts.append(random.choice(chars))
    return "".join(parts)


def create_account(password="masuk123!"):
    """Create disposable email account on mail.tm. Returns {email, password, token, id}."""
    domains = get_domains()
    domain = random.choice(domains)
    local = random_local()
    email = f"{local}@{domain}"

    r = requests.post(f"{BASE}/accounts", json={"address": email, "password": password}, timeout=10)
    r.raise_for_status()
    data = r.json()

    # Get auth token
    r2 = requests.post(f"{BASE}/token", json={"address": email, "password": password}, timeout=10)
    r2.raise_for_status()
    token = r2.json()["token"]

    return {"email": email, "password": password, "token": token, "id": data.get("id")}


def get_messages(token, wait=0):
    """Fetch inbox messages. Optionally wait up to `wait` seconds for new messages."""
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.time() + wait
    while True:
        r = requests.get(f"{BASE}/messages", headers=headers, timeout=10)
        r.raise_for_status()
        msgs = r.json().get("hydra:member", [])
        if msgs or time.time() >= deadline:
            return msgs
        time.sleep(2)


def get_message(token, msg_id):
    """Fetch full message content."""
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{BASE}/messages/{msg_id}", headers=headers, timeout=10)
    r.raise_for_status()
    return r.json()


def extract_links(text):
    """Extract URLs from text body."""
    import re
    return re.findall(r'https?://[^\s<>"\']+', text)
