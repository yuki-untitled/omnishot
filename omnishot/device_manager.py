# 仕様: docs/spec/screenshot-capture.md
# 仕様: docs/spec/device-selection.md
import atexit
import json
import os
import platform
import plistlib
import socket
import struct
import subprocess
import time

from . import paths
from .logs import add_log


def _recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("usbmuxd closed the connection")
        data += chunk
    return data


def _usbmuxd_connection_types():
    """usbmuxd に問い合わせ、iOS端末のUDIDごとの接続種別（"USB" / "Network"）を返す。失敗したら None。"""
    try:
        if platform.system() == "Windows":
            sock = socket.create_connection(("127.0.0.1", 27015), timeout=2.0)
        else:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect("/var/run/usbmuxd")
        with sock:
            body = plistlib.dumps({"MessageType": "ListDevices", "ClientVersionString": "omnishot", "ProgName": "omnishot"})
            sock.sendall(struct.pack("<IIII", 16 + len(body), 1, 8, 1) + body)
            length = struct.unpack("<I", _recv_exact(sock, 16)[:4])[0]
            reply = plistlib.loads(_recv_exact(sock, length - 16))
        # 同じ端末が USB と Wi-Fi の両方のエントリで現れることがある。USB のエントリが1つでもあれば USB とみなす
        types = {}
        for d in reply.get("DeviceList", []):
            serial = d["Properties"]["SerialNumber"]
            if types.get(serial) != "USB":
                types[serial] = d["Properties"].get("ConnectionType")
        return types
    except Exception as e:
        print(f"DEBUG: usbmuxd query failed: {e}")
        return None


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

    def list_devices(self):
        """USB接続されている端末の一覧を返す。要素は {"id", "os", "name"}（nameは取得できなければNone）。"""
        return self._list_android_devices() + self._list_ios_devices()

    def _list_android_devices(self):
        devices = []
        try:
            # サーバー起動を待つためタイムアウトを 5.0秒 に
            res = subprocess.run([self.adb, "devices", "-l"], capture_output=True, text=True, timeout=5.0, creationflags=paths.CREATE_NO_WINDOW)
            # 2行目以降が端末。例: "<serial> device usb:1-1 product:x model:Pixel_7 ..."
            for line in res.stdout.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) < 2 or parts[1] != "device":
                    continue
                # 仕様: docs/spec/device-selection.md（USB接続の端末のみを対象にする）
                if not any(p.startswith("usb:") for p in parts[2:]):
                    continue
                model = next((p[len("model:"):] for p in parts if p.startswith("model:")), None)
                devices.append({"id": parts[0], "os": "android", "name": model.replace("_", " ") if model else None})
        except Exception as e:
            print(f"DEBUG: Android check failed: {e}")
        return devices

    def _list_ios_devices(self):
        devices = []
        try:
            res = subprocess.run([self.ios, "list"], capture_output=True, text=True, timeout=3.0, creationflags=paths.CREATE_NO_WINDOW)
            udids = []
            for line in res.stdout.splitlines():
                try:
                    udids = json.loads(line).get("deviceList", udids)
                except (ValueError, AttributeError):
                    continue
            # 同じ端末が複数回返ることがあるため、順序を保ったまま重複を除く
            udids = list(dict.fromkeys(udids))
            connection_types = _usbmuxd_connection_types()
            for udid in udids:
                # 仕様: docs/spec/device-selection.md（Wi-Fi経由でだけ見える端末は載せない）
                # 接続種別を問い合わせできなかった場合は、端末を隠さないよう一覧に含める
                if connection_types is not None and connection_types.get(udid) != "USB":
                    continue
                devices.append({"id": udid, "os": "ios", "name": self._ios_device_name(udid)})
        except Exception as e:
            print(f"DEBUG: iOS check failed: {e}")
        return devices

    def _ios_device_name(self, udid):
        """端末名を返す。この Mac が信頼していない端末などで取得できなければ None。"""
        try:
            res = subprocess.run([self.ios, f"--udid={udid}", "info"], capture_output=True, text=True, timeout=3.0, creationflags=paths.CREATE_NO_WINDOW)
            for line in res.stdout.splitlines():
                try:
                    name = json.loads(line).get("DeviceName")
                except (ValueError, AttributeError):
                    continue
                if name:
                    return name
        except Exception:
            pass
        return None

    def resolve_device(self, device_id=""):
        """撮影する端末を、一覧と選択状態から1台に決める。成功時は ({"id", "os", "name"}, None)、失敗時は (None, メッセージ)。

        device_id が空の場合は、端末が1台のときだけその端末を使う。
        仕様: docs/spec/device-selection.md
        """
        devices = self.list_devices()

        if not devices:
            time.sleep(1.0)
            devices = self.list_devices()
            if not devices:
                if device_id:
                    return None, "❌ 選択した端末が接続されていません。ケーブルを確認してください。"
                return None, "❌ デバイスが検出されませんでした。ケーブルを確認してください。"

        if device_id:
            device = next((d for d in devices if d["id"] == device_id), None)
            if device is None:
                return None, "❌ 選択した端末が接続されていません。ケーブルを確認してください。"
            return device, None
        if len(devices) == 1:
            return devices[0], None
        return None, "❌ 撮影する端末を選択してください。"

    def start_stream(self, device_id=""):
        """撮影する端末を決めてストリームを開始する。成功時は ({"id", "os"}, None)、失敗時は (None, メッセージ)。

        device_id が空の場合は、端末が1台のときだけその端末を使う。
        """
        self.cleanup_all_processes()
        startupinfo = paths.get_startupinfo()

        device, error_msg = self.resolve_device(device_id)
        if not device:
            return None, error_msg

        try:
            if device["os"] == "ios":
                add_log("📱 iOS ストリーム接続を開始します...")
                env = os.environ.copy()
                env["ENABLE_GO_IOS_AGENT"] = "user"
                p = subprocess.Popen([self.ios, f"--udid={device['id']}", "screenshot", "--stream", "--port=3333"],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo, creationflags=paths.CREATE_NO_WINDOW
                )
                self.processes.append(p)
                time.sleep(1.5)
                return device, None

            # Androidは AndroidScreencapReceiver が `adb exec-out screencap` を
            # 都度実行して取得するため、ここでの常駐プロセス起動は不要
            add_log("🤖 Android ストリーム接続を開始します...")
            return device, None

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
            except Exception:
                pass
        self.processes.clear()


dev_manager = DeviceManager()
