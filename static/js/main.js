let currentImagesJson = "";
let logMessages = [];

// --- ボタン操作 ---
document.getElementById('startBtn').addEventListener('click', () => {
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

    // prefix入力欄を廃止したため、サーバーへは prefix を送らない
    fetch(`/start?interval=${interval}&settling=${settling}&mode=${mode}`)
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
let displayNames = {};
try {
    const stored = localStorage.getItem('displayNames');
    if (stored) displayNames = JSON.parse(stored);
} catch (e) {
    console.warn('Failed to load displayNames from localStorage', e);
}

// ギャラリー更新ロジック
function updateGallery() {
    fetch('/images')
        .then(res => res.json())
        .then(data => {
            // 💡 サーバーから届いたデータを、選択されている並び順にソートする
            const sortOrder = document.getElementById('sortSelect').value;
            data.sort((a, b) => {
                return sortOrder === 'desc' ? b.localeCompare(a) : a.localeCompare(b);
            });

            const newJson = JSON.stringify(data);
            if (currentImagesJson === "" || newJson !== currentImagesJson) {
                currentImagesJson = newJson;
                allImages = data;

                const gallery = document.getElementById('gallery');
                if (gallery) {
                    gallery.innerHTML = data.map(img => {
                        const displayName = displayNames[img] || img.replace(/\.png$/i, '');
                        
                        return `
                            <div class="card ${selectedFiles.has(img) ? 'selected' : ''}" data-filename="${img}">
                                <input type="checkbox" class="select-checkbox" 
                                    ${selectedFiles.has(img) ? 'checked' : ''} 
                                    onclick="toggleSelect('${img}')">
                                <img src="/static/captures/${img}?t=${new Date().getTime()}" onclick="openPreview('${img}')" style="cursor: pointer;">
                                <div class="card-info">
                                    <span class="display-name" data-filename="${img}">${escapeHtml(displayName)}</span>
                                </div>
                            </div>
                        `;
                    }).join('');
                }
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
    if (!gallery) return;

    // 💡 全選択解除などの際にも、現在の並び順を維持して再描画する
    const sortOrder = document.getElementById('sortSelect').value;
    allImages.sort((a, b) => {
        return sortOrder === 'desc' ? b.localeCompare(a) : a.localeCompare(b);
    });

    gallery.innerHTML = allImages.map(img => {
        const displayName = displayNames[img] || img.replace(/\.png$/i, '');

        return `
            <div class="card ${selectedFiles.has(img) ? 'selected' : ''}" data-filename="${img}">
                <input type="checkbox" class="select-checkbox" 
                    ${selectedFiles.has(img) ? 'checked' : ''} 
                    onclick="toggleSelect('${img}')">
                <img src="/static/captures/${img}?t=${new Date().getTime()}" onclick="openPreview('${img}')" style="cursor: pointer;">
                <div class="card-info">
                    <span class="display-name" data-filename="${img}">${escapeHtml(displayName)}</span>
                </div>
            </div>
        `;
    }).join('');
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
    // ダウンロード時にZIP名をユーザーに入力してもらう
    const defaultName = `manual_assets_${new Date().getTime()}`;
    const inputName = prompt('保存するZIPファイル名を入力してください（拡張子 .zip は不要）', defaultName);
    if (inputName === null) return; // キャンセル時は中断
    const zipFilename = inputName.trim() === '' ? defaultName + '.zip' : (inputName.endsWith('.zip') ? inputName : inputName + '.zip');

    // 選択ファイルを内部ファイル名の降順でソートし、新しい順でZIPに含める
    const selectedArray = Array.from(selectedFiles).sort((a, b) => b.localeCompare(a, undefined, { numeric: true, sensitivity: 'base' }));
    const nameMap = selectedArray.map(file => {
        const displayBase = displayNames[file] ? displayNames[file].replace(/\.png$/i, '') : file.replace(/\.png$/i, '');
        return { file, outputName: `${displayBase}.png` };
    });

    fetch('/download_selected', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filenames: selectedArray, zipName: zipFilename, nameMap })
    })
    .then(res => res.blob())
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = zipFilename;
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
    const interval = document.getElementById('checkInterval').value;
    const mode = document.getElementById('modeSelect').value;
    
    let settling;
    if (mode === 'static') {
        settling = document.getElementById('settlingTime').value;
    } else {
        const judgeCount = document.getElementById('judgeCount').value;
        settling = parseFloat(interval) * parseInt(judgeCount);
    }

    fetch(`/update_settings?interval=${interval}&settling=${settling}&mode=${mode}`);
}

// 各入力欄のイベント監視
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

// クリックで表示名を編集できるようにする（イベントデリゲーション）
document.addEventListener('click', (e) => {
    const target = e.target;
    if (target && target.classList && target.classList.contains('display-name')) {
        const filename = target.getAttribute('data-filename');
        startEditDisplayName(target, filename);
    }
});

function startEditDisplayName(spanEl, filename) {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'edit-name-input';
    
    // 現在の表示名（拡張子なし）を初期値にする
    const currentBase = (displayNames[filename] || filename).replace(/\.png$/i, '');
    input.value = currentBase;
    input.style.width = '100%';
    spanEl.replaceWith(input);
    input.focus();
    input.setSelectionRange(currentBase.length, currentBase.length);

    let isFinished = false;
    let isComposing = false;

    input.addEventListener('compositionstart', () => { isComposing = true; });
    input.addEventListener('compositionend', () => { isComposing = false; });

    function finish(save) {
        if (isFinished) return;
        isFinished = true;

        if (save) {
            let userInput = input.value.trim();
            const oldDisplay = displayNames[filename] || filename.replace(/\.png$/i, '');

            if (!userInput) {
                // 空白（空欄）にされた場合は表示名マップから消去
                delete displayNames[filename];
                
                // 💡 サーバーにリセットログを通知
                fetch('/rename', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ oldDisplay: oldDisplay, newDisplay: '' })
                });
            } else {
                const cleanInputBase = userInput.replace(/\.png$/i, '');
                
                // 変更がなければ何もしない
                if (cleanInputBase === currentBase) {
                    revertSpan();
                    return;
                }
                
                // 表示名マップに保存
                displayNames[filename] = cleanInputBase;

                // 💡 サーバーに変更ログを通知
                fetch('/rename', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ oldDisplay: oldDisplay, newDisplay: cleanInputBase })
                });
            }

            // ローカルストレージに保存
            try { localStorage.setItem('displayNames', JSON.stringify(displayNames)); } catch(e){}

            // UIを即座にリフレッシュ
            refreshGalleryUI();
        } else {
            revertSpan();
        }
    }

    function revertSpan() {
        const span = document.createElement('span');
        span.className = 'display-name';
        span.setAttribute('data-filename', filename);
        span.innerText = displayNames[filename] || filename.replace(/\.png$/i, '');
        input.replaceWith(span);
        isFinished = false;
    }

    input.addEventListener('blur', () => {
        if (!isComposing) finish(true);
    });

    input.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') {
            if (isComposing) return;
            ev.preventDefault();
            input.blur();
        } else if (ev.key === 'Escape') {
            ev.preventDefault();
            finish(false);
        }
    });
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

// 💡 並び替えが変更されたらUIを即リフレッシュ
document.getElementById('sortSelect').addEventListener('change', () => {
    refreshGalleryUI();
});

function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// 初期化実行
updateModeDisplay();
updateGallery();
startLogStream();