# 仕様: docs/spec/screenshot-capture.md
# 仕様: docs/spec/manual-capture.md
# 画面の解読・変化の判定・保存ファイル名・自動撮影のループ・手動撮影
import struct
import types

import cv2
import numpy as np
import pytest

from omnishot import capture, state
from omnishot.stream_receivers import decode_raw_screencap


def solid(value, size=40):
    return np.full((size, size, 3), value, dtype=np.uint8)


# ---------------------------------------------------------------------------
# raw の screencap の解読
# 仕様: docs/spec/bugs/LOCAL-020_Androidの画面取得に1コマ約1秒かかり自動撮影の反応が遅い.md
# ---------------------------------------------------------------------------
def _raw(w, h, fmt, rgba, colorspace=True):
    header = struct.pack("<III", w, h, fmt) + (struct.pack("<I", 0) if colorspace else b"")
    return header + bytes(rgba) * (w * h)


@pytest.mark.parametrize("fmt, pixel, expected_bgr", [
    (1, (10, 20, 30, 255), [30, 20, 10]),  # RGBA_8888
    (2, (10, 20, 30, 255), [30, 20, 10]),  # RGBX_8888
    (5, (10, 20, 30, 255), [10, 20, 30]),  # BGRA_8888
])
def test_decode_raw_pixel_formats(fmt, pixel, expected_bgr):
    frame = decode_raw_screencap(_raw(3, 2, fmt, pixel))
    assert frame.shape == (2, 3, 3)
    assert frame[0, 0].tolist() == expected_bgr


def test_decode_raw_without_colorspace_header():
    frame = decode_raw_screencap(_raw(3, 2, 1, (1, 2, 3, 255), colorspace=False))
    assert frame.shape == (2, 3, 3)


@pytest.mark.parametrize("data", [
    b"",
    b"\x00" * 11,
    _raw(3, 2, 4, (1, 2, 3, 4)),                  # 未対応の形式
    _raw(3, 2, 1, (1, 2, 3, 4))[:-1],             # 長さが合わない
    struct.pack("<III", 0, 0, 1),                 # 幅・高さが0
    cv2.imencode(".png", solid(0))[1].tobytes(),  # PNG
])
def test_decode_raw_rejects_unreadable_data(data):
    assert decode_raw_screencap(data) is None


# ---------------------------------------------------------------------------
# 変化の判定
# ---------------------------------------------------------------------------
def test_first_frame_becomes_baseline():
    assert capture.process_frame_changed(solid(0)) is False
    assert state.last_frame_data is not None


def test_none_frame_is_not_changed():
    assert capture.process_frame_changed(None) is False


def test_change_detected_without_moving_average():
    capture.process_frame_changed(solid(0), use_moving_average=False)
    assert capture.process_frame_changed(solid(0), use_moving_average=False) is False
    assert capture.process_frame_changed(solid(1), use_moving_average=False) is True


def test_moving_average_smooths_small_change():
    capture.process_frame_changed(solid(0))
    # 0 のままのコマが2つあると、次に 1 だけ変わっても平均 1/3 ≒ 0.33 > 0.25 で変化あり
    assert capture.process_frame_changed(solid(0)) is False
    assert capture.process_frame_changed(solid(0)) is False
    assert capture.process_frame_changed(solid(1)) is True


def test_static_mode_threshold_is_higher():
    capture.process_frame_changed(solid(0), use_moving_average=False)
    # 0.4 相当の変化: 通常（0.25）では変化、静的の閾値（0.5）では変化なし
    frame = solid(0)
    frame[: int(40 * 0.4)] = 1
    assert capture.process_frame_changed(frame, is_static_mode=True, use_moving_average=False) is False
    assert capture.process_frame_changed(frame, is_static_mode=False, use_moving_average=False) is True


def test_size_change_resets_baseline():
    capture.process_frame_changed(solid(0, size=40), use_moving_average=False)
    assert capture.process_frame_changed(solid(200, size=20), use_moving_average=False) is False


# ---------------------------------------------------------------------------
# 保存ファイル名
# ---------------------------------------------------------------------------
@pytest.fixture
def fixed_time(monkeypatch):
    fake = types.SimpleNamespace(
        strftime=lambda fmt: "20260924_153000" if "%Y%m%d" in fmt else "15:30:00",
        time=lambda: 0.0, sleep=lambda s: None)
    monkeypatch.setattr(capture, "time", fake)
    return fake


@pytest.mark.parametrize("device_type, prefix, manual, expected", [
    ("ios", "", False, "iOS_20260924_153000.png"),
    ("android", "", False, "Android_20260924_153000.png"),
    ("android", "login", False, "login_Android_20260924_153000.png"),
    ("ios", "", True, "Manual_iOS_20260924_153000.png"),
    ("ios", "login", True, "login_Manual_iOS_20260924_153000.png"),
])
def test_save_frame_file_name(save_dir, fixed_time, device_type, prefix, manual, expected):
    name = capture._save_frame(solid(0), device_type, prefix, manual=manual)
    assert name == expected
    assert (save_dir / expected).exists()


def test_save_frame_records_session(save_dir, fixed_time):
    state.current_session_id = 3
    name = capture._save_frame(solid(0), "ios", "")
    assert state.image_sessions == {name: 3}


def test_save_frame_without_session_is_unclassified(save_dir, fixed_time):
    capture._save_frame(solid(0), "ios", "")
    assert state.image_sessions == {}


# ---------------------------------------------------------------------------
# 自動撮影のループ
# 受信は台本どおりのコマを返し、「待つ」たびに次のコマが届く。台本が尽きたら停止する。
# ---------------------------------------------------------------------------
class ScriptedReceiver:
    def __init__(self, frames, healthy_until=None):
        # 保存したコマを番号で見分けられるよう、コマごとに別の配列にする
        self.frames = [f.copy() for f in frames]
        self.index = -1
        self._latest = None
        self.frame_seq = 0
        self.last_error = None
        self.healthy_until = healthy_until
        self.started = False
        self.stopped = False

    @property
    def latest_frame(self):
        return self._latest

    @latest_frame.setter
    def latest_frame(self, value):
        self._latest = value

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def is_healthy(self):
        return self.healthy_until is None or self.index < self.healthy_until

    def advance(self):
        self.index += 1
        if self.index >= len(self.frames):
            state.is_running = False
            return
        self._latest = self.frames[self.index]
        self.frame_seq += 1


def run_loop(monkeypatch, receivers, mode, interval=0.1, settling=0.3, start_results=None):
    """自動撮影のループを台本で動かし、(保存したコマの台本上の番号, ログ) を返す。"""
    receivers = list(receivers)
    current = {"receiver": None}
    saved, logs = [], []

    def create_receiver(device):
        current["receiver"] = receivers.pop(0)
        return current["receiver"]

    def sleep(seconds):
        current["receiver"].advance() if current["receiver"] else None

    def save_frame(frame, device_type, prefix, manual=False):
        receiver = current["receiver"]
        saved.append(next(i for i, f in enumerate(receiver.frames) if f is frame))
        return "x.png"

    starts = iter(start_results or [])
    device = {"id": "A", "os": "android", "name": None}
    monkeypatch.setattr(capture, "time", types.SimpleNamespace(sleep=sleep, time=lambda: 0.0, strftime=lambda f: ""))
    monkeypatch.setattr(capture, "_create_receiver", create_receiver)
    monkeypatch.setattr(capture, "_save_frame", save_frame)
    monkeypatch.setattr(capture, "add_log", logs.append)
    monkeypatch.setattr(capture.dev_manager, "start_stream", lambda device_id: next(starts, (device, None)))
    monkeypatch.setattr(capture.dev_manager, "stop_stream", lambda: None)
    monkeypatch.setattr(capture.dev_manager, "last_stream_error", None)

    state.current_config.update({"mode": mode, "interval": interval, "settling": settling, "device": "A", "prefix": ""})
    state.is_running = True
    state.current_session_id = 1
    capture.auto_capture_loop()
    return saved, logs


def test_dynamic_mode_captures_after_judge_count(monkeypatch):
    a, b = solid(0), solid(100)
    frames = [a, a, a, b, b, b, b, b, b]
    saved, logs = run_loop(monkeypatch, [ScriptedReceiver(frames)], "dynamic")
    # 最初のコマで1枚目、動いた後に3回静止して1枚。撮影後は動くまで撮らない
    assert saved == [2, 6]
    assert logs.count("🎬 画面動作中...") == 1
    assert "📊 静止確認: 3/3" in logs
    assert state.current_session_id is None


def test_dynamic_mode_resets_count_when_moving_again(monkeypatch):
    a, b, c = solid(0), solid(100), solid(200)
    frames = [a, b, b, c, c, c, c]
    saved, _ = run_loop(monkeypatch, [ScriptedReceiver(frames)], "dynamic")
    assert saved == [6]


def test_dynamic_mode_uses_rounded_judge_count(monkeypatch):
    # 仕様: docs/spec/bugs/LOCAL-022_動的モードで判定回数が設定より1回少なくなる組み合わせがある.md
    a = solid(0)
    frames = [a] * 5
    saved, logs = run_loop(monkeypatch, [ScriptedReceiver(frames)], "dynamic", interval=0.1, settling=0.1 * 3)
    assert saved == [2]
    assert "📊 静止確認: 3/3" in logs


def test_static_mode_captures_after_change(monkeypatch):
    a, b = solid(0), solid(100)
    frames = [a, b] + [b] * 30
    saved, logs = run_loop(monkeypatch, [ScriptedReceiver(frames)], "static", settling=0.4)
    # 変化を検知すると settling 待った後の最新のコマを保存し、その後は同じ画面では撮らない
    assert saved == [2]
    assert "🎬 変化検知... 待機中 (0.4s)" in logs


def test_reconnects_after_disconnect(monkeypatch):
    a = solid(0)
    first = ScriptedReceiver([a, a, a], healthy_until=1)
    first.last_error = "⚠️ Androidデバイスとの接続が切れました"
    second = ScriptedReceiver([a, a, a, a])
    saved, logs = run_loop(monkeypatch, [first, second], "dynamic")
    assert "⚠️ Androidデバイスとの接続が切れました" in logs
    assert "🔄 接続を再開しました（再接続 1/2）" in logs
    assert first.stopped and second.stopped
    assert state.active_receiver is None


def test_stops_after_too_many_reconnects(monkeypatch):
    a = solid(0)
    receivers = [ScriptedReceiver([a, a], healthy_until=0) for _ in range(3)]
    _, logs = run_loop(monkeypatch, receivers, "dynamic")
    assert "⚠️ 再接続に2回失敗したため、自動撮影を停止します。" in logs
    assert state.is_running is False


def test_start_failure_sets_error(monkeypatch):
    _, logs = run_loop(monkeypatch, [], "dynamic", start_results=[(None, "❌ だめ")])
    assert state.last_error == "❌ だめ"
    assert state.is_running is False
    assert logs == ["❌ だめ"]


# ---------------------------------------------------------------------------
# 手動撮影
# ---------------------------------------------------------------------------
def test_manual_capture_uses_running_receiver(monkeypatch, save_dir, fixed_time):
    state.is_running = True
    state.active_receiver = types.SimpleNamespace(latest_frame=solid(0))
    state.active_device = {"id": "A", "os": "android"}
    state.current_config["prefix"] = "p"
    assert capture.manual_capture("A") == ("p_Manual_Android_20260924_153000.png", None)


def test_manual_capture_without_frame_while_running(monkeypatch):
    state.is_running = True
    state.active_receiver = types.SimpleNamespace(latest_frame=None)
    state.active_device = {"id": "A", "os": "android"}
    filename, error = capture.manual_capture("A")
    assert filename is None and "画面を取得できませんでした" in error


def test_manual_capture_when_stopped(monkeypatch, save_dir, fixed_time):
    monkeypatch.setattr(capture.dev_manager, "resolve_device", lambda device_id: ({"id": "I", "os": "ios"}, None))
    monkeypatch.setattr(capture.dev_manager, "capture_single_frame", lambda device: solid(0))
    assert capture.manual_capture("I") == ("Manual_iOS_20260924_153000.png", None)


def test_manual_capture_device_error(monkeypatch):
    monkeypatch.setattr(capture.dev_manager, "resolve_device", lambda device_id: (None, "❌ 未接続"))
    assert capture.manual_capture("I") == (None, "❌ 未接続")


def test_manual_capture_rejects_concurrent_request():
    assert state.manual_capture_lock.acquire(blocking=False)
    try:
        filename, error = capture.manual_capture("A")
    finally:
        state.manual_capture_lock.release()
    assert filename is None and "手動撮影を処理中です" in error


def test_android_receiver_uses_selected_device():
    receiver = capture._create_receiver({"id": "SER", "os": "android"})
    assert receiver.screencap_command == [capture.dev_manager.adb, "-s", "SER", "exec-out", "screencap"]


@pytest.mark.parametrize("use_raw, expected_tail", [(True, ["screencap"]), (False, ["screencap", "-p"])])
def test_android_receiver_command(monkeypatch, use_raw, expected_tail):
    from omnishot import stream_receivers
    seen = []
    receiver = stream_receivers.AndroidScreencapReceiver(["adb", "-s", "SER", "exec-out", "screencap"])
    receiver.use_raw = use_raw
    monkeypatch.setattr(stream_receivers.subprocess, "run",
                        lambda cmd, **kw: seen.append(cmd) or types.SimpleNamespace(stdout=b""))
    assert receiver._capture_once()[1] is None
    assert seen[0][-len(expected_tail):] == expected_tail
