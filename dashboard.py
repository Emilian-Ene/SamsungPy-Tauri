import asyncio
import csv
import json
import socket
import threading
import time
import tkinter as tk
from io import BytesIO, StringIO
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    from PIL import Image, ImageTk
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

import customtkinter as ctk
from samsung_mdc import MDC

try:
    from samsungtvws import SamsungTVWS
    _SMARTTVWS_AVAILABLE = True
except ImportError:
    SamsungTVWS = None
    _SMARTTVWS_AVAILABLE = False

SAVED_DEVICES_FILE = Path("saved_devices.json")
APP_VERSION = "1.0.1"
PROTOCOL_OPTIONS = ["AUTO", "SIGNAGE_MDC", "SMART_TV_WS"]
SMART_TV_KEYS = [
    "KEY_HOME",
    "KEY_POWER",
    "KEY_MUTE",
    "KEY_VOLUP",
    "KEY_VOLDOWN",
    "KEY_SOURCE",
    "KEY_MENU",
    "KEY_RETURN",
    "KEY_UP",
    "KEY_DOWN",
    "KEY_LEFT",
    "KEY_RIGHT",
    "KEY_ENTER",
]

SMART_TV_HDMI_MACROS = {
    "HDMI1": ["KEY_SOURCE", "KEY_ENTER"],
    "HDMI2": ["KEY_SOURCE", "KEY_RIGHT", "KEY_ENTER"],
    "HDMI3": ["KEY_SOURCE", "KEY_RIGHT", "KEY_RIGHT", "KEY_ENTER"],
    "HDMI4": ["KEY_SOURCE", "KEY_RIGHT", "KEY_RIGHT", "KEY_RIGHT", "KEY_ENTER"],
}

POWER_MAP = {0: "OFF", 1: "ON", 2: "REBOOT"}
MUTE_MAP = {0: "OFF", 1: "ON", 255: "UNAVAILABLE"}
INPUT_SOURCE_MAP = {
    0x18: "DVI",
    0x21: "HDMI1",
    0x23: "HDMI2",
    0x25: "DISPLAY_PORT_1",
    0x31: "HDMI3",
    0x33: "HDMI4",
}
PICTURE_ASPECT_MAP = {
    0x10: "PC_16_9",
    0x18: "PC_4_3",
    0x20: "PC_ORIGINAL_RATIO",
    0x01: "VIDEO_16_9",
    0x0B: "VIDEO_4_3",
}

UNSUPPORTED_COMMAND_HINTS = {
    "all_keys_lock": "Global key lock is not implemented on this panel/firmware variant.",
    "osd_aspect_ratio": "OSD aspect ratio requires orientation/PIP features that are not enabled for this mode.",
    "osd_pip_orientation": "PIP orientation is available only when PIP/orientation modes are supported and active.",
    "osd_source_content_orientation": "Source content orientation is unavailable for the current source/panel mode.",
    "picture_mode": "Picture mode query/control is restricted in this panel configuration.",
    "screen_mode": "Screen mode is unavailable for the active input/source configuration.",
    "standby": "Standby control is not exposed by this panel through MDC in the current firmware/mode.",
    "video_wall_mode": "Video wall features are disabled because this panel is not configured as a video wall.",
    "video_wall_model": "Video wall model settings are unavailable when video wall mode is off.",
    "video_wall_state": "Video wall state is unavailable when video wall mode is not enabled.",
}


def normalize_device(item: dict):
    if not isinstance(item, dict):
        return None

    ip = str(item.get("ip", "")).strip()
    if not ip:
        return None

    try:
        device_id = int(item.get("id", 0))
    except Exception:
        device_id = 0

    try:
        port = int(item.get("port", 1515))
    except Exception:
        port = 1515

    protocol = str(item.get("protocol", "AUTO")).strip().upper()
    if protocol not in PROTOCOL_OPTIONS:
        protocol = "AUTO"

    return {
        "ip": ip,
        "port": port,
        "id": device_id,
        "protocol": protocol,
        "site": str(item.get("site", "")).strip(),
        "description": str(item.get("description", "")).strip(),
    }


def load_saved_devices() -> list[dict]:
    if not SAVED_DEVICES_FILE.exists():
        return []
    try:
        payload = json.loads(SAVED_DEVICES_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            return []
        return [d for d in (normalize_device(item) for item in payload) if d]
    except Exception:
        return []


def save_saved_devices(devices: list[dict]) -> None:
    SAVED_DEVICES_FILE.write_text(
        json.dumps(devices, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_imported_devices(file_name: str, raw_bytes: bytes) -> list[dict]:
    lower_name = file_name.lower()

    if lower_name.endswith(".json"):
        payload = json.loads(raw_bytes.decode("utf-8"))
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            return []
        return [d for d in (normalize_device(item) for item in payload) if d]

    if lower_name.endswith(".csv"):
        text = raw_bytes.decode("utf-8")
        reader = csv.DictReader(StringIO(text))
        parsed = []
        for row in reader:
            mapped = {
                "ip": row.get("ip") or row.get("IP") or "",
                "port": row.get("port") or row.get("PORT") or 1515,
                "id": row.get("id") or row.get("ID") or 0,
                "protocol": row.get("protocol") or row.get("PROTOCOL") or "AUTO",
                "site": row.get("site") or row.get("SITE") or "",
                "description": row.get("description") or row.get("DESCRIPTION") or "",
            }
            normalized = normalize_device(mapped)
            if normalized:
                parsed.append(normalized)
        return parsed

    return []


def merge_devices(existing_devices: list[dict], incoming_devices: list[dict]) -> tuple[list[dict], int, int]:
    merged = list(existing_devices)
    index_by_ip = {device.get("ip"): idx for idx, device in enumerate(merged)}
    added = 0
    updated = 0

    for device in incoming_devices:
        ip = device.get("ip")
        if ip in index_by_ip:
            merged[index_by_ip[ip]] = device
            updated += 1
        else:
            index_by_ip[ip] = len(merged)
            merged.append(device)
            added += 1

    return merged, added, updated


def find_device_by_ip(devices: list[dict], ip: str):
    ip_to_find = ip.strip()
    for device in devices:
        if device.get("ip") == ip_to_find:
            return device
    return None


def _label(code, mapping):
    if code is None:
        return "UNKNOWN"
    return mapping.get(int(code), f"UNKNOWN ({code})")


def decode_status(raw_status):
    values = list(raw_status)
    power = values[0] if len(values) > 0 else None
    volume = values[1] if len(values) > 1 else None
    mute = values[2] if len(values) > 2 else None
    input_source = values[3] if len(values) > 3 else None
    picture_aspect = values[4] if len(values) > 4 else None

    return {
        "power": _label(power, POWER_MAP),
        "volume": volume,
        "mute": _label(mute, MUTE_MAP),
        "input_source": _label(input_source, INPUT_SOURCE_MAP),
        "picture_aspect": _label(picture_aspect, PICTURE_ASPECT_MAP),
    }


class SamsungDashboard(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Samsung Hybrid Screen Dashboard")
        self.geometry("1220x780")
        self.minsize(1100, 720)

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # ── Colour palette (overridable per theme) ───────────────────────────
        self._palette = {
            "accent":       "#1f6aa5",
            "accent_hover": "#1a5a8f",
            "danger":       "#c0392b",
            "danger_hover": "#a93226",
            "success":      "#1e8449",
            "success_hover":"#176339",
            "warning":      "#d68910",
            "warning_hover":"#b7770d",
            "neutral":      "#2e4057",
            "neutral_hover":"#253448",
            "sidebar_bg":   "#1a1a2e",
            "card_bg":      "#16213e",
            "card2_bg":     "#0f3460",
            "bar_bg":       "#0d0d1a",
        }

        self.saved_devices = load_saved_devices()

        self.selected_device_var = ctk.StringVar(value="(manual entry)")
        self.appearance_var = ctk.StringVar(value="Dark")
        self.device_search_var = ctk.StringVar()

        self.ip_var = ctk.StringVar(value="192.168.1.50")
        self.port_var = ctk.StringVar(value="1515")
        self.id_var = ctk.StringVar(value="0")
        self.protocol_var = ctk.StringVar(value="AUTO")
        self.site_var = ctk.StringVar(value="")
        self.description_var = ctk.StringVar(value="")

        self.volume_var = ctk.IntVar(value=50)
        self.brightness_var = ctk.IntVar(value=50)
        self.mute_var = ctk.StringVar(value="OFF")
        self.input_var = ctk.StringVar(value="HDMI1")

        self.status_var = ctk.StringVar(value="Status: idle")
        self.network_var = ctk.StringVar(value="Network: checking...")

        self._all_cli_commands = sorted(MDC._commands.keys())
        self.cli_command_var = ctk.StringVar(value=self._all_cli_commands[0] if self._all_cli_commands else "")
        self.cli_arg_var = ctk.StringVar(value="")
        self.consumer_key_var = ctk.StringVar(value=SMART_TV_KEYS[0])
        self.consumer_repeat_var = ctk.StringVar(value="1")
        self.cli_log_box: ctk.CTkTextbox | None = None
        # dynamic per-field widgets rebuilt on command change
        self._cli_arg_rows: list[dict] = []   # [{"var": StringVar, "enum": list|None}, ...]

        self._build_ui()
        self._refresh_saved_devices_menu()
        self._schedule_network_check()

    # ── UI helpers ────────────────────────────────────────────────────────────
    def _btn(self, parent, text, command, color=None, hover=None, icon="", **kw):
        p = self._palette
        fg  = color or p["accent"]
        hov = hover or p["accent_hover"]
        lbl = f"{icon}  {text}" if icon else text
        return ctk.CTkButton(
            parent, text=lbl, command=command,
            fg_color=fg, hover_color=hov,
            corner_radius=8, font=ctk.CTkFont(size=12, weight="bold"),
            **kw,
        )

    def _card(self, parent, **kw):
        return ctk.CTkFrame(
            parent, corner_radius=12,
            fg_color=self._palette["card_bg"],
            border_width=1, border_color="#1e3a5f",
            **kw,
        )

    def _section_label(self, parent, text):
        return ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#7fb3d3",
        )

    def _build_ui(self):
        p = self._palette
        self.configure(fg_color=p["bar_bg"])
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        # ════════════════════════════════════════════════════════════════════
        # SIDEBAR
        # ════════════════════════════════════════════════════════════════════
        sidebar = ctk.CTkFrame(self, width=290, corner_radius=0, fg_color=p["sidebar_bg"])
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        sidebar.grid_rowconfigure(6, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        logo_frame = ctk.CTkFrame(sidebar, fg_color=p["card2_bg"], corner_radius=0)
        logo_frame.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(logo_frame, text="🖥  SamsungPy",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#e8f4fd").grid(row=0, column=0, padx=20, pady=16, sticky="w")
        ctk.CTkLabel(logo_frame, text="Hybrid Screen Control Dashboard",
                     font=ctk.CTkFont(size=11),
                     text_color="#7fb3d3").grid(row=1, column=0, padx=20, pady=(0, 14), sticky="w")

        self._section_label(sidebar, "  DEVICE MANAGEMENT").grid(
            row=1, column=0, padx=16, pady=(14, 4), sticky="w")

        mgmt = ctk.CTkFrame(sidebar, fg_color="transparent")
        mgmt.grid(row=2, column=0, padx=12, pady=(0, 6), sticky="ew")
        mgmt.grid_columnconfigure((0, 1), weight=1)
        self._btn(mgmt, "Save",   self.save_current_device,   icon="💾", height=32).grid(row=0, column=0, padx=3, pady=3, sticky="ew")
        self._btn(mgmt, "Delete", self.delete_selected_device, icon="🗑", color=p["danger"], hover=p["danger_hover"], height=32).grid(row=0, column=1, padx=3, pady=3, sticky="ew")
        self._btn(mgmt, "Import", self.import_devices,         icon="📥", color=p["neutral"], hover=p["neutral_hover"], height=32).grid(row=1, column=0, padx=3, pady=3, sticky="ew")
        self._btn(mgmt, "Export", self.export_devices,         icon="📤", color=p["neutral"], hover=p["neutral_hover"], height=32).grid(row=1, column=1, padx=3, pady=3, sticky="ew")

        ctk.CTkFrame(sidebar, height=1, fg_color="#2a3a5e").grid(
            row=3, column=0, sticky="ew", padx=16, pady=4)
        self._section_label(sidebar, "  SAVED DEVICES").grid(
            row=4, column=0, padx=16, pady=(6, 4), sticky="w")

        search_entry = ctk.CTkEntry(
            sidebar, textvariable=self.device_search_var,
            placeholder_text="🔍  Search devices...",
            fg_color=p["bar_bg"], border_color="#2a4f7a", corner_radius=8,
            height=30,
        )
        search_entry.grid(row=5, column=0, padx=10, pady=(0, 4), sticky="ew")
        self.device_search_var.trace_add("write", lambda *_: self._rebuild_devices_list())

        self.devices_scroll = ctk.CTkScrollableFrame(
            sidebar, fg_color="transparent", label_text="")
        self.devices_scroll.grid(row=6, column=0, sticky="nsew", padx=8, pady=(0, 4))
        self.devices_scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            sidebar,
            text=f"Powered by Ionut E Ene (dev mode) • v{APP_VERSION}",
            text_color="#7fb3d3",
            font=ctk.CTkFont(size=10),
        ).grid(row=7, column=0, padx=14, pady=(2, 10), sticky="w")

        # hidden OptionMenu kept only for API compatibility with _refresh_saved_devices_menu
        self.saved_device_menu = ctk.CTkOptionMenu(
            sidebar, variable=self.selected_device_var,
            values=["(manual entry)"], command=self._on_selected_device,
            width=1, height=1)
        self.saved_device_menu.grid_remove()

        # ════════════════════════════════════════════════════════════════════
        # MAIN AREA – tabview
        # ════════════════════════════════════════════════════════════════════
        tabs = ctk.CTkTabview(
            self, corner_radius=12,
            fg_color=p["bar_bg"],
            segmented_button_fg_color=p["card2_bg"],
            segmented_button_selected_color=p["accent"],
            segmented_button_selected_hover_color=p["accent_hover"],
            segmented_button_unselected_color=p["card2_bg"],
            segmented_button_unselected_hover_color=p["neutral"],
            text_color="#e8f4fd",
        )
        tabs.grid(row=0, column=1, padx=(0, 12), pady=(12, 4), sticky="nsew")
        tabs.add("📟  Dashboard")
        tabs.add("⌨️  CLI Commands")

        tab_dash = tabs.tab("📟  Dashboard")
        tab_cli  = tabs.tab("⌨️  CLI Commands")
        tab_dash.grid_columnconfigure(0, weight=1)
        tab_dash.grid_rowconfigure(4, weight=1)
        tab_cli.grid_columnconfigure(0, weight=1)
        tab_cli.grid_rowconfigure(4, weight=1)

        # ── Bottom status bar ─────────────────────────────────────────────
        status_bar = ctk.CTkFrame(self, height=32, corner_radius=0, fg_color=p["card2_bg"])
        status_bar.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(0, 4))
        status_bar.grid_columnconfigure(1, weight=1)
        self.net_dot = ctk.CTkLabel(status_bar, text="●", text_color="#e74c3c",
                                    width=20, font=ctk.CTkFont(size=14))
        self.net_dot.grid(row=0, column=0, padx=(10, 2), pady=4, sticky="w")
        ctk.CTkLabel(status_bar, textvariable=self.network_var,
                     text_color="#a0c4e0", font=ctk.CTkFont(size=11)).grid(
            row=0, column=1, padx=4, pady=4, sticky="w")
        ctk.CTkLabel(status_bar, textvariable=self.status_var,
                     text_color="#7fb3d3", font=ctk.CTkFont(size=11)).grid(
            row=0, column=2, padx=(0, 14), pady=4, sticky="e")

        # ════════════════════════════════════════════════════════════════════
        # TAB 1 – Dashboard
        # ════════════════════════════════════════════════════════════════════

        # Connection card
        conn_card = self._card(tab_dash)
        conn_card.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 5))
        self._section_label(conn_card, "  CONNECTION").grid(
            row=0, column=0, columnspan=7, padx=14, pady=(10, 4), sticky="w")
        for c in range(7):
            conn_card.grid_columnconfigure(c, weight=1)
        for col, (label, var) in enumerate([
            ("IP Address",  self.ip_var),
            ("Port",        self.port_var),
            ("Protocol",    self.protocol_var),
            ("Display ID",  self.id_var),
            ("Site",        self.site_var),
            ("Description", self.description_var),
        ]):
            ctk.CTkLabel(conn_card, text=label, font=ctk.CTkFont(size=11),
                         text_color="#7fb3d3").grid(row=1, column=col, padx=8, pady=(0, 2), sticky="w")
            if label == "Protocol":
                ctk.CTkOptionMenu(
                    conn_card,
                    variable=var,
                    values=PROTOCOL_OPTIONS,
                    fg_color=p["bar_bg"],
                    button_color="#2a4f7a",
                    button_hover_color="#345a87",
                    dropdown_fg_color=p["card2_bg"],
                ).grid(row=2, column=col, padx=8, pady=(0, 10), sticky="ew")
            else:
                ctk.CTkEntry(conn_card, textvariable=var,
                             fg_color=p["bar_bg"], border_color="#2a4f7a",
                             corner_radius=8).grid(row=2, column=col, padx=8, pady=(0, 10), sticky="ew")

        conn_actions = ctk.CTkFrame(conn_card, fg_color="transparent")
        conn_actions.grid(row=2, column=6, padx=8, pady=(0, 10), sticky="ew")
        conn_actions.grid_columnconfigure((0, 1), weight=1)
        self._btn(conn_actions, "Check Status", self.get_status,
                  icon="🔍", color=p["success"], hover=p["success_hover"],
                  height=36).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self._btn(conn_actions, "Auto Probe", self.auto_probe_protocol,
                  icon="🧭", color=p["neutral"], hover=p["neutral_hover"],
                  height=36).grid(row=0, column=1, padx=(4, 0), sticky="ew")

        # Quick actions card
        qa_card = self._card(tab_dash)
        qa_card.grid(row=1, column=0, sticky="ew", padx=8, pady=5)
        self._section_label(qa_card, "  QUICK ACTIONS").grid(
            row=0, column=0, columnspan=5, padx=14, pady=(10, 6), sticky="w")
        for col, (text, cmd, icon, clr, hov) in enumerate([
            ("Reboot",         self.reboot_screen,  "🔄", p["danger"],  p["danger_hover"]),
            ("Get Serial",     self.get_serial,     "🔢", p["neutral"], p["neutral_hover"]),
            ("Home (Content)", self.send_home_key,  "🏠", p["accent"],  p["accent_hover"]),
            ("Mute Toggle",    self.set_mute,       "🔇", p["warning"], p["warning_hover"]),
            ("Screenshot",     self.take_screenshot, "📸", p["success"], p["success_hover"]),
        ]):
            qa_card.grid_columnconfigure(col, weight=1)
            self._btn(qa_card, text, cmd, icon=icon, color=clr, hover=hov, height=38).grid(
                row=1, column=col, padx=8, pady=(0, 10), sticky="ew")

        # Controls card (volume + brightness)
        ctrl_card = self._card(tab_dash)
        ctrl_card.grid(row=2, column=0, sticky="ew", padx=8, pady=5)
        self._section_label(ctrl_card, "  CONTROLS").grid(
            row=0, column=0, columnspan=4, padx=14, pady=(10, 4), sticky="w")
        ctrl_card.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.vol_val_label = ctk.CTkLabel(ctrl_card, text="50", width=32,
                                          font=ctk.CTkFont(size=12, weight="bold"),
                                          text_color="#e8f4fd")
        ctk.CTkLabel(ctrl_card, text="🔊  Volume",
                     font=ctk.CTkFont(size=12), text_color="#a0c4e0").grid(
            row=1, column=0, padx=(14, 4), pady=(0, 2), sticky="w")
        self.vol_val_label.grid(row=1, column=1, padx=4, pady=(0, 2), sticky="w")
        ctk.CTkSlider(ctrl_card, from_=0, to=100, variable=self.volume_var,
                      progress_color=p["accent"], button_color=p["accent_hover"],
                      command=lambda v: self.vol_val_label.configure(text=str(int(v)))
                      ).grid(row=2, column=0, columnspan=2, padx=14, pady=(0, 4), sticky="ew")
        self._btn(ctrl_card, "Set Volume", self.set_volume,
                  icon="▶", height=32).grid(row=3, column=0, columnspan=2, padx=14, pady=(0, 10), sticky="ew")

        self.bri_val_label = ctk.CTkLabel(ctrl_card, text="50", width=32,
                                          font=ctk.CTkFont(size=12, weight="bold"),
                                          text_color="#e8f4fd")
        ctk.CTkLabel(ctrl_card, text="☀️  Brightness",
                     font=ctk.CTkFont(size=12), text_color="#a0c4e0").grid(
            row=1, column=2, padx=(14, 4), pady=(0, 2), sticky="w")
        self.bri_val_label.grid(row=1, column=3, padx=4, pady=(0, 2), sticky="w")
        ctk.CTkSlider(ctrl_card, from_=0, to=100, variable=self.brightness_var,
                      progress_color=p["warning"], button_color=p["warning_hover"],
                      command=lambda v: self.bri_val_label.configure(text=str(int(v)))
                      ).grid(row=2, column=2, columnspan=2, padx=14, pady=(0, 4), sticky="ew")
        self._btn(ctrl_card, "Set Brightness", self.set_brightness,
                  icon="▶", color=p["warning"], hover=p["warning_hover"],
                  height=32).grid(row=3, column=2, columnspan=2, padx=14, pady=(0, 10), sticky="ew")

        # Input source card
        inp_card = self._card(tab_dash)
        inp_card.grid(row=3, column=0, sticky="ew", padx=8, pady=5)
        self._section_label(inp_card, "  INPUT SOURCE").grid(
            row=0, column=0, columnspan=3, padx=14, pady=(10, 4), sticky="w")
        inp_card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(inp_card, text="Source:", text_color="#a0c4e0",
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=(14, 8), pady=(0, 10), sticky="w")
        ctk.CTkOptionMenu(inp_card, variable=self.input_var,
                          values=sorted(set(INPUT_SOURCE_MAP.values())),
                          fg_color=p["bar_bg"], button_color=p["accent"],
                          button_hover_color=p["accent_hover"],
                          corner_radius=8).grid(row=1, column=1, padx=8, pady=(0, 10), sticky="ew")
        self._btn(inp_card, "Set Input", self.set_input_source,
                  icon="📡", height=34).grid(row=1, column=2, padx=14, pady=(0, 10), sticky="ew")

        # Dashboard log
        log_card = self._card(tab_dash)
        log_card.grid(row=4, column=0, sticky="nsew", padx=8, pady=(5, 8))
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        self._section_label(log_card, "  ACTIVITY LOG").grid(
            row=0, column=0, padx=14, pady=(10, 4), sticky="w")
        self.log_box = ctk.CTkTextbox(
            log_card, wrap="word", corner_radius=8,
            fg_color=p["bar_bg"], border_width=0,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color="#a0c4e0",
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        # ════════════════════════════════════════════════════════════════════
        # TAB 2 – CLI Commands
        # ════════════════════════════════════════════════════════════════════

        cli_top_card = self._card(tab_cli)
        cli_top_card.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 5))
        cli_top_card.grid_columnconfigure(1, weight=1)
        self._section_label(cli_top_card, "  COMMAND").grid(
            row=0, column=0, columnspan=3, padx=14, pady=(10, 4), sticky="w")
        ctk.CTkLabel(cli_top_card, text="Search:", text_color="#a0c4e0",
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=(14, 6), pady=(0, 10), sticky="w")
        self.cli_command_menu = ctk.CTkComboBox(
            cli_top_card, variable=self.cli_command_var,
            values=self._all_cli_commands,
            command=self._on_cli_command_picked,
            fg_color=p["bar_bg"], border_color="#2a4f7a",
            button_color=p["accent"], button_hover_color=p["accent_hover"],
            dropdown_fg_color=p["card_bg"], dropdown_hover_color=p["card2_bg"],
            dropdown_text_color="#e8f4fd",
            corner_radius=8,
        )
        self.cli_command_menu.grid(row=1, column=1, padx=8, pady=(0, 10), sticky="ew")
        self.cli_command_menu.bind("<KeyRelease>", self._on_cli_search)
        cli_btn_row = ctk.CTkFrame(cli_top_card, fg_color="transparent")
        cli_btn_row.grid(row=1, column=2, padx=(0, 10), pady=(0, 10), sticky="e")
        self._btn(cli_btn_row, "Get",  self.cli_get, icon="⬇", width=88, height=34).pack(side="left", padx=(0, 5))
        self._btn(cli_btn_row, "Set",  self.cli_set, icon="⬆",
                  color=p["success"], hover=p["success_hover"], width=88, height=34).pack(side="left", padx=(0, 5))
        self._btn(cli_btn_row, "Clear",
                  lambda: self.cli_log_box and self.cli_log_box.delete("1.0", "end"),
                  color=p["neutral"], hover=p["neutral_hover"], width=88, height=34).pack(side="left")

        consumer_card = self._card(tab_cli)
        consumer_card.grid(row=1, column=0, sticky="ew", padx=8, pady=5)
        consumer_card.grid_columnconfigure(1, weight=1)
        self._section_label(consumer_card, "  CONSUMER SMART TV KEYS").grid(
            row=0, column=0, columnspan=5, padx=14, pady=(10, 4), sticky="w")
        ctk.CTkLabel(consumer_card, text="Key:", text_color="#a0c4e0",
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=(14, 6), pady=(0, 10), sticky="w")
        ctk.CTkOptionMenu(
            consumer_card,
            variable=self.consumer_key_var,
            values=SMART_TV_KEYS,
            fg_color=p["bar_bg"],
            button_color=p["accent"],
            button_hover_color=p["accent_hover"],
            corner_radius=8,
        ).grid(row=1, column=1, padx=8, pady=(0, 10), sticky="ew")
        ctk.CTkLabel(consumer_card, text="Repeat:", text_color="#a0c4e0",
                     font=ctk.CTkFont(size=12)).grid(row=1, column=2, padx=(8, 6), pady=(0, 10), sticky="w")
        ctk.CTkEntry(
            consumer_card,
            textvariable=self.consumer_repeat_var,
            width=70,
            fg_color=p["bar_bg"], border_color="#2a4f7a", corner_radius=8,
        ).grid(row=1, column=3, padx=(0, 8), pady=(0, 10), sticky="w")
        self._btn(consumer_card, "Send Key", self.cli_send_consumer_key,
                  icon="📺", color=p["warning"], hover=p["warning_hover"],
                  width=120, height=34).grid(row=1, column=4, padx=(0, 14), pady=(0, 10), sticky="e")

        ctk.CTkLabel(consumer_card, text="HDMI Macro:", text_color="#a0c4e0",
                     font=ctk.CTkFont(size=12)).grid(row=2, column=0, padx=(14, 6), pady=(0, 10), sticky="w")
        hdmi_macro_row = ctk.CTkFrame(consumer_card, fg_color="transparent")
        hdmi_macro_row.grid(row=2, column=1, columnspan=4, padx=(8, 14), pady=(0, 10), sticky="ew")
        for idx, hdmi_name in enumerate(["HDMI1", "HDMI2", "HDMI3", "HDMI4"]):
            hdmi_macro_row.grid_columnconfigure(idx, weight=1)
            self._btn(
                hdmi_macro_row,
                hdmi_name,
                command=lambda n=hdmi_name: self.cli_send_consumer_hdmi_macro(n),
                icon="🎛",
                color=p["neutral"],
                hover=p["neutral_hover"],
                height=30,
            ).grid(row=0, column=idx, padx=(0 if idx == 0 else 4, 0), sticky="ew")

        args_card = self._card(tab_cli)
        args_card.grid(row=2, column=0, sticky="ew", padx=8, pady=5)
        args_card.grid_columnconfigure(0, weight=1)
        self._section_label(args_card, "  ARGUMENTS").grid(
            row=0, column=0, padx=14, pady=(10, 4), sticky="w")
        self.cli_args_scroll = ctk.CTkScrollableFrame(
            args_card, fg_color=p["bar_bg"], corner_radius=8, height=160)
        self.cli_args_scroll.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.cli_args_scroll.grid_columnconfigure(1, weight=1)
        self.cli_args_scroll.grid_columnconfigure(3, weight=1)

        manual_card = self._card(tab_cli)
        manual_card.grid(row=3, column=0, sticky="ew", padx=8, pady=5)
        manual_card.grid_columnconfigure(1, weight=1)
        self._section_label(manual_card, "  MANUAL OVERRIDE  (optional)").grid(
            row=0, column=0, columnspan=3, padx=14, pady=(10, 4), sticky="w")
        ctk.CTkLabel(manual_card, text="Values:", text_color="#a0c4e0",
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=(14, 6), pady=(0, 10), sticky="w")
        self.cli_arg_entry = ctk.CTkEntry(
            manual_card, textvariable=self.cli_arg_var,
            placeholder_text="comma-separated — overrides pickers above, e.g.  ON,50",
            fg_color=p["bar_bg"], border_color="#2a4f7a", corner_radius=8,
        )
        self.cli_arg_entry.grid(row=1, column=1, columnspan=2, padx=(0, 14), pady=(0, 10), sticky="ew")
        self.timer15_hint_label = ctk.CTkLabel(
            manual_card,
            text="Tip: timer_15 format starts with timer_id (1-7), then values. Example: 1,08:00,ON,18:00,OFF,...",
            text_color="#7fb3d3",
            font=ctk.CTkFont(size=10),
            wraplength=560,
            justify="left",
        )
        self.timer15_hint_label.grid(row=2, column=0, columnspan=3, padx=14, pady=(0, 10), sticky="w")
        self.timer15_hint_label.grid_remove()

        cli_log_card = self._card(tab_cli)
        cli_log_card.grid(row=4, column=0, sticky="nsew", padx=8, pady=(5, 8))
        cli_log_card.grid_columnconfigure(0, weight=1)
        cli_log_card.grid_rowconfigure(1, weight=1)
        self._section_label(cli_log_card, "  COMMAND OUTPUT").grid(
            row=0, column=0, padx=14, pady=(10, 4), sticky="w")
        self.cli_log_box = ctk.CTkTextbox(
            cli_log_card, wrap="word", corner_radius=8,
            fg_color=p["bar_bg"], border_width=0,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color="#a0c4e0",
        )
        self.cli_log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self._on_cli_command_picked(self.cli_command_var.get())
        self.log("Dashboard ready.")

    def log(self, text: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_box.insert("end", f"[{timestamp}] {text}\n")
        self.log_box.see("end")

    def cli_log(self, text: str):
        if not self.cli_log_box:
            return
        timestamp = time.strftime("%H:%M:%S")
        self.cli_log_box.insert("end", f"[{timestamp}] {text}\n")
        self.cli_log_box.see("end")

    @staticmethod
    def _field_placeholder(field) -> str:
        """Return a helpful placeholder string based on the field type."""
        t = type(field).__name__
        range_ = getattr(field, "range", None)
        if t in ("Int", "Int+range"):
            if range_:
                lo, hi = range_.start, range_.stop - 1
                return f"int  ({lo}–{hi})"
            return "integer"
        if t == "Bool":
            return "ON | OFF (or 1 / 0)"
        if t == "Time":
            return "HH:MM  e.g. 08:30"
        if t == "Time12H":
            return "HH:MM  e.g. 08:30  (12-h clock)"
        if t == "DateTime":
            return "YYYY-MM-DD HH:MM  or  YYYY-MM-DD HH:MM:SS"
        if t == "IPAddress":
            return "e.g. 192.168.1.50"
        if t == "VideoWallModel":
            return "X,Y  e.g. 2,2"
        if t in ("Str", "StrCoded"):
            return "text string"
        if t == "Bitmask":
            enum = getattr(field, "enum", None)
            if enum:
                return "comma-sep list: " + ",".join(m.name for m in list(enum)[:3]) + "..."
        return "value"

    def _on_cli_search(self, event=None):
        """Filter the combobox dropdown list as the user types."""
        typed = self.cli_command_var.get().lower()
        filtered = [c for c in self._all_cli_commands if typed in c.lower()]
        self.cli_command_menu.configure(values=filtered if filtered else self._all_cli_commands)
        # auto-pick if the typed text is an exact match
        if typed in (c.lower() for c in self._all_cli_commands):
            exact = next(c for c in self._all_cli_commands if c.lower() == typed)
            self._on_cli_command_picked(exact)

    def _on_cli_command_picked(self, command_name: str):
        """Rebuild per-field argument rows for the chosen command."""
        if command_name == "timer_15":
            self.timer15_hint_label.grid()
        else:
            self.timer15_hint_label.grid_remove()

        for widget in self.cli_args_scroll.winfo_children():
            widget.destroy()
        self._cli_arg_rows.clear()

        command = MDC._commands.get(command_name)
        data_fields = getattr(command, "DATA", []) if command else []

        if not data_fields:
            ctk.CTkLabel(
                self.cli_args_scroll,
                text="No arguments — read-only command, use  Get  to query.",
                text_color="gray",
            ).grid(row=0, column=0, columnspan=4, padx=8, pady=6, sticky="w")
            return

        for row_idx, field in enumerate(data_fields):
            fname  = getattr(field, "name", f"arg{row_idx}")
            enum   = getattr(field, "enum", None)
            ftype  = type(field).__name__
            range_ = getattr(field, "range", None)

            # Build list of valid enum choices (works for Enum and Bitmask)
            enum_names = [m.name for m in enum] if enum else []

            # type annotation shown next to the field name
            if range_:
                lo, hi = range_.start, range_.stop - 1
                type_hint = f"int  {lo}–{hi}"
            elif ftype == "Bool":
                type_hint = "bool"
            elif ftype in ("Time", "Time12H"):
                type_hint = "HH:MM"
            elif ftype == "DateTime":
                type_hint = "datetime"
            elif ftype == "IPAddress":
                type_hint = "IP"
            elif ftype == "VideoWallModel":
                type_hint = "X,Y"
            elif ftype in ("Str", "StrCoded"):
                type_hint = "str"
            elif ftype == "Bitmask":
                type_hint = "list(,)"
            elif enum_names:
                type_hint = "enum"
            else:
                type_hint = ftype

            default = enum_names[0] if enum_names else ""
            var = ctk.StringVar(value=default)
            self._cli_arg_rows.append({"var": var, "enum": enum_names, "type": ftype})

            # ── field name + type label ──────────────────────────────────────
            label_text = f"{fname}\n({type_hint})"
            ctk.CTkLabel(
                self.cli_args_scroll,
                text=label_text,
                font=ctk.CTkFont(size=11, weight="bold"),
                width=145,
                anchor="w",
                justify="left",
            ).grid(row=row_idx, column=0, padx=(8, 4), pady=4, sticky="w")

            if enum_names:
                # ── enum / bitmask: dropdown + manual entry ──────────────────
                ctk.CTkOptionMenu(
                    self.cli_args_scroll,
                    variable=var,
                    values=enum_names,
                    width=180,
                ).grid(row=row_idx, column=1, padx=4, pady=4, sticky="ew")

                ctk.CTkLabel(
                    self.cli_args_scroll,
                    text="or type:",
                    text_color="gray",
                    width=55,
                ).grid(row=row_idx, column=2, padx=(6, 2), pady=4, sticky="w")

                ctk.CTkEntry(
                    self.cli_args_scroll,
                    textvariable=var,
                    placeholder_text=self._field_placeholder(field),
                ).grid(row=row_idx, column=3, padx=(0, 8), pady=4, sticky="ew")

            else:
                # ── free-entry: plain text with smart placeholder ────────────
                ctk.CTkEntry(
                    self.cli_args_scroll,
                    textvariable=var,
                    placeholder_text=self._field_placeholder(field),
                ).grid(row=row_idx, column=1, columnspan=3, padx=(4, 8), pady=4, sticky="ew")

    def _collect_cli_args(self) -> tuple:
        """Build args tuple: manual override wins if non-empty, else use per-field rows.

        For Int-typed fields the string value is cast to int so the library's
        pack() method receives the correct type.
        """
        raw_manual = self.cli_arg_var.get().strip()
        if raw_manual:
            return tuple(part.strip() for part in raw_manual.split(",") if part.strip())

        result = []
        for row in self._cli_arg_rows:
            val = row["var"].get().strip()
            if not val:
                continue
            # coerce numeric strings to int for Int fields
            if row.get("type") in ("Int",) and val.lstrip("-").isdigit():
                val = int(val)
            result.append(val)
        return tuple(result)

    @staticmethod
    def _friendly_mdc_error(command_name: str, exc: Exception) -> str:
        text = str(exc)

        if command_name == "timer_13" and "15 data-length version of timer received" in text:
            return "This panel uses TIMER_15. Use timer_15 with a timer_id (1-7)."
        if command_name == "timer_15" and "13 data-length version of timer received" in text:
            return "This panel uses TIMER_13. Use timer_13 for this device/firmware."

        if "Negative Acknowledgement" not in text:
            return text

        code = None
        try:
            code = int(text.split("error_code", 1)[1].split("]", 1)[0].strip())
        except Exception:
            code = None

        if code == 1:
            hint = UNSUPPORTED_COMMAND_HINTS.get(
                command_name,
                "Not supported on this panel or unavailable in current mode/source.",
            )
            return f"{command_name}: {hint}"
        if code in (130, 131, 132):
            hint = UNSUPPORTED_COMMAND_HINTS.get(
                command_name,
                "Orientation/PIP feature is unavailable in current panel mode.",
            )
            return (
                f"{command_name}: {hint} "
                f"(MDC error {code})."
            )

        return f"{text}"

    @staticmethod
    def _timer_requires_15(exc: Exception) -> bool:
        text = str(exc).lower()
        return "15 data-length version of timer received" in text

    @staticmethod
    def _timer_requires_13(exc: Exception) -> bool:
        text = str(exc).lower()
        return "13 data-length version of timer received" in text

    def cli_get(self):
        if self._effective_protocol() != "SIGNAGE_MDC":
            self.cli_log("CLI commands are MDC-only. Set Protocol to SIGNAGE_MDC (or AUTO + port 1515).")
            return

        command_name = self.cli_command_var.get().strip()
        if not command_name:
            return

        command = MDC._commands.get(command_name)
        if command and not getattr(command, 'GET', False):
            self.cli_log(f"{command_name}: this command does not support GET (read).")
            return

        args_tuple = self._collect_cli_args()
        if command_name == "timer_15" and not args_tuple:
            self.cli_log("timer_15 GET requires timer_id (1-7). Select/type it in Arguments.")
            return

        if command_name != "timer_15" and args_tuple:
            self.cli_log(f"{command_name}: GET ignores arguments; using read-only call.")

        async def _worker(mdc: MDC, display_id: int):
            if command_name in ("timer_13", "timer_15"):
                timer_id = None
                if args_tuple:
                    try:
                        timer_id = int(str(args_tuple[0]).strip())
                    except Exception:
                        timer_id = None

                if command_name == "timer_15":
                    if timer_id is None:
                        raise ValueError("timer_15 GET: timer_id must be a number (1-7).")
                    if timer_id < 1 or timer_id > 7:
                        raise ValueError("timer_15 GET: timer_id must be between 1 and 7.")
                    timer_data = tuple(args_tuple[1:])
                    if timer_data:
                        self.cli_log("timer_15 GET: extra values ignored; only timer_id is used for read.")
                    try:
                        return await mdc.timer_15(display_id, timer_id, ())
                    except Exception as exc:
                        if self._timer_requires_13(exc):
                            self.cli_log("Auto fallback: device expects timer_13, retrying.")
                            return await mdc.timer_13(display_id)
                        raise

                try:
                    return await mdc.timer_13(display_id)
                except Exception as exc:
                    if self._timer_requires_15(exc):
                        if timer_id is None:
                            raise ValueError("This device expects timer_15. Provide timer_id (1-7) in Arguments.") from exc
                        if timer_id < 1 or timer_id > 7:
                            raise ValueError("timer_15 GET: timer_id must be between 1 and 7.") from exc
                        self.cli_log("Auto fallback: device expects timer_15, retrying.")
                        return await mdc.timer_15(display_id, timer_id, ())
                    raise

            method = getattr(mdc, command_name)
            return await method(display_id)

        def _on_success(result):
            self.cli_log(f"{command_name} → {result}")
            self.log(f"CLI GET {command_name} OK")

        def _on_error(exc):
            self.cli_log(f"{command_name} GET failed: {self._friendly_mdc_error(command_name, exc)}")
            self.status_var.set(f"Status: CLI GET {command_name} failed")

        self.status_var.set(f"Status: CLI GET {command_name}...")

        def _thread():
            try:
                result = asyncio.run(self._execute_mdc(_worker))
                self.after(0, lambda: _on_success(result))
            except Exception as exc:
                self.after(0, lambda exc=exc: _on_error(exc))

        threading.Thread(target=_thread, daemon=True).start()

    def cli_set(self):
        if self._effective_protocol() != "SIGNAGE_MDC":
            self.cli_log("CLI commands are MDC-only. Set Protocol to SIGNAGE_MDC (or AUTO + port 1515).")
            return

        command_name = self.cli_command_var.get().strip()
        if not command_name:
            return

        command = MDC._commands.get(command_name)
        if command and not getattr(command, 'SET', False):
            self.cli_log(f"{command_name}: this command does not support SET (write).")
            return

        args_tuple = self._collect_cli_args()
        if command_name == "timer_15" and not args_tuple:
            self.cli_log("timer_15 SET requires timer_id (1-7) plus values. Fill Arguments first.")
            return

        async def _worker(mdc: MDC, display_id: int):
            if command_name in ("timer_13", "timer_15"):
                if command_name == "timer_13":
                    try:
                        return await mdc.timer_13(display_id, args_tuple)
                    except Exception as exc:
                        if self._timer_requires_15(exc):
                            self.cli_log("Auto fallback: device expects timer_15.")
                            self.cli_log("Use Manual Override as: timer_id, then timer_15 values.")
                        raise

                try:
                    timer_id = int(str(args_tuple[0]).strip())
                except Exception as exc:
                    raise ValueError("timer_15 SET: timer_id must be a number (1-7).") from exc

                if timer_id < 1 or timer_id > 7:
                    raise ValueError("timer_15 SET: timer_id must be between 1 and 7.")

                timer_data = tuple(args_tuple[1:])
                if not timer_data:
                    raise ValueError("timer_15 SET requires timer_id (1-7) plus values.")

                try:
                    return await mdc.timer_15(display_id, timer_id, timer_data)
                except Exception as exc:
                    if self._timer_requires_13(exc):
                        self.cli_log("Auto fallback: device expects timer_13, retrying with compatible fields.")
                        if len(timer_data) < 9:
                            raise ValueError("timer_13 fallback requires at least 9 timer values after timer_id.") from exc
                        return await mdc.timer_13(display_id, tuple(timer_data[:9]))
                    raise

            method = getattr(mdc, command_name)
            return await method(display_id, args_tuple)

        def _on_success(result):
            self.cli_log(f"{command_name}({', '.join(str(a) for a in args_tuple)}) → {result}")
            self.log(f"CLI SET {command_name} OK")

        def _on_error(exc):
            self.cli_log(f"{command_name} SET failed: {self._friendly_mdc_error(command_name, exc)}")
            self.status_var.set(f"Status: CLI SET {command_name} failed")

        self.status_var.set(f"Status: CLI SET {command_name}...")

        def _thread():
            try:
                result = asyncio.run(self._execute_mdc(_worker))
                self.after(0, lambda: _on_success(result))
            except Exception as exc:
                self.after(0, lambda exc=exc: _on_error(exc))

        threading.Thread(target=_thread, daemon=True).start()

    def cli_send_consumer_key(self):
        if self._effective_protocol() != "SMART_TV_WS":
            self.cli_log("Consumer key CLI is Smart TV only. Set Protocol to SMART_TV_WS (or AUTO + port 8002/8001).")
            return

        key = self.consumer_key_var.get().strip().upper()
        if key not in SMART_TV_KEYS:
            self.cli_log(f"Unknown Smart TV key: {key}")
            return

        try:
            repeat = int(self.consumer_repeat_var.get().strip())
        except Exception:
            self.cli_log("Repeat must be a number.")
            return

        if repeat < 1:
            repeat = 1
        if repeat > 20:
            repeat = 20

        def _smart_tv_worker(tv):
            self._smarttv_send_keys(tv, key, times=repeat)
            return f"{key} x{repeat}"

        self._run_async_action(
            "Smart TV key",
            mdc_worker=None,
            smart_tv_worker=_smart_tv_worker,
            on_success=lambda result: self.cli_log(f"Consumer CLI → {result}"),
        )

    def cli_send_consumer_hdmi_macro(self, hdmi_name: str):
        if self._effective_protocol() != "SMART_TV_WS":
            self.cli_log("HDMI macro is Smart TV only. Set Protocol to SMART_TV_WS (or AUTO + port 8002/8001).")
            return

        sequence = SMART_TV_HDMI_MACROS.get(hdmi_name)
        if not sequence:
            self.cli_log(f"Unknown HDMI macro: {hdmi_name}")
            return

        def _smart_tv_worker(tv):
            self._smarttv_send_sequence(tv, sequence)
            return f"{hdmi_name} ({' -> '.join(sequence)})"

        self._run_async_action(
            f"Smart TV {hdmi_name}",
            mdc_worker=None,
            smart_tv_worker=_smart_tv_worker,
            on_success=lambda result: self.cli_log(f"Consumer HDMI macro → {result}"),
        )

    def _validate_connection_fields(self) -> tuple[str, int, int, str]:
        ip = self.ip_var.get().strip()
        if not ip:
            raise ValueError("IP is required")

        try:
            port = int(self.port_var.get().strip())
        except Exception as exc:
            raise ValueError("Port must be a number") from exc

        try:
            display_id = int(self.id_var.get().strip())
        except Exception as exc:
            raise ValueError("Display ID must be a number") from exc

        protocol = self.protocol_var.get().strip().upper()
        if protocol not in PROTOCOL_OPTIONS:
            protocol = "AUTO"

        return ip, port, display_id, protocol

    def _effective_protocol(self) -> str:
        protocol = self.protocol_var.get().strip().upper()
        if protocol not in PROTOCOL_OPTIONS:
            protocol = "AUTO"

        if protocol != "AUTO":
            return protocol

        try:
            port = int(self.port_var.get().strip())
        except Exception:
            port = 1515

        return "SIGNAGE_MDC" if port == 1515 else "SMART_TV_WS"

    async def _execute_mdc(self, worker):
        ip, port, display_id, _ = self._validate_connection_fields()
        target = f"{ip}:{port}"
        async with MDC(target) as mdc:
            return await worker(mdc, display_id)

    def _execute_smart_tv_ws(self, worker):
        if not _SMARTTVWS_AVAILABLE:
            raise RuntimeError("samsungtvws is not installed. Run: pip install samsungtvws")

        ip, port, _, _ = self._validate_connection_fields()
        token_dir = Path.home() / "Documents" / "SamsungMDC" / "tokens"
        token_dir.mkdir(parents=True, exist_ok=True)
        token_file = token_dir / f"tv_token_{ip.replace('.', '_')}.txt"

        tv = SamsungTVWS(ip, port=port, token_file=str(token_file), name="SamsungPy Hybrid")
        try:
            return worker(tv)
        except Exception as exc:
            raise RuntimeError(self._format_smart_tv_error(exc, ip, port)) from exc

    @staticmethod
    def _format_smart_tv_error(exc: Exception, ip: str, port: int) -> str:
        text = str(exc)
        kind = exc.__class__.__name__

        if kind == "UnauthorizedError" or "ms.channel.unauthorized" in text:
            return (
                f"Smart TV authorization required on {ip}:{port}. "
                "Look at the TV and allow the remote request for SamsungPy Hybrid, then retry."
            )

        if kind in ("ConnectionFailure", "TimeoutError"):
            return (
                f"Smart TV connection failed on {ip}:{port}. "
                "Ensure TV is ON, same network, and use Auto Probe (ports 8002/8001)."
            )

        return f"Smart TV command failed on {ip}:{port}: {text or kind}"

    @staticmethod
    def _smarttv_send_key(tv, key: str) -> None:
        SamsungDashboard._smarttv_send_keys(tv, key, times=1)

    @staticmethod
    def _smarttv_send_keys(tv, key: str, times: int = 1) -> None:
        if not hasattr(tv, "send_key"):
            raise RuntimeError("Connected Smart TV client does not expose send_key().")

        try:
            tv.open()
            for _ in range(max(1, int(times))):
                tv.send_key(key)
        finally:
            try:
                tv.close()
            except Exception:
                pass

    @staticmethod
    def _smarttv_send_sequence(tv, keys: list[str], key_press_delay: float = 0.6) -> None:
        if not hasattr(tv, "send_key"):
            raise RuntimeError("Connected Smart TV client does not expose send_key().")

        try:
            tv.open()
            for key in keys:
                try:
                    tv.send_key(key, key_press_delay=key_press_delay)
                except TypeError:
                    tv.send_key(key)
        finally:
            try:
                tv.close()
            except Exception:
                pass

    def _run_async_action(self, action_name: str, mdc_worker=None, smart_tv_worker=None, on_success=None):
        self.status_var.set(f"Status: {action_name}...")

        def _thread_target():
            try:
                protocol = self._effective_protocol()
                if protocol == "SIGNAGE_MDC":
                    if not mdc_worker:
                        raise RuntimeError(f"{action_name} is not available for MDC in this screen.")
                    result = asyncio.run(self._execute_mdc(mdc_worker))
                else:
                    if not smart_tv_worker:
                        raise RuntimeError(f"{action_name} is not available for Smart TV WebSocket.")
                    result = self._execute_smart_tv_ws(smart_tv_worker)
                self.after(0, lambda: self._action_success(action_name, result, on_success))
            except Exception as exc:
                self.after(0, lambda exc=exc: self._action_error(action_name, exc))

        threading.Thread(target=_thread_target, daemon=True).start()

    def _action_success(self, action_name: str, result, on_success=None):
        self.status_var.set(f"Status: {action_name} OK")
        if on_success:
            on_success(result)
        else:
            self.log(f"{action_name} succeeded")

    def _action_error(self, action_name: str, exc: Exception):
        self.status_var.set(f"Status: {action_name} failed")
        self.log(f"{action_name} failed: {exc}")

    def _refresh_saved_devices_menu(self):
        values = ["(manual entry)"] + [device["ip"] for device in self.saved_devices]
        if self.selected_device_var.get() not in values:
            self.selected_device_var.set("(manual entry)")
        self.saved_device_menu.configure(values=values)
        self._rebuild_devices_list()

    def _rebuild_devices_list(self):
        """Repopulate the scrollable sidebar device list, honoring the search filter."""
        for widget in self.devices_scroll.winfo_children():
            widget.destroy()

        p = self._palette
        needle = self.device_search_var.get().lower().strip()
        visible = [
            d for d in self.saved_devices
            if not needle
            or needle in (d.get("ip", "")).lower()
            or needle in (d.get("site", "")).lower()
            or needle in (d.get("description", "")).lower()
            or needle in str(d.get("id", "")).lower()
        ]

        if not self.saved_devices:
            ctk.CTkLabel(
                self.devices_scroll,
                text="No saved devices yet.",
                text_color="#7fb3d3",
                font=ctk.CTkFont(size=12),
            ).grid(row=0, column=0, padx=8, pady=16)
            return

        if not visible:
            ctk.CTkLabel(
                self.devices_scroll,
                text="No devices match the search.",
                text_color="#7fb3d3",
                font=ctk.CTkFont(size=12),
            ).grid(row=0, column=0, padx=8, pady=16)
            return

        for row_idx, device in enumerate(visible):
            ip   = device.get("ip", "")
            did  = device.get("id", 0)
            port = device.get("port", 1515)
            protocol = str(device.get("protocol", "AUTO")).upper()
            site = device.get("site") or ip
            desc = device.get("description", "")

            is_selected = self.selected_device_var.get() == ip
            card_color  = p["card2_bg"] if is_selected else p["card_bg"]
            border_col  = p["accent"]   if is_selected else "#1e3a5f"

            card = ctk.CTkFrame(self.devices_scroll, corner_radius=10,
                                fg_color=card_color,
                                border_width=1, border_color=border_col)
            card.grid(row=row_idx, column=0, padx=4, pady=4, sticky="ew")
            card.grid_columnconfigure(0, weight=1)

            # site + IP labels
            info = ctk.CTkFrame(card, fg_color="transparent")
            info.grid(row=0, column=0, padx=10, pady=(6, 2), sticky="w")

            badge_text = "AUTO"
            badge_color = p["neutral"]
            if protocol == "SIGNAGE_MDC":
                badge_text = "MDC"
                badge_color = p["success"]
            elif protocol == "SMART_TV_WS":
                badge_text = "WS"
                badge_color = p["warning"]

            top_row = ctk.CTkFrame(info, fg_color="transparent")
            top_row.pack(fill="x", anchor="w")
            ctk.CTkLabel(top_row, text=site,
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color="#e8f4fd").pack(side="left", anchor="w")

            def _make_protocol_pick(captured_ip=ip, captured_protocol=protocol):
                def _pick():
                    self.selected_device_var.set(captured_ip)
                    self._on_selected_device(captured_ip)
                    if captured_protocol in PROTOCOL_OPTIONS:
                        self.protocol_var.set(captured_protocol)
                    self._rebuild_devices_list()
                    self.log(f"Applied protocol {self.protocol_var.get()} for {captured_ip}")
                    self.get_status()
                return _pick

            ctk.CTkButton(top_row, text=badge_text,
                          fg_color=badge_color,
                          hover_color=badge_color,
                          corner_radius=6,
                          width=42,
                          height=20,
                          text_color="#ffffff",
                          font=ctk.CTkFont(size=10, weight="bold"),
                          command=_make_protocol_pick()).pack(side="right", padx=(8, 0))

            ctk.CTkLabel(info, text=f"{ip}:{port}  ·  ID {did}  ·  {protocol}" + (f"  ·  {desc}" if desc else ""),
                         font=ctk.CTkFont(size=10), text_color="#7fb3d3").pack(anchor="w")

            btns = ctk.CTkFrame(card, fg_color="transparent")
            btns.grid(row=1, column=0, padx=8, pady=(2, 8), sticky="ew")
            btns.grid_columnconfigure((0, 1), weight=1)

            def _make_select(captured_ip=ip):
                def _select():
                    self.selected_device_var.set(captured_ip)
                    self._on_selected_device(captured_ip)
                    self._rebuild_devices_list()
                return _select

            def _make_connect(captured_ip=ip):
                def _connect():
                    self.selected_device_var.set(captured_ip)
                    self._on_selected_device(captured_ip)
                    self._rebuild_devices_list()
                    self.auto_probe_protocol(on_done=self.get_status)
                return _connect

            ctk.CTkButton(
                btns, text="Select", height=26, corner_radius=6,
                fg_color=p["neutral"], hover_color=p["neutral_hover"],
                font=ctk.CTkFont(size=11),
                command=_make_select(),
            ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
            ctk.CTkButton(
                btns, text="⚡ Connect", height=26, corner_radius=6,
                fg_color=p["success"], hover_color=p["success_hover"],
                font=ctk.CTkFont(size=11, weight="bold"),
                command=_make_connect(),
            ).grid(row=0, column=1, sticky="ew")

        self.devices_scroll.grid_columnconfigure(0, weight=1)

    def _on_selected_device(self, selected_ip: str):
        if selected_ip == "(manual entry)":
            return
        selected = find_device_by_ip(self.saved_devices, selected_ip)
        if not selected:
            return
        self.ip_var.set(selected.get("ip", ""))
        self.port_var.set(str(selected.get("port", 1515)))
        self.id_var.set(str(selected.get("id", 0)))
        self.protocol_var.set(selected.get("protocol", "AUTO"))
        self.site_var.set(selected.get("site", ""))
        self.description_var.set(selected.get("description", ""))

    def save_current_device(self):
        candidate = normalize_device(
            {
                "ip": self.ip_var.get(),
                "port": self.port_var.get(),
                "id": self.id_var.get(),
                "protocol": self.protocol_var.get(),
                "site": self.site_var.get(),
                "description": self.description_var.get(),
            }
        )
        if not candidate:
            messagebox.showerror("Invalid device", "Please enter a valid IP.")
            return

        existing = find_device_by_ip(self.saved_devices, candidate["ip"])
        if existing:
            existing.update(candidate)
            self.log(f"Updated saved device {candidate['ip']}")
        else:
            self.saved_devices.append(candidate)
            self.log(f"Saved new device {candidate['ip']}")

        save_saved_devices(self.saved_devices)
        self.selected_device_var.set(candidate["ip"])
        self._refresh_saved_devices_menu()

    def delete_selected_device(self):
        selected_ip = self.selected_device_var.get()
        if selected_ip == "(manual entry)":
            return

        before = len(self.saved_devices)
        self.saved_devices = [device for device in self.saved_devices if device.get("ip") != selected_ip]
        if len(self.saved_devices) == before:
            return

        save_saved_devices(self.saved_devices)
        self.selected_device_var.set("(manual entry)")
        self._refresh_saved_devices_menu()
        self.log(f"Deleted saved device {selected_ip}")

    def import_devices(self):
        file_path = filedialog.askopenfilename(
            title="Import devices",
            filetypes=[("JSON files", "*.json"), ("CSV files", "*.csv")],
        )
        if not file_path:
            return

        path = Path(file_path)
        try:
            imported = parse_imported_devices(path.name, path.read_bytes())
            if not imported:
                messagebox.showwarning("Import", "No valid devices found in file.")
                return

            merged, added_count, updated_count = merge_devices(self.saved_devices, imported)
            self.saved_devices = merged
            save_saved_devices(self.saved_devices)
            self._refresh_saved_devices_menu()
            self.log(f"Import complete: {added_count} added, {updated_count} updated")
        except Exception as exc:
            messagebox.showerror("Import failed", str(exc))

    def export_devices(self):
        if not self.saved_devices:
            messagebox.showinfo("Export", "No devices to export.")
            return

        file_path = filedialog.asksaveasfilename(
            title="Export devices",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        )
        if not file_path:
            return

        Path(file_path).write_text(json.dumps(self.saved_devices, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"Exported {len(self.saved_devices)} devices")

    def _schedule_network_check(self):
        def _check():
            ip = self.ip_var.get().strip()
            if not ip:
                self.after(0, lambda: self.network_var.set("Network: no IP"))
                self.after(0, lambda: self.net_dot.configure(text_color="#e74c3c"))
            else:
                try:
                    port = int(self.port_var.get().strip())
                    start = time.perf_counter()
                    with socket.create_connection((ip, port), timeout=1.5):
                        elapsed = int((time.perf_counter() - start) * 1000)
                        self.after(0, lambda: self.network_var.set(f"Network: ONLINE ({elapsed} ms)"))
                        self.after(0, lambda: self.net_dot.configure(text_color="#2ecc71"))
                except Exception:
                    self.after(0, lambda: self.network_var.set("Network: OFFLINE"))
                    self.after(0, lambda: self.net_dot.configure(text_color="#e74c3c"))
            self.after(10000, self._schedule_network_check)

        threading.Thread(target=_check, daemon=True).start()

    @staticmethod
    def _probe_port(ip: str, port: int, timeout: float = 1.0) -> bool:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except Exception:
            return False

    def _persist_detected_profile(self, ip: str, port: int, protocol: str) -> None:
        existing = find_device_by_ip(self.saved_devices, ip)
        if not existing:
            return

        changed = False
        if int(existing.get("port", 1515)) != int(port):
            existing["port"] = int(port)
            changed = True
        if str(existing.get("protocol", "AUTO")).upper() != str(protocol).upper():
            existing["protocol"] = str(protocol).upper()
            changed = True

        if not changed:
            return

        save_saved_devices(self.saved_devices)
        self._refresh_saved_devices_menu()
        self.log(f"Saved profile updated for {ip}: {protocol} on port {port}")

    def auto_probe_protocol(self, on_done=None):
        ip = self.ip_var.get().strip()
        if not ip:
            self.log("Auto probe failed: IP is required")
            self.status_var.set("Status: Auto Probe failed")
            return

        self.status_var.set("Status: Auto Probe...")

        def _thread_target():
            candidates = [
                (1515, "SIGNAGE_MDC"),
                (8002, "SMART_TV_WS"),
                (8001, "SMART_TV_WS"),
            ]

            found_port = None
            found_protocol = None

            for port, protocol in candidates:
                if self._probe_port(ip, port, timeout=1.2):
                    found_port = port
                    found_protocol = protocol
                    break

            def _apply_result():
                if found_port is None or found_protocol is None:
                    self.status_var.set("Status: Auto Probe failed")
                    self.network_var.set("Network: OFFLINE")
                    self.net_dot.configure(text_color="#e74c3c")
                    self.log("Auto probe: no supported control ports reachable (1515/8002/8001)")
                    return

                self.port_var.set(str(found_port))
                self.protocol_var.set(found_protocol)
                self._persist_detected_profile(ip, found_port, found_protocol)
                self.status_var.set("Status: Auto Probe OK")
                self.network_var.set(f"Network: ONLINE (port {found_port})")
                self.net_dot.configure(text_color="#2ecc71")
                self.log(f"Auto probe: selected {found_protocol} on {ip}:{found_port}")
                if callable(on_done):
                    on_done()

            self.after(0, _apply_result)

        threading.Thread(target=_thread_target, daemon=True).start()

    def get_status(self):
        async def _mdc_worker(mdc: MDC, display_id: int):
            return await mdc.status(display_id)

        def _smart_tv_worker(tv):
            info = {}
            if hasattr(tv, "rest_device_info"):
                try:
                    info = tv.rest_device_info()
                except Exception:
                    info = {}
            return info

        def _on_success(result):
            if isinstance(result, tuple):
                decoded = decode_status(result)
                self.log(
                    "Power: {power}, Volume: {volume}, Mute: {mute}, Input: {input_source}, Aspect: {picture_aspect}".format(
                        **decoded
                    )
                )
                return

            device_name = result.get("device", {}).get("name") if isinstance(result, dict) else None
            model_name = result.get("device", {}).get("modelName") if isinstance(result, dict) else None
            self.log(f"Smart TV reachable. Device: {device_name or 'N/A'}, Model: {model_name or 'N/A'}")

        self._run_async_action("Status", _mdc_worker, _smart_tv_worker, _on_success)

    def get_serial(self):
        async def _mdc_worker(mdc: MDC, display_id: int):
            return await mdc.serial_number(display_id)

        def _smart_tv_worker(tv):
            return "Not available on Smart TV WebSocket API"

        self._run_async_action("Serial", _mdc_worker, _smart_tv_worker, lambda serial: self.log(f"Serial: {serial}"))

    def reboot_screen(self):
        async def _mdc_worker(mdc: MDC, display_id: int):
            await mdc.power(display_id, ("REBOOT",))
            return None

        def _smart_tv_worker(tv):
            self._smarttv_send_key(tv, "KEY_POWER")
            return None

        self._run_async_action("Reboot", _mdc_worker, _smart_tv_worker)

    def send_home_key(self):
        async def _mdc_worker(mdc: MDC, display_id: int):
            await mdc.virtual_remote(display_id, ("KEY_CONTENT",))
            return None

        def _smart_tv_worker(tv):
            self._smarttv_send_key(tv, "KEY_HOME")
            return None

        self._run_async_action("Home", _mdc_worker, _smart_tv_worker)

    def set_volume(self):
        value = int(self.volume_var.get())

        async def _mdc_worker(mdc: MDC, display_id: int):
            await mdc.volume(display_id, (value,))
            return value

        def _smart_tv_worker(tv):
            raise RuntimeError("Absolute volume set is not supported in hybrid mode for Smart TVs.")

        self._run_async_action("Set volume", _mdc_worker, _smart_tv_worker, lambda result: self.log(f"Volume set to {result}"))

    def set_brightness(self):
        value = int(self.brightness_var.get())

        async def _mdc_worker(mdc: MDC, display_id: int):
            await mdc.brightness(display_id, (value,))
            return value

        def _smart_tv_worker(tv):
            raise RuntimeError("Brightness control is not supported on Smart TV WebSocket API.")

        self._run_async_action("Set brightness", _mdc_worker, _smart_tv_worker, lambda result: self.log(f"Brightness set to {result}"))

    def set_input_source(self):
        source = self.input_var.get().strip()

        async def _mdc_worker(mdc: MDC, display_id: int):
            await mdc.input_source(display_id, (source,))
            return source

        def _smart_tv_worker(tv):
            raise RuntimeError("Direct input source switching is not supported on Smart TV WebSocket API.")

        self._run_async_action("Set input", _mdc_worker, _smart_tv_worker, lambda result: self.log(f"Input source set to {result}"))

    def set_mute(self):
        current = self.mute_var.get().strip().upper()
        next_state = "ON" if current != "ON" else "OFF"
        self.mute_var.set(next_state)

        async def _mdc_worker(mdc: MDC, display_id: int):
            await mdc.mute(display_id, (next_state,))
            return next_state

        def _smart_tv_worker(tv):
            self._smarttv_send_key(tv, "KEY_MUTE")
            return next_state

        self._run_async_action("Mute", _mdc_worker, _smart_tv_worker, lambda result: self.log(f"Mute set to {result}"))

    def take_screenshot(self):
        """Capture a screenshot from the Samsung display and show/save it."""
        async def _mdc_worker(mdc: MDC, display_id: int):
            if not hasattr(mdc, "screen_capture"):
                raise RuntimeError("screen_capture is not supported by this python-samsung-mdc version or device.")
            return await mdc.screen_capture(display_id)

        def _smart_tv_worker(tv):
            raise RuntimeError("Screenshot capture is not supported on Smart TV WebSocket API.")

        def _on_success(image_bytes: bytes):
            # Save to user Documents folder so it works both in dev and as EXE
            ip = self.ip_var.get().strip().replace(".", "_")
            ts = time.strftime("%Y%m%d_%H%M%S")
            docs = Path.home() / "Documents" / "SamsungMDC"
            docs.mkdir(parents=True, exist_ok=True)
            out_path = docs / f"screenshot_{ip}_{ts}.jpg"
            out_path.write_bytes(image_bytes)
            self.log(f"Screenshot saved: {out_path}")

            # Show preview popup
            if not _PIL_AVAILABLE:
                messagebox.showinfo("Screenshot", f"Saved to {out_path}\n(Install Pillow to enable preview)")
                return

            try:
                img = Image.open(BytesIO(image_bytes))
                img.thumbnail((960, 600))

                popup = ctk.CTkToplevel(self)
                popup.title(f"Screenshot – {self.ip_var.get()}")
                popup.grab_set()

                photo = ImageTk.PhotoImage(img)
                # keep reference so GC doesn't destroy it
                popup._photo_ref = photo

                lbl = tk.Label(popup, image=photo, bg="#0d0d1a")
                lbl.pack(padx=10, pady=10)

                def _save_as():
                    dest = filedialog.asksaveasfilename(
                        title="Save screenshot",
                        defaultextension=".jpg",
                        initialfile=out_path.name,
                        filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png"), ("All files", "*.*")],
                    )
                    if dest:
                        Path(dest).write_bytes(image_bytes)
                        self.log(f"Screenshot saved as: {dest}")

                btn_row = ctk.CTkFrame(popup, fg_color="transparent")
                btn_row.pack(pady=(0, 10))
                ctk.CTkButton(btn_row, text="💾  Save As…", command=_save_as,
                              fg_color=self._palette["accent"],
                              hover_color=self._palette["accent_hover"],
                              width=130, height=32).pack(side="left", padx=6)
                ctk.CTkButton(btn_row, text="Close", command=popup.destroy,
                              fg_color=self._palette["neutral"],
                              hover_color=self._palette["neutral_hover"],
                              width=90, height=32).pack(side="left", padx=6)
            except Exception as exc:
                self.log(f"Screenshot preview error: {exc}")
                messagebox.showinfo("Screenshot", f"Saved to {out_path}")

        self._run_async_action("Screenshot", _mdc_worker, _smart_tv_worker, _on_success)


def main() -> None:
    app = SamsungDashboard()
    app.mainloop()


if __name__ == "__main__":
    main()
