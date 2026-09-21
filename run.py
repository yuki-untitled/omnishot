# 仕様: docs/spec/native-window.md
import platform
import subprocess
import threading
import time
import urllib.request

import webview

from omnishot import create_app, paths
from omnishot.logs import add_log

HOST = '127.0.0.1'
PORT = 5001
BASE_URL = f'http://{HOST}:{PORT}'


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


def _free_port():
    """前回の起動で残ったプロセスがポートを握っていた場合に備え、使用中のプロセスを終了する。"""
    try:
        if platform.system() == "Windows":
            subprocess.run('cmd /c "for /f \"tokens=5\" %a in (\'netstat -aon ^| findstr 5001\') do taskkill /f /pid %a"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=paths.CREATE_NO_WINDOW)
        else:
            subprocess.run("kill -9 $(lsof -t -i:5001)", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)
    except Exception: pass


if __name__ == '__main__':
    _free_port()

    add_log("🚀 OmniShot を起動中...")
    app = create_app()
    threading.Thread(
        target=lambda: app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True),
        daemon=True,
    ).start()
    _wait_for_server()

    _accept_first_mouse_on_macos()
    window = webview.create_window("OmniShot", BASE_URL, width=1280, height=860)
    window.events.closing += _shutdown_via_http
    webview.start()
