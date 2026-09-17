# 仕様: docs/spec/screenshot-capture.md
import atexit
import os
import platform
import subprocess
import time

from . import paths
from .logs import add_log

CREATE_NO_WINDOW = paths.CREATE_NO_WINDOW


class DeviceManager:
    def __init__(self):
        # 属性の定義は必ずここで行います
        self.processes = []

        if platform.system() == "Windows":
            self.adb = os.path.join(paths.base_path, "bin", "win", "adb.exe")
            self.ios = os.path.join(paths.base_path, "bin", "win", "go-ios.exe")
        else:
            self.adb = os.path.join(paths.base_path, "bin", "mac", "adb")
            self.ios = os.path.join(paths.base_path, "bin", "mac", "go-ios")
            if os.path.exists(self.adb): os.chmod(self.adb, 0o755)
            if os.path.exists(self.ios): os.chmod(self.ios, 0o755)

        atexit.register(self.cleanup_all_processes)

    def detect_device(self):
        found_devices = []

        # 1. Android判定
        try:
            # サーバー起動を待つためタイムアウトを 5.0秒 に
            res = subprocess.run([self.adb, "devices"], capture_output=True, text=True, timeout=5.0, creationflags=CREATE_NO_WINDOW)
            lines = res.stdout.strip().split('\n')
            # 2行目以降のデバイスリストをチェック
            for line in lines[1:]:
                if "\tdevice" in line:
                    found_devices.append("android")
                    break
        except Exception as e:
            print(f"DEBUG: Android check failed: {e}")

        # 2. iOS判定 (結果が空リストでないことを厳密に確認)
        try:
            res = subprocess.run([self.ios, "list"], capture_output=True, text=True, timeout=1.0, creationflags=CREATE_NO_WINDOW)
            # JSONが空ではない、かつリストの中身があるか確認
            if "deviceList" in res.stdout and '[]' not in res.stdout:
                found_devices.append("ios")
        except: pass

        return found_devices

    def start_stream(self):
        self.cleanup_all_processes()
        device_list = self.detect_device()
        startupinfo = paths.get_startupinfo()

        if not device_list:
            time.sleep(1.0)
            devices = self.detect_device()
            if not devices:
                return None, "❌ デバイスが検出されませんでした。ケーブルを確認してください。"

        device = device_list[0]  # 最初のデバイスを優先して使用

        try:
            if device == "ios":
                add_log("📱 iOS ストリーム接続を開始します...")
                env = os.environ.copy()
                env["ENABLE_GO_IOS_AGENT"] = "user"
                p = subprocess.Popen([self.ios, "screenshot", "--stream", "--port=3333"],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo, creationflags=CREATE_NO_WINDOW
                )
                self.processes.append(p)
                time.sleep(1.5)
                return "ios", None  # タプルで返す

            elif device == "android":
                # Androidは AndroidScreencapReceiver が `adb exec-out screencap` を
                # 都度実行して取得するため、ここでの常駐プロセス起動は不要
                add_log("🤖 Android ストリーム接続を開始します...")
                return "android", None  # タプルで返す

        except Exception as e:
            add_log(f"詳細エラー: {type(e).__name__}: {str(e)}")
            return None, f"❌ ストリームの開始に失敗しました: {str(e)}"

    def stop_stream(self):
        """ストリームプロセスを安全にクローズ（クラス内で完結）"""
        self.cleanup_all_processes()
        add_log("🔌 ストリーム接続を閉じました")

    def cleanup_all_processes(self):
        """管理している全プロセスを終了"""
        for p in self.processes:
            try:
                p.terminate()
                p.wait(timeout=1)
            except:
                pass
        self.processes.clear()


dev_manager = DeviceManager()
