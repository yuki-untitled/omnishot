// ==========================================================================
// ギャラリー（一覧・選択・表示名の変更・選択した画像の削除とダウンロード）
// 仕様: docs/spec/gallery.md
// ==========================================================================
import { captureUrl, downloadFrom, escapeHtml, postJson, timestampString } from './util.js';

const elGallery = document.getElementById('gallery');
const elDeviceFilter = document.getElementById('deviceFilter');
const elSortSelect = document.getElementById('sortSelect');
const elSelectAllBtn = document.getElementById('selectAllBtn');
const elDeselectAllBtn = document.getElementById('deselectAllBtn');
const elDeleteSelectedBtn = document.getElementById('deleteSelectedBtn');
const elDownloadBtn = document.getElementById('downloadBtn');
const elSelectCount = document.getElementById('selectCount');
const elDownloadCount = document.getElementById('downloadCount');

// 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md
// 表示名はサーバー側（/images のレスポンス）が唯一の情報源。localStorageには保存しない。
export const gallery = {
    allImages: [],
    displayNames: {},
    // 仕様: docs/spec/session-grouping.md（ファイル名 -> セッションID、セッションID -> セッション情報）
    imageSessions: {},
    sessions: {},
};
let currentImagesJson = "";
const selectedFiles = new Set();

// ギャラリー更新ロジック（定期ポーリング）
export function updateGallery() {
    fetch('/images')
        .then(res => res.json())
        .then(data => {
            const newJson = JSON.stringify(data);

            // 💡 サーバーデータに変化があった場合のみ並び替えと再描画を実行（軽量化・パタつき防止）
            if (currentImagesJson === "" || newJson !== currentImagesJson) {
                currentImagesJson = newJson;
                gallery.allImages = data.images;
                gallery.displayNames = data.displayNames || {};
                // 仕様: docs/spec/session-grouping.md
                gallery.imageSessions = data.imageSessions || {};
                gallery.sessions = data.sessions || {};
                refreshGalleryUI();
            }
            setTimeout(updateGallery, 1500);
        })
        .catch(err => {
            console.error("Gallery update error:", err);
            setTimeout(updateGallery, 3000); // エラー時は少し間隔を空けてリトライ
        });
}

// 仕様: docs/spec/manual-capture.md（ファイル名先頭の "Manual_" を除いた部分でOS種別を判定する）
function deviceTypeOf(img) {
    return img.toLowerCase().replace(/^manual_/, '');
}

function defaultDisplayName(img) {
    return img.replace(/\.png$/i, '');
}

// 仕様: docs/spec/session-grouping.md
// 画像が属するセッションを表すキー（未登録＝未分類）。連続する同じキーを1つの区切りにまとめる。
function sessionGroupKey(img) {
    const sessionId = gallery.imageSessions[img];
    return sessionId === undefined ? 'unclassified' : `session:${sessionId}`;
}

function sessionHeadingHtml(img) {
    const { allImages, imageSessions, sessions } = gallery;
    const sessionId = imageSessions[img];
    if (sessionId === undefined) {
        const count = allImages.filter(name => imageSessions[name] === undefined).length;
        return `<div class="session-heading">未分類（${count}枚）</div>`;
    }
    const info = sessions[sessionId] || {};
    const count = allImages.filter(name => imageSessions[name] === sessionId).length;
    return `<div class="session-heading">セッション${sessionId}（${escapeHtml(info.startedAt || '')} - ${count}枚）</div>`;
}

function cardHtml(img, timestamp) {
    const displayName = gallery.displayNames[img] || defaultDisplayName(img);
    const isSelected = selectedFiles.has(img);
    const isManual = /^manual_/i.test(img);
    const safeName = escapeHtml(img);
    return `
        <div class="card ${isSelected ? 'selected' : ''}" data-filename="${safeName}">
            ${isManual ? '<span class="manual-badge">手動</span>' : ''}
            <input type="checkbox" class="select-checkbox" ${isSelected ? 'checked' : ''}>
            <img src="${captureUrl(img)}?t=${timestamp}" class="card-image" style="cursor: pointer;">
            <div class="card-info">
                <span class="display-name" data-filename="${safeName}">${escapeHtml(displayName)}</span>
            </div>
        </div>
    `;
}

// ギャラリーUIの生成・描画
export function refreshGalleryUI() {
    if (!elGallery) return;

    const sortOrder = elSortSelect.value;
    const filterValue = elDeviceFilter.value;

    // 1. まずフィルタリングしてからソートする（"ios_..." や "android_..." で判定）
    const filteredImages = gallery.allImages
        .filter(img => filterValue === 'all' || deviceTypeOf(img).startsWith(filterValue))
        .sort((a, b) => sortOrder === 'desc' ? b.localeCompare(a) : a.localeCompare(b));

    // 2. 「未分類」は撮影時刻に関わらず常に末尾へまとめる（セッションの一覧を確認しやすくするため）
    // 仕様: docs/spec/session-grouping.md
    const isUnclassified = img => gallery.imageSessions[img] === undefined;
    const orderedImages = filteredImages.filter(img => !isUnclassified(img))
        .concat(filteredImages.filter(isUnclassified));

    // 3. セッションの区切りを挿入しながら描画（各セッション内の並び順は変えない）
    const timestamp = Date.now();
    let previousGroupKey = null;
    const html = [];
    orderedImages.forEach(img => {
        const groupKey = sessionGroupKey(img);
        if (groupKey !== previousGroupKey) {
            html.push(sessionHeadingHtml(img));
            previousGroupKey = groupKey;
        }
        html.push(cardHtml(img, timestamp));
    });
    elGallery.innerHTML = html.join('');
}

// ==========================================================================
// 選択
// ==========================================================================
function toggleSelect(filename) {
    if (selectedFiles.has(filename)) {
        selectedFiles.delete(filename);
    } else {
        selectedFiles.add(filename);
    }
    updateSelectionUI();
}

// 選択した画像に対する操作ボタンの表示/非表示
function updateSelectionUI() {
    const count = selectedFiles.size;
    if (elSelectCount) elSelectCount.innerText = count;
    if (elDownloadCount) elDownloadCount.innerText = count;

    const displayStyle = count > 0 ? 'inline-block' : 'none';
    if (elDeselectAllBtn) elDeselectAllBtn.style.display = displayStyle;
    if (elDeleteSelectedBtn) elDeleteSelectedBtn.style.display = displayStyle;
    if (elDownloadBtn) elDownloadBtn.style.display = displayStyle;
}

function deleteSelected() {
    if (selectedFiles.size === 0) return;
    const message = selectedFiles.size === gallery.allImages.length
        ? `${selectedFiles.size}件の全ての画像を削除しますか？`
        : `${selectedFiles.size}件の画像を削除しますか？`;
    if (!confirm(message)) return;

    postJson('/delete_selected', { filenames: Array.from(selectedFiles) }).then(() => {
        selectedFiles.clear();
        updateSelectionUI();
    });
}

function downloadSelected() {
    if (selectedFiles.size === 0) return;

    const defaultName = `OmniShot_${timestampString(new Date())}`;
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
            downloadFrom(url, zipFilename);
            window.URL.revokeObjectURL(url);
        })
        .catch(err => console.error("Download error:", err));
}

// ==========================================================================
// 表示名の変更
// 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md
// ==========================================================================
function startEditDisplayName(spanEl, filename) {
    const { displayNames } = gallery;
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

        if (!save) {
            revertSpan();
            return;
        }
        const cleanInputBase = input.value.trim().replace(/\.png$/i, '');
        if (cleanInputBase === currentBase) {
            revertSpan();
            return;
        }

        // ファイル名をキーにサーバーへ永続化する（表示名文字列同士の比較には依存しない）
        if (cleanInputBase) {
            gallery.displayNames[filename] = cleanInputBase;
        } else {
            delete gallery.displayNames[filename];
        }
        postJson('/rename', { filename: filename, displayName: cleanInputBase })
            .catch(err => console.error("Rename error:", err));
        refreshGalleryUI();
    }

    function revertSpan() {
        const span = document.createElement('span');
        span.className = 'display-name';
        span.setAttribute('data-filename', filename);
        span.innerText = gallery.displayNames[filename] || defaultDisplayName(filename);
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
// イベント
// ==========================================================================
export function initGallery({ onOpenPreview }) {
    // カードの中のクリックは、ギャラリーでまとめて受け取る（ファイル名は data-filename から読む）
    elGallery.addEventListener('click', (e) => {
        const target = e.target;
        const card = target.closest('.card');
        if (!card) return;
        const filename = card.dataset.filename;
        if (target.classList.contains('select-checkbox')) {
            toggleSelect(filename);
        } else if (target.classList.contains('card-image')) {
            onOpenPreview(filename);
        } else if (target.classList.contains('display-name')) {
            startEditDisplayName(target, filename);
        }
    });

    elSelectAllBtn.addEventListener('click', () => {
        if (gallery.allImages.length === 0) return;
        gallery.allImages.forEach(img => selectedFiles.add(img));
        updateSelectionUI();
        refreshGalleryUI();
    });

    elDeselectAllBtn.addEventListener('click', () => {
        selectedFiles.clear();
        updateSelectionUI();
        refreshGalleryUI();
    });

    elDeviceFilter.addEventListener('change', refreshGalleryUI);
    elSortSelect.addEventListener('change', refreshGalleryUI);
    elDeleteSelectedBtn.addEventListener('click', deleteSelected);
    elDownloadBtn.addEventListener('click', downloadSelected);
}
