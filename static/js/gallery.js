// ==========================================================================
// ギャラリー（一覧・選択・表示名の変更・選択した画像の削除とダウンロード）
// セッション単位の操作（名前の変更・ダウンロード・並べ替え）もここで扱う。
// 仕様: docs/spec/gallery.md
// 仕様: docs/spec/session-grouping.md
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

// 仕様: docs/spec/session-grouping.md（セッション内の並べ替え。永続化しない）
// セッションID -> 並べ替えたファイル名の並び。並べ替えていないセッションは持たない。
const manualOrder = new Map();
// セッション名の編集中・ドラッグ中は、定期更新による再描画で操作が途切れないよう、再描画を保留する。
let isEditingSessionName = false;
let isDragging = false;

// ギャラリー更新ロジック（定期ポーリング）
export function updateGallery() {
    fetch('/images')
        .then(res => res.json())
        .then(data => {
            const newJson = JSON.stringify(data);

            // 💡 サーバーデータに変化があった場合のみ並び替えと再描画を実行（軽量化・パタつき防止）
            const isBusy = isEditingSessionName || isDragging;
            if (!isBusy && (currentImagesJson === "" || newJson !== currentImagesJson)) {
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

function matchesDeviceFilter(img) {
    const filterValue = elDeviceFilter.value;
    return filterValue === 'all' || deviceTypeOf(img).startsWith(filterValue);
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

// 仕様: docs/spec/session-grouping.md（見出しの名前・開始日時・枚数と、セッション単位のダウンロードボタン）
function sessionHeadingHtml(img) {
    const { allImages, imageSessions, sessions } = gallery;
    const sessionId = imageSessions[img];
    // 仕様: docs/spec/session-grouping.md（セッション単位の全選択・削除・ダウンロード）
    const actions = (key) => `<span class="session-actions">`
        + `<button type="button" class="session-action session-select" data-session="${key}">全選択</button>`
        + `<button type="button" class="session-action session-delete" data-session="${key}" title="このセッションの画像をすべて削除">削除</button>`
        + `<button type="button" class="session-action session-download" data-session="${key}" title="このセッションの画像をZIPでダウンロード">ダウンロード</button>`
        + `</span>`;
    if (sessionId === undefined) {
        const count = allImages.filter(name => imageSessions[name] === undefined).length;
        return `<div class="session-heading"><span class="session-title">未分類</span><span class="session-meta">（${count}枚）</span>${actions('unclassified')}</div>`;
    }
    const info = sessions[sessionId] || {};
    const count = allImages.filter(name => imageSessions[name] === sessionId).length;
    const title = info.name ? escapeHtml(info.name) : `セッション${sessionId}`;
    return `<div class="session-heading"><span class="session-title editable" data-session="${sessionId}" title="クリックして名前を変更">${title}</span><span class="session-meta">（${escapeHtml(info.startedAt || '')} - ${count}枚）</span>${actions(sessionId)}</div>`;
}

// 仕様: docs/spec/bugs/LOCAL-037_新しい順でも新しいセッションが上に表示されない.md
// 画像の並びは、ファイル名ではなく撮影した時刻の順で決める。/images の画像は撮影が新しい順に届くので、その位置を使う。
// 並び順設定に従う比較関数（新しい順は撮影が新しい画像が先）を返す。
function chronologicalComparator() {
    const rank = new Map(gallery.allImages.map((img, index) => [img, index]));
    return elSortSelect.value === 'desc'
        ? (a, b) => rank.get(a) - rank.get(b)
        : (a, b) => rank.get(b) - rank.get(a);
}

// 仕様: docs/spec/session-grouping.md（セッション内の並べ替え）
// セッションの画像を、画面に表示する順に返す。並べ替えたセッションは手動の順序、そうでなければ並び順設定に従う。
// 並べ替えた後に増えた画像は、末尾に古い順で加える。
function sessionImagesInDisplayOrder(sessionId) {
    const members = gallery.allImages.filter(img => gallery.imageSessions[img] === sessionId);
    const manual = manualOrder.get(sessionId);
    if (!manual) return members.sort(chronologicalComparator());
    const memberSet = new Set(members);
    const known = manual.filter(img => memberSet.has(img));
    const knownSet = new Set(known);
    const oldestFirst = (a, b) => members.indexOf(b) - members.indexOf(a);
    const added = members.filter(img => !knownSet.has(img)).sort(oldestFirst);
    return known.concat(added);
}

function cardHtml(img, timestamp) {
    const displayName = gallery.displayNames[img] || defaultDisplayName(img);
    const isSelected = selectedFiles.has(img);
    const isManual = /^manual_/i.test(img);
    const safeName = escapeHtml(img);
    // 仕様: docs/spec/session-grouping.md（並べ替えられるのはセッションの画像だけ。未分類は対象外）
    const sessionId = gallery.imageSessions[img];
    return `
        <div class="card ${isSelected ? 'selected' : ''}" data-filename="${safeName}"${sessionId === undefined ? '' : ` data-session="${sessionId}" draggable="true"`}>
            ${isManual ? '<span class="manual-badge">手動</span>' : ''}
            <input type="checkbox" class="select-checkbox" ${isSelected ? 'checked' : ''}>
            <img src="${captureUrl(img)}?t=${timestamp}" class="card-image" style="cursor: pointer;" draggable="false">
            <div class="card-info">
                <span class="display-name" data-filename="${safeName}">${escapeHtml(displayName)}</span>
            </div>
        </div>
    `;
}

// ギャラリーUIの生成・描画
export function refreshGalleryUI() {
    if (!elGallery) return;

    // 1. まずフィルタリングしてからソートする（"ios_..." や "android_..." で判定）
    const filteredImages = gallery.allImages
        .filter(matchesDeviceFilter)
        .sort(chronologicalComparator());

    // 2. セッションごとにまとめる。見出しはセッション番号の順（新しい順は番号の大きい順）に並べ、
    //    「未分類」は撮影時刻に関わらず常に末尾へまとめる（セッションの一覧を確認しやすくするため）。
    //    並べ替えたセッションは、手動の順序で表示する（それ以外の並び順は変えない）。
    // 仕様: docs/spec/session-grouping.md
    const groups = new Map();
    filteredImages.forEach(img => {
        const groupKey = sessionGroupKey(img);
        if (!groups.has(groupKey)) groups.set(groupKey, []);
        groups.get(groupKey).push(img);
    });
    const sessionIdOf = images => gallery.imageSessions[images[0]];
    const sign = elSortSelect.value === 'desc' ? -1 : 1;
    const orderedGroups = Array.from(groups.values()).sort((a, b) => {
        const idA = sessionIdOf(a);
        const idB = sessionIdOf(b);
        if (idA === undefined || idB === undefined) return (idA === undefined) - (idB === undefined);
        return sign * (idA - idB);
    });
    const timestamp = Date.now();
    const html = [];
    orderedGroups.forEach(images => {
        const sessionId = sessionIdOf(images);
        let shown = images;
        if (sessionId !== undefined && manualOrder.has(sessionId)) {
            const inGroup = new Set(images);
            shown = sessionImagesInDisplayOrder(sessionId).filter(img => inGroup.has(img));
        }
        html.push(sessionHeadingHtml(images[0]));
        shown.forEach(img => html.push(cardHtml(img, timestamp)));
    });
    elGallery.innerHTML = html.join('');
    updateSessionSelectButtons();
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
    updateSessionSelectButtons();
}

// 仕様: docs/spec/session-grouping.md（セッション単位の全選択・削除）
// 対象は、ギャラリーに表示されている（端末フィルタで隠れていない）そのセッションの画像
function visibleImagesOfSession(sessionKey) {
    const groupKey = sessionKey === 'unclassified' ? 'unclassified' : `session:${sessionKey}`;
    return gallery.allImages.filter(img => sessionGroupKey(img) === groupKey && matchesDeviceFilter(img));
}

// 見出しの「全選択」ボタンは、そのセッションの画像がすべて選択済みなら「選択解除」にする
function updateSessionSelectButtons() {
    elGallery.querySelectorAll('.session-select').forEach(button => {
        const images = visibleImagesOfSession(button.dataset.session);
        const allSelected = images.length > 0 && images.every(img => selectedFiles.has(img));
        button.textContent = allSelected ? '選択解除' : '全選択';
    });
}

function toggleSessionSelection(sessionKey) {
    const images = visibleImagesOfSession(sessionKey);
    const allSelected = images.length > 0 && images.every(img => selectedFiles.has(img));
    images.forEach(img => allSelected ? selectedFiles.delete(img) : selectedFiles.add(img));
    updateSelectionUI();
    refreshGalleryUI();
}

function deleteSession(sessionKey) {
    const images = visibleImagesOfSession(sessionKey);
    if (images.length === 0) return;
    const title = sessionKey === 'unclassified'
        ? '未分類'
        : ((gallery.sessions[sessionKey] || {}).name || `セッション${sessionKey}`);
    if (!confirm(`「${title}」の${images.length}枚の画像を削除しますか？`)) return;

    postJson('/delete_selected', { filenames: images }).then(() => {
        images.forEach(img => selectedFiles.delete(img));
        updateSelectionUI();
    });
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
        .then(blob => saveBlob(blob, zipFilename))
        .catch(err => console.error("Download error:", err));
}

function saveBlob(blob, filename) {
    const url = window.URL.createObjectURL(blob);
    downloadFrom(url, filename);
    // アプリのウィンドウは保存先の選択後にURLを読むため、すぐには解放しない
    setTimeout(() => window.URL.revokeObjectURL(url), 60000);
}

// 仕様: docs/spec/session-grouping.md（セッション単位のダウンロード）
// ZIPのファイル名と、ZIP内の連番はサーバーが決める。並べ替えたセッションだけ、画面の並びを送る。
function downloadSession(sessionKey) {
    const sessionId = sessionKey === 'unclassified' ? null : Number(sessionKey);
    const order = sessionId !== null && manualOrder.has(sessionId) ? sessionImagesInDisplayOrder(sessionId) : [];
    postJson('/download_session', { sessionId, order })
        .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const zipFilename = decodeURIComponent(res.headers.get('X-Zip-Name'));
            return res.blob().then(blob => saveBlob(blob, zipFilename));
        })
        .catch(err => console.error("Session download error:", err));
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
// セッション名の変更
// 仕様: docs/spec/session-grouping.md（1〜50文字。空にすると「セッション N」に戻る）
// ==========================================================================
const SESSION_NAME_MAX_LENGTH = 50;

function startEditSessionName(spanEl, sessionId) {
    const currentName = (gallery.sessions[sessionId] || {}).name || '';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'edit-name-input session-name-input';
    input.maxLength = SESSION_NAME_MAX_LENGTH;
    input.placeholder = `セッション${sessionId}`;
    input.value = currentName;
    spanEl.replaceWith(input);
    isEditingSessionName = true;
    input.focus();
    input.select();

    let isFinished = false;
    let isComposing = false;
    input.addEventListener('compositionstart', () => { isComposing = true; });
    input.addEventListener('compositionend', () => { isComposing = false; });

    function finish(save) {
        if (isFinished) return;
        isFinished = true;
        isEditingSessionName = false;

        const newName = input.value.trim();
        if (save && newName !== currentName) {
            if (!gallery.sessions[sessionId]) gallery.sessions[sessionId] = {};
            if (newName) {
                gallery.sessions[sessionId].name = newName;
            } else {
                delete gallery.sessions[sessionId].name;
            }
            postJson('/rename_session', { sessionId, name: newName })
                // サーバーの内容で、次の定期更新を必ず描画し直す
                .then(() => { currentImagesJson = ""; })
                .catch(err => console.error("Session rename error:", err));
        }
        refreshGalleryUI();
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
// セッション内の並べ替え（ドラッグ＆ドロップ）
// 仕様: docs/spec/session-grouping.md（同じセッションの中だけ移動できる）
// ==========================================================================
let dragged = null;

function clearDropMarks() {
    elGallery.querySelectorAll('.drop-before, .drop-after, .dragging')
        .forEach(el => el.classList.remove('drop-before', 'drop-after', 'dragging'));
}

function endDrag() {
    dragged = null;
    isDragging = false;
    clearDropMarks();
}

// ドロップ先のカードの左半分なら手前、右半分なら後ろへ入れる
function isBeforeTarget(e, card) {
    const rect = card.getBoundingClientRect();
    return e.clientX < rect.left + rect.width / 2;
}

function dropTargetCard(e) {
    if (!dragged) return null;
    const card = e.target.closest('.card');
    if (!card || card.dataset.filename === dragged.filename) return null;
    return Number(card.dataset.session) === dragged.sessionId ? card : null;
}

function initSessionReorder() {
    elGallery.addEventListener('dragstart', (e) => {
        const card = e.target.closest ? e.target.closest('.card') : null;
        if (!card || !card.dataset.session) {
            e.preventDefault();
            return;
        }
        dragged = { filename: card.dataset.filename, sessionId: Number(card.dataset.session) };
        isDragging = true;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', dragged.filename);
        card.classList.add('dragging');
    });

    elGallery.addEventListener('dragover', (e) => {
        const card = dropTargetCard(e);
        if (!card) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        elGallery.querySelectorAll('.drop-before, .drop-after')
            .forEach(el => el.classList.remove('drop-before', 'drop-after'));
        card.classList.add(isBeforeTarget(e, card) ? 'drop-before' : 'drop-after');
    });

    elGallery.addEventListener('drop', (e) => {
        const card = dropTargetCard(e);
        if (!card) return;
        e.preventDefault();
        const { filename, sessionId } = dragged;
        const list = sessionImagesInDisplayOrder(sessionId).filter(img => img !== filename);
        const index = list.indexOf(card.dataset.filename) + (isBeforeTarget(e, card) ? 0 : 1);
        list.splice(index, 0, filename);
        manualOrder.set(sessionId, list);
        endDrag();
        refreshGalleryUI();
    });

    elGallery.addEventListener('dragend', endDrag);
}

// ==========================================================================
// イベント
// ==========================================================================
export function initGallery({ onOpenPreview }) {
    // カードの中のクリックは、ギャラリーでまとめて受け取る（ファイル名は data-filename から読む）
    elGallery.addEventListener('click', (e) => {
        const target = e.target;
        // セッションの見出し（名前の変更・セッション単位のダウンロード）
        const sessionButton = target.closest('.session-action');
        if (sessionButton) {
            const sessionKey = sessionButton.dataset.session;
            if (sessionButton.classList.contains('session-select')) toggleSessionSelection(sessionKey);
            else if (sessionButton.classList.contains('session-delete')) deleteSession(sessionKey);
            else downloadSession(sessionKey);
            return;
        }
        if (target.classList.contains('session-title') && target.dataset.session) {
            startEditSessionName(target, Number(target.dataset.session));
            return;
        }
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

    initSessionReorder();

    elDeviceFilter.addEventListener('change', refreshGalleryUI);
    // 仕様: docs/spec/session-grouping.md（並び順設定を変えると、手動の並べ替えは破棄される）
    elSortSelect.addEventListener('change', () => {
        manualOrder.clear();
        refreshGalleryUI();
    });
    elDeleteSelectedBtn.addEventListener('click', deleteSelected);
    elDownloadBtn.addEventListener('click', downloadSelected);
}
