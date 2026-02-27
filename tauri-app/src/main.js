import './styles.css';
import { invoke } from '@tauri-apps/api/core';
import { Notyf } from 'notyf';
import 'notyf/notyf.min.css';

const $ = (id) => document.getElementById(id);

let savedDevices = [];
let cliCommands = [];
let cliCommandMap = new Map();
const WEB_SAVED_DEVICES_KEY = 'samsung_saved_devices_v1';
const WEB_BACKEND_URL = 'http://127.0.0.1:8765';
const notyf = new Notyf({
  duration: 2600,
  position: { x: 'right', y: 'top' },
  dismissible: true,
  ripple: false,
  types: [
    {
      type: 'info',
      background: '#1f2937',
      className: 'toast-info',
    },
    {
      type: 'success',
      background: '#1f2937',
      className: 'toast-success',
    },
    {
      type: 'error',
      background: '#1f2937',
      className: 'toast-error',
    },
  ],
});
const SMART_TV_KEYS = [
  'KEY_HOME',
  'KEY_POWER',
  'KEY_MUTE',
  'KEY_VOLUP',
  'KEY_VOLDOWN',
  'KEY_SOURCE',
  'KEY_MENU',
  'KEY_RETURN',
  'KEY_UP',
  'KEY_DOWN',
  'KEY_LEFT',
  'KEY_RIGHT',
  'KEY_ENTER',
];

function nowTag() {
  return new Date().toLocaleTimeString();
}

function logLine(message) {
  const box = $('commandLog');
  box.textContent += `[${nowTag()}] ${message}\n`;
  box.scrollTop = box.scrollHeight;
}

function stringifyError(error) {
  if (!error) {
    return 'Unknown error';
  }
  if (typeof error === 'string') {
    return error;
  }
  if (typeof error === 'object' && 'message' in error) {
    return String(error.message);
  }
  return String(error);
}

function showToast(message, type = 'info') {
  const normalizedType =
    type === 'success' || type === 'error' || type === 'info' ? type : 'info';
  notyf.open({ type: normalizedType, message });
}

function setConnectionFields(device) {
  $('ip').value = device.ip ?? '';
  $('port').value = Number(device.port ?? 1515);
  $('displayId').value = Number(device.id ?? 0);
  $('protocol').value = device.protocol ?? 'AUTO';
  $('site').value = device.site ?? '';
  $('description').value = device.description ?? '';
}

function renderSavedDevices(list) {
  savedDevices = Array.isArray(list) ? list : [];
  const select = $('savedDeviceSelect');
  select.innerHTML = '';

  const manual = document.createElement('option');
  manual.value = '';
  manual.textContent = '(manual entry)';
  select.appendChild(manual);

  for (const device of savedDevices) {
    const option = document.createElement('option');
    option.value = device.ip;
    option.textContent = `${device.ip}${device.site ? ` - ${device.site}` : ''}`;
    select.appendChild(option);
  }

  select.value = '';
}

function normalizeSavedDeviceWeb(device) {
  if (!device || typeof device !== 'object') {
    return null;
  }

  const ip = String(device.ip ?? '').trim();
  if (!ip) {
    return null;
  }

  const port = Number(device.port ?? 1515);
  const id = Number(device.id ?? 0);
  const protocol = String(device.protocol ?? 'AUTO').toUpperCase();

  return {
    ip,
    port: Number.isFinite(port) ? port : 1515,
    id: Number.isFinite(id) ? id : 0,
    protocol:
      protocol === 'SIGNAGE_MDC' || protocol === 'SMART_TV_WS'
        ? protocol
        : 'AUTO',
    site: String(device.site ?? '').trim(),
    description: String(device.description ?? '').trim(),
  };
}

function loadSavedDevicesWeb() {
  try {
    const raw = localStorage.getItem(WEB_SAVED_DEVICES_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.map(normalizeSavedDeviceWeb).filter(Boolean);
  } catch (_error) {
    return [];
  }
}

function saveSavedDevicesWeb(list) {
  localStorage.setItem(WEB_SAVED_DEVICES_KEY, JSON.stringify(list));
}

async function loadSavedDevicesAny() {
  try {
    const list = await invoke('load_saved_devices');
    return { list, source: 'tauri' };
  } catch (_error) {
    return { list: loadSavedDevicesWeb(), source: 'web' };
  }
}

async function upsertSavedDeviceAny(device) {
  try {
    const list = await invoke('upsert_saved_device', { device });
    return { list, source: 'tauri' };
  } catch (_error) {
    const current = loadSavedDevicesWeb();
    const normalized = normalizeSavedDeviceWeb(device);
    if (!normalized) {
      throw new Error('IP is required');
    }

    const idx = current.findIndex((item) => item.ip === normalized.ip);
    if (idx >= 0) {
      current[idx] = normalized;
    } else {
      current.push(normalized);
    }

    saveSavedDevicesWeb(current);
    return { list: current, source: 'web' };
  }
}

async function deleteSavedDeviceAny(ip) {
  try {
    const list = await invoke('delete_saved_device', { ip });
    return { list, source: 'tauri' };
  } catch (_error) {
    const current = loadSavedDevicesWeb();
    const cleanedIp = String(ip ?? '').trim();
    const next = current.filter((item) => item.ip !== cleanedIp);

    if (next.length === current.length) {
      throw new Error('Device not found');
    }

    saveSavedDevicesWeb(next);
    return { list: next, source: 'web' };
  }
}

async function refreshSavedDevices() {
  try {
    const { list, source } = await loadSavedDevicesAny();
    renderSavedDevices(list);
    logLine(`Loaded ${list.length} saved devices (${source})`);
  } catch (error) {
    logLine(`Load devices failed: ${String(error)}`);
  }
}

function readConnection() {
  return {
    ip: $('ip').value.trim(),
    port: Number($('port').value),
    display_id: Number($('displayId').value),
    protocol: $('protocol').value,
    site: $('site').value.trim(),
    description: $('description').value.trim(),
  };
}

function renderOutput(payload) {
  $('output').textContent = JSON.stringify(payload, null, 2);
}

function effectiveProtocol() {
  const protocol = $('protocol').value;
  if (protocol !== 'AUTO') {
    return protocol;
  }

  const port = Number($('port').value);
  return port === 1515 ? 'SIGNAGE_MDC' : 'SMART_TV_WS';
}

function parseManualCliArgs() {
  const raw = $('cliArgs').value.trim();
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed;
    }
  } catch (_error) {
    // ignore and fallback
  }

  return raw
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      if (/^-?\d+$/.test(item)) {
        return Number(item);
      }
      return item;
    });
}

function getSelectedCliCommandMeta() {
  const commandName = $('cliCommand').value;
  return cliCommandMap.get(commandName) ?? null;
}

function coerceFieldValue(value, fieldType) {
  if (fieldType === 'Int' && /^-?\d+$/.test(value)) {
    return Number(value);
  }
  return value;
}

function collectStructuredCliArgs() {
  const inputs = Array.from(document.querySelectorAll('.cli-arg-input'));
  const result = [];
  for (const input of inputs) {
    const value = input.value.trim();
    if (!value) {
      continue;
    }
    const fieldType = input.dataset.fieldType || '';
    result.push(coerceFieldValue(value, fieldType));
  }
  return result;
}

function parseCliArgs() {
  const manual = parseManualCliArgs();
  if (manual) {
    return manual;
  }
  return collectStructuredCliArgs();
}

function renderCliArgRows(commandName) {
  const container = $('cliArgRows');
  container.innerHTML = '';

  const meta = cliCommandMap.get(commandName);
  if (!meta) {
    const empty = document.createElement('div');
    empty.className = 'cli-arg-empty';
    empty.textContent = 'Select an MDC command.';
    container.appendChild(empty);
    return;
  }

  if (!meta.fields || meta.fields.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'cli-arg-empty';
    empty.textContent = 'No arguments — read-only command, use CLI GET.';
    container.appendChild(empty);
    return;
  }

  for (const field of meta.fields) {
    const label = document.createElement('label');
    label.className = 'cli-arg-label';
    label.textContent = `${field.name} (${field.type})`;

    if (Array.isArray(field.enum) && field.enum.length > 0) {
      const select = document.createElement('select');
      select.className = 'cli-arg-input';
      select.dataset.fieldType = field.type || '';
      for (const optionName of field.enum) {
        const option = document.createElement('option');
        option.value = optionName;
        option.textContent = optionName;
        select.appendChild(option);
      }

      container.appendChild(label);
      container.appendChild(select);
      continue;
    }

    const input = document.createElement('input');
    input.className = 'cli-arg-input';
    input.dataset.fieldType = field.type || '';
    input.placeholder = field.placeholder || 'value';

    container.appendChild(label);
    container.appendChild(input);
  }
}

function populateCliCommands() {
  const select = $('cliCommand');
  select.innerHTML = '';

  for (const command of cliCommands) {
    const option = document.createElement('option');
    option.value = command.name;
    option.textContent = command.name;
    select.appendChild(option);
  }

  if (cliCommands.length > 0) {
    select.value = cliCommands[0].name;
    renderCliArgRows(cliCommands[0].name);
  }
}

async function loadCliCatalog() {
  const applyCommands = (commands) => {
    if (!Array.isArray(commands)) {
      logLine('CLI catalog load failed: invalid response format');
      return false;
    }

    cliCommands = commands;
    cliCommandMap = new Map(commands.map((item) => [item.name, item]));
    populateCliCommands();
    logLine(`Loaded ${commands.length} CLI commands`);
    return true;
  };

  try {
    const response = await invoke('device_action', {
      action: 'cli_catalog',
      payload: {},
    });

    if (applyCommands(response?.data?.commands)) {
      logLine('CLI schema source: Tauri Python bridge');
      return;
    }
  } catch (error) {
    logLine(`Tauri CLI catalog unavailable: ${String(error)}`);
  }

  try {
    const response = await fetch(`/src/cli_catalog.json?t=${Date.now()}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    if (applyCommands(payload?.commands)) {
      logLine('CLI schema source: web fallback file src/cli_catalog.json');
      return;
    }
  } catch (error) {
    logLine(`Web CLI catalog fallback failed: ${String(error)}`);
    logLine('Run: py py/export_cli_catalog.py (inside tauri-app)');
  }
}

function initSmartTvKeys() {
  const select = $('consumerKey');
  select.innerHTML = '';
  for (const key of SMART_TV_KEYS) {
    const option = document.createElement('option');
    option.value = key;
    option.textContent = key;
    select.appendChild(option);
  }
}

function bindButtonAction(buttonId, action) {
  const button = $(buttonId);
  if (!button) {
    return;
  }

  const buttonLabel = button.textContent?.trim() || buttonId;

  button.addEventListener('click', () => {
    Promise.resolve(action())
      .then((result) => {
        if (result && typeof result === 'object' && 'ok' in result) {
          if (result.ok) {
            showToast(`${buttonLabel}: success`, 'success');
          } else {
            showToast(
              `${buttonLabel}: ${stringifyError(result.error || 'failed')}`,
              'error',
            );
          }
          return;
        }

        showToast(`${buttonLabel}: done`, 'info');
      })
      .catch((error) => {
        console.error(error);
        showToast(`${buttonLabel}: ${stringifyError(error)}`, 'error');
      });
  });
}

async function callAction(action, data = {}) {
  const payload = { ...readConnection(), ...data };
  logLine(
    `Action '${action}' sent to ${payload.ip}:${payload.port} (${payload.protocol})`,
  );

  try {
    const response = await invoke('device_action', { action, payload });
    renderOutput(response);
    if (response?.ok) {
      logLine(`Action '${action}' completed (tauri)`);
    } else {
      logLine(
        `Action '${action}' failed (tauri): ${String(response?.error ?? 'unknown error')}`,
      );
    }
    return response;
  } catch (_tauriError) {
    // fallback below
  }

  try {
    const response = await fetch(`${WEB_BACKEND_URL}/device_action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, payload }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const dataResponse = await response.json();
    renderOutput(dataResponse);
    if (dataResponse?.ok) {
      logLine(`Action '${action}' completed (web backend)`);
    } else {
      logLine(
        `Action '${action}' failed (web backend): ${String(dataResponse?.error ?? 'unknown error')}`,
      );
    }
    return dataResponse;
  } catch (error) {
    logLine(`Action '${action}' failed: ${String(error)}`);
    logLine(`Tip: start web backend with 'py py/web_backend.py' in tauri-app`);
    const failed = { ok: false, error: String(error) };
    renderOutput(failed);
    return failed;
  }
}

async function saveCurrentDevice() {
  const payload = readConnection();
  if (!payload.ip) {
    logLine('Save failed: IP is required');
    return;
  }

  try {
    const { list, source } = await upsertSavedDeviceAny({
      ip: payload.ip,
      port: payload.port,
      id: payload.display_id,
      protocol: payload.protocol,
      site: payload.site,
      description: payload.description,
    });
    renderSavedDevices(list);
    $('savedDeviceSelect').value = payload.ip;
    logLine(`Saved device ${payload.ip} (${source})`);
  } catch (error) {
    logLine(`Save device failed: ${String(error)}`);
  }
}

async function deleteSelectedDevice() {
  const selectedIp = $('savedDeviceSelect').value || $('ip').value.trim();
  if (!selectedIp) {
    logLine('Delete skipped: no selected device');
    return;
  }

  try {
    const { list, source } = await deleteSavedDeviceAny(selectedIp);
    renderSavedDevices(list);
    logLine(`Deleted device ${selectedIp} (${source})`);
  } catch (error) {
    logLine(`Delete failed: ${String(error)}`);
  }
}

function applySelectedDevice() {
  const selectedIp = $('savedDeviceSelect').value;
  if (!selectedIp) {
    logLine('Manual entry mode active');
    return;
  }

  const selected = savedDevices.find((item) => item.ip === selectedIp);
  if (!selected) {
    logLine(`Selected device ${selectedIp} not found`);
    return;
  }

  setConnectionFields(selected);
  logLine(`Applied saved device ${selectedIp}`);
}

async function runAutoProbe() {
  const ip = $('ip').value.trim();
  if (!ip) {
    logLine('Auto probe failed: IP is required');
    return;
  }

  logLine(`Auto probe started for ${ip}`);
  try {
    const probe = await invoke('auto_probe', { ip });
    if (probe.ok) {
      $('port').value = Number(probe.port);
      $('protocol').value = probe.protocol;
      renderOutput(probe);
      logLine(
        `Auto probe success: ${ip} -> ${probe.protocol} on port ${probe.port}`,
      );
    } else {
      renderOutput(probe);
      logLine(`Auto probe failed: ${probe.error}`);
    }
    return;
  } catch (_error) {
    // fallback below
  }

  try {
    const response = await fetch(
      `${WEB_BACKEND_URL}/auto_probe?ip=${encodeURIComponent(ip)}`,
    );
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const probe = await response.json();
    renderOutput(probe);

    if (probe?.ok) {
      $('port').value = Number(probe.port);
      $('protocol').value = probe.protocol;
      logLine(
        `Auto probe success: ${ip} -> ${probe.protocol} on port ${probe.port} (web backend)`,
      );
    } else {
      logLine(
        `Auto probe failed (web backend): ${String(probe?.error ?? 'unknown error')}`,
      );
    }
  } catch (error) {
    logLine(`Auto probe exception: ${String(error)}`);
    logLine(`Tip: start web backend with 'py py/web_backend.py' in tauri-app`);
  }
}

async function runCliGet() {
  if (effectiveProtocol() !== 'SIGNAGE_MDC') {
    logLine(
      'CLI commands are MDC-only. Set Protocol to SIGNAGE_MDC (or AUTO + port 1515).',
    );
    return;
  }

  const command = $('cliCommand').value.trim();
  if (!command) {
    logLine('CLI GET failed: command is required');
    return;
  }

  const meta = getSelectedCliCommandMeta();
  if (meta && !meta.get) {
    logLine(`${command}: this command does not support GET (read).`);
    return;
  }

  const args = parseCliArgs();
  if (command === 'timer_15' && args.length === 0) {
    logLine('timer_15 GET requires timer_id (1-7). Fill command arguments.');
    return;
  }

  if (command !== 'timer_15' && args.length > 0) {
    logLine(`${command}: GET ignores arguments; using read-only call.`);
  }

  await callAction('cli_get', {
    command,
    args,
  });
}

async function runCliSet() {
  if (effectiveProtocol() !== 'SIGNAGE_MDC') {
    logLine(
      'CLI commands are MDC-only. Set Protocol to SIGNAGE_MDC (or AUTO + port 1515).',
    );
    return;
  }

  const command = $('cliCommand').value.trim();
  if (!command) {
    logLine('CLI SET failed: command is required');
    return;
  }

  const meta = getSelectedCliCommandMeta();
  if (meta && !meta.set) {
    logLine(`${command}: this command does not support SET (write).`);
    return;
  }

  const args = parseCliArgs();
  if (command === 'timer_15' && args.length === 0) {
    logLine(
      'timer_15 SET requires timer_id (1-7) plus values. Fill Arguments first.',
    );
    return;
  }

  await callAction('cli_set', {
    command,
    args,
  });
}

async function sendConsumerKey() {
  if (effectiveProtocol() !== 'SMART_TV_WS') {
    logLine(
      'Consumer key CLI is Smart TV only. Set Protocol to SMART_TV_WS (or AUTO + port 8002/8001).',
    );
    return;
  }

  let repeat = Number($('consumerRepeat').value);
  if (Number.isNaN(repeat) || repeat < 1) {
    repeat = 1;
  }
  if (repeat > 20) {
    repeat = 20;
  }
  $('consumerRepeat').value = String(repeat);

  await callAction('consumer_key', {
    key: $('consumerKey').value,
    repeat,
  });
}

async function sendHdmiMacro(hdmi) {
  if (effectiveProtocol() !== 'SMART_TV_WS') {
    logLine(
      'HDMI macro is Smart TV only. Set Protocol to SMART_TV_WS (or AUTO + port 8002/8001).',
    );
    return;
  }

  await callAction('hdmi_macro', { hdmi });
}

bindButtonAction('btnStatus', () => callAction('status'));
bindButtonAction('btnPowerOn', () => callAction('power', { state: 'ON' }));
bindButtonAction('btnPowerOff', () => callAction('power', { state: 'OFF' }));
bindButtonAction('btnReboot', () => callAction('power', { state: 'REBOOT' }));
bindButtonAction('btnSetVolume', () =>
  callAction('set_volume', { value: Number($('volume').value) }),
);
bindButtonAction('btnSetBrightness', () =>
  callAction('set_brightness', { value: Number($('brightness').value) }),
);
bindButtonAction('btnSetMute', () =>
  callAction('set_mute', { state: $('mute').value }),
);
bindButtonAction('btnSetInput', () =>
  callAction('set_input', { source: $('inputSource').value }),
);
bindButtonAction('btnLoadDevices', refreshSavedDevices);
bindButtonAction('btnSaveDevice', saveCurrentDevice);
bindButtonAction('btnDeleteDevice', deleteSelectedDevice);
bindButtonAction('btnApplyDevice', applySelectedDevice);
bindButtonAction('btnAutoProbe', runAutoProbe);
$('savedDeviceSelect').addEventListener('change', applySelectedDevice);

bindButtonAction('btnCliGet', runCliGet);
bindButtonAction('btnCliSet', runCliSet);
bindButtonAction('btnConsumerKey', sendConsumerKey);
bindButtonAction('btnHdmi1', () => sendHdmiMacro('HDMI1'));
bindButtonAction('btnHdmi2', () => sendHdmiMacro('HDMI2'));
bindButtonAction('btnHdmi3', () => sendHdmiMacro('HDMI3'));
bindButtonAction('btnHdmi4', () => sendHdmiMacro('HDMI4'));
$('cliCommand').addEventListener('change', (event) =>
  renderCliArgRows(event.target.value),
);

refreshSavedDevices();
initSmartTvKeys();
loadCliCatalog();
logLine('Dashboard initialized');
