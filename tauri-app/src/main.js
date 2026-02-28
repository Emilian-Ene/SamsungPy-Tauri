import { invoke } from '@tauri-apps/api/core';
import { Notyf } from 'notyf';
import 'notyf/notyf.min.css';

const $ = (id) => document.getElementById(id);

let savedDevices = [];
const WEB_SELECTED_DEVICE_KEY = 'samsung_selected_device_ip_v1';
const WEB_CHECKED_DEVICES_KEY = 'samsung_checked_devices_v1';
let selectedSavedDeviceIp = localStorage.getItem(WEB_SELECTED_DEVICE_KEY) || '';
let checkedSavedDeviceIps = new Set();
let cliCommands = [];
let cliCommandMap = new Map();
const WEB_SAVED_DEVICES_KEY = 'samsung_saved_devices_v1';
const WEB_BACKEND_URL = 'http://127.0.0.1:8765';

try {
  const rawChecked = localStorage.getItem(WEB_CHECKED_DEVICES_KEY);
  if (rawChecked) {
    const parsedChecked = JSON.parse(rawChecked);
    if (Array.isArray(parsedChecked)) {
      checkedSavedDeviceIps = new Set(
        parsedChecked.map((item) => String(item || '').trim()).filter(Boolean),
      );
    }
  }
} catch (_error) {
  checkedSavedDeviceIps = new Set();
}
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
const INPUT_SOURCE_GET_ONLY = new Set([
  'DVI_VIDEO',
  'HDMI1_PC',
  'HDMI2_PC',
  'HDMI3_PC',
  'HDMI4_PC',
]);
const INPUT_SOURCE_MODEL_DEPENDENT = new Set([
  'URL_LAUNCHER',
  'MAGIC_INFO',
  'TV_DTV',
  'RF_TV',
  'WIDI_SCREEN_MIRRORING',
  'MEDIA_MAGIC_INFO_S',
  'OCM',
  'HD_BASE_T',
]);
const WRITE_ACTIONS = new Set([
  'power',
  'set_volume',
  'set_brightness',
  'set_mute',
  'set_input',
  'cli_set',
  'consumer_key',
  'hdmi_macro',
]);
const TIMER_INDEXED_COMMANDS = new Set(['timer_13', 'timer_15']);

function persistDeviceSelectionState() {
  if (selectedSavedDeviceIp) {
    localStorage.setItem(WEB_SELECTED_DEVICE_KEY, selectedSavedDeviceIp);
  } else {
    localStorage.removeItem(WEB_SELECTED_DEVICE_KEY);
  }

  localStorage.setItem(
    WEB_CHECKED_DEVICES_KEY,
    JSON.stringify(Array.from(checkedSavedDeviceIps)),
  );
}

function nowTag() {
  return new Date().toLocaleTimeString();
}

function logLine(message) {
  const logText = `[${nowTag()}] ${message}\n`;
  const targets = ['commandLog', 'commandLogWs'];
  for (const targetId of targets) {
    const box = $(targetId);
    if (!box) {
      continue;
    }
    box.textContent += logText;
    box.scrollTop = box.scrollHeight;
  }
}

function clearLog(logId) {
  const box = $(logId);
  if (!box) {
    return { ok: false, error: `Log box not found: ${logId}` };
  }

  box.textContent = '';
  return { ok: true, message: 'log cleared' };
}

function saveLog(logId, filenamePrefix) {
  const box = $(logId);
  if (!box) {
    return { ok: false, error: `Log box not found: ${logId}` };
  }

  const text = String(box.textContent || '').trim();
  if (!text) {
    return { ok: false, error: 'Log is empty' };
  }

  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const filename = `${filenamePrefix}_${stamp}.log`;
  const blob = new Blob([text + '\n'], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);

  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);

  return { ok: true, message: `saved ${filename}` };
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

function detectNak(error) {
  const text = stringifyError(error);
  return /\bNAK\b|NAKError|negative acknowledgement/i.test(text);
}

function normalizeActionResult(action, backend, result) {
  const normalized =
    result && typeof result === 'object'
      ? { ...result }
      : { ok: false, error: stringifyError(result) };

  normalized.action = normalized.action || action;
  normalized.backend = normalized.backend || backend;
  normalized.nak = Boolean(normalized.nak) || detectNak(normalized.error);
  normalized.ack = Boolean(normalized.ok) && !normalized.nak;
  return normalized;
}

function validateInputSourceSelection(source) {
  const normalizedSource = String(source || '')
    .trim()
    .toUpperCase();
  if (!normalizedSource) {
    return { ok: false, error: 'Input source is required' };
  }

  if (INPUT_SOURCE_GET_ONLY.has(normalizedSource)) {
    return {
      ok: false,
      error: `${normalizedSource} is get-only for many models and cannot be set.`,
    };
  }

  if (INPUT_SOURCE_MODEL_DEPENDENT.has(normalizedSource)) {
    return {
      ok: true,
      warning: `${normalizedSource} depends on model support and may be rejected by device.`,
    };
  }

  return { ok: true };
}

function setConnectionFields(device) {
  $('ip').value = device.ip ?? '';
  $('port').value = Number(device.port ?? 1515);
  $('displayId').value = Number(device.id ?? 0);
  $('protocol').value = device.protocol ?? 'AUTO';
  $('site').value = device.site ?? '';
  $('description').value = device.description ?? '';
}

function renderSavedDeviceList(selectedIp = selectedSavedDeviceIp) {
  const listContainer = $('savedDeviceList');
  if (!listContainer) {
    return;
  }

  listContainer.innerHTML = '';

  if (savedDevices.length === 0) {
    const empty = document.createElement('li');
    empty.className = 'saved-device-empty';
    empty.textContent = 'No saved devices yet.';
    listContainer.appendChild(empty);
    return;
  }

  for (const device of savedDevices) {
    const row = document.createElement('li');
    row.className = 'saved-device-row';

    const rowMain = document.createElement('div');
    rowMain.className = 'saved-device-main';

    const selectCheckbox = document.createElement('input');
    selectCheckbox.type = 'checkbox';
    selectCheckbox.className = 'saved-device-check';
    selectCheckbox.checked = checkedSavedDeviceIps.has(device.ip);
    selectCheckbox.setAttribute('aria-label', `Select ${device.ip}`);

    const item = document.createElement('div');
    item.className = 'saved-device-item';
    item.textContent = `${device.ip}${device.site ? ` - ${device.site}` : ''}`;

    const rowActions = document.createElement('div');
    rowActions.className = 'saved-device-row-actions';

    const openBtn = document.createElement('button');
    openBtn.type = 'button';
    openBtn.className = 'saved-device-row-btn';
    openBtn.textContent = 'Open';

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'saved-device-row-btn';
    deleteBtn.textContent = 'Delete';

    if (device.ip === selectedIp) {
      item.classList.add('active');
      row.classList.add('active');
    }

    selectCheckbox.addEventListener('change', () => {
      if (selectCheckbox.checked) {
        checkedSavedDeviceIps.add(device.ip);
      } else {
        checkedSavedDeviceIps.delete(device.ip);
      }

      persistDeviceSelectionState();
    });

    item.addEventListener('click', () => {
      const result = applySelectedDevice(device.ip);
      renderOutput(result);
      if (!result.ok) {
        showToast(
          `Select: ${stringifyError(result.error || 'failed')}`,
          'error',
        );
      }
    });

    openBtn.addEventListener('click', () => {
      const result = applySelectedDevice(device.ip);
      renderOutput(result);
      if (result.ok) {
        switchWorkflowPage('controls');
        showToast(`Open: ${result.message || 'success'}`, 'success');
      } else {
        showToast(`Open: ${stringifyError(result.error || 'failed')}`, 'error');
      }
    });

    deleteBtn.addEventListener('click', async () => {
      const result = await deleteSavedDeviceByIp(device.ip);
      renderOutput(result);
      if (result.ok) {
        showToast(`Delete: ${result.message || 'success'}`, 'success');
      } else {
        showToast(
          `Delete: ${stringifyError(result.error || 'failed')}`,
          'error',
        );
      }
    });

    rowMain.appendChild(selectCheckbox);
    rowMain.appendChild(item);
    rowActions.appendChild(openBtn);
    rowActions.appendChild(deleteBtn);
    row.appendChild(rowMain);
    row.appendChild(rowActions);
    listContainer.appendChild(row);
  }
}

function renderSavedDevices(list, selectedIp = '') {
  savedDevices = Array.isArray(list) ? list : [];
  const desiredIp = String(selectedIp || '').trim();
  const validIps = new Set(savedDevices.map((item) => item.ip));
  checkedSavedDeviceIps = new Set(
    Array.from(checkedSavedDeviceIps).filter((ip) => validIps.has(ip)),
  );

  if (validIps.has(desiredIp)) {
    selectedSavedDeviceIp = desiredIp;
  } else if (validIps.has(selectedSavedDeviceIp)) {
    // keep previous selected value
  } else {
    selectedSavedDeviceIp = '';
  }

  persistDeviceSelectionState();
  renderSavedDeviceList(selectedSavedDeviceIp);
}

function csvEscape(value) {
  const text = String(value ?? '');
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function parseCsvLine(line) {
  const result = [];
  let current = '';
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];

    if (char === '"') {
      const nextChar = line[index + 1];
      if (inQuotes && nextChar === '"') {
        current += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === ',' && !inQuotes) {
      result.push(current);
      current = '';
      continue;
    }

    current += char;
  }

  result.push(current);
  return result;
}

function csvFieldIndex(headers, names) {
  for (const name of names) {
    const index = headers.indexOf(name);
    if (index >= 0) {
      return index;
    }
  }
  return -1;
}

function normalizeCsvHeader(name) {
  return String(name || '')
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '');
}

async function exportDevicesCsv() {
  if (!savedDevices.length) {
    return { ok: false, error: 'No saved devices to export' };
  }

  const lines = ['ip,display_id,site,description'];
  for (const device of savedDevices) {
    lines.push(
      [
        csvEscape(device.ip),
        csvEscape(Number(device.id ?? 0)),
        csvEscape(device.site ?? ''),
        csvEscape(device.description ?? ''),
      ].join(','),
    );
  }

  const csvText = lines.join('\r\n');
  const blob = new Blob([csvText], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  const stamp = new Date().toISOString().slice(0, 10);
  link.href = url;
  link.download = `devices_${stamp}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);

  logLine(`Exported ${savedDevices.length} devices to CSV`);
  return {
    ok: true,
    message: `exported ${savedDevices.length} devices`,
    count: savedDevices.length,
  };
}

async function importDevicesCsvFromText(csvText) {
  const rows = String(csvText || '')
    .split(/\r?\n/)
    .map((row) => row.trim())
    .filter(Boolean);

  if (!rows.length) {
    return { ok: false, error: 'CSV file is empty' };
  }

  const headerCells = parseCsvLine(rows[0]).map(normalizeCsvHeader);
  const ipIndex = csvFieldIndex(headerCells, ['ip']);
  const displayIdIndex = csvFieldIndex(headerCells, ['displayid', 'id']);
  const siteIndex = csvFieldIndex(headerCells, ['site']);
  const descriptionIndex = csvFieldIndex(headerCells, ['description']);

  if (ipIndex < 0) {
    return { ok: false, error: 'CSV header must include ip' };
  }

  const existingByIp = new Map(
    savedDevices.map((device) => [device.ip, device]),
  );
  let importedCount = 0;
  let lastImportedIp = '';
  let lastList = savedDevices;

  for (let rowIndex = 1; rowIndex < rows.length; rowIndex += 1) {
    const cols = parseCsvLine(rows[rowIndex]);
    const ip = String(cols[ipIndex] ?? '').trim();
    if (!ip) {
      continue;
    }

    const rawId = String(cols[displayIdIndex] ?? '').trim();
    const parsedId = rawId === '' ? 0 : Number(rawId);
    const id = Number.isFinite(parsedId) ? parsedId : 0;
    const site = String(cols[siteIndex] ?? '').trim();
    const description = String(cols[descriptionIndex] ?? '').trim();
    const existing = existingByIp.get(ip);

    const payload = {
      ip,
      id,
      site,
      description,
      port: Number(existing?.port ?? 1515),
      protocol: existing?.protocol ?? 'AUTO',
    };

    const result = await upsertSavedDeviceAny(payload);
    lastList = result.list;
    existingByIp.set(ip, payload);
    importedCount += 1;
    lastImportedIp = ip;
  }

  if (!importedCount) {
    return { ok: false, error: 'No valid rows to import' };
  }

  renderSavedDevices(lastList, lastImportedIp);
  logLine(`Imported ${importedCount} devices from CSV`);
  return {
    ok: true,
    message: `imported ${importedCount} devices`,
    count: importedCount,
  };
}

async function importDevicesCsv() {
  const input = $('deviceCsvInput');
  if (!input) {
    return { ok: false, error: 'CSV file input not found' };
  }

  const file = input.files?.[0];
  if (!file) {
    return { ok: false, error: 'No CSV file selected' };
  }

  const text = await file.text();
  return importDevicesCsvFromText(text);
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
    renderSavedDevices(list, selectedSavedDeviceIp);
    logLine(`Loaded ${list.length} saved devices (${source})`);
    return {
      ok: true,
      message: `loaded ${list.length} devices`,
      source,
      count: list.length,
    };
  } catch (error) {
    logLine(`Load devices failed: ${String(error)}`);
    return { ok: false, error: String(error) };
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

function setQuickOutputLine(summary, healthState) {
  const quickBox = $('quickOutputLine');
  if (!quickBox) {
    return;
  }

  quickBox.textContent = String(summary ?? '');
  if (healthState) {
    quickBox.dataset.health = healthState;
  } else {
    delete quickBox.dataset.health;
  }
}

function buildHumanQuickMessage(payload) {
  const action = String(payload?.action || '').trim();
  const data = payload?.data;

  if (action === 'status' && data?.status && typeof data.status === 'object') {
    const status = data.status;
    return `Status - Power: ${status.power ?? 'N/A'}, Volume: ${status.volume ?? 'N/A'}, Mute: ${status.mute ?? 'N/A'}, Input: ${status.input_source ?? 'N/A'}, Aspect: ${status.picture_aspect ?? 'N/A'}`;
  }

  if (action === 'power') {
    return `Power command sent: ${data?.state ?? 'OK'}`;
  }

  if (action === 'set_volume') {
    return `Volume set to ${data?.value ?? 'N/A'}`;
  }

  if (action === 'set_brightness') {
    return `Brightness set to ${data?.value ?? 'N/A'}`;
  }

  if (action === 'set_mute') {
    return `Mute set to ${data?.state ?? 'N/A'}`;
  }

  if (action === 'set_input') {
    return `Input source set to ${data?.source ?? 'N/A'}`;
  }

  if (action === 'cli_get') {
    const command = data?.command ?? payload?.command ?? 'command';
    const result = data?.result;
    if (
      typeof result === 'string' &&
      result.trim() &&
      result.length <= 48 &&
      !/[\{\}\[\]]/.test(result)
    ) {
      return `Read ${command} successful: ${result}`;
    }
    return `Read ${command} successful`;
  }

  if (action === 'cli_set') {
    const command = data?.command ?? payload?.command ?? 'command';
    return `Set ${command} successful`;
  }

  if (action === 'auto_probe') {
    return `Auto probe completed`;
  }

  return null;
}

function renderOutput(payload) {
  const outputText = JSON.stringify(payload, null, 2);
  const targets = ['output', 'outputWs'];
  for (const targetId of targets) {
    const box = $(targetId);
    if (!box) {
      continue;
    }
    box.textContent = outputText;
  }

  const quickBox = $('quickOutputLine');
  if (quickBox) {
    let summary = '';
    if (payload && typeof payload === 'object') {
      const okTag = payload.maybeSent
        ? '[SENT]'
        : payload.noAck
          ? '[NO-ACK]'
          : payload.nak
            ? '[NAK]'
            : payload.ack
              ? '[ACK]'
              : 'ok' in payload
                ? payload.ok
                  ? '[OK]'
                  : '[ERROR]'
                : '';
      const humanMessage = payload.ok ? buildHumanQuickMessage(payload) : null;
      const actionName = payload.action ? `${payload.action}: ` : '';
      const message =
        humanMessage ||
        payload.message ||
        payload.error ||
        payload.warning ||
        payload.action ||
        '';
      summary = `${okTag} ${String(message || JSON.stringify(payload))}`.trim();
      if (actionName) {
        summary =
          `${okTag} ${actionName}${String(message || '').trim()}`.trim();
      }
    } else {
      summary = String(payload ?? '');
    }
    setQuickOutputLine(summary, payload?.healthState || null);
  }
}

async function fetchJsonWithTimeout(url, timeoutMs = 3500) {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const response = await fetch(url, {
      method: 'GET',
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    });

    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (_parseError) {
        data = null;
      }
    }

    return {
      ok: response.ok,
      status: response.status,
      data,
      raw: text,
    };
  } catch (error) {
    if (timedOut) {
      throw new Error(`Request timeout after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function postJsonWithTimeout(url, body, timeoutMs = 5500) {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const response = await fetch(url, {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(body),
    });

    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (_parseError) {
        data = null;
      }
    }

    return {
      ok: response.ok,
      status: response.status,
      data,
      raw: text,
    };
  } catch (error) {
    if (timedOut) {
      throw new Error(`Request timeout after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function runConnectionTest() {
  const { ip } = readConnection();
  if (!ip) {
    const error = 'IP is required before running Test.';
    const result = {
      ok: false,
      healthState: 'offline',
      message: `🔴 Backend unknown | Screen unknown. ${error}`,
      error,
    };
    setQuickOutputLine(result.message, result.healthState);
    logLine(`Test: ${error}`);
    return result;
  }

  let tauriProbeError = null;
  try {
    const probe = await invoke('auto_probe', { ip });
    if (probe?.ok) {
      $('port').value = Number(probe.port);
      $('protocol').value = probe.protocol;

      const statusPayload = {
        ip,
        port: Number(probe.port),
        display_id: Number($('displayId').value || 0),
        protocol: probe.protocol,
        timeout_s: 25,
      };

      try {
        const statusCheck = await invoke('device_action', {
          action: 'status',
          payload: statusPayload,
        });

        if (statusCheck?.ok) {
          const message = `🟢 Tauri bridge online | Screen online (${ip}) | Ready to send commands.`;
          const result = {
            ok: true,
            healthState: 'online',
            message,
            backend: 'tauri',
            backendOnline: true,
            screenOnline: true,
            commandReady: true,
            ip,
            protocol: probe.protocol,
            port: probe.port,
          };
          setQuickOutputLine(message, 'online');
          logLine(
            `Test: tauri bridge online, screen online, command test passed (${ip})`,
          );
          renderOutput(result);
          return result;
        }

        const statusError = statusCheck?.error || 'Unknown status error';
        const message = `🟡 Tauri bridge online | Screen responds on port, but command test failed (${ip})`;
        const result = {
          ok: false,
          healthState: 'warn',
          message,
          warning:
            'tauri bridge online, tv reachable, command channel not ready',
          backend: 'tauri',
          error: String(statusError),
          backendOnline: true,
          screenOnline: true,
          commandReady: false,
          ip,
        };
        setQuickOutputLine(message, 'warn');
        logLine(
          `Test: tauri bridge online, screen port reachable, but status command failed (${ip}) - ${String(statusError)}`,
        );
        renderOutput(result);
        return result;
      } catch (error) {
        const message = `🟡 Tauri bridge online | Screen port open, but command check timed out (${ip})`;
        const result = {
          ok: false,
          healthState: 'warn',
          message,
          warning: 'tauri bridge online, tv reachable, command timeout',
          backend: 'tauri',
          error: stringifyError(error),
          backendOnline: true,
          screenOnline: true,
          commandReady: false,
          ip,
        };
        setQuickOutputLine(message, 'warn');
        logLine(
          `Test: tauri bridge online, screen port reachable, but command check timeout (${ip}) - ${stringifyError(error)}`,
        );
        renderOutput(result);
        return result;
      }
    }
  } catch (error) {
    tauriProbeError = stringifyError(error);
    logLine(
      `Test: tauri bridge probe failed for ${ip} (${tauriProbeError}); falling back to web backend`,
    );
  }

  let backendHealth = null;
  try {
    backendHealth = await fetchJsonWithTimeout(
      `${WEB_BACKEND_URL}/health`,
      2500,
    );
  } catch (error) {
    const message = `🔴 Backend offline | Screen not tested (${stringifyError(error)})`;
    const result = {
      ok: false,
      healthState: 'offline',
      message,
      error: stringifyError(error),
      tauriError: tauriProbeError || undefined,
      backendOnline: false,
      screenOnline: false,
      ip,
    };
    setQuickOutputLine(message, 'offline');
    logLine(`Test: backend offline; screen check skipped for ${ip}`);
    renderOutput(result);
    return result;
  }

  if (!backendHealth.ok || !backendHealth.data?.ok) {
    const backendError =
      backendHealth.data?.error ||
      backendHealth.raw ||
      `HTTP ${backendHealth.status}`;
    const message = `🔴 Backend offline | Screen not tested (${backendError})`;
    const result = {
      ok: false,
      healthState: 'offline',
      message,
      error: String(backendError),
      backendOnline: false,
      screenOnline: false,
      ip,
    };
    setQuickOutputLine(message, 'offline');
    logLine(
      `Test: backend offline (${backendError}); screen check skipped for ${ip}`,
    );
    renderOutput(result);
    return result;
  }

  let probe = null;
  try {
    probe = await fetchJsonWithTimeout(
      `${WEB_BACKEND_URL}/auto_probe?ip=${encodeURIComponent(ip)}`,
      4000,
    );
  } catch (error) {
    const message = `🟡 Backend online | Screen offline (${stringifyError(error)})`;
    const result = {
      ok: false,
      healthState: 'warn',
      message,
      warning: 'backend online, tv offline',
      error: stringifyError(error),
      backendOnline: true,
      screenOnline: false,
      ip,
    };
    setQuickOutputLine(message, 'warn');
    logLine(`Test: backend online, screen offline (${ip})`);
    renderOutput(result);
    return result;
  }

  if (probe.ok && probe.data?.ok) {
    $('port').value = Number(probe.data.port);
    $('protocol').value = probe.data.protocol;

    const statusPayload = {
      ip,
      port: Number(probe.data.port),
      display_id: Number($('displayId').value || 0),
      protocol: probe.data.protocol,
    };

    try {
      const statusCheck = await postJsonWithTimeout(
        `${WEB_BACKEND_URL}/device_action`,
        {
          action: 'status',
          payload: {
            ...statusPayload,
            timeout_s: 25,
          },
        },
        30000,
      );

      if (statusCheck.ok && statusCheck.data?.ok) {
        const message = `🟢 Backend online | Screen online (${ip}) | Ready to send commands.`;
        const result = {
          ok: true,
          healthState: 'online',
          message,
          backendOnline: true,
          screenOnline: true,
          commandReady: true,
          ip,
          protocol: probe.data.protocol,
          port: probe.data.port,
        };
        setQuickOutputLine(message, 'online');
        logLine(
          `Test: backend online, screen online, command test passed (${ip})`,
        );
        renderOutput(result);
        return result;
      }

      const statusError =
        statusCheck.data?.error ||
        statusCheck.raw ||
        `HTTP ${statusCheck.status}`;
      const message = `🟡 Backend online | Screen responds on port, but command test failed (${ip})`;
      const result = {
        ok: false,
        healthState: 'warn',
        message,
        warning: 'backend online, tv reachable, command channel not ready',
        error: String(statusError),
        backendOnline: true,
        screenOnline: true,
        commandReady: false,
        ip,
      };
      setQuickOutputLine(message, 'warn');
      logLine(
        `Test: backend online, screen port reachable, but status command failed (${ip}) - ${String(statusError)}`,
      );
      renderOutput(result);
      return result;
    } catch (error) {
      const message = `🟡 Backend online | Screen port open, but command check timed out (${ip})`;
      const result = {
        ok: false,
        healthState: 'warn',
        message,
        warning: 'backend online, tv reachable, command timeout',
        error: stringifyError(error),
        backendOnline: true,
        screenOnline: true,
        commandReady: false,
        ip,
      };
      setQuickOutputLine(message, 'warn');
      logLine(
        `Test: backend online, screen port reachable, but command check timeout (${ip}) - ${stringifyError(error)}`,
      );
      renderOutput(result);
      return result;
    }
  }

  const probeError = probe.data?.error || probe.raw || `HTTP ${probe.status}`;
  const message = `🟡 Backend online | Screen offline (${ip})`;
  const result = {
    ok: false,
    healthState: 'warn',
    message,
    warning: 'backend online, tv offline',
    error: String(probeError),
    backendOnline: true,
    screenOnline: false,
    ip,
  };
  setQuickOutputLine(message, 'warn');
  logLine(
    `Test: backend online, screen offline (${ip}) - ${String(probeError)}`,
  );
  renderOutput(result);
  return result;
}

function effectiveProtocol() {
  const protocol = $('protocol').value;
  if (protocol !== 'AUTO') {
    return protocol;
  }

  const port = Number($('port').value);
  return port === 1515 ? 'SIGNAGE_MDC' : 'SMART_TV_WS';
}

function getActionTimeoutMs(action) {
  if (action === 'status' || action === 'cli_get' || action === 'cli_set') {
    return 25000;
  }
  if (WRITE_ACTIONS.has(action)) {
    return 20000;
  }
  return 15000;
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

      const emptyOption = document.createElement('option');
      emptyOption.value = '';
      emptyOption.textContent = '-- optional --';
      emptyOption.selected = true;
      select.appendChild(emptyOption);

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

function switchWorkflowPage(pageName) {
  const validPages = new Set(['connection', 'controls', 'ws']);
  const normalizedPage = validPages.has(pageName) ? pageName : 'connection';
  const pages = document.querySelectorAll('.workflow-page');
  const tabs = document.querySelectorAll('.page-tab');

  for (const page of pages) {
    const isActive = page.dataset.page === normalizedPage;
    page.classList.toggle('active', isActive);
  }

  for (const tab of tabs) {
    const isActive = tab.dataset.pageTarget === normalizedPage;
    tab.classList.toggle('active', isActive);
    tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
  }
}

function initWorkflowNavigation() {
  const tabs = document.querySelectorAll('.page-tab');
  for (const tab of tabs) {
    tab.addEventListener('click', () => {
      switchWorkflowPage(tab.dataset.pageTarget || 'connection');
    });
  }

  switchWorkflowPage('connection');
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
          renderOutput(result);
          if (result.ok) {
            showToast(
              result.message
                ? `${buttonLabel}: ${result.message}`
                : `${buttonLabel}: success`,
              'success',
            );
          } else {
            showToast(
              `${buttonLabel}: ${stringifyError(result.error || 'failed')}`,
              'error',
            );
          }
          return;
        }

        const invalidResult = {
          ok: false,
          error: 'Invalid action result: expected an object with an ok field.',
        };
        renderOutput(invalidResult);
        showToast(`${buttonLabel}: ${invalidResult.error}`, 'error');
      })
      .catch((error) => {
        console.error(error);
        showToast(`${buttonLabel}: ${stringifyError(error)}`, 'error');
      });
  });
}

async function callAction(action, data = {}) {
  const timeoutMs = getActionTimeoutMs(action);
  const payload = {
    ...readConnection(),
    ...data,
    timeout_s: Math.ceil(timeoutMs / 1000),
  };
  let tauriFallbackErrorText = null;
  logLine(
    `Action '${action}' sent to ${payload.ip}:${payload.port} (${payload.protocol})`,
  );

  try {
    const response = await invoke('device_action', { action, payload });
    const normalized = normalizeActionResult(action, 'tauri', response);
    renderOutput(normalized);
    if (normalized.ok) {
      logLine(
        `Action '${action}' completed (tauri)${normalized.ack ? ' [ACK]' : ''}`,
      );
    } else if (normalized.nak) {
      logLine(
        `Action '${action}' rejected (tauri) [NAK]: ${String(normalized.error ?? 'unknown error')}`,
      );
    } else {
      logLine(
        `Action '${action}' failed (tauri): ${String(normalized.error ?? 'unknown error')}`,
      );
    }
    return normalized;
  } catch (tauriError) {
    tauriFallbackErrorText = String(tauriError);
    logLine(
      `Action '${action}' tauri bridge failed: ${tauriFallbackErrorText}`,
    );
    // fallback below
  }

  try {
    const response = await postJsonWithTimeout(
      `${WEB_BACKEND_URL}/device_action`,
      { action, payload },
      timeoutMs + 5000,
    );

    const rawBody = response.raw;
    let dataResponse = response.data;

    if (!response.ok) {
      const backendError =
        dataResponse &&
        typeof dataResponse === 'object' &&
        'error' in dataResponse
          ? String(dataResponse.error)
          : rawBody || `HTTP ${response.status}`;
      throw new Error(`HTTP ${response.status}: ${backendError}`);
    }

    if (!dataResponse || typeof dataResponse !== 'object') {
      dataResponse = {
        ok: true,
        data: rawBody,
      };
    }

    const normalized = normalizeActionResult(
      action,
      'web-backend',
      dataResponse,
    );
    renderOutput(normalized);
    if (normalized.ok) {
      logLine(
        `Action '${action}' completed (web backend)${normalized.ack ? ' [ACK]' : ''}`,
      );
    } else if (normalized.nak) {
      logLine(
        `Action '${action}' rejected (web backend) [NAK]: ${String(normalized.error ?? 'unknown error')}`,
      );
    } else {
      logLine(
        `Action '${action}' failed (web backend): ${String(normalized.error ?? 'unknown error')}`,
      );
    }
    return normalized;
  } catch (error) {
    const errorText = String(error);
    const backendUnavailable =
      /(failed to fetch|connection refused|econnrefused|err_connection_refused|networkerror|enotfound|backend unavailable)/i.test(
        errorText,
      );
    const deviceTimeoutOrUnreachable =
      /(winerror\s*121|semaphore timeout|connect timeout|response header read timeout|timed?\s*out|timeout)/i.test(
        errorText,
      );
    const writeTimeoutNoAck =
      WRITE_ACTIONS.has(action) && deviceTimeoutOrUnreachable;
    const likelySentButFailed =
      WRITE_ACTIONS.has(action) &&
      !deviceTimeoutOrUnreachable &&
      /(HTTP\s+5\d\d|connection reset|broken pipe|remote end closed connection)/i.test(
        errorText,
      );
    const healthState = backendUnavailable
      ? 'offline'
      : deviceTimeoutOrUnreachable
        ? 'warn'
        : 'warn';

    logLine(`Action '${action}' failed: ${errorText}`);
    if (likelySentButFailed) {
      logLine(
        `Action '${action}' may still be applied on device despite backend response failure.`,
      );
    } else if (writeTimeoutNoAck) {
      logLine(
        `Action '${action}' timed out waiting for ACK; device may still have applied the command.`,
      );
    }
    if (backendUnavailable) {
      logLine(
        `Tip: start web backend with 'py py/web_backend.py' in tauri-app`,
      );
      if (tauriFallbackErrorText) {
        logLine(
          `Tip: tauri bridge error before fallback: ${tauriFallbackErrorText}`,
        );
      }
    } else if (deviceTimeoutOrUnreachable) {
      logLine(
        `Tip: backend is online but device is not reachable in time (check network/VPN route/firewall).`,
      );
    }
    const failed = {
      ok: false,
      action,
      backend: 'web-backend',
      error: errorText,
      nak: detectNak(errorText),
      ack: false,
      healthState,
      backendOnline: !backendUnavailable,
      screenOnline: backendUnavailable ? false : undefined,
      noAck: writeTimeoutNoAck,
      maybeSent: likelySentButFailed,
      tauriError: tauriFallbackErrorText || undefined,
      message: writeTimeoutNoAck
        ? 'Backend online, but no ACK from device (network timeout/unreachable).'
        : likelySentButFailed
          ? 'Sent to device; backend response failed (state may have changed).'
          : backendUnavailable
            ? tauriFallbackErrorText
              ? 'Tauri bridge failed and web backend is unreachable.'
              : 'Backend offline or unreachable.'
            : deviceTimeoutOrUnreachable
              ? 'Backend online, but device timed out/unreachable.'
              : undefined,
    };
    renderOutput(failed);
    return failed;
  }
}

function requireSignageProtocol(actionLabel) {
  if (effectiveProtocol() === 'SIGNAGE_MDC') {
    return null;
  }

  return {
    ok: false,
    error: `${actionLabel} is signage-only. Set Protocol to SIGNAGE_MDC (or AUTO + port 1515).`,
  };
}

async function addCurrentDevice() {
  const payload = readConnection();
  const ip = String(payload.ip || '').trim();
  if (!ip) {
    const error = 'IP is required';
    logLine(`Add device failed: ${error}`);
    return { ok: false, error };
  }

  const exists = savedDevices.some((item) => item.ip === ip);
  if (exists) {
    const error = `${ip} already exists. Select it and use Update.`;
    logLine(`Add device skipped: ${error}`);
    return { ok: false, error };
  }

  try {
    const { list, source } = await upsertSavedDeviceAny({
      ip,
      port: payload.port,
      id: payload.display_id,
      protocol: payload.protocol,
      site: payload.site,
      description: payload.description,
    });
    renderSavedDevices(list, ip);
    logLine(`Added device ${ip} (${source})`);
    return { ok: true, message: `added ${ip}`, ip, source };
  } catch (error) {
    logLine(`Add device failed: ${String(error)}`);
    return { ok: false, error: String(error) };
  }
}

async function saveCurrentDevice() {
  const payload = readConnection();
  if (!selectedSavedDeviceIp) {
    const error =
      'No selected device to update. Use Add Device flow to create a new device.';
    logLine(`Update failed: ${error}`);
    return { ok: false, error };
  }

  const selected = savedDevices.find(
    (item) => item.ip === selectedSavedDeviceIp,
  );
  if (!selected) {
    const error = `Selected device ${selectedSavedDeviceIp} not found.`;
    logLine(`Update failed: ${error}`);
    return { ok: false, error };
  }

  const nextIp = String(payload.ip || '').trim();
  if (!nextIp) {
    const error = 'IP is required';
    logLine(`Update failed: ${error}`);
    return { ok: false, error };
  }

  try {
    if (nextIp !== selectedSavedDeviceIp) {
      await deleteSavedDeviceAny(selectedSavedDeviceIp);
    }

    const { list, source } = await upsertSavedDeviceAny({
      ip: nextIp,
      port: payload.port,
      id: payload.display_id,
      protocol: payload.protocol,
      site: payload.site,
      description: payload.description,
    });
    renderSavedDevices(list, nextIp);
    logLine(
      nextIp === selectedSavedDeviceIp
        ? `Updated device ${selectedSavedDeviceIp} (${source})`
        : `Updated device ${selectedSavedDeviceIp} -> ${nextIp} (${source})`,
    );
    return {
      ok: true,
      message:
        nextIp === selectedSavedDeviceIp
          ? `updated ${selectedSavedDeviceIp}`
          : `updated ${selectedSavedDeviceIp} -> ${nextIp}`,
      ip: nextIp,
      source,
    };
  } catch (error) {
    logLine(`Update device failed: ${String(error)}`);
    return { ok: false, error: String(error) };
  }
}

async function deleteSavedDeviceByIp(ip) {
  const selectedIp = String(ip || '').trim();
  if (!selectedIp) {
    const error = 'No selected device';
    logLine(`Delete skipped: ${error.toLowerCase()}`);
    return { ok: false, error };
  }

  try {
    const { list, source } = await deleteSavedDeviceAny(selectedIp);
    checkedSavedDeviceIps.delete(selectedIp);
    const nextSelectedIp =
      selectedSavedDeviceIp === selectedIp ? '' : selectedSavedDeviceIp;
    renderSavedDevices(list, nextSelectedIp);
    logLine(`Deleted device ${selectedIp} (${source})`);
    return {
      ok: true,
      message: `deleted ${selectedIp}`,
      ip: selectedIp,
      source,
    };
  } catch (error) {
    logLine(`Delete failed: ${String(error)}`);
    return { ok: false, error: String(error) };
  }
}

async function deleteCheckedDevices() {
  const checkedIps = Array.from(checkedSavedDeviceIps);
  if (!checkedIps.length) {
    return { ok: false, error: 'No checked devices' };
  }

  let deletedCount = 0;
  let lastList = savedDevices;
  let lastSource = 'web';

  for (const ip of checkedIps) {
    try {
      const { list, source } = await deleteSavedDeviceAny(ip);
      lastList = list;
      lastSource = source;
      deletedCount += 1;
      checkedSavedDeviceIps.delete(ip);
      if (selectedSavedDeviceIp === ip) {
        selectedSavedDeviceIp = '';
      }
    } catch (error) {
      logLine(`Delete checked failed for ${ip}: ${String(error)}`);
    }
  }

  if (!deletedCount) {
    return { ok: false, error: 'Failed to delete checked devices' };
  }

  const nextSelectedIp = selectedSavedDeviceIp;
  renderSavedDevices(lastList, nextSelectedIp);
  return {
    ok: true,
    message: `deleted ${deletedCount} checked devices`,
    count: deletedCount,
    source: lastSource,
  };
}

function clearCheckedDevices() {
  checkedSavedDeviceIps = new Set();
  persistDeviceSelectionState();
  renderSavedDeviceList(selectedSavedDeviceIp);
  return { ok: true, message: 'cleared selected checkboxes' };
}

async function deleteSelectedDevice() {
  const selectedIp = selectedSavedDeviceIp || $('ip').value.trim();
  return deleteSavedDeviceByIp(selectedIp);
}

function applySelectedDevice(selectedIpOverride) {
  const selectedIp = String(selectedIpOverride ?? selectedSavedDeviceIp).trim();
  if (!selectedIp) {
    selectedSavedDeviceIp = '';
    persistDeviceSelectionState();
    renderSavedDeviceList('');
    logLine('Manual entry mode active');
    return { ok: false, error: 'No selected device' };
  }

  const selected = savedDevices.find((item) => item.ip === selectedIp);
  if (!selected) {
    selectedSavedDeviceIp = '';
    persistDeviceSelectionState();
    renderSavedDeviceList('');
    logLine(`Selected device ${selectedIp} not found`);
    return { ok: false, error: `Selected device ${selectedIp} not found` };
  }

  selectedSavedDeviceIp = selectedIp;
  persistDeviceSelectionState();
  setConnectionFields(selected);
  renderSavedDeviceList(selectedIp);
  logLine(`Applied saved device ${selectedIp}`);
  return { ok: true, message: `applied ${selectedIp}`, ip: selectedIp };
}

async function runAutoProbe() {
  const ip = $('ip').value.trim();
  if (!ip) {
    const error = 'IP is required';
    logLine(`Auto probe failed: ${error}`);
    return { ok: false, error };
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
      return probe;
    } else {
      renderOutput(probe);
      logLine(`Auto probe failed: ${probe.error}`);
      return probe;
    }
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
    return probe;
  } catch (error) {
    logLine(`Auto probe exception: ${String(error)}`);
    logLine(`Tip: start web backend with 'py py/web_backend.py' in tauri-app`);
    return { ok: false, error: String(error) };
  }
}

async function runCliGet() {
  if (effectiveProtocol() !== 'SIGNAGE_MDC') {
    const error =
      'CLI commands are MDC-only. Set Protocol to SIGNAGE_MDC (or AUTO + port 1515).';
    logLine(error);
    return { ok: false, error };
  }

  const command = $('cliCommand').value.trim();
  if (!command) {
    const error = 'CLI GET failed: command is required';
    logLine(error);
    return { ok: false, error };
  }

  const meta = getSelectedCliCommandMeta();
  if (meta && !meta.get) {
    const error = `${command}: this command does not support GET (read).`;
    logLine(error);
    return { ok: false, error };
  }

  const args = parseCliArgs();
  const isTimerIndexed = TIMER_INDEXED_COMMANDS.has(command);
  if (isTimerIndexed && args.length === 0) {
    const error = `${command} GET requires timer_id (1-7). Fill command arguments.`;
    logLine(error);
    return { ok: false, error };
  }

  if (!isTimerIndexed && args.length > 0) {
    const error = `${command}: GET does not accept arguments.`;
    logLine(error);
    return { ok: false, error };
  }

  return await callAction('cli_get', {
    command,
    args,
  });
}

async function runCliSet() {
  if (effectiveProtocol() !== 'SIGNAGE_MDC') {
    const error =
      'CLI commands are MDC-only. Set Protocol to SIGNAGE_MDC (or AUTO + port 1515).';
    logLine(error);
    return { ok: false, error };
  }

  const command = $('cliCommand').value.trim();
  if (!command) {
    const error = 'CLI SET failed: command is required';
    logLine(error);
    return { ok: false, error };
  }

  const meta = getSelectedCliCommandMeta();
  if (meta && !meta.set) {
    const error = `${command}: this command does not support SET (write).`;
    logLine(error);
    return { ok: false, error };
  }

  const args = parseCliArgs();
  if (meta?.fields?.length > 0 && args.length === 0) {
    const requiredFields = meta.fields.map((field) => field.name).join(', ');
    const error = `${command}: SET requires arguments (${requiredFields}).`;
    logLine(error);
    return { ok: false, error };
  }

  if (TIMER_INDEXED_COMMANDS.has(command) && args.length === 0) {
    const error = `${command} SET requires timer_id (1-7) plus values. Fill Arguments first.`;
    logLine(error);
    return { ok: false, error };
  }

  return await callAction('cli_set', {
    command,
    args,
  });
}

async function runSetVolume() {
  const blocked = requireSignageProtocol('Set Volume');
  if (blocked) {
    logLine(blocked.error);
    return blocked;
  }

  return await callAction('set_volume', { value: Number($('volume').value) });
}

async function runSetBrightness() {
  const blocked = requireSignageProtocol('Set Brightness');
  if (blocked) {
    logLine(blocked.error);
    return blocked;
  }

  return await callAction('set_brightness', {
    value: Number($('brightness').value),
  });
}

async function runSetInput() {
  const blocked = requireSignageProtocol('Set Input');
  if (blocked) {
    logLine(blocked.error);
    return blocked;
  }

  const source = $('inputSource').value;
  const validation = validateInputSourceSelection(source);
  if (!validation.ok) {
    logLine(`set_input validation: ${validation.error}`);
    return { ok: false, action: 'set_input', error: validation.error };
  }

  if (validation.warning) {
    logLine(`set_input warning: ${validation.warning}`);
  }

  const result = await callAction('set_input', { source });
  if (validation.warning) {
    return {
      ...result,
      warning: validation.warning,
      message: result.ok
        ? `${result.message || 'completed'}; ${validation.warning}`
        : result.message,
    };
  }

  return result;
}

async function sendConsumerKey() {
  if (effectiveProtocol() !== 'SMART_TV_WS') {
    const error =
      'Consumer key CLI is Smart TV only. Set Protocol to SMART_TV_WS (or AUTO + port 8002/8001).';
    logLine(error);
    return { ok: false, error };
  }

  let repeat = Number($('consumerRepeat').value);
  if (Number.isNaN(repeat) || repeat < 1) {
    repeat = 1;
  }
  if (repeat > 20) {
    repeat = 20;
  }
  $('consumerRepeat').value = String(repeat);

  return await callAction('consumer_key', {
    key: $('consumerKey').value,
    repeat,
  });
}

async function sendHdmiMacro(hdmi) {
  if (effectiveProtocol() !== 'SMART_TV_WS') {
    const error =
      'HDMI macro is Smart TV only. Set Protocol to SMART_TV_WS (or AUTO + port 8002/8001).';
    logLine(error);
    return { ok: false, error };
  }

  return await callAction('hdmi_macro', { hdmi });
}

bindButtonAction('btnStatus', () => callAction('status'));
bindButtonAction('btnTestConnection', runConnectionTest);
bindButtonAction('btnPowerOn', () => callAction('power', { state: 'ON' }));
bindButtonAction('btnPowerOff', () => callAction('power', { state: 'OFF' }));
bindButtonAction('btnReboot', () => callAction('power', { state: 'REBOOT' }));
bindButtonAction('btnSetVolume', runSetVolume);
bindButtonAction('btnSetBrightness', runSetBrightness);
bindButtonAction('btnSetMute', () =>
  callAction('set_mute', { state: $('mute').value }),
);
bindButtonAction('btnSetInput', runSetInput);
bindButtonAction('btnLoadDevices', refreshSavedDevices);
bindButtonAction('btnAddDevice', addCurrentDevice);
bindButtonAction('btnSaveDevice', saveCurrentDevice);
bindButtonAction('btnDeleteDevice', deleteCheckedDevices);
bindButtonAction('btnClearCheckedDevices', clearCheckedDevices);
bindButtonAction('btnAutoProbe', runAutoProbe);
bindButtonAction('btnExportDevices', exportDevicesCsv);
bindButtonAction('btnImportDevices', () => {
  const input = $('deviceCsvInput');
  if (!input) {
    return { ok: false, error: 'CSV file input not found' };
  }
  input.click();
  return { ok: true, message: 'choose a CSV file to import' };
});

$('deviceCsvInput')?.addEventListener('change', async (event) => {
  const input = event.target;
  const result = await importDevicesCsv();
  renderOutput(result);
  if (result.ok) {
    showToast(`Import CSV: ${result.message || 'success'}`, 'success');
  } else {
    showToast(
      `Import CSV: ${stringifyError(result.error || 'failed')}`,
      'error',
    );
  }
  if (input) {
    input.value = '';
  }
});

bindButtonAction('btnCliGet', runCliGet);
bindButtonAction('btnCliSet', runCliSet);
bindButtonAction('btnConsumerKey', sendConsumerKey);
bindButtonAction('btnHdmi1', () => sendHdmiMacro('HDMI1'));
bindButtonAction('btnHdmi2', () => sendHdmiMacro('HDMI2'));
bindButtonAction('btnHdmi3', () => sendHdmiMacro('HDMI3'));
bindButtonAction('btnHdmi4', () => sendHdmiMacro('HDMI4'));
bindButtonAction('btnClearLog', () => clearLog('commandLog'));
bindButtonAction('btnSaveLog', () => saveLog('commandLog', 'command_log'));
bindButtonAction('btnClearLogWs', () => clearLog('commandLogWs'));
bindButtonAction('btnSaveLogWs', () =>
  saveLog('commandLogWs', 'command_log_ws'),
);
$('cliCommand').addEventListener('change', (event) =>
  renderCliArgRows(event.target.value),
);

refreshSavedDevices();
initSmartTvKeys();
loadCliCatalog();
initWorkflowNavigation();
logLine('Dashboard initialized');
