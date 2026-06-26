#!/usr/bin/env python3
"""mitmproxy addon — intercept Xiaomi registration traffic.

Usage:
    mitmdump -s mitm_intercept.py -p 8080 --set block_global=false

Then set browser proxy to 127.0.0.1:8080 and register manually at:
    https://account.xiaomi.com/pass/register

All requests/responses are logged to intercept_output/ for RE.
"""
import json
import os
import re
from datetime import datetime
from mitmproxy import http

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "intercept_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

XIAOMI_DOMAINS = [
    "account.xiaomi.com",
    "passport.xiaomi.com",
    "auth.xiaomi.com",
    "api.account.xiaomi.com",
]

ALIYUN_DOMAINS = [
    "dashscope.console.aliyun.com",
    "passport.aliyun.com",
    "login.aliyun.com",
    "account.aliyun.com",
]

captured = []


def request(flow: http.HTTPFlow):
    host = flow.request.pretty_host
    is_xiaomi = any(d in host for d in XIAOMI_DOMAINS)
    is_aliyun = any(d in host for d in ALIYUN_DOMAINS)

    if not (is_xiaomi or is_aliyun):
        return

    platform = "xiaomi" if is_xiaomi else "aliyun"
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "platform": platform,
        "method": flow.request.method,
        "url": flow.request.pretty_url,
        "headers": dict(flow.request.headers),
        "body": None,
    }

    if flow.request.content:
        try:
            body = flow.request.content.decode("utf-8", errors="replace")
            # Try to parse as form data
            if "application/x-www-form-urlencoded" in flow.request.headers.get("content-type", ""):
                entry["body"] = dict(re.findall(r'([^&=]+)=([^&]*)', body))
            elif "application/json" in flow.request.headers.get("content-type", ""):
                entry["body"] = json.loads(body)
            else:
                entry["body"] = body[:2000]
        except Exception:
            entry["body"] = flow.request.content[:2000].hex()

    captured.append(entry)
    _save(platform)


def response(flow: http.HTTPFlow):
    host = flow.request.pretty_host
    is_xiaomi = any(d in host for d in XIAOMI_DOMAINS)
    is_aliyun = any(d in host for d in ALIYUN_DOMAINS)

    if not (is_xiaomi or is_aliyun):
        return

    # Highlight key responses
    url = flow.request.pretty_url
    keywords = ["register", "login", "token", "cookie", "verify", "code", "sendEmail", "sendCode"]
    is_key = any(k in url.lower() for k in keywords)

    resp_entry = {
        "url": url,
        "status": flow.response.status_code,
        "headers": dict(flow.response.headers),
        "cookies": {},
    }

    # Extract cookies from Set-Cookie headers
    set_cookies = flow.response.headers.get_all("set-cookie")
    for sc in set_cookies:
        match = re.match(r'([^=]+)=([^;]*)', sc)
        if match:
            resp_entry["cookies"][match.group(1)] = match.group(2)

    # Extract response body
    if flow.response.content:
        try:
            ct = flow.response.headers.get("content-type", "")
            if "json" in ct:
                resp_entry["body"] = json.loads(flow.response.content.decode("utf-8", errors="replace"))
            elif "javascript" in ct:
                text = flow.response.content.decode("utf-8", errors="replace")
                # Xiaomi often returns JSONP: callback({...})
                match = re.search(r'callback\(({.*})\)', text)
                if match:
                    resp_entry["body"] = json.loads(match.group(1))
                else:
                    resp_entry["body"] = text[:3000]
            else:
                resp_entry["body"] = flow.response.content.decode("utf-8", errors="replace")[:3000]
        except Exception:
            resp_entry["body"] = flow.response.content[:1000].hex()

    if is_key:
        # Save key response separately
        _save_key_response(url, resp_entry)

    # Update last captured entry
    if captured:
        captured[-1]["response"] = resp_entry


def _save(platform: str):
    path = os.path.join(OUTPUT_DIR, f"{platform}_traffic.json")
    with open(path, "w") as f:
        json.dump(captured, f, indent=2, default=str)


def _save_key_response(url: str, resp: dict):
    ts = datetime.utcnow().strftime("%H%M%S")
    safe_url = re.sub(r'[^\w]', '_', url)[:60]
    path = os.path.join(OUTPUT_DIR, f"key_{ts}_{safe_url}.json")
    with open(path, "w") as f:
        json.dump({"url": url, "response": resp}, f, indent=2, default=str)
