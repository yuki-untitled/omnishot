import collections

# 仕様: README.md#✨-主な機能
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
}
