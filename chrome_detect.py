"""Chrome version auto-detection for Windows/Mac/Linux.

Detects installed Chrome version so undetected_chromedriver
downloads the matching ChromeDriver version.
"""
import sys
import os
import re
import subprocess
import shutil


def detect_chrome_version() -> int | None:
    """Return major Chrome version (e.g. 149) or None if not found."""
    version_str = None

    if sys.platform == "win32":
        version_str = _detect_windows()
    elif sys.platform == "darwin":
        version_str = _detect_macos()
    else:
        version_str = _detect_linux()

    if version_str:
        m = re.search(r"(\d+)", version_str)
        if m:
            return int(m.group(1))
    return None


def _detect_windows() -> str | None:
    # Try registry first
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for path in (
                r"Software\Google\Chrome\BLBeacon",
                r"Software\Wow6432Node\Google\Chrome\BLBeacon",
            ):
                try:
                    key = winreg.OpenKey(hive, path)
                    val, _ = winreg.QueryValueEx(key, "version")
                    winreg.CloseKey(key)
                    return val
                except OSError:
                    pass
    except ImportError:
        pass

    # Try common install paths
    for base in (
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ):
        if not base:
            continue
        chrome_path = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
        if os.path.exists(chrome_path):
            return _version_from_binary(chrome_path)

    # Try PATH
    chrome_path = shutil.which("chrome") or shutil.which("google-chrome")
    if chrome_path:
        return _version_from_binary(chrome_path)

    return None


def _detect_macos() -> str | None:
    paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions",
    ]
    for p in paths:
        if os.path.exists(p):
            return _version_from_binary(p)
    # Try mdfind
    try:
        out = subprocess.check_output(
            ["mdfind", "kMDItemCFBundleIdentifier == 'com.google.Chrome'"],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode().strip()
        if out:
            plist = os.path.join(out.split("\n")[0], "Contents", "Info.plist")
            if os.path.exists(plist):
                import plistlib
                with open(plist, "rb") as f:
                    info = plistlib.load(f)
                return info.get("CFBundleShortVersionString")
    except Exception:
        pass
    return None


def _detect_linux() -> str | None:
    for cmd in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
        path = shutil.which(cmd)
        if path:
            return _version_from_binary(path)
    return None


def _version_from_binary(path: str) -> str | None:
    try:
        out = subprocess.check_output(
            [path, "--version"], timeout=5, stderr=subprocess.DEVNULL
        ).decode().strip()
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else None
    except Exception:
        return None


if __name__ == "__main__":
    ver = detect_chrome_version()
    print(f"Chrome version: {ver}" if ver else "Chrome not found")
