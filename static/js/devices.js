// ==========================================================================
// 撮影端末の選択
// 仕様: docs/spec/device-selection.md
// 選択状態は保存しない（画面上のプルダウンの値のみ）。
// ==========================================================================
import { ui } from './state.js';

const elDeviceSelect = document.getElementById('deviceSelect');
const elRefreshDevicesBtn = document.getElementById('refreshDevicesBtn');
const elManualCaptureBtn = document.getElementById('manualCaptureBtn');
const elStartBtn = document.getElementById('startBtn');

const DEVICE_OS_GROUPS = [
    { os: 'ios', label: 'iOS' },
    { os: 'android', label: 'Android' },
];

export function selectedDeviceId() {
    return elDeviceSelect.value;
}

// 「OS・端末名・識別子の末尾6文字」。識別子は、機種ごとに共通になりやすい先頭ではなく末尾を使う
function deviceLabel(device) {
    const osLabel = device.os === 'ios' ? 'iOS' : 'Android';
    const shortId = device.id.slice(-6);
    return device.name ? `${osLabel}・${device.name}・${shortId}` : `${osLabel}・${shortId}`;
}

// 撮影中・検出中は、端末の選択と更新を操作できない
export function updateDeviceControls() {
    const disabled = ui.isCapturing || ui.isLoadingDevices;
    elDeviceSelect.disabled = disabled;
    elRefreshDevicesBtn.disabled = disabled;

    // 仕様: docs/spec/bugs/LOCAL-023_端末が見つかりませんの表示中に撮影できてしまう.md
    // 「端末が見つかりません」「検出中...」の間は、手動撮影・自動撮影を押せない
    const noDevice = ui.isLoadingDevices || ui.devices.length === 0;
    elManualCaptureBtn.disabled = noDevice || ui.isManualCapturing;
    elStartBtn.disabled = noDevice;
}

// 仕様: docs/spec/device-selection.md（2台以上で未選択のときは撮影しない）
export function confirmDeviceSelected() {
    if (ui.devices.length >= 2 && !elDeviceSelect.value) {
        alert("撮影する端末を選択してください");
        return false;
    }
    return true;
}

function createOption(value, text) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = text;
    return option;
}

function renderDevices(previousId) {
    const devices = ui.devices;
    elDeviceSelect.innerHTML = '';

    if (devices.length === 0) {
        elDeviceSelect.appendChild(createOption('', '端末が見つかりません'));
        elDeviceSelect.value = '';
        return;
    }
    if (devices.length === 1) {
        elDeviceSelect.appendChild(createOption(devices[0].id, deviceLabel(devices[0])));
    } else {
        // 2台以上は OS ごとに見出しを付けてまとめる。端末が無い OS の見出しは出さない
        elDeviceSelect.appendChild(createOption('', '端末を選択してください'));
        DEVICE_OS_GROUPS.forEach(({ os, label }) => {
            const inGroup = devices.filter(device => device.os === os);
            if (inGroup.length === 0) return;
            const group = document.createElement('optgroup');
            group.label = `-- ${label} --`;
            inGroup.forEach(device => group.appendChild(createOption(device.id, deviceLabel(device))));
            elDeviceSelect.appendChild(group);
        });
    }

    // 1台なら自動で選ぶ。2台以上は、更新前の選択が一覧に残っていれば維持し、無ければ未選択にする
    const keep = devices.some(device => device.id === previousId) ? previousId : '';
    elDeviceSelect.value = devices.length === 1 ? devices[0].id : keep;
}

export function loadDevices() {
    const previousId = elDeviceSelect.value;
    ui.isLoadingDevices = true;
    updateDeviceControls();
    elDeviceSelect.innerHTML = '<option value="">検出中...</option>';

    return fetch('/devices')
        .then(res => res.json())
        .then(list => {
            ui.devices = list;
            renderDevices(previousId);
        })
        .catch(err => {
            console.error("Device list error:", err);
            ui.devices = [];
            renderDevices('');
        })
        .finally(() => {
            ui.isLoadingDevices = false;
            updateDeviceControls();
        });
}

export function initDevices() {
    elRefreshDevicesBtn.addEventListener('click', loadDevices);
}
