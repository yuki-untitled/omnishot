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


# 仕様: docs/spec/session-grouping.md（セッション名の変更・セッション単位のダウンロード）
def _session(session_id, *names, name=None):
    state.sessions[session_id] = {"startedAt": "2026/09/29 10:00:00"}
    if name:
        state.sessions[session_id]["name"] = name
    for n in names:
        state.image_sessions[n] = session_id


def test_rename_session(client):
    _session(1)
    res = client.post("/rename_session", json={"sessionId": 1, "name": "  ログイン手順 "})
    assert res.get_json() == {"sessionId": 1, "name": "ログイン手順"}
    assert state.sessions[1]["name"] == "ログイン手順"
    # /images にも名前が含まれる
    assert client.get("/images").get_json()["sessions"]["1"]["name"] == "ログイン手順"
    # 空にすると未設定に戻る
    client.post("/rename_session", json={"sessionId": 1, "name": " "})
    assert "name" not in state.sessions[1]


def test_rename_session_limits(client):
    _session(1)
    assert client.post("/rename_session", json={"sessionId": 1, "name": "あ" * 50}).status_code == 200
    assert client.post("/rename_session", json={"sessionId": 1, "name": "あ" * 51}).status_code == 400
    assert client.post("/rename_session", json={"sessionId": 9, "name": "x"}).status_code == 404
    assert client.post("/rename_session", json={"sessionId": None, "name": "x"}).status_code == 404
    assert client.post("/rename_session", json={"sessionId": True, "name": "x"}).status_code == 404


def test_download_session_numbers_files(client, save_dir):
    for i, n in enumerate(["a.png", "b.png", "c.png", "other.png", "loose.png"]):
        _touch(save_dir, n, 100 + i)
    _session(1, "a.png", "b.png", "c.png", name="ログイン/手順")
    _session(2, "other.png")
    client.post("/rename", json={"filename": "b.png", "displayName": "確認画面"})

    res = client.post("/download_session", json={"sessionId": 1})
    assert res.status_code == 200
    assert res.headers["X-Zip-Name"] == "%E3%83%AD%E3%82%B0%E3%82%A4%E3%83%B3_%E6%89%8B%E9%A0%86.zip"
    with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
        assert zf.namelist() == ["001_a.png", "002_確認画面.png", "003_c.png"]


def test_download_session_applies_order(client, save_dir):
    for i, n in enumerate(["a.png", "b.png", "c.png"]):
        _touch(save_dir, n, 100 + i)
    _session(1, "a.png", "b.png", "c.png")
    _session(2)  # 別セッションの画像や存在しない画像は、順序に含めても無視される
    state.image_sessions["z.png"] = 2
    res = client.post("/download_session", json={"sessionId": 1, "order": ["c.png", "z.png", "gone.png", "a.png"]})
    assert res.headers["X-Zip-Name"] == "%E3%82%BB%E3%83%83%E3%82%B7%E3%83%A7%E3%83%B31.zip"
    with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
        assert zf.namelist() == ["001_c.png", "002_a.png", "003_b.png"]


def test_download_session_unclassified(client, save_dir):
    _touch(save_dir, "a.png", 100)
    _touch(save_dir, "loose.png", 200)
    _session(1, "a.png")
    res = client.post("/download_session", json={"sessionId": None})
    assert res.headers["X-Zip-Name"] == "%E6%9C%AA%E5%88%86%E9%A1%9E.zip"
    with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
        assert zf.namelist() == ["001_loose.png"]


@pytest.mark.parametrize("body, status", [
    ({"sessionId": 9}, 404),
    ({"sessionId": 1}, 400),  # 画像が1枚もない
    ({"sessionId": 1, "order": ["../a.png"]}, 400),
    ({"sessionId": 1, "order": "a.png"}, 400),
])
def test_download_session_rejects(client, body, status):
    _session(1)
    assert client.post("/download_session", json=body).status_code == status


def test_download_selected_is_not_numbered(client, save_dir):
    _touch(save_dir, "a.png", 100)
    res = client.post("/download_selected", json={"filenames": ["a.png"]})
    with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
        assert zf.namelist() == ["a.png"]


# 仕様: docs/spec/bugs/LOCAL-037_新しい順でも新しいセッションが上に表示されない.md
def test_images_are_newest_first_by_time_not_by_name(client, save_dir):
    _touch(save_dir, "login_iOS_20260929_100000.png", 100)  # 名前は大きいが、撮影は古い
    _touch(save_dir, "Android_20260929_100500.png", 200)
    _touch(save_dir, "Manual_iOS_20260929_101000.png", 300)
    assert client.get("/images").get_json()["images"] == [
        "Manual_iOS_20260929_101000.png", "Android_20260929_100500.png", "login_iOS_20260929_100000.png"]


def test_images_with_same_time_are_ordered_by_name(client, save_dir):
    _touch(save_dir, "a.png", 100)
    _touch(save_dir, "b.png", 100)
    assert client.get("/images").get_json()["images"] == ["b.png", "a.png"]
