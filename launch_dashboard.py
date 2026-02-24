import os
import sys
import subprocess
import tempfile

from dashboard import main
from auth_gate import require_online_password


def create_desktop_shortcut():
    """Create a desktop shortcut for SamsungMDCDashboard.exe (runs once)."""
    try:
        # Only meaningful when running as a frozen PyInstaller exe
        if not getattr(sys, "frozen", False):
            return

        exe_path = sys.executable
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        shortcut_path = os.path.join(desktop, "Samsung MDC Dashboard.lnk")

        if os.path.exists(shortcut_path):
            return  # Already created

        # Write a tiny VBScript and run it to create the .lnk
        vbs = (
            f'Set oWS = WScript.CreateObject("WScript.Shell")\n'
            f'sLinkFile = "{shortcut_path}"\n'
            f'Set oLink = oWS.CreateShortcut(sLinkFile)\n'
            f'oLink.TargetPath = "{exe_path}"\n'
            f'oLink.WorkingDirectory = "{os.path.dirname(exe_path)}"\n'
            f'oLink.Description = "Samsung MDC Dashboard"\n'
            f'oLink.Save\n'
        )

        vbs_file = os.path.join(tempfile.gettempdir(), "_create_shortcut.vbs")
        with open(vbs_file, "w") as f:
            f.write(vbs)

        subprocess.run(
            ["cscript", "//Nologo", vbs_file],
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass  # Never crash the app over a shortcut


if __name__ == "__main__":
    if not require_online_password():
        raise SystemExit(1)
    create_desktop_shortcut()
    main()
