# 仕様: docs/spec/native-window.md
import platform
import sys
import threading
import time
import urllib.request

import webview

from omnishot import create_app, port_guard, update_check
from omnishot.logs import add_log

HOST = '127.0.0.1'
PORT = 5001
BASE_URL = f'http://{HOST}:{PORT}'

# 仕様: docs/spec/native-window.md（ウィンドウの大きさの下限。撮影の設定欄が2行で収まる幅）
WINDOW_SIZE = (1280, 860)
WINDOW_MIN_SIZE = (940, 600)


def _wait_for_server(timeout=10.0):
    """Flaskの起動完了を待つ。固定sleepではなく/statusへの短いポーリングで確認する。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{BASE_URL}/status", timeout=0.5)
            return True
        except Exception:
            time.sleep(0.05)
    return False


def _shutdown_via_http():
    """ウィンドウが閉じられた時、既存の/shutdownハンドラと同じ後始末を通す。"""
    try:
        req = urllib.request.Request(f"{BASE_URL}/shutdown", method="POST")
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


def _accept_first_mouse_on_macos():
    """Macで、非アクティブなウィンドウへの最初のクリックを、ウィンドウの有効化だけに使わず画面にも渡す。

    仕様: docs/spec/bugs/LOCAL-012_起動直後の最初のクリックが設定ガイドのタブに効かない.md
    起動元のアプリ（ターミナル・IDE）がフォーカスを持つと、起動直後のウィンドウは非アクティブになり、
    最初のクリックが有効化に消費されてページに届かない。WebViewの受け付け設定を変えて防ぐ。
    """
    if platform.system() != "Darwin":
        return
    try:
        import objc
        from webview.platforms import cocoa

        def acceptsFirstMouse_(self, event):
            return True

        objc.classAddMethods(
            cocoa.BrowserView.WebKitHost,
            [objc.selector(acceptsFirstMouse_, signature=b'B@:@')],
        )
    except Exception as e:
        add_log(f"⚠️ 最初のクリックを受け付ける設定に失敗しました: {e}")


if __name__ == '__main__':
    # 仕様: docs/spec/bugs/LOCAL-042_起動時と終了時の後始末がアプリが作っていないファイルやプロセスに影響する.md
    # 前回の OmniShot が残っていれば終了する。別のアプリがポートを使っているときは、終了せずに知らせて起動をやめる
    if port_guard.free_port(PORT):
        port_guard.show_port_in_use_dialog(PORT)
        sys.exit(1)

    add_log("🚀 OmniShot を起動中...")
    app = create_app()
    threading.Thread(
        target=lambda: app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True),
        daemon=True,
    ).start()
    _wait_for_server()
    # 仕様: docs/spec/update-notification.md（新しい版の確認は、画面の表示を待たせず、起動時に1回だけ始める）
    update_check.start_background()

    _accept_first_mouse_on_macos()
    # 仕様: docs/spec/bugs/LOCAL-033_アプリ化するとスクリーンショットをダウンロードできない.md
    webview.settings['ALLOW_DOWNLOADS'] = True
    window = webview.create_window("OmniShot", BASE_URL, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], min_size=WINDOW_MIN_SIZE)
    window.events.closing += _shutdown_via_http
    webview.start()
