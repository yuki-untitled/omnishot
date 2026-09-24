import sys

import pytest

import omnishot  # noqa: F401  (パッケージを先に読み込み、SAVE_DIR を持つモジュールを揃える)
from omnishot import capture, display_names, routes, state  # noqa: F401


@pytest.fixture
def save_dir(tmp_path, monkeypatch):
    """キャプチャの保存先を一時フォルダに差し替える。"""
    for name, module in list(sys.modules.items()):
        if not name.startswith("omnishot"):
            continue
        if hasattr(module, "SAVE_DIR"):
            monkeypatch.setattr(module, "SAVE_DIR", str(tmp_path))
        if hasattr(module, "DISPLAY_NAMES_FILE"):
            monkeypatch.setattr(module, "DISPLAY_NAMES_FILE", str(tmp_path / "display_names.json"))
    return tmp_path


@pytest.fixture(autouse=True)
def go_ios_work_dir(tmp_path, monkeypatch):
    """go-ios の作業フォルダを一時フォルダに差し替える（テストで ~/Library/Application Support を作らない）。"""
    from omnishot import paths
    work_dir = tmp_path / "go-ios-work"
    monkeypatch.setattr(paths, "GO_IOS_WORK_DIR", str(work_dir))
    return work_dir


@pytest.fixture(autouse=True)
def reset_state():
    """テストごとに共有状態を初期化する。"""
    state.score_history.clear()
    state.is_running = False
    state.last_error = None
    state.last_frame_data = None
    state.current_config.update({"interval": state.DEFAULT_INTERVAL, "settling": state.DEFAULT_SETTLING, "prefix": "", "mode": "static", "device": ""})
    state.active_receiver = None
    state.active_device = None
    state.session_counter = 0
    state.current_session_id = None
    state.sessions.clear()
    state.image_sessions.clear()
    yield
