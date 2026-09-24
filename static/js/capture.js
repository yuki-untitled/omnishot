// ==========================================================================
// 撮影（設定・自動撮影・手動撮影・状態の監視）
// 仕様: docs/spec/screenshot-capture.md
// ==========================================================================
import { confirmDeviceSelected, loadDevices, selectedDeviceId, updateDeviceControls } from './devices.js';
import { updateGallery } from './gallery.js';
import { ui } from './state.js';

const elStartBtn = document.getElementById('startBtn');
const elStopBtn = document.getElementById('stopBtn');
const elManualCaptureBtn = document.getElementById('manualCaptureBtn');
const elStatus = document.getElementById('status');
const elCheckInterval = document.getElementById('checkInterval');
const elSettlingTime = document.getElementById('settlingTime');
const elJudgeCount = document.getElementById('judgeCount');
const elModeSelect = document.getElementById('modeSelect');
const elStaticLabel = document.getElementById('staticLabel');
const elDynamicLabel = document.getElementById('dynamicLabel');

const STATUS_POLL_INTERVAL_MS = 2000;

// 撮影ステータス表示の切り替え
function setStatus(capturing) {
    ui.isCapturing = capturing;
    elStatus.innerText = capturing ? "Status: Capturing..." : "Status: Idle";
    elStatus.style.color = capturing ? "#2ecc71" : "#888";
    updateDeviceControls();
}

// ==========================================================================
// 設定（数値を範囲内に収めて、サーバーに送る）
// ==========================================================================
function clampInput(el, parse, fallback, min, max) {
    const value = Math.max(min, Math.min(max, parse(el.value) || fallback));
    el.value = value;
    return value;
}

function getClampedSettings() {
    const interval = clampInput(elCheckInterval, parseFloat, 0.5, 0.1, 30);
    const settling = clampInput(elSettlingTime, parseFloat, 1.0, 0.1, 30);
    const judgeCount = clampInput(elJudgeCount, parseInt, 3, 1, 10);
    const mode = elModeSelect.value;
    // 動的モードでは、チェック間隔 × 判定回数 を静止待ち時間として送る
    const finalSettling = mode === 'static' ? settling : interval * judgeCount;
    return { interval, finalSettling, mode };
}

function settingsQuery() {
    const { interval, finalSettling, mode } = getClampedSettings();
    return `interval=${interval}&settling=${finalSettling}&mode=${mode}`;
}

function sendSettings() {
    fetch(`/update_settings?${settingsQuery()}`);
}

// モード選択に連動した設定欄のトグル制御
export function updateModeDisplay() {
    const isStatic = elModeSelect.value === 'static';
    if (elStaticLabel) elStaticLabel.style.display = isStatic ? 'inline' : 'none';
    if (elDynamicLabel) elDynamicLabel.style.display = isStatic ? 'none' : 'inline';
}

// ==========================================================================
// 操作
// ==========================================================================
function startAutoCapture() {
    if (!confirmDeviceSelected()) return;
    fetch(`/start?${settingsQuery()}&device=${encodeURIComponent(selectedDeviceId())}`)
        .then(() => setStatus(true));
}

function stopAutoCapture() {
    fetch('/stop')
        .then(() => setStatus(false));
}

// 仕様: docs/spec/manual-capture.md
// 2台以上で未選択なら画面側で止め、選択した端末が未接続かどうかはサーバー側（dev_manager.resolve_device）で判定する。
// 処理中はボタンを無効化し、連打による多重保存を防ぐ。
function manualCapture() {
    if (!confirmDeviceSelected()) return;
    ui.isManualCapturing = true;
    updateDeviceControls();
    fetch(`/manual_capture?device=${encodeURIComponent(selectedDeviceId())}`, { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                alert(data.error);
                // 仕様: docs/spec/device-selection.md（選択した端末が接続されていないときは、一覧を検出し直す）
                if (data.device_missing) loadDevices();
            } else {
                updateGallery();
            }
        })
        .catch(err => console.error("Manual capture error:", err))
        .finally(() => {
            ui.isManualCapturing = false;
            updateDeviceControls();
        });
}

// サーバー側で自動撮影が止まったら（切断・エラーなど）、画面の状態を合わせて理由を表示する
function pollStatus() {
    fetch('/status')
        .then(res => res.json())
        .then(data => {
            if (!ui.isCapturing || data.is_running) return;
            setStatus(false);
            // エラー理由があればそれを表示、なければ標準メッセージ
            alert(data.error ? `${data.error}` : "自動撮影を停止しました。");
            // 仕様: docs/spec/device-selection.md（選択した端末が接続されていないときは、一覧を検出し直す）
            if (data.device_missing) loadDevices();
        })
        .catch(err => console.error("Status check failed:", err));
}

export function initCapture() {
    setInterval(pollStatus, STATUS_POLL_INTERVAL_MS);

    elStartBtn.addEventListener('click', startAutoCapture);
    elStopBtn.addEventListener('click', stopAutoCapture);
    elManualCaptureBtn.addEventListener('click', manualCapture);

    // 各設定入力欄のリアルタイム同期
    elCheckInterval.addEventListener('input', sendSettings);
    elSettlingTime.addEventListener('input', sendSettings);
    elJudgeCount.addEventListener('input', sendSettings);
    elModeSelect.addEventListener('change', () => {
        updateModeDisplay();
        sendSettings();
    });
}
