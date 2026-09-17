# 仕様: docs/spec/screenshot-capture.md
import os
import time

import cv2
import numpy as np

from . import state
from .device_manager import dev_manager
from .logs import add_log
from .paths import SAVE_DIR
from .stream_receivers import AndroidScreencapReceiver, iOSStreamReceiver


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

    device_type, error_msg = dev_manager.start_stream()
    if not device_type:
        state.last_error = error_msg
        add_log(f"{error_msg}")
        state.is_running = False
        return

    add_log("▶️ 自動撮影を開始しました")
    stable_count = 0
    already_captured = False

    if device_type == "android":
        receiver = AndroidScreencapReceiver(dev_manager.adb)
    else:
        receiver = iOSStreamReceiver("http://127.0.0.1:3333")

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
                    timestamp = time.strftime("%Y%m%d_%H%M%S")

                    device_label = device_type.capitalize() # ios -> Ios となるため、以下の微調整を推奨
                    if device_type.lower() == 'ios': device_label = 'iOS'
                    elif device_type.lower() == 'android': device_label = 'Android'
                    final_name = f"{conf['prefix']}_{device_label}_{timestamp}.png" if conf['prefix'] else f"{device_label}_{timestamp}.png"

                    dest_path = os.path.join(SAVE_DIR, final_name)

                    cv2.imwrite(dest_path, final_frame)
                    add_log(f"📸 撮影完了: {final_name}")

                    # 撮影直後の状態を基準にする
                    state.last_frame_data = cv2.cvtColor(final_frame, cv2.COLOR_BGR2GRAY)

                    # 判定履歴をリセットして、連続撮影を防止する
                    state.score_history.clear()

                    # 撮影直後のフレームをスキップして、判定を安定させる
                    for _ in range(10):
                        if not state.is_running: break
                        receiver.latest_frame = None
                        time.sleep(0.05)

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
                            timestamp = time.strftime("%Y%m%d_%H%M%S")

                            device_label = device_type.capitalize()
                            if device_type.lower() == 'ios': device_label = 'iOS'
                            elif device_type.lower() == 'android': device_label = 'Android'
                            final_name = f"{conf['prefix']}_{device_label}_{timestamp}.png" if conf['prefix'] else f"{device_label}_{timestamp}.png"

                            dest_path = os.path.join(SAVE_DIR, final_name)

                            cv2.imwrite(dest_path, frame)
                            add_log(f"📸 撮影完了: {final_name}")

                            # 撮影後のクールダウン（判定ロジックを強制リセット）
                            already_captured = True
                            stable_count = 0

                            # ここで現在のフレームを基準に上書きし、変化検知を「なし」からスタートさせる
                            state.last_frame_data = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                            # 【改善】sleepの代わりに、受信バッファを空にする（捨ててから次に進む）
                            for _ in range(20): # 少し多めに回す
                                if not state.is_running: break
                                receiver.latest_frame = None
                                time.sleep(0.05) # 合計1秒分を「受信待ち」で潰す

        elapsed = time.time() - start_time
        sleep_time = max(0.01, conf["interval"] - elapsed)
        time.sleep(sleep_time)

    receiver.stop()
    dev_manager.stop_stream()
