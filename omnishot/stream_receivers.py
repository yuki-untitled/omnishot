# 仕様: docs/spec/screenshot-capture.md
import subprocess
import threading
import time
import urllib.request

import cv2
import numpy as np

from .logs import add_log


class iOSStreamReceiver(threading.Thread):
    """iOS専用:バックグラウンドで常にストリームを読み込み、常に最新の1コマだけを保持するクラス"""
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.latest_frame = None
        # 仕様: docs/spec/bugs/LOCAL-004_動的モードのフレーム重複による誤検知.md
        self.frame_seq = 0
        self.running = True
        self.daemon = True

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
                                    self.latest_frame = frame
                                    self.frame_seq += 1
                            else:
                                break
            except Exception as e:
                # 接続が切れたらエラーを記録し、runningをFalseにしてループを終了させる
                add_log(f"⚠️ iOS device disconnected: {e}")
                self.last_error = f"⚠️ iOSデバイスとの接続が切れました"
                self.running = False
                break

    def stop(self):
        self.running = False

    def is_healthy(self):
        return self.is_alive() and self.running


class AndroidScreencapReceiver(threading.Thread):
    """Android専用：ADB経由でJPEGを連続キャプチャするクラス"""
    def __init__(self, adb_path):
        super().__init__()
        self.adb = adb_path
        self.latest_frame = None
        # 仕様: docs/spec/bugs/LOCAL-004_動的モードのフレーム重複による誤検知.md
        self.frame_seq = 0
        self.running = True
        self.daemon = True

    def run(self):
        while self.running:
            try:
                res = subprocess.run([self.adb, "exec-out", "screencap", "-p"], capture_output=True, check=True)
                if res.stdout:
                    frame = cv2.imdecode(np.frombuffer(res.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        self.latest_frame = frame
                        self.frame_seq += 1
            except Exception as e:
                add_log(f"⚠️ Android device disconnected: {e}")
                self.last_error = f"⚠️ Androidデバイスとの接続が切れました"
                self.running = False
                break
            time.sleep(0.05)

    def stop(self):
        self.running = False

    def is_healthy(self):
        return self.is_alive() and self.running
