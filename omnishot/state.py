import collections
import threading

# 仕様: docs/spec/screenshot-capture.md
# 他モジュールからは必ず `from omnishot import state` した上で
# `state.xxx = ...` の属性代入でアクセスする（`from omnishot.state import xxx` は禁止）。
# バックグラウンドスレッド（auto_capture_loop）とFlaskルートの双方から
# 再代入されるため、モジュール属性として共有する必要がある。
score_history = collections.deque(maxlen=3)
is_running = False
last_error = None
last_frame_data = None

current_config = {
    "interval": 0.2,
    "settling": 0.4,
    "prefix": "",
    "mode": "static",
    # 仕様: docs/spec/device-selection.md（撮影する端末の識別子。空なら端末が1台のときだけ自動で使う）
    "device": "",
}

# 仕様: docs/spec/manual-capture.md
# 自動撮影が「撮影中」の間、手動撮影が同じ受信中フレームを使えるようにするための参照。
# 撮影中でなければ None。
active_receiver = None
active_device = None
# 手動撮影の連打による多重保存を防ぐためのロック。
manual_capture_lock = threading.Lock()

# 仕様: docs/spec/session-grouping.md
# いずれもアプリを終了すると失われる（永続化しない）。
# 次に開始するセッションへ振る番号のカウンタ。
session_counter = 0
# 実行中のセッションID。Noneの間に撮影された画像は「未分類」として扱う。
current_session_id = None
# セッションID -> {"startedAt": "YYYY/MM/DD HH:MM:SS"}
sessions = {}
# ファイル名 -> セッションID（未登録のファイルは「未分類」）
image_sessions = {}
