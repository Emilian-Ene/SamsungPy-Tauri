#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

const BRIDGE_PATH: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../py/bridge.py");
const BRIDGE_SOURCE: &str = include_str!(concat!(env!("CARGO_MANIFEST_DIR"), "/../py/bridge.py"));

fn bridge_binary_candidates() -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            candidates.push(exe_dir.join("bridge_runtime").join("bridge.exe"));
            candidates.push(exe_dir.join("bridge.exe"));
            candidates.push(
                exe_dir
                    .join("resources")
                    .join("bridge_runtime")
                    .join("bridge.exe"),
            );
            candidates.push(exe_dir.join("resources").join("bridge.exe"));
            candidates.push(
                exe_dir
                    .join("..")
                    .join("Resources")
                    .join("bridge_runtime")
                    .join("bridge.exe"),
            );
            candidates.push(
                exe_dir
                    .join("..")
                    .join("Resources")
                    .join("bridge.exe"),
            );
        }
    }

    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("py").join("bridge_runtime").join("bridge.exe"));
        candidates.push(cwd.join("bridge_runtime").join("bridge.exe"));
        candidates.push(cwd.join("bridge.exe"));
    }

    let mut unique = Vec::new();
    for candidate in candidates {
        if !unique.iter().any(|existing: &PathBuf| existing == &candidate) {
            unique.push(candidate);
        }
    }

    unique
}

#[derive(Clone, Copy)]
struct PythonLauncher {
    label: &'static str,
    program: &'static str,
    args: &'static [&'static str],
}

fn python_launchers() -> Vec<PythonLauncher> {
    vec![
        PythonLauncher {
            label: "py -3",
            program: "py",
            args: &["-3"],
        },
        PythonLauncher {
            label: "python",
            program: "python",
            args: &[],
        },
        PythonLauncher {
            label: "python3",
            program: "python3",
            args: &[],
        },
        PythonLauncher {
            label: "py",
            program: "py",
            args: &[],
        },
    ]
}

fn apply_no_window(command: &mut Command) {
    #[cfg(windows)]
    {
        command.creation_flags(CREATE_NO_WINDOW);
    }
}

fn launcher_command(launcher: PythonLauncher) -> Command {
    let mut command = Command::new(launcher.program);
    for arg in launcher.args {
        command.arg(arg);
    }
    command.env("PYTHONUTF8", "1");
    apply_no_window(&mut command);
    command
}

fn launcher_has_required_modules(launcher: PythonLauncher) -> Result<bool, String> {
    let check_script = "import importlib.util;mods=('samsung_mdc','samsungtvws');missing=[m for m in mods if importlib.util.find_spec(m) is None];print('OK' if not missing else 'MISSING:'+','.join(missing))";

    let output = launcher_command(launcher)
        .arg("-c")
        .arg(check_script)
        .output()
        .map_err(|e| format!("{} start failed: {e}", launcher.label))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        return Err(format!(
            "{} probe failed. stdout='{}' stderr='{}'",
            launcher.label, stdout, stderr
        ));
    }

    let probe = String::from_utf8_lossy(&output.stdout).trim().to_string();
    Ok(probe == "OK")
}

fn bridge_script_candidates() -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    candidates.push(PathBuf::from(BRIDGE_PATH));

    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            candidates.push(exe_dir.join("py").join("bridge.py"));
            candidates.push(exe_dir.join("bridge.py"));
            candidates.push(exe_dir.join("resources").join("py").join("bridge.py"));
            candidates.push(exe_dir.join("resources").join("bridge.py"));
            candidates.push(exe_dir.join("..").join("Resources").join("py").join("bridge.py"));
            candidates.push(exe_dir.join("..").join("Resources").join("bridge.py"));
        }
    }

    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("py").join("bridge.py"));
        candidates.push(cwd.join("bridge.py"));
    }

    let mut unique = Vec::new();
    for candidate in candidates {
        if !unique.iter().any(|existing: &PathBuf| existing == &candidate) {
            unique.push(candidate);
        }
    }

    unique
}

fn ensure_embedded_bridge_file() -> Result<PathBuf, String> {
    let base = dirs::data_local_dir()
        .or_else(dirs::data_dir)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")));
    let runtime_dir = base.join("SamsungMdcTauri").join("runtime");
    fs::create_dir_all(&runtime_dir)
        .map_err(|e| format!("Cannot create runtime bridge directory {}: {e}", runtime_dir.display()))?;

    let bridge_file = runtime_dir.join("bridge.py");
    fs::write(&bridge_file, BRIDGE_SOURCE)
        .map_err(|e| format!("Cannot materialize embedded bridge.py at {}: {e}", bridge_file.display()))?;

    Ok(bridge_file)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SavedDevice {
    ip: String,
    port: u16,
    id: i32,
    protocol: String,
    site: String,
    description: String,
}

fn saved_devices_path() -> PathBuf {
    let base = dirs::data_local_dir()
        .or_else(dirs::data_dir)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")));
    base.join("SamsungMdcTauri").join("saved_devices.json")
}

fn normalize_protocol(value: &str) -> String {
    match value.trim().to_uppercase().as_str() {
        "SIGNAGE_MDC" => "SIGNAGE_MDC".to_string(),
        "SMART_TV_WS" => "SMART_TV_WS".to_string(),
        _ => "AUTO".to_string(),
    }
}

fn normalize_device(input: Value) -> Result<SavedDevice, String> {
    let ip = input
        .get("ip")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_string();

    if ip.is_empty() {
        return Err("IP is required".to_string());
    }

    let port = input
        .get("port")
        .and_then(Value::as_u64)
        .and_then(|n| u16::try_from(n).ok())
        .unwrap_or(1515);

    let id = input
        .get("id")
        .and_then(Value::as_i64)
        .and_then(|n| i32::try_from(n).ok())
        .unwrap_or(0);

    let protocol = normalize_protocol(input.get("protocol").and_then(Value::as_str).unwrap_or("AUTO"));
    let site = input
        .get("site")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_string();
    let description = input
        .get("description")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_string();

    Ok(SavedDevice {
        ip,
        port,
        id,
        protocol,
        site,
        description,
    })
}

fn load_saved_devices_internal() -> Result<Vec<SavedDevice>, String> {
    let path = saved_devices_path();
    if !path.exists() {
        return Ok(Vec::new());
    }

    let text = fs::read_to_string(&path)
        .map_err(|e| format!("Cannot read saved devices file {}: {e}", path.display()))?;
    if text.trim().is_empty() {
        return Ok(Vec::new());
    }

    let parsed: Value =
        serde_json::from_str(&text).map_err(|e| format!("Invalid saved_devices.json: {e}"))?;
    let list = match parsed {
        Value::Array(arr) => arr,
        Value::Object(_) => vec![parsed],
        _ => Vec::new(),
    };

    let mut out = Vec::new();
    for item in list {
        if let Ok(device) = normalize_device(item) {
            out.push(device);
        }
    }
    Ok(out)
}

fn save_saved_devices_internal(devices: &[SavedDevice]) -> Result<(), String> {
    let path = saved_devices_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| {
            format!(
                "Cannot create saved devices directory {}: {e}",
                parent.display()
            )
        })?;
    }
    let json = serde_json::to_string_pretty(devices)
        .map_err(|e| format!("Cannot serialize saved devices: {e}"))?;
    fs::write(&path, json).map_err(|e| format!("Cannot write {}: {e}", path.display()))
}

fn probe_port(ip: &str, port: u16, timeout_ms: u64) -> bool {
    let addr = format!("{ip}:{port}");
    let socket: Result<SocketAddr, _> = addr.parse();
    let Ok(socket) = socket else {
        return false;
    };
    TcpStream::connect_timeout(&socket, Duration::from_millis(timeout_ms)).is_ok()
}

fn run_bridge(action: &str, payload: &Value) -> Result<Value, String> {
    let payload_str = payload.to_string();
    let bridge_binary = bridge_binary_candidates()
        .into_iter()
        .find(|path| path.exists() && path.is_file());

    if let Some(bridge_exe) = bridge_binary {
        let output = {
            let mut command = Command::new(&bridge_exe);
            apply_no_window(&mut command);
            command.arg(action).arg(&payload_str).output()
        };

        match output {
            Ok(out) => {
                if out.status.success() {
                    let stdout = String::from_utf8_lossy(&out.stdout).trim().to_string();
                    return serde_json::from_str::<Value>(&stdout).map_err(|e| {
                        format!(
                            "Invalid JSON from bundled bridge.exe: {e}. Output: {stdout}"
                        )
                    });
                }

                let stderr = String::from_utf8_lossy(&out.stderr).trim().to_string();
                let stdout = String::from_utf8_lossy(&out.stdout).trim().to_string();
                return Err(format!(
                    "Bundled bridge.exe failed at {}. stdout='{}' stderr='{}'",
                    bridge_exe.display(),
                    stdout,
                    stderr
                ));
            }
            Err(err) => {
                return Err(format!(
                    "Unable to start bundled bridge.exe at {}: {err}",
                    bridge_exe.display()
                ));
            }
        }
    }

    let bridge_candidates = bridge_script_candidates();

    let mut last_error = String::from("Bundled bridge.exe not found and no Python launcher available.");
    let launchers = python_launchers();
    let mut preferred_launchers = Vec::new();
    let mut launcher_diagnostics = Vec::new();

    let bridge_path = match bridge_candidates.into_iter().find(|path| path.exists()) {
        Some(path) => path,
        None => ensure_embedded_bridge_file()?,
    };

    for launcher in launchers.iter().copied() {
        match launcher_has_required_modules(launcher) {
            Ok(true) => preferred_launchers.push(launcher),
            Ok(false) => launcher_diagnostics.push(format!(
                "{} missing required modules (samsung_mdc and/or samsungtvws)",
                launcher.label
            )),
            Err(err) => launcher_diagnostics.push(err),
        }
    }

    let execution_order = if preferred_launchers.is_empty() {
        launchers.clone()
    } else {
        preferred_launchers
    };

    for launcher in execution_order {
        let output = launcher_command(launcher)
            .arg(&bridge_path)
            .arg(action)
            .arg(&payload_str)
            .output();

        match output {
            Ok(out) => {
                if out.status.success() {
                    let stdout = String::from_utf8_lossy(&out.stdout).trim().to_string();
                    return serde_json::from_str::<Value>(&stdout)
                        .map_err(|e| format!("Invalid JSON from bridge: {e}. Output: {stdout}"));
                }

                let stderr = String::from_utf8_lossy(&out.stderr).trim().to_string();
                let stdout = String::from_utf8_lossy(&out.stdout).trim().to_string();
                if stderr.contains("ModuleNotFoundError") {
                    last_error = format!(
                        "{} bridge failed: missing Python dependency. stdout='{stdout}' stderr='{stderr}'",
                        launcher.label
                    );
                } else {
                    last_error = format!(
                        "{} bridge failed. stdout='{stdout}' stderr='{stderr}'",
                        launcher.label
                    );
                }
            }
            Err(err) => {
                last_error = format!("Unable to start {}: {err}", launcher.label);
            }
        }
    }

    if !launcher_diagnostics.is_empty() {
        return Err(format!(
            "{last_error}. Python diagnostics: {}",
            launcher_diagnostics.join(" | ")
        ));
    }

    Err(last_error)
}

#[tauri::command]
fn device_action(action: String, payload: Value) -> Result<Value, String> {
    run_bridge(&action, &payload)
}

#[tauri::command]
fn load_saved_devices() -> Result<Vec<SavedDevice>, String> {
    load_saved_devices_internal()
}

#[tauri::command]
fn upsert_saved_device(device: Value) -> Result<Vec<SavedDevice>, String> {
    let candidate = normalize_device(device)?;
    let mut devices = load_saved_devices_internal()?;

    if let Some(existing) = devices.iter_mut().find(|d| d.ip == candidate.ip) {
        *existing = candidate;
    } else {
        devices.push(candidate);
    }

    save_saved_devices_internal(&devices)?;
    Ok(devices)
}

#[tauri::command]
fn delete_saved_device(ip: String) -> Result<Vec<SavedDevice>, String> {
    let mut devices = load_saved_devices_internal()?;
    let before = devices.len();
    devices.retain(|d| d.ip != ip.trim());

    if devices.len() == before {
        return Err("Device not found".to_string());
    }

    save_saved_devices_internal(&devices)?;
    Ok(devices)
}

#[tauri::command]
fn auto_probe(ip: String) -> Result<Value, String> {
    let ip_clean = ip.trim().to_string();
    if ip_clean.is_empty() {
        return Err("IP is required".to_string());
    }

    let probes = [
        (1515_u16, "SIGNAGE_MDC"),
        (8002_u16, "SMART_TV_WS"),
        (8001_u16, "SMART_TV_WS"),
    ];

    for (port, protocol) in probes {
        if probe_port(&ip_clean, port, 1200) {
            return Ok(serde_json::json!({
                "ok": true,
                "ip": ip_clean,
                "port": port,
                "protocol": protocol,
            }));
        }
    }

    Ok(serde_json::json!({
        "ok": false,
        "ip": ip_clean,
        "error": "No supported control ports reachable (1515/8002/8001)",
    }))
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            device_action,
            load_saved_devices,
            upsert_saved_device,
            delete_saved_device,
            auto_probe
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
