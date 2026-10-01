// JSONをPOSTする共通ヘルパー
export function postJson(url, body) {
    return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
}

// HTMLエスケープヘルパー
export function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// 保存した画像のURL
export function captureUrl(filename) {
    return `/static/captures/${encodeURIComponent(filename)}`;
}

// リンクをクリックしたことにしてダウンロードする
export function downloadFrom(href, filename) {
    const link = document.createElement('a');
    link.style.display = 'none';
    link.href = href;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// "YYYYMMDD_HHMMSS"
export function timestampString(date) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

// 仕様: docs/spec/capture-metadata.md（取得できなかった撮影情報の項目の表示）
export const UNKNOWN_INFO = '不明';

const OS_LABELS = { ios: 'iOS', android: 'Android' };

// "iOS 17.5.1"（版が取得できなかったときは "iOS 不明"）
export function osLabel(info) {
    return `${OS_LABELS[info.os] || info.os} ${info.osVersion || UNKNOWN_INFO}`;
}
