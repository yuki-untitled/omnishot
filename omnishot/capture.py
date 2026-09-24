# 仕様: docs/spec/screenshot-capture.md
import os
import subprocess
import tempfile
import time

import cv2
import numpy as np

from . import paths, state
from .device_manager import dev_manager
from .logs import add_log
from .paths import SAVE_DIR
from .stream_receivers import AndroidScreencapReceiver, iOSStreamReceiver


DEVICE_LABELS = {"ios": "iOS", "android": "Android"}


def _create_receiver(device):
    if device["os"] == "android":
        return AndroidScreencapReceiver(dev_manager.adb, device["id"])
    return iOSStreamReceiver("http://127.0.0.1:3333")


def _save_frame(frame, device_type, prefix, manual=False):
    """フレームをキャプチャ保存先へPNGとして保存し、保存したファイル名を返す。

    仕様: docs/spec/manual-capture.md（手動撮影は "Manual_" を付けて自動撮影と区別する）
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    device_label = DEVICE_LABELS.get(device_type.lower(), device_type.capitalize())
    manual_marker = "Manual_" if manual else ""
    final_name = f"{prefix}_{manual_marker}{device_label}_{timestamp}.png" if prefix else f"{manual_marker}{device_label}_{timestamp}.png"
    cv2.imwrite(os.path.join(SAVE_DIR, final_name), frame)
    add_log(f"📸 撮影完了: {final_name}")
    return final_name


# 仕様: docs/spec/manual-capture.md
# 自動撮影が停止中の手動撮影は、常時ストリームを新規起動せず、1回分のコマンドだけで画面を取得する
# （ストリームの起動・接続待ちを挟まないため、接続が不安定な状況でも失敗しにくい）。
def _capture_single_frame(device):
    """指定端末の画面を1回だけ取得してフレーム（numpy配列）を返す。取得できなければNone。"""
    if device["os"] == "android":
        try:
            cmd = [dev_manager.adb, "-s", device["id"], "exec-out", "screencap", "-p"]
            res = subprocess.run(cmd, capture_output=True, timeout=10, creationflags=paths.CREATE_NO_WINDOW)
            if not res.stdout:
                stderr = res.stderr.decode('utf-8', errors='replace').strip() if res.stderr else ""
                add_log(f"⚠️ Android screenshot failed: {stderr or 'no output'}")
                return None
            return cv2.imdecode(np.frombuffer(res.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception as e:
            add_log(f"⚠️ Android screenshot failed: {e}")
            return None

    # iOS: 常時ストリームではなく、1回分の screenshot コマンドで一時ファイルに書き出す
    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        env = os.environ.copy()
        env["ENABLE_GO_IOS_AGENT"] = "user"
        cmd = [dev_manager.ios, f"--udid={device['id']}", "screenshot", f"--output={tmp_path}"]
        res = subprocess.run(cmd, env=env, capture_output=True, timeout=15, creationflags=paths.CREATE_NO_WINDOW)
        frame = cv2.imread(tmp_path)
        if frame is None:
            add_log(f"⚠️ iOS screenshot failed: exit code {res.returncode}")
        return frame
    except Exception as e:
        add_log(f"⚠️ iOS screenshot failed: {e}")
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def manual_capture(device_id):
    """手動撮影を1回だけ行い、保存したファイル名を返す。失敗時は (None, エラーメッセージ)。"""
    if not state.manual_capture_lock.acquire(blocking=False):
        return None, "❌ 手動撮影を処理中です。少し待ってから押してください。"

    try:
        # 自動撮影が動作中なら、その受信中のフレームをそのまま使う（新たにストリームは開始しない）
        if state.is_running and state.active_receiver is not None:
            frame = state.active_receiver.latest_frame
            if frame is None:
                return None, "❌ 画面を取得できませんでした。時間を置いて再度お試しください。"
            return _save_frame(frame, state.active_device["os"], state.current_config["prefix"], manual=True), None

        # 自動撮影が停止中の場合は、端末を決めて1回分だけ画面を取得する
        device, error_msg = dev_manager.resolve_device(device_id)
        if not device:
            return None, error_msg

        frame = _capture_single_frame(device)
        if frame is None:
            return None, "❌ 画面を取得できませんでした。時間を置いて再度お試しください。"
        return _save_frame(frame, device["os"], state.current_config["prefix"], manual=True), None
    finally:
        state.manual_capture_lock.release()


def _set_baseline(frame):
    """撮影直後のフレームを変化検知の基準にする。"""
    state.last_frame_data = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _discard_frames(receiver, count):
    """受信バッファを捨てながら待つ（撮影直後のフレームを判定に使わないため）。"""
    for _ in range(count):
        if not state.is_running: break
        receiver.latest_frame = None
        time.sleep(0.05)


def process_frame_changed(frame, is_static_mode=False):
    if frame is None: return False

    h, w = frame.shape[:2]
    target_w, target_h = w // 2, h // 2
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (target_w, target_h), interpolation=cv2.INTER_AREA)
    gray = cv2.medianBlur(gray, 3)

    # 基準データチェック
    if state.last_frame_data is None or state.last_frame_data.shape != gray.shape:
        state.last_frame_data = gray
        return False

    # 差分計算
    diff = cv2.absdiff(state.last_frame_data, gray)
    score = np.mean(diff)

    # 4. 3フレームの移動平均を取る
    state.score_history.append(score)
    score = sum(state.score_history) / len(state.score_history)

    # 4. 閾値判定
    threshold = 0.5 if is_static_mode else 0.25

    if score > threshold:
        state.last_frame_data = gray
        return True
    return False


def auto_capture_loop():
    state.last_error = None

    device, error_msg = dev_manager.start_stream(state.current_config["device"])
    if not device:
        state.last_error = error_msg
        add_log(f"{error_msg}")
        state.is_running = False
        return

    add_log("▶️ 自動撮影を開始しました")
    stable_count = 0
    already_captured = False

    device_type = device["os"]
    receiver = _create_receiver(device)
    # 仕様: docs/spec/manual-capture.md（撮影中の手動撮影が同じ受信中フレームを使えるようにする）
    state.active_receiver = receiver
    state.active_device = device
    receiver.start()
    time.sleep(0.5)
    last_frame_seq = None

    while state.is_running:
        if not receiver.is_healthy():
            state.last_error = receiver.last_error or "ストリームが切断されました。"
            add_log(f"{state.last_error}")
            state.is_running = False
            break
        start_time = time.time()
        conf = state.current_config

        # 【改善1】receiver から取得する時は、最短で最新のものだけを取る
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

        # 【改善2】変化検知は 1 回のみ。sleep は外す
        changed = process_frame_changed(frame)

        frames_needed = max(1, int(conf["settling"] / conf["interval"]))

        # ==========================================
        # 🟢 静的モードの仕様
        # 動いたら指定した秒数（settling）後に撮影
        # ==========================================
        if conf["mode"] == "static":
            if changed:
                add_log(f"🎬 変化検知... 待機中 ({conf['settling']}s)")
                if conf["settling"] > 0:
                    time.sleep(conf["settling"])

                if state.is_running:
                    # 待機が明けた「その瞬間」の最新フレームを再度取得して保存
                    final_frame = receiver.latest_frame if receiver.latest_frame is not None else frame
                    _save_frame(final_frame, device_type, conf['prefix'])

                    # 撮影直後の状態を基準にする
                    _set_baseline(final_frame)

                    # 判定履歴をリセットして、連続撮影を防止する
                    state.score_history.clear()

                    # 撮影直後のフレームをスキップして、判定を安定させる
                    _discard_frames(receiver, 10)

        # ==========================================
        # 🔵 動的モードの仕様
        # 動いている時は撮影しない。
        # 静止判定中に再び動き始めたら撮影しない、再び静止するまで動作中判定。
        # 静止してから指定判定を満たしたら撮影。一度撮影したら動くまで撮影しない。
        # ==========================================
        else:
            if changed:
                # 💡 画面が動き続けている間、または静止判定中に再び動き始めた場合
                already_captured = False # 撮影許可を戻す
                stable_count = 0         # 静止カウントを容赦なくゼロにリセット
                add_log("🎬 画面動作中...")
            else:
                # 完全に動きが止まっている（静止中）場合
                if already_captured:
                    # 💡 一度撮影した後は、次に画面が動くまで完全に沈黙（ログも出さない）
                    pass
                else:
                    stable_count += 1
                    add_log(f"📊 静止確認: {stable_count}/{frames_needed}")

                    # 指定された秒数（回数）ずっと静止し続けた瞬間
                    if stable_count >= frames_needed:
                        if state.is_running:
                            _save_frame(frame, device_type, conf['prefix'])

                            # 撮影後のクールダウン（判定ロジックを強制リセット）
                            already_captured = True
                            stable_count = 0

                            # ここで現在のフレームを基準に上書きし、変化検知を「なし」からスタートさせる
                            _set_baseline(frame)

                            # 受信バッファを空にする（合計1秒分を「受信待ち」で潰す）
                            _discard_frames(receiver, 20)

        elapsed = time.time() - start_time
        sleep_time = max(0.01, conf["interval"] - elapsed)
        time.sleep(sleep_time)

    receiver.stop()
    dev_manager.stop_stream()
    # 仕様: docs/spec/manual-capture.md（撮影中の手動撮影が同じ受信中フレームを使えるようにする）
    state.active_receiver = None
    state.active_device = None
