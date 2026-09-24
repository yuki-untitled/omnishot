# 仕様: docs/spec/gallery.md
# 仕様: docs/spec/session-grouping.md
# 仕様: docs/spec/device-selection.md
# 画面からの要求（Flask のエンドポイント）
import io
import os
import zipfile

import pytest

from omnishot import create_app, state
from omnishot.device_manager import DEVICE_NOT_CONNECTED_MESSAGE, dev_manager


@pytest.fixture
def client(save_dir):
    app = create_app()
    app.testing = True
    return app.test_client()


def _touch(save_dir, name, mtime):
    mtime += 1_790_000_000  # ZIP は1980年より前の時刻を扱えないため
    path = save_dir / name
    path.write_bytes(b"png")
    os.utime(path, (mtime, mtime))


def test_status(client):
    state.last_error = DEVICE_NOT_CONNECTED_MESSAGE
    assert client.get("/status").get_json() == {
        "is_running": False, "error": DEVICE_NOT_CONNECTED_MESSAGE, "device_missing": True, "mode": "static"}


def test_devices_logs_android_problems(client, monkeypatch):
    logged = []
    monkeypatch.setattr(dev_manager, "list_devices", lambda: [{"id": "A", "os": "android", "name": None}])
    monkeypatch.setattr(dev_manager, "android_device_problems", ["⚠️ Android端末（…ABC123）: だめ"])
    monkeypatch.setattr("omnishot.routes.add_log", logged.append)
    assert client.get("/devices").get_json() == [{"id": "A", "os": "android", "name": None}]
    assert logged == ["⚠️ Android端末（…ABC123）: だめ"]


def test_images_newest_first_with_names_and_sessions(client, save_dir):
    _touch(save_dir, "iOS_1.png", 100)
    _touch(save_dir, "iOS_2.png", 200)
    (save_dir / "note.txt").write_text("x")
    (save_dir / "display_names.json").write_text('{"iOS_1.png": "一枚目", "gone.png": "消えた"}', encoding="utf-8")
    state.sessions[1] = {"startedAt": "2026/09/24 15:30:00"}
    state.image_sessions.update({"iOS_2.png": 1, "gone.png": 1})
    assert client.get("/images").get_json() == {
        "images": ["iOS_2.png", "iOS_1.png"],
        "displayNames": {"iOS_1.png": "一枚目"},
        "imageSessions": {"iOS_2.png": 1},
        "sessions": {"1": {"startedAt": "2026/09/24 15:30:00"}},
    }


def test_rename_and_clear_display_name(client, save_dir):
    _touch(save_dir, "iOS_1.png", 100)
    assert client.post("/rename", json={"filename": "iOS_1.png", "displayName": " 名前 "}).get_json() == {
        "filename": "iOS_1.png", "displayName": "名前"}
    assert client.post("/rename", json={"filename": "iOS_1.png", "displayName": ""}).get_json() == {
        "filename": "iOS_1.png", "displayName": None}


@pytest.mark.parametrize("filename, status", [("../x.png", 400), ("", 400), ("none.png", 404)])
def test_rename_rejects_bad_filename(client, filename, status):
    assert client.post("/rename", json={"filename": filename, "displayName": "a"}).status_code == status


def test_delete_selected_removes_files_names_and_sessions(client, save_dir):
    _touch(save_dir, "a.png", 100)
    _touch(save_dir, "b.png", 100)
    client.post("/rename", json={"filename": "a.png", "displayName": "A"})
    state.image_sessions.update({"a.png": 1, "b.png": 1})
    assert client.post("/delete_selected", json={"filenames": ["a.png"]}).status_code == 200
    assert not (save_dir / "a.png").exists() and (save_dir / "b.png").exists()
    assert state.image_sessions == {"b.png": 1}
    assert client.get("/images").get_json()["displayNames"] == {}


@pytest.mark.parametrize("filenames", [["../a.png"], ["a.png", "sub/b.png"], [".."], "a.png", [1]])
def test_delete_selected_rejects_bad_names(client, save_dir, filenames):
    _touch(save_dir, "a.png", 100)
    assert client.post("/delete_selected", json={"filenames": filenames}).status_code == 400
    assert (save_dir / "a.png").exists()


def test_clear_all(client, save_dir):
    _touch(save_dir, "a.png", 100)
    state.image_sessions["a.png"] = 1
    assert client.post("/clear_all").status_code == 200
    assert list(save_dir.iterdir()) == []
    assert state.image_sessions == {}


def test_download_selected_uses_display_names(client, save_dir):
    _touch(save_dir, "a.png", 100)
    _touch(save_dir, "b.png", 100)
    client.post("/rename", json={"filename": "a.png", "displayName": "ログイン/画面.PNG"})
    res = client.post("/download_selected", json={"filenames": ["a.png", "b.png", "none.png"], "zipName": "まとめ"})
    assert res.status_code == 200
    assert "filename*=UTF-8''%E3%81%BE%E3%81%A8%E3%82%81.zip" in res.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
        assert zf.namelist() == ["ログイン画面.png", "b.png"]


def test_download_selected_default_zip_name(client, save_dir):
    _touch(save_dir, "a.png", 100)
    res = client.post("/download_selected", json={"filenames": ["a.png"], "zipName": "/"})
    assert "filename=captures_" in res.headers["Content-Disposition"]


@pytest.mark.parametrize("filenames, status", [([], 400), (["../a.png"], 400)])
def test_download_selected_rejects(client, filenames, status):
    assert client.post("/download_selected", json={"filenames": filenames}).status_code == status


def test_update_settings(client):
    client.get("/update_settings?interval=0.5&settling=1.5&mode=dynamic&prefix=p")
    assert state.current_config == {"interval": 0.5, "settling": 1.5, "prefix": "p", "mode": "dynamic", "device": ""}


def test_start_creates_session_and_runs_loop(client, monkeypatch):
    started = []
    monkeypatch.setattr("omnishot.routes.auto_capture_loop", lambda: started.append(state.current_session_id))
    client.get("/start?interval=0.1&settling=0.3&mode=dynamic&device=A")
    assert state.is_running is True
    assert state.current_config["device"] == "A"
    assert state.current_session_id == 1 and list(state.sessions) == [1]
    # 撮影中にもう一度押しても、新しいセッションは作らない
    client.get("/start?interval=0.1&settling=0.3&mode=dynamic&device=A")
    assert list(state.sessions) == [1]
    client.get("/stop")
    assert state.is_running is False


def test_manual_capture_route(client, monkeypatch):
    monkeypatch.setattr("omnishot.routes.manual_capture", lambda device_id: ("x.png", None))
    assert client.post("/manual_capture?device=A").get_json() == {"filename": "x.png"}
    monkeypatch.setattr("omnishot.routes.manual_capture", lambda device_id: (None, DEVICE_NOT_CONNECTED_MESSAGE))
    res = client.post("/manual_capture?device=A")
    assert res.status_code == 400
    assert res.get_json() == {"error": DEVICE_NOT_CONNECTED_MESSAGE, "device_missing": True}


def test_settings_default_when_not_sent(client):
    # 仕様: docs/spec/screenshot-capture.md#実現内容what（設定の初期値）
    client.get("/update_settings")
    assert (state.current_config["interval"], state.current_config["settling"]) == (0.3, 1.0)
