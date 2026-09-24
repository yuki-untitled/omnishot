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
import threading
import time

from . import paths
from .logs import add_log

# 仕様: docs/spec/device-selection.md（このメッセージのときは、画面が端末の一覧を自動で検出し直す）
DEVICE_NOT_CONNECTED_MESSAGE = "❌ 選択した端末が接続されていません。ケーブルを確認してください。"

# iOSストリーム（mjpegサーバー）が待ち受けるポート。capture.py の受信側もこれを参照する。
IOS_STREAM_PORT = 3333


# 仕様: docs/spec/bugs/LOCAL-017_ストリーム接続の一時的な切断で自動撮影全体が停止する.md
def _wait_for_port(host, port, timeout, process=None):
    """指定ポートが接続を受け付けるようになるまで待つ。processを渡すと、途中でプロセスが
    終了した場合はタイムアウトを待たずに諦める。準備できればTrue、できなければFalse。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            return False
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


# 仕様: docs/spec/bugs/LOCAL-025_iOSのトンネルに古い接続が残ると撮影を開始できず理由も表示されない.md
def go_ios_error_message(line):
    """go-iosのJSON形式のログ1行から、error/fatalレベルのmsgを返す（それ以外はNone）。
    go-ios 1.3.2 から level が大文字（"ERROR"）になったため、大文字・小文字を区別しない。
    """
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict) or str(data.get("level", "")).lower() not in ("fatal", "error"):
        return None
    return data.get("msg") or line


def is_ios_tunnel_unreachable(message):
    """go-iosの失敗理由が、トンネル経由で端末に接続できなかったことを示すか。"""
    return bool(message) and "could not connect to RSD" in message


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
        # 仕様: docs/spec/bugs/LOCAL-017_ストリーム接続の一時的な切断で自動撮影全体が停止する.md
        # go-iosの標準エラー出力から拾った、直近の致命的エラーの内容（無ければNone）。
        # HTTP接続が切れた際のメッセージ（例:「Remote end closed connection without response」）
        # だけでは原因が分からないため、可能ならこちらをユーザー向けエラーに反映する。
        self.last_stream_error = None

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
        """選択された端末が接続されていれば、その端末を返す。成功時は ({"id", "os", "name"}, None)、失敗時は (None, メッセージ)。

        仕様: docs/spec/device-selection.md
        仕様: docs/spec/bugs/LOCAL-023_端末が見つかりませんの表示中に撮影できてしまう.md
        device_id が空の場合は、画面の一覧に無い端末を撮影しないよう、自分で端末を選ばずに断る。
        """
        if not device_id:
            return None, "❌ 撮影する端末が選ばれていません。更新ボタンで端末を検出してください。"

        devices = self.list_devices()
        if not devices:
            time.sleep(1.0)
            devices = self.list_devices()

        device = next((d for d in devices if d["id"] == device_id), None)
        if device is None:
            return None, DEVICE_NOT_CONNECTED_MESSAGE
        return device, None

    def start_stream(self, device_id=""):
        """選択された端末のストリームを開始する。成功時は ({"id", "os"}, None)、失敗時は (None, メッセージ)。"""
        self.cleanup_all_processes()
        startupinfo = paths.get_startupinfo()

        device, error_msg = self.resolve_device(device_id)
        if not device:
            return None, error_msg

        try:
            if device["os"] == "ios":
                add_log("📱 iOS ストリーム接続を開始します...")
                error_msg = self._start_ios_stream(device, startupinfo, timeout=5.0)
                # 仕様: docs/spec/bugs/LOCAL-025_iOSのトンネルに古い接続が残ると撮影を開始できず理由も表示されない.md
                # 仕様: docs/spec/native-window.md（トンネルが起動途中なら、準備ができるのを待つ）
                if error_msg and self.recover_ios_connection(device["id"], self.last_stream_error):
                    error_msg = self._start_ios_stream(device, startupinfo, timeout=15.0)
                if error_msg:
                    return None, error_msg
                return device, None

            # Androidは AndroidScreencapReceiver が `adb exec-out screencap` を
            # 都度実行して取得するため、ここでの常駐プロセス起動は不要
            add_log("🤖 Android ストリーム接続を開始します...")
            return device, None

        except Exception as e:
            add_log(f"詳細エラー: {type(e).__name__}: {str(e)}")
            return None, f"❌ ストリームの開始に失敗しました: {str(e)}"

    def _start_ios_stream(self, device, startupinfo, timeout):
        """go-iosのストリーム（mjpegサーバー）を起動する。成功時はNone、失敗時はユーザー向けメッセージ。"""
        env = os.environ.copy()
        env["ENABLE_GO_IOS_AGENT"] = "user"
        p = subprocess.Popen(
            [self.ios, f"--udid={device['id']}", "screenshot", "--stream", f"--port={IOS_STREAM_PORT}"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            startupinfo=startupinfo, creationflags=paths.CREATE_NO_WINDOW,
        )
        self.processes.append(p)
        self.last_stream_error = None
        # 仕様: docs/spec/bugs/LOCAL-017_ストリーム接続の一時的な切断で自動撮影全体が停止する.md
        # go-ios の標準エラー出力は、以前は破棄していて失敗原因が分からなかったため、監視して切断理由を保持する
        stderr_thread = threading.Thread(target=self._stream_stderr_to_log, args=(p.stderr,), daemon=True)
        stderr_thread.start()

        # 固定時間（旧: 1.5秒）待つのではなく、実際にポートが受け付け可能になるまで待つ。
        # 起動が遅い端末では固定時間では足りず、逆に起動が速い場合は待ちすぎになっていた。
        if _wait_for_port("127.0.0.1", IOS_STREAM_PORT, timeout=timeout, process=p):
            return None

        exit_code = p.poll()
        self.cleanup_all_processes()
        # 仕様: docs/spec/bugs/LOCAL-025_iOSのトンネルに古い接続が残ると撮影を開始できず理由も表示されない.md
        # 終了直前に出た理由を読み終えてから、メッセージに含める
        stderr_thread.join(timeout=1.0)
        if self.last_stream_error:
            return f"❌ iOSストリームの起動に失敗しました（{self.last_stream_error}）。"
        if exit_code is not None:
            return f"❌ iOSストリームの起動に失敗しました（go-iosが終了コード{exit_code}で終了しました）。"
        return "❌ iOSストリームの起動がタイムアウトしました。時間を置いて再度お試しください。"

    def _ios_tunnel_endpoint(self, udid, env):
        """トンネルの一覧から、端末の接続先 (address, rsdPort) を返す。無ければNone。"""
        try:
            res = subprocess.run([self.ios, "tunnel", "ls"], env=env, capture_output=True, text=True, timeout=5,
                                 creationflags=paths.CREATE_NO_WINDOW)
            lines = res.stdout.strip().splitlines()
            for t in (json.loads(lines[-1]) if lines else []):
                if isinstance(t, dict) and t.get("udid") == udid:
                    return (t.get("address"), t.get("rsdPort"))
        except Exception:
            pass
        return None

    def recover_ios_connection(self, udid, reason):
        """iOSの画面取得の失敗から立ち直れそうなら、トンネルを整えてTrueを返す（呼び出し側は1回だけやり直す）。

        仕様: docs/spec/bugs/LOCAL-025_iOSのトンネルに古い接続が残ると撮影を開始できず理由も表示されない.md
        仕様: docs/spec/native-window.md（終了時にトンネルを止めるため、次の起動直後はトンネルが起動途中のことがある）
        - トンネル経由で端末に接続できない: トンネルに古い接続が残っているため、起動し直す
        - トンネルの一覧に端末が無い: トンネルが起動途中のため、準備ができるのを待つ
          （iOS 16 以前はトンネルを使わないため、待っても載らずFalseになる）
        """
        env = os.environ.copy()
        env["ENABLE_GO_IOS_AGENT"] = "user"
        if is_ios_tunnel_unreachable(reason):
            return self.restart_ios_tunnel(udid)
        if self._ios_tunnel_endpoint(udid, env) is None:
            add_log("⏳ iOSのトンネルの起動を待っています...")
            return self._wait_for_ios_tunnel(udid, env)
        return False

    def _wait_for_ios_tunnel(self, udid, env, exclude=None, timeout=10.0):
        """トンネルの一覧に、端末の接続（exclude と異なるもの）が載るまで待つ。載ればTrue。
        一覧を問い合わせると、トンネルが止まっていれば自動で起動する。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            endpoint = self._ios_tunnel_endpoint(udid, env)
            if endpoint is not None and endpoint != exclude:
                return True
            time.sleep(0.5)
        return False

    def restart_ios_tunnel(self, udid):
        """go-iosの常駐トンネル（エージェント）を止めて起動し直し、端末の新しい接続ができるまで待つ。できればTrue。

        仕様: docs/spec/bugs/LOCAL-025_iOSのトンネルに古い接続が残ると撮影を開始できず理由も表示されない.md
        止める命令は古いトンネルが止まる前に返り、しばらくは古い接続先が一覧に残る。古い接続先を使うと
        また失敗するため、止める前と異なる接続先が一覧に載るまで待つ。実測では約2秒。
        """
        add_log("🔄 iOSのトンネルに接続できないため、トンネルを起動し直します...")
        env = os.environ.copy()
        env["ENABLE_GO_IOS_AGENT"] = "user"
        old_endpoint = self._ios_tunnel_endpoint(udid, env)
        if not self.stop_ios_tunnel():
            return False
        if self._wait_for_ios_tunnel(udid, env, exclude=old_endpoint):
            return True
        add_log("⚠️ トンネルの起動を待ちましたが、端末の新しい接続を確認できませんでした")
        return False

    def stop_ios_tunnel(self):
        """go-iosの常駐トンネル（エージェント）を止める。止める命令を送れたらTrue。

        仕様: docs/spec/native-window.md（終了時の後始末でトンネルも止める）
        仕様: docs/spec/bugs/LOCAL-025_iOSのトンネルに古い接続が残ると撮影を開始できず理由も表示されない.md
        """
        env = os.environ.copy()
        env["ENABLE_GO_IOS_AGENT"] = "user"
        try:
            subprocess.run([self.ios, "tunnel", "stopagent"], env=env, capture_output=True, timeout=10,
                           creationflags=paths.CREATE_NO_WINDOW)
            return True
        except Exception as e:
            add_log(f"⚠️ トンネルの停止に失敗しました: {e}")
            return False

    def _stream_stderr_to_log(self, pipe):
        """go-iosの標準エラー出力を監視し、JSON形式のfatal/errorログがあれば、切断時に
        ユーザー向けメッセージへ反映できるよう self.last_stream_error に保持する。
        Live Logsを埋めないよう、通常のログへは転送しない。

        仕様: docs/spec/bugs/LOCAL-017_ストリーム接続の一時的な切断で自動撮影全体が停止する.md
        """
        try:
            for raw_line in iter(pipe.readline, b''):
                line = raw_line.decode('utf-8', errors='replace').rstrip()
                if not line:
                    continue
                message = go_ios_error_message(line)
                if message:
                    self.last_stream_error = message
        except Exception:
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def stop_stream(self):
        """ストリームプロセスを安全にクローズ（クラス内で完結）"""
        self.cleanup_all_processes()
        add_log("🔌 ストリーム接続を閉じました")

    def cleanup_all_processes(self):
        """管理している全プロセスを終了。

        仕様: docs/spec/bugs/LOCAL-017_ストリーム接続の一時的な切断で自動撮影全体が停止する.md
        terminate()で終わらない場合はkill()で確実に終了させる。終了し切れずポートを
        握ったままのプロセスが残ると、次回のストリーム起動が不安定になるため。
        """
        for p in self.processes:
            try:
                p.terminate()
                p.wait(timeout=1)
                continue
            except Exception:
                pass
            try:
                p.kill()
                p.wait(timeout=1)
            except Exception:
                pass
        self.processes.clear()


dev_manager = DeviceManager()
