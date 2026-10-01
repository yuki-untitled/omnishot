// ==========================================================================
// アップデート通知（起動時に確認した結果、新しい版があれば画面上部に表示する）
// 仕様: docs/spec/update-notification.md
// ==========================================================================
import { postJson } from './util.js';

const elBanner = document.getElementById('updateBanner');
const elMessage = document.getElementById('updateMessage');
const elOpenBtn = document.getElementById('updateOpenBtn');
const elCloseBtn = document.getElementById('updateCloseBtn');

// サーバーの確認は別のスレッドで行うため、確認中は結果が出るまで間隔を空けて問い合わせる
const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 10;

function showUpdate(info) {
    elMessage.textContent = `新しい版 ${info.latest} があります（現在 ${info.current}）`;
    elBanner.style.display = 'flex';
}

function checkUpdate(pollCount) {
    fetch('/update_info')
        .then(res => res.json())
        .then(info => {
            if (info.status === 'available') {
                showUpdate(info);
            } else if (info.status === 'checking' && pollCount < MAX_POLLS) {
                setTimeout(() => checkUpdate(pollCount + 1), POLL_INTERVAL_MS);
            }
        })
        // 確認に失敗しても何も表示しない
        .catch(() => {});
}

export function initUpdateNotice() {
    elOpenBtn.addEventListener('click', () => postJson('/update_info/open', {}));
    elCloseBtn.addEventListener('click', () => {
        elBanner.style.display = 'none';
        postJson('/update_info/dismiss', {});
    });
    checkUpdate(0);
}
