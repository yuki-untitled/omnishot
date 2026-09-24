// ==========================================================================
// 画像のプレビュー
// 仕様: docs/spec/gallery.md
// ==========================================================================
import { gallery, updateGallery } from './gallery.js';
import { captureUrl, downloadFrom, postJson } from './util.js';

const elPreviewModal = document.getElementById('previewModal');
const elPreviewImage = document.getElementById('previewImage');
const elPreviewInfo = document.getElementById('previewInfo');
const elCloseModalBtn = document.getElementById('closeModalBtn');
const elPrevBtn = document.getElementById('prevBtn');
const elNextBtn = document.getElementById('nextBtn');
const elPreviewDownloadBtn = document.getElementById('previewDownloadBtn');
const elPreviewDeleteBtn = document.getElementById('previewDeleteBtn');

let currentPreviewIndex = 0;

export function openPreview(filename) {
    currentPreviewIndex = gallery.allImages.indexOf(filename);
    showPreview();
}

function showPreview() {
    const { allImages } = gallery;
    if (allImages.length === 0) return;

    const img = allImages[currentPreviewIndex];
    if (elPreviewImage) elPreviewImage.src = `${captureUrl(img)}?t=${Date.now()}`;
    if (elPreviewInfo) elPreviewInfo.innerText = `${currentPreviewIndex + 1} / ${allImages.length} - ${img}`;
    if (elPreviewModal) elPreviewModal.style.display = 'flex';
}

function isPreviewOpen() {
    return elPreviewModal.style.display === 'flex';
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
    if (currentPreviewIndex < gallery.allImages.length - 1) {
        currentPreviewIndex++;
        showPreview();
    }
}

function downloadCurrentPreview() {
    const filename = gallery.allImages[currentPreviewIndex];
    downloadFrom(captureUrl(filename), filename);
}

function deleteCurrentPreview() {
    const filename = gallery.allImages[currentPreviewIndex];
    if (!confirm(`${filename} を削除しますか？`)) return;

    postJson('/delete_selected', { filenames: [filename] }).then(() => {
        // サーバーからデータ取得し直してUIを更新
        updateGallery();

        // モーダルの挙動制御
        if (gallery.allImages.length <= 1) {
            closePreview();
        } else {
            // 削除後、次の画像へスライド
            if (currentPreviewIndex >= gallery.allImages.length - 1) {
                currentPreviewIndex--;
            }
            showPreview();
        }
    });
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
