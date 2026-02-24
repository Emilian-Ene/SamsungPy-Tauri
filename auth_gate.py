import sys
import urllib.request
from pathlib import Path

PASSWORD_SOURCE_URL = "https://raw.githubusercontent.com/Emilian-Ene/SamsungPy.v3/main/auth_password.txt"
APP_TITLE = "Samsung MDC Dashboard"
FETCH_TIMEOUT_SECONDS = 8
MAX_ATTEMPTS = 3
LOCAL_PASSWORD_FILE = Path(__file__).with_name("auth_password.txt")


def _show_message(kind: str, title: str, message: str) -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if kind == "error":
            messagebox.showerror(title, message, parent=root)
        else:
            messagebox.showinfo(title, message, parent=root)
    finally:
        root.destroy()


def _prompt_password(prompt: str) -> str | None:
    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return simpledialog.askstring(APP_TITLE, prompt, show="*", parent=root)
    finally:
        root.destroy()


def _fetch_expected_password() -> str | None:
    try:
        req = urllib.request.Request(
            PASSWORD_SOURCE_URL,
            headers={"User-Agent": "SamsungMDCDashboard-Auth/1.0"},
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8", errors="ignore")
    except Exception:
        text = ""

    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned and not cleaned.startswith("#"):
            return cleaned

    try:
        if LOCAL_PASSWORD_FILE.exists():
            local_text = LOCAL_PASSWORD_FILE.read_text(encoding="utf-8", errors="ignore")
            for line in local_text.splitlines():
                cleaned = line.strip()
                if cleaned and not cleaned.startswith("#"):
                    return cleaned
    except Exception:
        return None

    return ""


def require_online_password() -> bool:
    expected_password = _fetch_expected_password()

    if expected_password is None:
        _show_message(
            "error",
            "Password Validation Failed",
            "Could not load startup password from GitHub or local auth_password.txt.",
        )
        return False

    if expected_password == "":
        _show_message(
            "error",
            "Password Not Configured",
            "No password found in auth_password.txt on GitHub.",
        )
        return False

    for attempt in range(1, MAX_ATTEMPTS + 1):
        typed = _prompt_password("Enter password to open the app:")

        if typed is None:
            _show_message("info", "Cancelled", "App closed.")
            return False

        if typed == expected_password:
            return True

        attempts_left = MAX_ATTEMPTS - attempt
        if attempts_left > 0:
            _show_message("error", "Wrong Password", f"Incorrect password. Attempts left: {attempts_left}")

    _show_message("error", "Access Denied", "Too many failed attempts.")
    return False


if __name__ == "__main__":
    ok = require_online_password()
    raise SystemExit(0 if ok else 1)
