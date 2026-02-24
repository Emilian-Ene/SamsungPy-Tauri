"""
Update notifier for SamsungMDCDashboard.
Checks GitHub Releases and notifies users when a newer EXE is available.
"""

import json
import re
import urllib.request
import webbrowser

GITHUB_REPO = "Emilian-Ene/SamsungPy.v2"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
UPDATE_NOTIFY_ENABLED = True


def _parse_version(v: str) -> tuple:
    """Convert a version string like 'v1.2.3', 'v.1.2.3' or '1.2.3' to a comparable tuple."""
    v = v.lstrip("v").lstrip(".").strip()
    parts = re.split(r"[.\-]", v)
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            break
    return tuple(result)


def _show_dialog(kind: str, title: str, message: str) -> bool:
    """Show a minimal Tk dialog. kind: 'yesno', 'error', 'info'. Returns True/False for yesno."""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if kind == "yesno":
            return messagebox.askyesno(title, message, parent=root)
        elif kind == "error":
            messagebox.showerror(title, message, parent=root)
        else:
            messagebox.showinfo(title, message, parent=root)
    finally:
        root.destroy()
    return False


def check_and_update(current_version: str) -> None:
    """
    Check GitHub for a newer release.
    If one is found, show a message and offer a download link.
    Silently skips on any network / parse error so the app always starts normally.
    """
    if not UPDATE_NOTIFY_ENABLED:
        return

    # ── 1. Fetch latest release from GitHub API ──────────────────────────────
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"User-Agent": "SamsungMDCDashboard-Updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return  # No internet or API down — start the app normally

    # ── 2. Compare versions ───────────────────────────────────────────────────
    latest_tag = data.get("tag_name", "")
    latest_ver = _parse_version(latest_tag)
    current_ver = _parse_version(current_version)

    if not latest_ver or latest_ver <= current_ver:
        return  # Already up to date

    # ── 3. Find the EXE asset in the release ─────────────────────────────────
    assets = data.get("assets", [])
    exe_asset = next(
        (a for a in assets if a["name"].lower().endswith(".exe")),
        None,
    )
    if not exe_asset:
        return  # No EXE in this release — skip silently

    download_url = exe_asset["browser_download_url"]
    asset_name = exe_asset["name"]
    release_page = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases")

    # ── 4. Ask the user ───────────────────────────────────────────────────────
    notes = data.get("body", "").strip()
    note_snippet = f"\n\nRelease notes:\n{notes[:300]}" if notes else ""

    answer = _show_dialog(
        "yesno",
        "Update Available",
        f"A new version is available:  {latest_tag}\n"
        f"You are running:             v{current_version}\n\n"
        f"Open download page now? ({asset_name})"
        f"{note_snippet}",
    )
    if not answer:
        return

    # ── 5. Open browser to download URL (fallback to release page) ──────────
    try:
        webbrowser.open(download_url, new=2)
    except Exception:
        try:
            webbrowser.open(release_page, new=2)
        except Exception:
            _show_dialog(
                "info",
                "Update Link",
                f"Download latest EXE here:\n{download_url}",
            )
