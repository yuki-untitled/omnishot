// ==========================================================================
// Live Logs（サーバーのログを受け取って表示する）
// ==========================================================================
import { updateGallery } from './gallery.js';
import { escapeHtml } from './util.js';

const elLogConsole = document.getElementById('logConsole');
const MAX_LOG_LINES = 50;
const logMessages = [];

function appendLog(message) {
    logMessages.push(message);
    if (logMessages.length > MAX_LOG_LINES) {
        logMessages.shift();
    }
    if (elLogConsole) {
        // 仕様: docs/spec/bugs/LOCAL-010_ログ表示にHTMLを含む文字列がそのまま解釈される.md
        elLogConsole.innerHTML = logMessages.slice().reverse().map(msg => `<div>${escapeHtml(msg)}</div>`).join('');
    }
}

export function startLogStream() {
    const source = new EventSource('/logs/stream');
    source.onmessage = (event) => {
        appendLog(event.data);
        // 撮影したら、ギャラリーをすぐに更新する
        if (event.data.includes('保存完了') || event.data.includes('撮影完了')) {
            updateGallery();
        }
    };
    source.onerror = () => {
        console.warn('Log stream disconnected; retrying...');
    };
}
