# auto-keys

CLI + TUI tool untuk auto-generate disposable email, register akun Xiaomi MiMo, dan extract API keys secara batch.

## Features

- 📧 **Disposable Email** — mail.tm API, zero cost
- 🔐 **Auto Register** — Xiaomi MiMo platform via Selenium
- 🔑 **API Key Extraction** — auto-create API keys dari platform.xiaomimimo.com
- 📊 **Rich TUI Dashboard** — live progress, stats, per-account status
- 🖱️ **reCAPTCHA v2** — semi-auto (user klik 1 tombol per akun)
- 📁 **Per-account Output** — JSON credential + TXT API key per akun

## Prerequisites

- **Python 3.10+** — https://python.org
- **Google Chrome** — https://chrome.google.com

## Install

### Windows
```cmd
git clone https://github.com/Khairulumam92/auto-keys.git
cd auto-keys
setup.bat
```

### Linux/macOS
```bash
git clone https://github.com/Khairulumam92/auto-keys.git
cd auto-keys
pip install -r requirements.txt
```

## Usage

### TUI Mode (Recommended)

Interactive dashboard dengan live progress dan stats:

```bash
# Atur jumlah akun (default: 45)
python tui.py --count 10

# Test 3 akun dulu
python tui.py --count 3 --no-headless

# Full 45 akun
python tui.py --count 45 --no-headless

# Custom password
python tui.py --count 20 --password "MyP@ss123"

# Custom output dir
python tui.py --count 50 -o results/
```

### CLI Mode

```bash
# Generate disposable email saja
python cli.py email -c 5 -v

# Parse API keys dari file
python cli.py keys api_keys.txt

# Lihat real endpoints Xiaomi MiMo
python cli.py endpoints -p xiaomi

# Lihat endpoints DashScope/Qwen
python cli.py endpoints -p qwen

# Tampilkan hasil dari JSON
python cli.py show output/account1.json
```

### Selenium Direct

```bash
# Register langsung via browser
python selenium_recaptcha.py --count 5 --no-headless -v
```

## Registration Modes

### 1. Semi-Auto (Default, Free)
Browser terbuka → auto-fill email + password → user klik "I'm not a robot" → auto-submit → extract cookies → create API key.

```bash
python tui.py --count 45 --no-headless
```

**Trade-off:** 1 klik manual per akun. 45 akun = ~10-15 menit.

### 2. Auto (CAPTCHA Solver API)
Fully automated via 2captcha atau capsolver:

```bash
python tui.py --count 45 --mode auto --solver 2captcha --key YOUR_API_KEY
```

**Cost:** ~$3/1000 solves (2captcha) atau ~$0.4/1000 (capsolver).

### 3. Cookies Import
Import existing cookies, just create API keys:

```bash
python tui.py --count 45 --mode cookies --cookies cookies.json
```

## Output Format

### Per-Account Files

```
output/
├── account1.json           # Credential akun 1
├── account-api1.txt        # API key akun 1
├── account2.json           # Credential akun 2
├── account-api2.txt        # API key akun 2
├── ...
├── account45.json          # Credential akun 45
├── account-api45.txt       # API key akun 45
├── summary_YYYYMMDD.json   # Semua akun gabungan
└── all_api_keys_YYYYMMDD.txt  # Semua API keys
```

### account1.json
```json
{
  "email": "abc123@web-library.net",
  "password": "masuk123!",
  "cookies": {
    "passToken": "V1:DXmurwq2/...",
    "cUserId": "i2pFH_0AWU_5vBl0",
    "userId": "6879419701"
  },
  "api_keys": ["sk-sl286q937vsg..."],
  "created_at": "2026-06-26T12:00:00Z",
  "status": "success",
  "ultraspeed": true,
  "error": null
}
```

### account-api1.txt
```
sk-sl286q937vsgkchjtd39smddqfskk6vxz38w5qz5qfxw1bbj
```

## Flow Diagram

```
┌─────────────┐    ┌──────────────────┐    ┌───────────────────┐
│  mail.tm    │───>│ account.xiaomi   │───>│ platform.xiaomi   │
│  disposable │    │ .com/pass/       │    │ mimimo.com/api/v1 │
│  email      │    │ register         │    │ /keys             │
└─────────────┘    │                  │    │                   │
                   │ [auto-fill]      │    │ [create API key]  │
                   │ [reCAPTCHA v2]   │    │                   │
                   │ [submit]         │    └───────────────────┘
                   └──────────────────┘
```

## Architecture

```
auto-keys/
├── tui.py                  # Rich TUI dashboard (main entry)
├── cli.py                  # Click CLI (6 commands)
├── selenium_recaptcha.py   # Selenium + reCAPTCHA handler
├── full_pipeline.py        # ddddocr CAPTCHA solver
├── captcha_solver.py       # 2captcha/capsolver integration
├── mitm_intercept.py       # Traffic capture for RE
├── selenium_helper.py      # Browser automation helper
├── providers/
│   ├── tempmail.py         # mail.tm disposable email
│   ├── xiaomi.py           # Xiaomi MiMo endpoints
│   └── qwen.py             # DashScope/Qwen endpoints
├── core/
│   ├── manager.py          # Credential pool management
│   └── output.py           # JSON/TXT formatter
├── requirements.txt
├── setup.bat               # Windows setup script
└── README.md
```

## Endpoints (Verified)

### Xiaomi MiMo
| Endpoint | URL |
|----------|-----|
| Platform | https://platform.xiaomimimo.com |
| API Base | https://platform.xiaomimimo.com/api/v1/ |
| Models | /api/v1/models (public) |
| API Keys | /api/v1/keys (auth required) |
| Register | https://account.xiaomi.com/pass/register |
| Login | https://account.xiaomi.com/pass/serviceLogin |
| SID | api-platform |

### DashScope/Qwen
| Endpoint | URL |
|----------|-----|
| Base | https://dashscope.console.aliyun.com |
| Register | /api/account/register |
| API Key | /api/apikey/create |

## Troubleshooting

### Chrome not found
Install Chrome: https://chrome.google.com

### undetected-chromedriver version mismatch
Auto-detects Chrome version. If issues:
```bash
pip install --upgrade undetected-chromedriver
```

### reCAPTCHA timeout
- Pastikan browser visible (`--no-headless`)
- Klik "I'm not a robot" dalam 180 detik
- Kalau timeout, akun di-skip dan lanjut ke berikutnya

### mail.tm rate limit
Tunggu 30 detik antar batch. Tool sudah auto-delay 2-3 detik.

## License

For authorized security research and testing only.

## Disclaimer

This tool is for authorized penetration testing and security research.
Users are responsible for compliance with applicable laws and terms of service.
