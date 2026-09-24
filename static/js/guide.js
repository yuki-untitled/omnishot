// ==========================================================================
// 設定ガイド
// 仕様: docs/spec/bugs/LOCAL-013_設定ガイドの次回から表示しないを廃止し起動時の自動表示をやめる.md
// 起動時には自動表示せず、「設定ガイド」ボタンで開く。表示に関する保存データは持たない。
// ==========================================================================
const elGuideModal = document.getElementById('guideModal');
const elOpenGuideBtn = document.getElementById('openGuideBtn');
const elCloseGuideBtn = document.getElementById('closeGuideBtn');
const elTabIosBtn = document.getElementById('tabIosBtn');
const elTabAndroidBtn = document.getElementById('tabAndroidBtn');
const elGuideIos = document.getElementById('guideIos');
const elGuideAndroid = document.getElementById('guideAndroid');

function showTab(os) {
    const isIos = os === 'ios';
    elTabIosBtn.classList.toggle('active', isIos);
    elTabAndroidBtn.classList.toggle('active', !isIos);
    elGuideIos.style.display = isIos ? 'block' : 'none';
    elGuideAndroid.style.display = isIos ? 'none' : 'block';
}

export function initGuide() {
    elOpenGuideBtn.addEventListener('click', () => {
        if (elGuideModal) elGuideModal.style.display = 'flex';
    });
    elCloseGuideBtn.addEventListener('click', () => {
        elGuideModal.style.display = 'none';
    });
    elTabIosBtn.addEventListener('click', () => showTab('ios'));
    elTabAndroidBtn.addEventListener('click', () => showTab('android'));
}
