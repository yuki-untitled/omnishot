# 仕様: docs/spec/screenshot-capture.md
import subprocess
import threading
import time
import urllib.request

import cv2
import numpy as np

from .logs import add_log


class _FrameReceiver(threading.Thread):
    """常に最新の1コマだけを保持する受信スレッドの共通処理。"""
    def __init__(self):
        super().__init__()
        self.latest_frame = None
        # 仕様: docs/spec/bugs/LOCAL-004_動的モードのフレーム重複による誤検知.md
        self.frame_seq = 0
        self.running = True
        self.daemon = True
        self.last_error = None

    def _publish(self, frame):
        self.latest_frame = frame
        self.frame_seq += 1

    def stop(self):
        self.running = False

    def is_healthy(self):
        return self.is_alive() and self.running


class iOSStreamReceiver(_FrameReceiver):
    """iOS専用:バックグラウンドで常にストリームを読み込み、常に最新の1コマだけを保持するクラス"""
    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        while self.running:
            try:
                # 接続エラーが起きたら即座に外側のループまで抜けるように
                with urllib.request.urlopen(self.url, timeout=5) as stream:
                    bytes_data = b''
                    while self.running:
                        chunk = stream.read(4096)
                        if not chunk: break
                        bytes_data += chunk

                        while True:
                            a = bytes_data.find(b'\xff\xd8')
                            b = bytes_data.find(b'\xff\xd9')
                            if a != -1 and b != -1 and a < b:
                                jpg = bytes_data[a:b+2]
                                bytes_data = bytes_data[b+2:]
                                frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                                if frame is not None:
                                    self._publish(frame)
                            else:
                                break
            except Exception as e:
                # 接続が切れたらエラーを記録し、runningをFalseにしてループを終了させる
                add_log(f"⚠️ iOS device disconnected: {e}")
                self.last_error = "⚠️ iOSデバイスとの接続が切れました"
                self.running = False
                break


class AndroidScreencapReceiver(_FrameReceiver):
    """Android専用：ADB経由でPNGを連続キャプチャするクラス"""
    def __init__(self, adb_path, serial=None):
        super().__init__()
        self.adb = adb_path
        # 仕様: docs/spec/device-selection.md（複数接続時は選択した端末を指定する）
        self.serial = serial

    def run(self):
        while self.running:
            try:
                cmd = [self.adb] + (["-s", self.serial] if self.serial else []) + ["exec-out", "screencap", "-p"]
                res = subprocess.run(cmd, capture_output=True, check=True)
                if res.stdout:
                    frame = cv2.imdecode(np.frombuffer(res.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        self._publish(frame)
            except Exception as e:
                add_log(f"⚠️ Android device disconnected: {e}")
                self.last_error = "⚠️ Androidデバイスとの接続が切れました"
                self.running = False
                break
            time.sleep(0.05)
