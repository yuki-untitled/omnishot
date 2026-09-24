# 仕様: docs/spec/screenshot-capture.md
"""撮影: 画面の変化の判定、自動撮影のループ、手動撮影、画像の保存。"""
import os
import time

import cv2
import numpy as np

from . import state
from .device_manager import IOS_STREAM_PORT, dev_manager
from .logs import add_log
from .paths import SAVE_DIR
from .stream_receivers import AndroidScreencapReceiver, iOSStreamReceiver


DEVICE_LABELS = {"ios": "iOS", "android": "Android"}

# 仕様: docs/spec/screenshot-capture.md（接続の一時的な切断からの自動再接続）
# ストリーム接続はiOS/Android共通で不安定になることがあるため、切断のたびに
# 自動撮影全体を止めるのではなく、この回数までは黙って再接続を試みる。
MAX_RECONNECT_ATTEMPTS = 2
RECONNECT_DELAY = 1.5

# 変化ありとみなす差分（比較用の画像の画素の差の平均）
STATIC_MODE_THRESHOLD = 0.5
DEFAULT_THRESHOLD = 0.25

CAPTURE_FAILED_MESSAGE = "❌ 画面を取得できませんでした。時間を置いて再度お試しください。"


def _create_receiver(device):
    if device["os"] == "android":
        return AndroidScreencapReceiver(dev_manager.adb_command(device["id"], "exec-out", "screencap"))
    return iOSStreamReceiver(f"http://127.0.0.1:{IOS_STREAM_PORT}")


def _save_frame(frame, device_type, prefix, manual=False):
    """フレームをキャプチャ保存先へPNGとして保存し、保存したファイル名を返す。

    仕様: docs/spec/manual-capture.md（手動撮影は "Manual_" を付けて自動撮影と区別する）
    仕様: docs/spec/session-grouping.md（実行中のセッションがあれば、その画像として記録する）
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    device_label = DEVICE_LABELS.get(device_type.lower(), device_type.capitalize())
    manual_marker = "Manual_" if manual else ""
    final_name = f"{prefix}_{manual_marker}{device_label}_{timestamp}.png" if prefix else f"{manual_marker}{device_label}_{timestamp}.png"
    cv2.imwrite(os.path.join(SAVE_DIR, final_name), frame)
    if state.current_session_id is not None:
        state.image_sessions[final_name] = state.current_session_id
    add_log(f"📸 撮影完了: {final_name}")
    return final_name


# ---------------------------------------------------------------------------
# 手動撮影
# 仕様: docs/spec/manual-capture.md
# ---------------------------------------------------------------------------
def manual_capture(device_id):
    """手動撮影を1回だけ行い、保存したファイル名を返す。失敗時は (None, エラーメッセージ)。"""
    if not state.manual_capture_lock.acquire(blocking=False):
        return None, "❌ 手動撮影を処理中です。少し待ってから押してください。"

    try:
        # 自動撮影が動作中なら、その受信中のフレームをそのまま使う（新たにストリームは開始しない）
        if state.is_running and state.active_receiver is not None:
            frame = state.active_receiver.latest_frame
            device_type = state.active_device["os"]
        else:
            # 自動撮影が停止中の場合は、端末を決めて1回分だけ画面を取得する
            device, error_msg = dev_manager.resolve_device(device_id)
            if not device:
                return None, error_msg
            frame = dev_manager.capture_single_frame(device)
            device_type = device["os"]

        if frame is None:
            return None, CAPTURE_FAILED_MESSAGE
        return _save_frame(frame, device_type, state.current_config["prefix"], manual=True), None
    finally:
        state.manual_capture_lock.release()


# ---------------------------------------------------------------------------
# 変化の判定
# ---------------------------------------------------------------------------
def _to_compare_image(frame):
    """変化検知の比較用に、グレースケール化・縮小・ノイズ除去した画像を返す。"""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    return cv2.medianBlur(gray, 3)


def _set_baseline(frame):
    """撮影直後のフレームを変化検知の基準にする。

    仕様: docs/spec/bugs/LOCAL-019_動的モードで操作を止めてから撮影までが遅く連続した操作で撮り漏れる.md
    判定時と同じ比較用の画像にしておく（以前はサイズが異なり、撮影後の最初のコマが
    変化の有無に関わらず基準に置き換わるだけになっていた）。
    """
    state.last_frame_data = _to_compare_image(frame)


def process_frame_changed(frame, is_static_mode=False, use_moving_average=True):
    """基準のコマから変化したかを判定する。変化していれば、このコマを新しい基準にする。"""
    if frame is None: return False

    gray = _to_compare_image(frame)

    # 基準が無い（または画面の大きさが変わった）場合は、このコマを基準にする
    if state.last_frame_data is None or state.last_frame_data.shape != gray.shape:
        state.last_frame_data = gray
        return False

    score = np.mean(cv2.absdiff(state.last_frame_data, gray))

    # 直近3コマの移動平均を取る
    # 仕様: docs/spec/bugs/LOCAL-019_動的モードで操作を止めてから撮影までが遅く連続した操作で撮り漏れる.md
    # 動的モードでは、止まった後も過去の大きな変化量が平均に残って静止判定が遅れるため、使わない
    if use_moving_average:
        state.score_history.append(score)
        score = sum(state.score_history) / len(state.score_history)

    threshold = STATIC_MODE_THRESHOLD if is_static_mode else DEFAULT_THRESHOLD
    if score > threshold:
        state.last_frame_data = gray
        return True
    return False


def _discard_frames(receiver, count):
    """受信バッファを捨てながら待つ（撮影直後のフレームを判定に使わないため）。"""
    for _ in range(count):
        if not state.is_running: break
        receiver.latest_frame = None
        time.sleep(0.05)


def _capture_after_settling(receiver, frame, device_type, conf):
    """静的モード: 動いたら指定した秒数（settling）後に撮影する。"""
    add_log(f"🎬 変化検知... 待機中 ({conf['settling']}s)")
    if conf["settling"] > 0:
        time.sleep(conf["settling"])
    if not state.is_running:
        return

    # 待機が明けた「その瞬間」の最新フレームを保存し、撮影直後の状態を基準にする
    final_frame = receiver.latest_frame if receiver.latest_frame is not None else frame
    _save_frame(final_frame, device_type, conf['prefix'])
    _set_baseline(final_frame)
    # 判定履歴をリセットし、撮影直後のフレームを捨てて、連続撮影を防ぐ
    state.score_history.clear()
    _discard_frames(receiver, 10)


class _DynamicModeJudge:
    """動的モード: 動いている間は撮影しない。静止が判定回数続いたら撮影し、次に動くまでは撮影しない。

    静止を数えている途中で再び動き始めたら、数え直す。
    """
    def __init__(self):
        self.stable_count = 0
        self.already_captured = False

    def on_frame(self, frame, changed, device_type, conf):
        if changed:
            self.already_captured = False
            self.stable_count = 0
            add_log("🎬 画面動作中...")
            return
        # 一度撮影した後は、次に画面が動くまで何もしない（ログも出さない）
        if self.already_captured:
            return

        # 仕様: docs/spec/bugs/LOCAL-022_動的モードで判定回数が設定より1回少なくなる組み合わせがある.md
        # 動的モードでは settling = チェック間隔 × 判定回数 が送られてくる。小数の誤差で
        # 割り算が 2.9999… になることがあるため、切り捨てではなく四捨五入で回数に戻す
        frames_needed = max(1, round(conf["settling"] / conf["interval"]))
        self.stable_count += 1
        add_log(f"📊 静止確認: {self.stable_count}/{frames_needed}")
        if self.stable_count < frames_needed or not state.is_running:
            return

        _save_frame(frame, device_type, conf['prefix'])
        self.already_captured = True
        self.stable_count = 0
        # 仕様: docs/spec/bugs/LOCAL-019_動的モードで操作を止めてから撮影までが遅く連続した操作で撮り漏れる.md
        # 撮影直後に受信を捨てて待つと、その間の画面遷移を見逃すため、このコマを基準にして次のコマから判定を再開する
        _set_baseline(frame)


# ---------------------------------------------------------------------------
# 自動撮影のループ
# ---------------------------------------------------------------------------
def _watch_receiver(receiver, device_type):
    """受信したコマを判定し、条件を満たしたら撮影する。停止されたらFalse、切断されたらTrueを返す。"""
    dynamic_judge = _DynamicModeJudge()
    last_frame_seq = None

    while state.is_running:
        if not receiver.is_healthy():
            # 仕様: docs/spec/bugs/LOCAL-017_ストリーム接続の一時的な切断で自動撮影全体が停止する.md
            # HTTP接続が切れた際のメッセージ（例:「Remote end closed connection without
            # response」）だけでは原因が分からないため、go-ios自身が報告した理由があれば使う
            state.last_error = dev_manager.last_stream_error or receiver.last_error or "ストリームが切断されました。"
            dev_manager.last_stream_error = None
            add_log(f"{state.last_error}")
            return True
        start_time = time.time()
        conf = state.current_config

        frame = receiver.latest_frame
        frame_seq = receiver.frame_seq
        if frame is None:
            time.sleep(0.05)
            continue

        # 仕様: docs/spec/bugs/LOCAL-004_動的モードのフレーム重複による誤検知.md
        # まだ新しいフレームが届いていない場合、同じフレームを「変化なし」として
        # 二重にカウントしてしまうと誤って静止判定・撮影されるため、判定自体をスキップする
        if frame_seq == last_frame_seq:
            time.sleep(0.01)
            continue
        last_frame_seq = frame_seq

        changed = process_frame_changed(frame, use_moving_average=(conf["mode"] == "static"))
        if conf["mode"] == "static":
            if changed:
                _capture_after_settling(receiver, frame, device_type, conf)
        else:
            dynamic_judge.on_frame(frame, changed, device_type, conf)

        elapsed = time.time() - start_time
        time.sleep(max(0.01, conf["interval"] - elapsed))
    return False


def auto_capture_loop():
    state.last_error = None
    device_id = state.current_config["device"]
    reconnect_attempts = 0

    while state.is_running:
        device, error_msg = dev_manager.start_stream(device_id)
        if not device:
            state.last_error = error_msg
            add_log(f"{error_msg}")
            state.is_running = False
            break

        if reconnect_attempts == 0:
            add_log("▶️ 自動撮影を開始しました")
        else:
            add_log(f"🔄 接続を再開しました（再接続 {reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS}）")

        receiver = _create_receiver(device)
        # 仕様: docs/spec/manual-capture.md（撮影中の手動撮影が同じ受信中フレームを使えるようにする）
        state.active_receiver = receiver
        state.active_device = device
        receiver.start()
        time.sleep(0.5)
        # 前の接続の判定状態を持ち越さない
        state.last_frame_data = None
        state.score_history.clear()

        disconnected = _watch_receiver(receiver, device["os"])

        receiver.stop()
        dev_manager.stop_stream()
        state.active_receiver = None
        state.active_device = None

        if not state.is_running or not disconnected:
            break  # ユーザーが停止した、または致命的なエラーで終了した

        reconnect_attempts += 1
        if reconnect_attempts > MAX_RECONNECT_ATTEMPTS:
            add_log(f"⚠️ 再接続に{MAX_RECONNECT_ATTEMPTS}回失敗したため、自動撮影を停止します。")
            state.is_running = False
            break

        time.sleep(RECONNECT_DELAY)

    # 仕様: docs/spec/session-grouping.md（セッション終了の後始末）
    state.current_session_id = None
