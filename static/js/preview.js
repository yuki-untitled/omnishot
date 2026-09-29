// ==========================================================================
// 画像のプレビュー
// 仕様: docs/spec/gallery.md
// ==========================================================================
import { gallery, reloadGallery } from './gallery.js';
import { captureUrl, downloadFrom, postJson } from './util.js';

const elPreviewModal = document.getElementById('previewModal');
const elPreviewImage = document.getElementById('previewImage');
const elPreviewInfo = document.getElementById('previewInfo');
const elCloseModalBtn = document.getElementById('closeModalBtn');
const elPrevBtn = document.getElementById('prevBtn');
const elNextBtn = document.getElementById('nextBtn');
const elPreviewDownloadBtn = document.getElementById('previewDownloadBtn');
const elPreviewDeleteBtn = document.getElementById('previewDeleteBtn');

// 仕様: docs/spec/bugs/LOCAL-043_プレビューで画像を削除すると削除した画像が表示され前後の移動が画面の並びと違う.md
// プレビューの前後の移動と枚数は、ギャラリーが画面に表示している並び（gallery.displayOrder）に従う。
// 開いている画像はファイル名で覚え、一覧が更新されて並びが変わっても、同じ画像を表示し続ける。
let currentFile = null;

function currentIndex() {
    return gallery.displayOrder.indexOf(currentFile);
}

export function openPreview(filename) {
    currentFile = filename;
    showPreview();
}

function showPreview() {
    const images = gallery.displayOrder;
    const index = currentIndex();
    if (index < 0) return;

    if (elPreviewImage) elPreviewImage.src = `${captureUrl(currentFile)}?t=${Date.now()}`;
    if (elPreviewInfo) elPreviewInfo.innerText = `${index + 1} / ${images.length} - ${currentFile}`;
    if (elPreviewModal) elPreviewModal.style.display = 'flex';
}

function isPreviewOpen() {
    return elPreviewModal.style.display === 'flex';
}

function closePreview() {
    if (elPreviewModal) elPreviewModal.style.display = 'none';
}

function movePreview(step) {
    const index = currentIndex() + step;
    if (index < 0 || index >= gallery.displayOrder.length) return;
    currentFile = gallery.displayOrder[index];
    showPreview();
}

const prevImage = () => movePreview(-1);
const nextImage = () => movePreview(1);

function downloadCurrentPreview() {
    if (currentIndex() < 0) return;
    downloadFrom(captureUrl(currentFile), currentFile);
}

function deleteCurrentPreview() {
    const index = currentIndex();
    if (index < 0) return;
    if (!confirm(`${currentFile} を削除しますか？`)) return;

    // 削除の後に一覧を取得し直し、その一覧で、次に表示する画像を決める
    // （画面の並びで、削除した画像の次。最後の画像だったときは前。1枚もなくなったら閉じる）
    postJson('/delete_selected', { filenames: [currentFile] })
        .then(() => reloadGallery())
        .then(() => {
            const images = gallery.displayOrder;
            if (images.length === 0) {
                closePreview();
                return;
            }
            currentFile = images[Math.min(index, images.length - 1)];
            showPreview();
        })
        .catch(err => console.error("Preview delete error:", err));
}

export function initPreview() {
    elCloseModalBtn.addEventListener('click', closePreview);
    elPrevBtn.addEventListener('click', prevImage);
    elNextBtn.addEventListener('click', nextImage);
    elPreviewDownloadBtn.addEventListener('click', downloadCurrentPreview);
    elPreviewDeleteBtn.addEventListener('click', deleteCurrentPreview);

    elPreviewModal.addEventListener('click', (e) => {
        if (e.target.id === 'previewModal') closePreview();
    });

    // キーボード操作（ESC / 左右矢印キー）
    document.addEventListener('keydown', (e) => {
        if (!isPreviewOpen()) return;
        if (e.key === 'Escape') closePreview();
        if (e.key === 'ArrowLeft') prevImage();
        if (e.key === 'ArrowRight') nextImage();
    });
}
