# 仕様: docs/spec/device-selection.md
# 端末の一覧の検出（adb・go-ios の出力の解析）と、撮影する端末の決定
import io
import json
import subprocess
import types

import pytest

from omnishot import device_manager as dm_module
from omnishot.device_manager import DEVICE_NOT_CONNECTED_MESSAGE, DeviceManager


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def manager():
    return DeviceManager()


ADB_HEADER = "List of devices attached\n"


def test_android_lists_usb_devices_with_model_name(manager, monkeypatch):
    out = ADB_HEADER + "ZY22ABC123 device usb:1-1 product:x model:moto_g24 device:y transport_id:1\n"
    monkeypatch.setattr(manager, "_adb_devices", lambda: _completed(out))
    assert manager._list_android_devices() == [{"id": "ZY22ABC123", "os": "android", "name": "moto g24"}]
    assert manager.android_device_problems == []


def test_android_without_model_has_no_name(manager, monkeypatch):
    out = ADB_HEADER + "ZY22ABC123 device usb:1-1\n"
    monkeypatch.setattr(manager, "_adb_devices", lambda: _completed(out))
    assert manager._list_android_devices() == [{"id": "ZY22ABC123", "os": "android", "name": None}]


def test_android_excludes_wifi_devices(manager, monkeypatch):
    out = ADB_HEADER + "192.168.0.5:5555 device product:x model:Pixel_7 transport_id:2\n"
    monkeypatch.setattr(manager, "_adb_devices", lambda: _completed(out))
    assert manager._list_android_devices() == []
    assert manager.android_device_problems == []


@pytest.mark.parametrize("state_word, expected", [
    ("unauthorized", "USBデバッグが許可されていません"),
    ("offline", "端末が応答していません"),
    ("authorizing", "USBデバッグの許可を確認しています"),
    ("recovery", "撮影できる状態ではありません（adbの状態: recovery）"),
])
def test_android_not_ready_devices_are_reported(manager, monkeypatch, state_word, expected):
    out = ADB_HEADER + f"ZY22ABC123 {state_word} usb:1-1 transport_id:1\n"
    monkeypatch.setattr(manager, "_adb_devices", lambda: _completed(out))
    assert manager._list_android_devices() == []
    assert len(manager.android_device_problems) == 1
    assert manager.android_device_problems[0].startswith("⚠️ Android端末（…ABC123）: ")
    assert expected in manager.android_device_problems[0]


def test_android_no_permissions_state(manager, monkeypatch):
    out = ADB_HEADER + "ZY22ABC123 no permissions (user in plugdev group) usb:1-1\n"
    monkeypatch.setattr(manager, "_adb_devices", lambda: _completed(out))
    assert manager._list_android_devices() == []
    assert "adbの状態: no permissions" in manager.android_device_problems[0]


def test_android_rechecks_once_after_server_start(manager, monkeypatch):
    # 仕様: docs/spec/native-window.md（adb サーバーを起動した直後に端末が0台なら、1秒待って1回だけ検出し直す）
    results = iter([
        _completed(ADB_HEADER, stderr="* daemon not running; starting now at tcp:5037\n* daemon started successfully\n"),
        _completed(ADB_HEADER + "ZY22ABC123 device usb:1-1 model:moto_g24\n"),
    ])
    calls = []
    monkeypatch.setattr(manager, "_adb_devices", lambda: calls.append(1) or next(results))
    monkeypatch.setattr(dm_module.time, "sleep", lambda s: None)
    assert [d["id"] for d in manager._list_android_devices()] == ["ZY22ABC123"]
    assert len(calls) == 2


def test_android_does_not_recheck_without_server_start(manager, monkeypatch):
    calls = []
    monkeypatch.setattr(manager, "_adb_devices", lambda: calls.append(1) or _completed(ADB_HEADER))
    assert manager._list_android_devices() == []
    assert len(calls) == 1


def test_android_adb_failure_returns_empty(manager, monkeypatch):
    def fail():
        raise FileNotFoundError("adb")
    monkeypatch.setattr(manager, "_adb_devices", fail)
    assert manager._list_android_devices() == []
    assert manager.android_device_problems == []


def _fake_ios_run(list_stdout, names):
    def run(cmd, **kwargs):
        if cmd[1] == "list":
            return _completed(list_stdout)
        udid = cmd[1][len("--udid="):]
        name = names.get(udid)
        return _completed(json.dumps({"DeviceName": name}) + "\n" if name else "")
    return run


def test_ios_lists_usb_devices_without_duplicates(manager, monkeypatch):
    list_out = '{"level":"info","msg":"x"}\n' + json.dumps({"deviceList": ["AAA111", "BBB222", "AAA111"]}) + "\n"
    monkeypatch.setattr(dm_module.subprocess, "run", _fake_ios_run(list_out, {"AAA111": "Eidome's iPhone"}))
    monkeypatch.setattr(dm_module, "_usbmuxd_connection_types", lambda: {"AAA111": "USB", "BBB222": "USB"})
    assert manager._list_ios_devices() == [
        {"id": "AAA111", "os": "ios", "name": "Eidome's iPhone"},
        {"id": "BBB222", "os": "ios", "name": None},
    ]


def test_ios_excludes_network_only_devices(manager, monkeypatch):
    list_out = json.dumps({"deviceList": ["AAA111", "BBB222"]}) + "\n"
    monkeypatch.setattr(dm_module.subprocess, "run", _fake_ios_run(list_out, {}))
    monkeypatch.setattr(dm_module, "_usbmuxd_connection_types", lambda: {"AAA111": "Network", "BBB222": "USB"})
    assert [d["id"] for d in manager._list_ios_devices()] == ["BBB222"]


def test_ios_keeps_devices_when_usbmuxd_unavailable(manager, monkeypatch):
    list_out = json.dumps({"deviceList": ["AAA111"]}) + "\n"
    monkeypatch.setattr(dm_module.subprocess, "run", _fake_ios_run(list_out, {}))
    monkeypatch.setattr(dm_module, "_usbmuxd_connection_types", lambda: None)
    assert [d["id"] for d in manager._list_ios_devices()] == ["AAA111"]


def test_list_devices_puts_android_first(manager, monkeypatch):
    monkeypatch.setattr(manager, "_list_android_devices", lambda: [{"id": "A", "os": "android", "name": None}])
    monkeypatch.setattr(manager, "_list_ios_devices", lambda: [{"id": "I", "os": "ios", "name": None}])
    assert [d["id"] for d in manager.list_devices()] == ["A", "I"]


def test_resolve_device_requires_selection(manager):
    device, message = manager.resolve_device("")
    assert device is None
    assert "撮影する端末が選ばれていません" in message


def test_resolve_device_returns_connected_device(manager, monkeypatch):
    monkeypatch.setattr(manager, "list_devices", lambda: [{"id": "A", "os": "android", "name": None}])
    assert manager.resolve_device("A") == ({"id": "A", "os": "android", "name": None}, None)


def test_resolve_device_retries_once_when_empty(manager, monkeypatch):
    results = iter([[], [{"id": "A", "os": "android", "name": None}]])
    monkeypatch.setattr(manager, "list_devices", lambda: next(results))
    monkeypatch.setattr(dm_module.time, "sleep", lambda s: None)
    assert manager.resolve_device("A")[0]["id"] == "A"


def test_resolve_device_missing(manager, monkeypatch):
    monkeypatch.setattr(manager, "list_devices", lambda: [{"id": "B", "os": "android", "name": None}])
    assert manager.resolve_device("A") == (None, DEVICE_NOT_CONNECTED_MESSAGE)


# 仕様: docs/spec/bugs/LOCAL-025_iOSのトンネルに古い接続が残ると撮影を開始できず理由も表示されない.md
@pytest.mark.parametrize("line, expected", [
    ('{"level":"ERROR","msg":"could not connect to RSD"}', "could not connect to RSD"),
    ('{"level":"fatal","msg":"boom"}', "boom"),
    ('{"level":"error"}', '{"level":"error"}'),
    ('{"level":"INFO","msg":"hello"}', None),
    ("not json", None),
    ("[1, 2]", None),
])
def test_go_ios_error_message(line, expected):
    assert dm_module.go_ios_error_message(line) == expected


@pytest.mark.parametrize("message, expected", [
    ("could not connect to RSD, host fd03::1", True),
    ("something else", False),
    (None, False),
    ("", False),
])
def test_is_ios_tunnel_unreachable(message, expected):
    assert dm_module.is_ios_tunnel_unreachable(message) is expected


def test_stop_ios_tunnel_does_not_enable_agent(manager, monkeypatch):
    # 仕様: docs/spec/bugs/LOCAL-030_終了時にiOSのトンネルが動いていないとトンネルが起動して残る.md
    seen = types.SimpleNamespace(cmd=None, env=None)

    def run(cmd, env=None, **kwargs):
        seen.cmd, seen.env = cmd, env
        return _completed()
    monkeypatch.setenv("ENABLE_GO_IOS_AGENT", "user")
    monkeypatch.setattr(dm_module.subprocess, "run", run)
    assert manager.stop_ios_tunnel() is True
    assert seen.cmd[1:] == ["tunnel", "stopagent"]
    assert "ENABLE_GO_IOS_AGENT" not in seen.env


@pytest.mark.parametrize("agent, expected", [(True, "user"), (False, None)])
def test_go_ios_env(monkeypatch, agent, expected):
    monkeypatch.setenv("ENABLE_GO_IOS_AGENT", "kernel")
    assert dm_module._go_ios_env(agent).get("ENABLE_GO_IOS_AGENT") == expected


# 仕様: docs/spec/bugs/LOCAL-032_アプリ化するとiOSのトンネルが起動できずトンネルの起動が連鎖し続ける.md
@pytest.mark.parametrize("call", [
    lambda m: m._list_ios_devices(),
    lambda m: m._ios_device_name("U"),
    lambda m: m._ios_screenshot_once({"id": "U", "os": "ios"}),
    lambda m: m._ios_tunnel_endpoint("U"),
    lambda m: m.stop_ios_tunnel(),
])
def test_go_ios_runs_in_work_dir(manager, monkeypatch, go_ios_work_dir, call):
    cwds = []
    def run(cmd, cwd=None, **kwargs):
        cwds.append(cwd)
        return _completed(json.dumps({"deviceList": []}) + "\n" if cmd[1] == "list" else "")
    monkeypatch.setattr(dm_module.subprocess, "run", run)
    call(manager)
    assert cwds and all(c == str(go_ios_work_dir) for c in cwds)
    assert go_ios_work_dir.is_dir()


def test_ios_stream_runs_in_work_dir(manager, monkeypatch, go_ios_work_dir):
    seen = {}
    class FakePopen:
        def __init__(self, cmd, cwd=None, **kwargs):
            seen["cwd"] = cwd
            self.stderr = io.BytesIO(b"")
        def poll(self):
            return 1
    monkeypatch.setattr(dm_module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(manager, "cleanup_all_processes", lambda: None)
    manager._start_ios_stream({"id": "U", "os": "ios"}, timeout=0.1)
    assert seen["cwd"] == str(go_ios_work_dir)


def test_adb_command(manager):
    assert manager.adb_command("SER", "exec-out", "screencap") == [manager.adb, "-s", "SER", "exec-out", "screencap"]
    assert manager.adb_command("", "devices") == [manager.adb, "devices"]


# 仕様: docs/spec/manual-capture.md（停止中の手動撮影は、1回分のコマンドで画面を取得する）
def test_android_single_frame(manager, monkeypatch):
    import cv2
    import numpy as np
    png = cv2.imencode(".png", np.zeros((4, 4, 3), dtype=np.uint8))[1].tobytes()
    seen = []
    monkeypatch.setattr(dm_module.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or _completed(png))
    frame = manager.capture_single_frame({"id": "SER", "os": "android"})
    assert frame.shape == (4, 4, 3)
    assert seen == [[manager.adb, "-s", "SER", "exec-out", "screencap", "-p"]]


def test_android_single_frame_failure_is_logged(manager, monkeypatch):
    logs = []
    monkeypatch.setattr(dm_module, "add_log", logs.append)
    monkeypatch.setattr(dm_module.subprocess, "run", lambda cmd, **kw: _completed(b"", stderr=b"error: device offline"))
    assert manager.capture_single_frame({"id": "SER", "os": "android"}) is None
    assert logs == ["⚠️ Android screenshot failed: error: device offline"]


def test_ios_single_frame_retries_once_after_recovery(manager, monkeypatch):
    results = iter([(None, "could not connect to RSD"), ("FRAME", None)])
    monkeypatch.setattr(manager, "_ios_screenshot_once", lambda device: next(results))
    monkeypatch.setattr(manager, "recover_ios_connection", lambda udid, reason: reason == "could not connect to RSD")
    assert manager.capture_single_frame({"id": "U", "os": "ios"}) == "FRAME"


def test_ios_single_frame_reports_reason(manager, monkeypatch):
    logs = []
    monkeypatch.setattr(dm_module, "add_log", logs.append)
    monkeypatch.setattr(manager, "_ios_screenshot_once", lambda device: (None, "boom"))
    monkeypatch.setattr(manager, "recover_ios_connection", lambda udid, reason: False)
    assert manager.capture_single_frame({"id": "U", "os": "ios"}) is None
    assert logs == ["⚠️ iOS screenshot failed: boom"]


def test_ios_screenshot_once_reads_go_ios_error(manager, monkeypatch):
    stderr = b'{"level":"INFO","msg":"x"}\n{"level":"ERROR","msg":"could not connect to RSD"}\n'
    seen = types.SimpleNamespace(env=None)

    def run(cmd, env=None, **kw):
        seen.env = env
        return _completed(b"", stderr=stderr, returncode=1)
    monkeypatch.setattr(dm_module.subprocess, "run", run)
    assert manager._ios_screenshot_once({"id": "U", "os": "ios"}) == (None, "could not connect to RSD")
    assert seen.env["ENABLE_GO_IOS_AGENT"] == "user"
