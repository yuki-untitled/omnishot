// ==========================================================================
// 接続確認（接続した端末の準備の状態の表示と、iPhone・Android の準備を進めるボタン）
// 仕様: docs/spec/setup-guide.md
// 「接続確認」ボタンで開き、開いている間、端末の状態を確認して表示する。表示に関する保存データは持たない。
// ==========================================================================
import { escapeHtml, postJson } from './util.js';

const elConnectionModal = document.getElementById('connectionModal');
const elConnectionCheckBtn = document.getElementById('connectionCheckBtn');
const elCloseConnectionBtn = document.getElementById('closeConnectionBtn');
const elIosStatus = document.getElementById('iosStatus');
const elAndroidStatus = document.getElementById('androidStatus');

const POLL_INTERVAL_MS = 2000;
const READY_MESSAGE = '撮影の準備ができています';
let pollTimer = null;
let isPolling = false;
let pollGeneration = 0;
let renderedJson = "";
// 端末ごとの、ボタンを押した結果のメッセージ（次に押すまで表示する）
const actionMessages = {};

const ICONS = { ok: '✅', todo: '⚠️', unknown: '❔' };

function deviceLabel(name, fallback, id) {
    return `${escapeHtml(name || fallback)}（…${escapeHtml(id.slice(-6))}）`;
}

function itemHtml(level, title, detail, buttonHtml) {
    return `<div class="setup-item"><span class="setup-icon">${ICONS[level]}</span>`
        + `<div class="setup-item-body"><b>${title}</b>`
        + (detail ? `<div class="setup-detail">${detail}</div>` : '')
        + (buttonHtml || '')
        + `</div></div>`;
}

// 仕様: docs/spec/setup-guide.md（準備ができた端末の、実行結果のメッセージは消す）
// 「デベロッパモードをオンにしてください」などの案内が、オンにした後も残らないようにする。
function pruneActionMessages(data) {
    data.ios.devices.forEach(device => {
        if (device.trusted && device.developerMode === true) delete actionMessages[device.id];
    });
    data.android.devices.forEach(device => {
        if (device.state === 'device') delete actionMessages[device.id];
    });
}

function messageHtml(id) {
    return actionMessages[id] ? `<div class="setup-message">${escapeHtml(actionMessages[id])}</div>` : '';
}

function deviceHtml(label, itemsHtml, isReady, id) {
    return `<div class="setup-device"><div class="setup-device-name">${label}</div>${itemsHtml}`
        + (isReady ? `<div class="setup-ready">✅ ${READY_MESSAGE}</div>` : '')
        + messageHtml(id) + `</div>`;
}

function iosStatusHtml(ios, isWindows) {
    if (!ios.available) {
        const detail = isWindows
            ? 'iPhone を検出できません。<a href="https://www.apple.com/jp/itunes/" target="_blank" class="setup-link">iTunes</a> をインストールしてください。'
            : 'iPhone との通信を開始できません。';
        return itemHtml('todo', '接続', detail);
    }
    if (ios.devices.length === 0) {
        return itemHtml('todo', '端末が接続されていません', 'USB で iPhone を接続してください。');
    }
    return ios.devices.map(device => {
        const items = [itemHtml('ok', '接続', '')];
        if (device.trusted) {
            items.push(itemHtml('ok', '信頼', ''));
        } else {
            items.push(itemHtml('todo', '信頼', 'iPhone に表示される「このコンピュータを信頼しますか？」で「信頼」を押してください。'));
        }
        if (device.developerMode === true) {
            items.push(itemHtml('ok', 'デベロッパモード', ''));
        } else if (device.developerMode === false) {
            items.push(itemHtml('todo', 'デベロッパモード', 'オフです。設定に項目が見つからないときは、下のボタンで項目を表示できます。',
                `<button type="button" class="setup-button" data-action="ios-devmode" data-id="${escapeHtml(device.id)}">デベロッパモードの項目を表示する</button>`));
        } else {
            items.push(itemHtml('unknown', 'デベロッパモード', '状態を確認できません（「信頼」を済ませると確認できます）。'));
        }
        const isReady = device.trusted && device.developerMode === true;
        return deviceHtml(deviceLabel(device.name, 'iPhone', device.id), items.join(''), isReady, device.id);
    }).join('');
}

function androidStatusHtml(android) {
    if (android.devices.length === 0) {
        return itemHtml('todo', '端末が接続されていません',
            'USB で Android 端末を接続してください。接続しても表示されないときは、端末の「開発者オプション」で「USBデバッグ」がオンか確認してください（「手順を見る」）。');
    }
    return android.devices.map(device => {
        const items = [itemHtml('ok', '接続と USB デバッグ', '')];
        if (device.state === 'device') {
            items.push(itemHtml('ok', '許可', ''));
        } else if (device.state === 'unauthorized') {
            items.push(itemHtml('todo', '許可', '端末の画面の「USBデバッグを許可しますか？」で「許可」を押してください。表示されないときは、下のボタンで表示し直せます。',
                `<button type="button" class="setup-button" data-action="android-auth" data-id="${escapeHtml(device.id)}">許可を要求する</button>`));
        } else {
            items.push(itemHtml('todo', '許可', escapeHtml(device.hint || '')));
        }
        return deviceHtml(deviceLabel(device.name, 'Android端末', device.id), items.join(''), device.state === 'device', device.id);
    }).join('');
}

function renderStatus(data) {
    pruneActionMessages(data);
    const json = JSON.stringify([data, actionMessages]);
    if (json === renderedJson) return;
    renderedJson = json;
    elIosStatus.innerHTML = iosStatusHtml(data.ios, data.windows);
    elAndroidStatus.innerHTML = androidStatusHtml(data.android);
}

// 開始し直したときに、前の確認の続きが二重に動かないよう、世代番号で見分ける
function pollStatus(generation) {
    fetch('/setup_status')
        .then(res => res.json())
        .then(data => { if (generation === pollGeneration) renderStatus(data); })
        .catch(err => console.error("Setup status error:", err))
        .finally(() => {
            // ガイドが閉じられていたら、確認をやめる
            if (isPolling && generation === pollGeneration) {
                pollTimer = setTimeout(() => pollStatus(generation), POLL_INTERVAL_MS);
            }
        });
}

function startPolling() {
    if (isPolling) return;
    isPolling = true;
    pollGeneration += 1;
    renderedJson = "";
    pollStatus(pollGeneration);
}

function stopPolling() {
    isPolling = false;
    pollGeneration += 1;
    clearTimeout(pollTimer);
}

async function postSetupAction(url, body) {
    const res = await postJson(url, body);
    return res.json();
}

async function enableIosDeveloperMode(udid) {
    if (!confirm('iPhone の設定に「デベロッパモード」の項目を表示します。\n\n'
        + 'パスコードを設定していない iPhone は、デベロッパモードがオンになり、iPhone が自動で再起動します。\n\n実行しますか？')) return;
    const data = await postSetupAction('/setup/ios_developer_mode', { udid });
    if (data.result === 'revealed') {
        actionMessages[udid] = 'iPhone の「設定」＞「プライバシーとセキュリティ」の一番下の「デベロッパモード」をオンにして、再起動してください。';
    } else if (data.result === 'enabled') {
        actionMessages[udid] = 'iPhone が再起動します。再起動後、表示される「オンにする」を押してください。';
    } else {
        actionMessages[udid] = `実行できませんでした: ${data.message || '理由を取得できませんでした。'}`;
    }
}

async function requestAndroidAuthorization(serial) {
    if (!confirm('端末に「USBデバッグを許可しますか？」を表示し直すために、adb サーバーを起動し直します。\n\n'
        + 'Android Studio など、ほかのツールが adb サーバーを使っている場合は、端末との接続が一時的に切れます。\n\n実行しますか？')) return;
    const data = await postSetupAction('/setup/android_authorization', {});
    actionMessages[serial] = data.result === 'requested'
        ? '端末の画面で「許可」を押してください（「常に許可する」にチェックを入れると、次回から表示されません）。'
        : (data.message || 'adb サーバーを起動し直せませんでした。');
}

function onStatusClick(e) {
    const button = e.target.closest('.setup-button');
    if (!button) return;
    const { action, id } = button.dataset;
    const run = action === 'ios-devmode' ? enableIosDeveloperMode(id) : requestAndroidAuthorization(id);
    run.catch(err => {
        console.error("Setup action error:", err);
        actionMessages[id] = '実行できませんでした。';
    }).finally(() => {
        // 次の確認を待たず、結果をすぐ表示する
        if (isPolling) { stopPolling(); startPolling(); }
    });
}

function showTab(os) {
    const isIos = os === 'ios';
    elTabIosBtn.classList.toggle('active', isIos);
    elTabAndroidBtn.classList.toggle('active', !isIos);
    elGuideIos.style.display = isIos ? 'block' : 'none';
    elGuideAndroid.style.display = isIos ? 'none' : 'block';
}

export function initConnectionCheck() {
    elConnectionCheckBtn.addEventListener('click', () => {
        elConnectionModal.style.display = 'flex';
        startPolling();
    });
    elCloseConnectionBtn.addEventListener('click', () => {
        elConnectionModal.style.display = 'none';
        stopPolling();
    });
    elIosStatus.addEventListener('click', onStatusClick);
    elAndroidStatus.addEventListener('click', onStatusClick);
}
