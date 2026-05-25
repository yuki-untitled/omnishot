let currentImagesJson = "";
let logMessages = [];

// --- ボタン操作 ---
document.getElementById('startBtn').addEventListener('click', () => {
    const prefix = document.getElementById('prefix').value;
    const interval = document.getElementById('checkInterval').value;
    const mode = document.getElementById('modeSelect').value;
    
    let settling;
    if (mode === 'static') {
        settling = document.getElementById('settlingTime').value;
    } else {
        // 動的モード時は判定回数から秒数を計算
        const judgeCount = document.getElementById('judgeCount').value;
        settling = parseFloat(interval) * parseInt(judgeCount);
    }

    fetch(`/start?prefix=${encodeURIComponent(prefix)}&interval=${interval}&settling=${settling}&mode=${mode}`)
        .then(() => {
            document.getElementById('status').innerText = "Status: Capturing...";
            document.getElementById('status').style.color = "#2ecc71";
        });
});

document.getElementById('stopBtn').addEventListener('click', () => {
    fetch('/stop')
        .then(() => {
            document.getElementById('status').innerText = "Status: Idle";
            document.getElementById('status').style.color = "#888";
        });
});

let selectedFiles = new Set();
let allImages = [];
let currentPreviewIndex = 0;

// ギャラリー更新ロジック
function updateGallery() {
    fetch('/images')
        .then(res => res.json())
        .then(data => {
            const newJson = JSON.stringify(data);
            if (newJson !== currentImagesJson) {
                currentImagesJson = newJson;
                allImages = data; // プレビュー用に保存
                const gallery = document.getElementById('gallery');
                gallery.innerHTML = data.map(img => `
                    <div class="card ${selectedFiles.has(img) ? 'selected' : ''}" data-filename="${img}">
                        <input type="checkbox" class="select-checkbox" 
                            ${selectedFiles.has(img) ? 'checked' : ''} 
                            onclick="toggleSelect('${img}')">
                        <img src="/static/captures/${img}?t=${new Date().getTime()}" onclick="openPreview('${img}')" style="cursor: pointer;">
                        <div class="card-info">${img}</div>
                    </div>
                `).join('');
            }
            setTimeout(updateGallery, 1500);
        });
}

// プレビューモーダル関連
function openPreview(filename) {
    currentPreviewIndex = allImages.indexOf(filename);
    showPreview();
}

function showPreview() {
    if (allImages.length === 0) return;
    
    const img = allImages[currentPreviewIndex];
    const modal = document.getElementById('previewModal');
    const previewImg = document.getElementById('previewImage');
    const previewInfo = document.getElementById('previewInfo');
    
    previewImg.src = `/static/captures/${img}?t=${new Date().getTime()}`;
    previewInfo.innerText = `${currentPreviewIndex + 1} / ${allImages.length} - ${img}`;
    modal.style.display = 'flex';
}

function closePreview() {
    document.getElementById('previewModal').style.display = 'none';
}

function prevImage() {
    if (currentPreviewIndex > 0) {
        currentPreviewIndex--;
        showPreview();
    }
}

function nextImage() {
    if (currentPreviewIndex < allImages.length - 1) {
        currentPreviewIndex++;
        showPreview();
    }
}

// モーダルボタンイベント
document.getElementById('closeModalBtn').addEventListener('click', closePreview);
document.getElementById('prevBtn').addEventListener('click', prevImage);
document.getElementById('nextBtn').addEventListener('click', nextImage);

// ESCキーで閉じる
document.addEventListener('keydown', (e) => {
    const modal = document.getElementById('previewModal');
    if (modal.style.display === 'flex') {
        if (e.key === 'Escape') closePreview();
        if (e.key === 'ArrowLeft') prevImage();
        if (e.key === 'ArrowRight') nextImage();
    }
});

// モーダル背景クリックで閉じる
document.getElementById('previewModal').addEventListener('click', (e) => {
    if (e.target.id === 'previewModal') closePreview();
});

// 選択状態の切り替え
window.toggleSelect = function(filename) {
    if (selectedFiles.has(filename)) {
        selectedFiles.delete(filename);
    } else {
        selectedFiles.add(filename);
    }
    updateUI();
};

// 共通のUI更新関数
function updateUI() {
    const count = selectedFiles.size;
    
    const deselectBtn = document.getElementById('deselectAllBtn');
    const delBtn = document.getElementById('deleteSelectedBtn');
    const dlBtn = document.getElementById('downloadBtn');
    
    document.getElementById('selectCount').innerText = count;
    document.getElementById('downloadCount').innerText = count;
    
    const display = count > 0 ? 'inline-block' : 'none';
    deselectBtn.style.display = display;
    delBtn.style.display = display;
    dlBtn.style.display = display;
}

// 全選択ボタン
document.getElementById('selectAllBtn').addEventListener('click', () => {
    if (allImages.length === 0) return;
    
    allImages.forEach(img => selectedFiles.add(img));
    updateUI();
    refreshGalleryUI();
});

// 選択解除ボタン
document.getElementById('deselectAllBtn').addEventListener('click', () => {
    selectedFiles.clear();
    updateUI();
    refreshGalleryUI();
});

// ギャラリーUI更新関数
function refreshGalleryUI() {
    const gallery = document.getElementById('gallery');
    gallery.innerHTML = allImages.map(img => `
        <div class="card ${selectedFiles.has(img) ? 'selected' : ''}" data-filename="${img}">
            <input type="checkbox" class="select-checkbox" 
                ${selectedFiles.has(img) ? 'checked' : ''} 
                onclick="toggleSelect('${img}')">
            <img src="/static/captures/${img}?t=${new Date().getTime()}" onclick="openPreview('${img}')" style="cursor: pointer;">
            <div class="card-info">${img}</div>
        </div>
    `).join('');
}

// 選択削除ボタン
document.getElementById('deleteSelectedBtn').addEventListener('click', () => {
    if (selectedFiles.size === 0) return;
    
    const message = selectedFiles.size === allImages.length 
        ? `${selectedFiles.size}件の全ての画像を削除しますか？`
        : `${selectedFiles.size}件の画像を削除しますか？`;
    
    if (confirm(message)) {
        fetch('/delete_selected', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filenames: Array.from(selectedFiles) })
        }).then(() => {
            selectedFiles.clear();
            updateUI();
        });
    }
});

// ダウンロードボタンのイベント
document.getElementById('downloadBtn').addEventListener('click', () => {
    if (selectedFiles.size === 0) return;

    fetch('/download_selected', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filenames: Array.from(selectedFiles) })
    })
    .then(res => res.blob())
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = `manual_assets_${new Date().getTime()}.zip`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
    })
    .catch(err => console.error("Download error:", err));
});

// --- ログストリーム ---
function appendLog(message) {
    logMessages.push(message);
    if (logMessages.length > 50) {
        logMessages.shift();
    }
    const logConsole = document.getElementById('logConsole');
    if (logConsole) {
        logConsole.innerHTML = logMessages.slice().reverse().map(msg => `<div>${msg}</div>`).join('');
    }
}

function startLogStream() {
    const source = new EventSource('/logs/stream');
    source.onmessage = (event) => {
        appendLog(event.data);
        if (event.data.includes('保存完了') || event.data.includes('撮影完了')) {
            updateGallery();
        }
    };
    source.onerror = () => {
        // ブラウザのEventSourceは自動リコネクトするので、ここでは特に何もしない。
        console.warn('Log stream disconnected; retrying...');
    };
}

// 設定が変更されたら即座にサーバーへ送る関数
function sendSettings() {
    const prefix = document.getElementById('prefix').value;
    const interval = document.getElementById('checkInterval').value;
    const mode = document.getElementById('modeSelect').value;
    
    let settling;
    if (mode === 'static') {
        settling = document.getElementById('settlingTime').value;
    } else {
        const judgeCount = document.getElementById('judgeCount').value;
        settling = parseFloat(interval) * parseInt(judgeCount);
    }

    fetch(`/update_settings?prefix=${encodeURIComponent(prefix)}&interval=${interval}&settling=${settling}&mode=${mode}`);
}

// 各入力欄のイベント監視
document.getElementById('prefix').addEventListener('input', sendSettings);
document.getElementById('checkInterval').addEventListener('input', sendSettings);
document.getElementById('settlingTime').addEventListener('input', sendSettings);
document.getElementById('judgeCount').addEventListener('input', sendSettings);
document.getElementById('modeSelect').addEventListener('change', () => {
    updateModeDisplay();
    sendSettings();
});

// モード変更時の表示切り替え
function updateModeDisplay() {
    const mode = document.getElementById('modeSelect').value;
    const staticLabel = document.getElementById('staticLabel');
    const dynamicLabel = document.getElementById('dynamicLabel');
    
    if (mode === 'static') {
        if (staticLabel) staticLabel.style.display = 'inline';
        if (dynamicLabel) dynamicLabel.style.display = 'none';
    } else {
        if (staticLabel) staticLabel.style.display = 'none';
        if (dynamicLabel) dynamicLabel.style.display = 'inline';
    }
}

// --- 初回セットアップガイドの制御 ---
const guideModal = document.getElementById('guideModal');
const tabAndroidBtn = document.getElementById('tabAndroidBtn');
const tabIosBtn = document.getElementById('tabIosBtn');
const guideAndroid = document.getElementById('guideAndroid');
const guideIos = document.getElementById('guideIos');

// アプリ起動時に「非表示フラグ」がなければモーダルを出す
window.addEventListener('DOMContentLoaded', () => {
    const isSkipped = localStorage.getItem('skipSetupGuide');
    if (!isSkipped) {
        if (guideModal) guideModal.style.display = 'flex';
    }
});

// 【追加】ヘッダー右端の「❓ 設定ガイド」ボタンを押したときの処理
document.getElementById('openGuideBtn').addEventListener('click', () => {
    if (guideModal) guideModal.style.display = 'flex';
});

// アプリ終了ボタンの処理
function shutdownApp() {
    if (confirm("アプリケーションを終了しますか？\n（サーバーが停止し、この画面は使えなくなります）")) {
        fetch('/shutdown', { method: 'POST' })
            .then(response => {
                alert("アプリケーションを終了しました。このタブを閉じてもらって大丈夫です。");
                window.close(); // ブラウザのタブを閉じる試み
            })
            .catch(err => console.error("Shutdown error:", err));
    }
}

// タブ切り替え: Androidを選択した時
tabAndroidBtn.addEventListener('click', () => {
    tabAndroidBtn.style.background = '#2ecc71';
    tabIosBtn.style.background = '#555'; 
    guideAndroid.style.display = 'block';
    guideIos.style.display = 'none';
});

// タブ切り替え: iOSを選択した時
tabIosBtn.addEventListener('click', () => {
    tabAndroidBtn.style.background = '#555';
    tabIosBtn.style.background = '#2ecc71';
    guideAndroid.style.display = 'none';
    guideIos.style.display = 'block';
});

// 閉じるボタン（チェックが付いていたらローカルストレージに保存）
document.getElementById('closeGuideBtn').addEventListener('click', () => {
    if (document.getElementById('skipGuideCheck').checked) {
        localStorage.setItem('skipSetupGuide', 'true');
    }
    guideModal.style.display = 'none';
});

// 初期化実行
updateModeDisplay();
updateGallery();
startLogStream();