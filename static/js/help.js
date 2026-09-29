// ==========================================================================
// 使い方ページのタブ
// 仕様: docs/spec/setup-guide.md（使い方・iPhone の準備・Android の準備・困ったとき）
// URL の # で開くタブを指定できる（例: /help#ios）。指定が無ければ「使い方」を開く。
// ==========================================================================
const TAB_IDS = ['usage', 'ios', 'android', 'trouble'];

function showTab(id) {
    const tab = TAB_IDS.includes(id) ? id : 'usage';
    TAB_IDS.forEach(name => {
        document.getElementById(`tab-${name}`).classList.toggle('active', name === tab);
        document.getElementById(`panel-${name}`).style.display = name === tab ? 'block' : 'none';
    });
}

TAB_IDS.forEach(name => {
    document.getElementById(`tab-${name}`).addEventListener('click', () => {
        // ページを再読み込みせずに、URL の # だけを合わせる（戻る操作でタブが戻る）
        history.replaceState(null, '', `#${name}`);
        showTab(name);
    });
});
window.addEventListener('hashchange', () => showTab(location.hash.slice(1)));
showTab(location.hash.slice(1));
