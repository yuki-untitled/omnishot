# 仕様: docs/spec/screenshot-capture.md
import struct
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
                # 仕様: docs/spec/bugs/LOCAL-021_停止を押すとiOSの切断の警告が表示される.md
                # 停止した後のエラーは、go-ios の終了で通信が切れただけなので切断として扱わない
                if not self.running:
                    break
                # 接続が切れたらエラーを記録し、runningをFalseにしてループを終了させる
                add_log(f"⚠️ iOS device disconnected: {e}")
                self.last_error = "⚠️ iOSデバイスとの接続が切れました"
                self.running = False
                break


# 仕様: docs/spec/bugs/LOCAL-020_Androidの画面取得に1コマ約1秒かかり自動撮影の反応が遅い.md
# raw の screencap のピクセル形式（Android の PixelFormat）と、BGR への変換方法
_RAW_PIXEL_FORMATS = {
    1: cv2.COLOR_RGBA2BGR,  # RGBA_8888
    2: cv2.COLOR_RGBA2BGR,  # RGBX_8888
    5: cv2.COLOR_BGRA2BGR,  # BGRA_8888
}


def decode_raw_screencap(data):
    """`screencap`（-p なし）の出力を BGR のフレームにする。読めない形式なら None。

    出力は「幅・高さ・形式（各4バイト）＋（Android 9 以降は色空間4バイト）」のヘッダーの後に、
    1ピクセル4バイトの画素が並ぶ。
    """
    if len(data) < 12:
        return None
    w, h, fmt = struct.unpack_from("<III", data)
    if fmt not in _RAW_PIXEL_FORMATS or w == 0 or h == 0:
        return None
    header_size = len(data) - w * h * 4
    if header_size not in (12, 16):
        return None
    pixels = np.frombuffer(data, dtype=np.uint8, offset=header_size).reshape(h, w, 4)
    return cv2.cvtColor(pixels, _RAW_PIXEL_FORMATS[fmt])


class AndroidScreencapReceiver(_FrameReceiver):
    """Android専用：ADB経由で画面を連続キャプチャするクラス

    仕様: docs/spec/bugs/LOCAL-020_Androidの画面取得に1コマ約1秒かかり自動撮影の反応が遅い.md
    端末上での PNG 圧縮が重い（1コマ約1.2秒）ため、圧縮しない raw で取得し、さらに
    取得を並行させてコマの届く間隔を縮める。raw を読めない端末では PNG に切り替える。
    """
    WORKERS = 2

    def __init__(self, adb_path, serial=None):
        super().__init__()
        self.adb = adb_path
        # 仕様: docs/spec/device-selection.md（複数接続時は選択した端末を指定する）
        self.serial = serial
        self.use_raw = True
        self._publish_lock = threading.Lock()
        self._last_started_at = 0.0

    def _capture_once(self):
        """1コマ取得し、(取得を始めた時刻, フレーム or None) を返す。"""
        use_raw = self.use_raw
        cmd = [self.adb] + (["-s", self.serial] if self.serial else []) + ["exec-out", "screencap"] + ([] if use_raw else ["-p"])
        started_at = time.time()
        res = subprocess.run(cmd, capture_output=True, check=True)
        if not res.stdout:
            return started_at, None
        if use_raw:
            frame = decode_raw_screencap(res.stdout)
            if frame is None and self.use_raw:
                self.use_raw = False
                add_log("⚠️ この端末は高速な画面取得に対応していないため、従来の方法で取得します")
            return started_at, frame
        return started_at, cv2.imdecode(np.frombuffer(res.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)

    def _worker(self, delay):
        time.sleep(delay)
        while self.running:
            try:
                started_at, frame = self._capture_once()
            except Exception as e:
                if self.running:
                    add_log(f"⚠️ Android device disconnected: {e}")
                    self.last_error = "⚠️ Androidデバイスとの接続が切れました"
                    self.running = False
                break
            if frame is None:
                continue
            # 並行した取得の結果が前後して届いた場合、古い画面で新しい画面を上書きしない
            with self._publish_lock:
                if started_at <= self._last_started_at:
                    continue
                self._last_started_at = started_at
                self._publish(frame)

    def run(self):
        # 取得の開始をずらして、コマがなるべく等間隔に届くようにする
        helpers = [threading.Thread(target=self._worker, args=(0.3 * i,), daemon=True) for i in range(1, self.WORKERS)]
        for t in helpers:
            t.start()
        self._worker(0)
        for t in helpers:
            t.join()
