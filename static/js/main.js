// ==========================================================================
// 画面の初期化
// ==========================================================================
import { initCapture, updateModeDisplay } from './capture.js';
import { initConnectionCheck } from './connection.js';
import { initDevices, loadDevices } from './devices.js';
import { initGallery, updateGallery } from './gallery.js';
import { startLogStream } from './logs.js';
import { initPreview, openPreview } from './preview.js';

const elShutdownBtn = document.getElementById('shutdownBtn');

// アプリ終了ボタン
function shutdownApp() {
    if (!confirm("アプリケーションを終了しますか？\n（サーバーが停止し、この画面は使えなくなります）")) return;
    fetch('/shutdown', { method: 'POST' })
        .then(() => {
            // 仕様: docs/spec/bugs/LOCAL-011_アプリ終了時のメッセージがブラウザのタブ前提のまま.md
            alert("アプリケーションを終了しました。");
            window.close();
        })
        .catch(err => console.error("Shutdown error:", err));
}

initCapture();
initDevices();
initGallery({ onOpenPreview: openPreview });
initPreview();
initConnectionCheck();
elShutdownBtn.addEventListener('click', shutdownApp);

updateModeDisplay();
updateGallery();
startLogStream();
loadDevices();
