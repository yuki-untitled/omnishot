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
