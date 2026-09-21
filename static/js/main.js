// ==========================================================================
// 1. グローバル状態管理 & キャッシュ要素の定義
// ==========================================================================
let currentImagesJson = "";
let logMessages = [];
let selectedFiles = new Set();
let allImages = [];
let currentPreviewIndex = 0;
let displayNames = {};

// DOM要素をキャッシュ（高速化のため一度だけ取得）
const elStartBtn = document.getElementById('startBtn');
const elStopBtn = document.getElementById('stopBtn');
const elCheckInterval = document.getElementById('checkInterval');
const elSettlingTime = document.getElementById('settlingTime');
const elJudgeCount = document.getElementById('judgeCount');
const elModeSelect = document.getElementById('modeSelect');
const elDeviceFilter = document.getElementById('deviceFilter');
const elSortSelect = document.getElementById('sortSelect');
const elStatus = document.getElementById('status');
const elGallery = document.getElementById('gallery');
const elLogConsole = document.getElementById('logConsole');

const elPreviewModal = document.getElementById('previewModal');
const elPreviewImage = document.getElementById('previewImage');
const elPreviewInfo = document.getElementById('previewInfo');
const elCloseModalBtn = document.getElementById('closeModalBtn');
const elPrevBtn = document.getElementById('prevBtn');
const elNextBtn = document.getElementById('nextBtn');

const elDeselectAllBtn = document.getElementById('deselectAllBtn');
const elDeleteSelectedBtn = document.getElementById('deleteSelectedBtn');
const elDownloadBtn = document.getElementById('downloadBtn');
const elSelectCount = document.getElementById('selectCount');
const elDownloadCount = document.getElementById('downloadCount');

const elGuideModal = document.getElementById('guideModal');
const elTabAndroidBtn = document.getElementById('tabAndroidBtn');
const elTabIosBtn = document.getElementById('tabIosBtn');
const elGuideAndroid = document.getElementById('guideAndroid');
const elGuideIos = document.getElementById('guideIos');
const elCloseGuideBtn = document.getElementById('closeGuideBtn');
const elOpenGuideBtn = document.getElementById('openGuideBtn');

// 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md
// 表示名はサーバー側（/images のレスポンス）が唯一の情報源。localStorageには保存しない。

// JSONをPOSTする共通ヘルパー
function postJson(url, body) {
    return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
}

// 撮影ステータス表示の切り替え
function setStatus(isCapturing) {
    elStatus.innerText = isCapturing ? "Status: Capturing..." : "Status: Idle";
    elStatus.style.color = isCapturing ? "#2ecc71" : "#888";
}

// ==========================================================================
// 2. ギャラリー & UI 制御関数
// ==========================================================================

// ギャラリー更新ロジック（定期ポーリング）
function updateGallery() {
    fetch('/images')
        .then(res => res.json())
        .then(data => {
            const newJson = JSON.stringify(data);
            
            // 💡 サーバーデータに変化があった場合のみ並び替えと再描画を実行（軽量化・パタつき防止）
            if (currentImagesJson === "" || newJson !== currentImagesJson) {
                currentImagesJson = newJson;
                allImages = data.images;
                displayNames = data.displayNames || {};
                refreshGalleryUI();
            }
            setTimeout(updateGallery, 1500);
        })
        .catch(err => {
            console.error("Gallery update error:", err);
            setTimeout(updateGallery, 3000); // エラー時は少し間隔を空けてリトライ
        });
}

// ギャラリーUIの生成・描画
function refreshGalleryUI() {
    if (!elGallery) return;

    const sortOrder = elSortSelect.value;
    const filterValue = elDeviceFilter.value; // 追加: フィルター値を取得

    // 1. まずフィルタリングしてからソートする
    let filteredImages = allImages.filter(img => {
        if (filterValue === 'all') return true;
        return img.toLowerCase().startsWith(filterValue); // "ios_..." や "android_..." で判定
    });

    // 2. ソート
    filteredImages.sort((a, b) => {
        return sortOrder === 'desc' ? b.localeCompare(a) : a.localeCompare(b);
    });

    const timestamp = Date.now();
    elGallery.innerHTML = filteredImages.map(img => {
        const displayName = displayNames[img] || img.replace(/\.png$/i, '');
        const isSelected = selectedFiles.has(img);
        
        return `
            <div class="card ${isSelected ? 'selected' : ''}" data-filename="${img}">
                <input type="checkbox" class="select-checkbox" 
                    ${isSelected ? 'checked' : ''} 
                    onclick="toggleSelect('${img}')">
                <img src="/static/captures/${img}?t=${timestamp}" onclick="openPreview('${img}')" style="cursor: pointer;">
                <div class="card-info">
                    <span class="display-name" data-filename="${img}">${escapeHtml(displayName)}</span>
                </div>
            </div>
        `;
    }).join('');
}

// 選択状態の切り替え
window.toggleSelect = function(filename) {
    if (selectedFiles.has(filename)) {
        selectedFiles.delete(filename);
    } else {
        selectedFiles.add(filename);
    }
    updateUI();
};

// 共通アクションボタンの表示/非表示状態更新
function updateUI() {
    const count = selectedFiles.size;
    
    if (elSelectCount) elSelectCount.innerText = count;
    if (elDownloadCount) elDownloadCount.innerText = count;
    
    const displayStyle = count > 0 ? 'inline-block' : 'none';
    if (elDeselectAllBtn) elDeselectAllBtn.style.display = displayStyle;
    if (elDeleteSelectedBtn) elDeleteSelectedBtn.style.display = displayStyle;
    if (elDownloadBtn) elDownloadBtn.style.display = displayStyle;
}

// モード選択に連動した設定欄のトグル制御
function updateModeDisplay() {
    const isStatic = elModeSelect.value === 'static';
    const staticLabel = document.getElementById('staticLabel');
    const dynamicLabel = document.getElementById('dynamicLabel');

    if (staticLabel) staticLabel.style.display = isStatic ? 'inline' : 'none';
    if (dynamicLabel) dynamicLabel.style.display = isStatic ? 'none' : 'inline';
}

// ステータスの監視とUI同期
setInterval(() => {
    fetch('/status')
        .then(res => res.json())
        .then(data => {
            const isCapturing = elStatus.innerText.includes("Capturing");
            
            if (isCapturing && !data.is_running) {
                setStatus(false);

                // エラー理由があればそれを表示、なければ標準メッセージ
                const message = data.error ? `${data.error}` : "自動撮影を停止しました。";
                alert(message);
            }
        })
        .catch(err => console.error("Status check failed:", err));
}, 2000);


// ==========================================================================
// 3. プレビューモーダル制御
// ==========================================================================
function openPreview(filename) {
    currentPreviewIndex = allImages.indexOf(filename);
    showPreview();
}

function showPreview() {
    if (allImages.length === 0) return;
    
    const img = allImages[currentPreviewIndex];
    if (elPreviewImage) elPreviewImage.src = `/static/captures/${img}?t=${Date.now()}`;
    if (elPreviewInfo) elPreviewInfo.innerText = `${currentPreviewIndex + 1} / ${allImages.length} - ${img}`;
    if (elPreviewModal) elPreviewModal.style.display = 'flex';
}

function closePreview() {
    if (elPreviewModal) elPreviewModal.style.display = 'none';
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

function downloadCurrentPreview() {
    const filename = allImages[currentPreviewIndex];
    const link = document.createElement('a');
    link.href = `/static/captures/${filename}`;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function deleteCurrentPreview() {
    const filename = allImages[currentPreviewIndex];
    if (!confirm(`${filename} を削除しますか？`)) return;

    postJson('/delete_selected', { filenames: [filename] }).then(() => {
        // サーバーからデータ取得し直してUIを更新
        updateGallery();
        
        // モーダルの挙動制御
        if (allImages.length <= 1) {
            closePreview();
        } else {
            // 削除後、次の画像へスライド
            if (currentPreviewIndex >= allImages.length - 1) {
                currentPreviewIndex--;
            }
            showPreview();
        }
    });
}


// ==========================================================================
// 4. 数値ガード & サーバー同期
// ==========================================================================
function getClampedSettings() {
    let interval = parseFloat(elCheckInterval.value) || 0.5;
    interval = Math.max(0.1, Math.min(30, interval));
    elCheckInterval.value = interval;

    let settling = parseFloat(elSettlingTime.value) || 1.0;
    settling = Math.max(0.1, Math.min(30, settling));
    elSettlingTime.value = settling;

    let judgeCount = parseInt(elJudgeCount.value) || 3;
    judgeCount = Math.max(1, Math.min(10, judgeCount));
    elJudgeCount.value = judgeCount;

    const mode = elModeSelect.value;
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


// ==========================================================================
// 5. 表示名の動的編集（イベントデリゲーション）
// ==========================================================================
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
            const userInput = input.value.trim();
            const cleanInputBase = userInput.replace(/\.png$/i, '');

            if (cleanInputBase === currentBase) {
                revertSpan();
                return;
            }

            // 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md
            // ファイル名をキーにサーバーへ永続化する（表示名文字列同士の比較には依存しない）
            if (cleanInputBase) {
                displayNames[filename] = cleanInputBase;
            } else {
                delete displayNames[filename];
            }

            postJson('/rename', { filename: filename, displayName: cleanInputBase })
                .catch(err => console.error("Rename error:", err));

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


// ==========================================================================
// 6. Live Logs & サーバー通信ストリーム
// ==========================================================================
function appendLog(message) {
    logMessages.push(message);
    if (logMessages.length > 50) {
        logMessages.shift();
    }
    if (elLogConsole) {
        // 仕様: docs/spec/bugs/LOCAL-010_ログ表示にHTMLを含む文字列がそのまま解釈される.md
        elLogConsole.innerHTML = logMessages.slice().reverse().map(msg => `<div>${escapeHtml(msg)}</div>`).join('');
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
        console.warn('Log stream disconnected; retrying...');
    };
}


// ==========================================================================
// 7. 各種イベントリスナーの設定
// ==========================================================================

// 自動撮影コントロール系
elStartBtn.addEventListener('click', () => {
    fetch(`/start?${settingsQuery()}`)
        .then(() => setStatus(true));
});

elStopBtn.addEventListener('click', () => {
    fetch('/stop')
        .then(() => setStatus(false));
});

// 各設定入力欄のリアルタイム同期
elCheckInterval.addEventListener('input', sendSettings);
elSettlingTime.addEventListener('input', sendSettings);
elJudgeCount.addEventListener('input', sendSettings);
elModeSelect.addEventListener('change', () => {
    updateModeDisplay();
    sendSettings();
});

// ギャラリーの全選択・解除・ソート
document.getElementById('selectAllBtn').addEventListener('click', () => {
    if (allImages.length === 0) return;
    allImages.forEach(img => selectedFiles.add(img));
    updateUI();
    refreshGalleryUI();
});

elDeselectAllBtn.addEventListener('click', () => {
    selectedFiles.clear();
    updateUI();
    refreshGalleryUI();
});

elDeviceFilter.addEventListener('change', () => {
    refreshGalleryUI();
});

elSortSelect.addEventListener('change', () => {
    refreshGalleryUI();
});

// 選択アイテムの削除・ダウンロード
elDeleteSelectedBtn.addEventListener('click', () => {
    if (selectedFiles.size === 0) return;
    const message = selectedFiles.size === allImages.length 
        ? `${selectedFiles.size}件の全ての画像を削除しますか？`
        : `${selectedFiles.size}件の画像を削除しますか？`;
    
    if (confirm(message)) {
        postJson('/delete_selected', { filenames: Array.from(selectedFiles) }).then(() => {
            selectedFiles.clear();
            updateUI();
        });
    }
});

elDownloadBtn.addEventListener('click', () => {
    if (selectedFiles.size === 0) return;

    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const date = String(now.getDate()).padStart(2, '0');
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    
    const defaultName = `OmniShot_${year}${month}${date}_${hours}${minutes}${seconds}`;
    const inputName = prompt('保存するZIPファイル名を入力してください（拡張子 .zip は不要）', defaultName);
    if (inputName === null) return;
    
    const zipFilename = inputName.trim() === '' ? defaultName + '.zip' : (inputName.endsWith('.zip') ? inputName : inputName + '.zip');

    const selectedArray = Array.from(selectedFiles).sort((a, b) => b.localeCompare(a, undefined, { numeric: true, sensitivity: 'base' }));

    // 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md
    // ZIP内のファイル名はサーバー側に永続化された表示名を使って決定するため、ここでは送らない
    postJson('/download_selected', { filenames: selectedArray, zipName: zipFilename })
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

// モーダル操作ボタン関係
elCloseModalBtn.addEventListener('click', closePreview);
elPrevBtn.addEventListener('click', prevImage);
elNextBtn.addEventListener('click', nextImage);

elPreviewModal.addEventListener('click', (e) => {
    if (e.target.id === 'previewModal') closePreview();
});

// キーボード操作（ESC / 左右矢印キー）
document.addEventListener('keydown', (e) => {
    if (elPreviewModal.style.display === 'flex') {
        if (e.key === 'Escape') closePreview();
        if (e.key === 'ArrowLeft') prevImage();
        if (e.key === 'ArrowRight') nextImage();
    }
});

// セットアップガイドの制御関係
// 仕様: docs/spec/bugs/LOCAL-013_設定ガイドの次回から表示しないを廃止し起動時の自動表示をやめる.md
// 起動時には自動表示せず、「設定ガイド」ボタンで開く。表示に関する保存データは持たない。
elOpenGuideBtn.addEventListener('click', () => {
    if (elGuideModal) elGuideModal.style.display = 'flex';
});

elTabAndroidBtn.addEventListener('click', () => {
    elTabAndroidBtn.style.background = '#2ecc71';
    elTabIosBtn.style.background = '#555';
    elGuideAndroid.style.display = 'block';
    elGuideIos.style.display = 'none';
});

elTabIosBtn.addEventListener('click', () => {
    elTabAndroidBtn.style.background = '#555';
    elTabIosBtn.style.background = '#2ecc71';
    elGuideAndroid.style.display = 'none';
    elGuideIos.style.display = 'block';
});

elCloseGuideBtn.addEventListener('click', () => {
    elGuideModal.style.display = 'none';
});

// アプリ終了ボタン
window.shutdownApp = function() {
    if (confirm("アプリケーションを終了しますか？\n（サーバーが停止し、この画面は使えなくなります）")) {
        fetch('/shutdown', { method: 'POST' })
            .then(() => {
                // 仕様: docs/spec/bugs/LOCAL-011_アプリ終了時のメッセージがブラウザのタブ前提のまま.md
                alert("アプリケーションを終了しました。");
                window.close();
            })
            .catch(err => console.error("Shutdown error:", err));
    }
};

// HTMLエスケープヘルパー
function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


// ==========================================================================
// 8. システム初期化
// ==========================================================================
updateModeDisplay();
updateGallery();
startLogStream();