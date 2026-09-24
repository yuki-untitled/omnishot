# 仕様: docs/spec/screenshot-capture.md
# 仕様: docs/spec/device-selection.md
"""端末（adb・go-ios）とのやり取り: 一覧の検出、ストリームの起動、1回だけの画面取得、iOS のトンネルの管理。"""
import atexit
import json
import os
import platform
import plistlib
import socket
import struct
import subprocess
import tempfile
import threading
import time

import cv2

from . import paths
from .logs import add_log
from .stream_receivers import decode_image

# 仕様: docs/spec/device-selection.md（このメッセージのときは、画面が端末の一覧を自動で検出し直す）
DEVICE_NOT_CONNECTED_MESSAGE = "❌ 選択した端末が接続されていません。ケーブルを確認してください。"

# 仕様: docs/spec/device-selection.md（撮影できる状態ではない Android 端末の理由と対処）
ANDROID_STATE_HINTS = {
    "unauthorized": "USBデバッグが許可されていません。端末の画面の「USBデバッグを許可しますか？」で「許可」を押してから、更新ボタンを押してください。",
    "offline": "端末が応答していません。ケーブルを挿し直してから、更新ボタンを押してください。",
    "authorizing": "USBデバッグの許可を確認しています。少し待ってから、更新ボタンを押してください。",
}

# iOSストリーム（mjpegサーバー）が待ち受けるポート。capture.py の受信側もこれを参照する。
IOS_STREAM_PORT = 3333


def _run(cmd, timeout, env=None, text=False):
    """コンソールウィンドウを出さずにコマンドを実行し、出力を受け取る。"""
    return subprocess.run(cmd, env=env, capture_output=True, text=text, timeout=timeout,
                          creationflags=paths.CREATE_NO_WINDOW)


def _go_ios_env(agent=True):
    """go-ios に渡す環境変数。

    agent=True: iOS 17 以降の通信に使う常駐トンネル（エージェント）を、必要なら自動で起動させる。
    agent=False: 自動で起動させない。
      仕様: docs/spec/bugs/LOCAL-030_終了時にiOSのトンネルが動いていないとトンネルが起動して残る.md
      トンネルを止める命令に付けると、トンネルが動いていないときに起動してしまい残るため。
    """
    env = os.environ.copy()
    if agent:
        env["ENABLE_GO_IOS_AGENT"] = "user"
    else:
        env.pop("ENABLE_GO_IOS_AGENT", None)
    return env


def _stderr_text(res):
    return res.stderr.decode('utf-8', errors='replace').strip() if res.stderr else ""


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


def _json_lines(stdout):
    """go-ios の出力（1行に1つの JSON）のうち、読める行を dict として順に返す。"""
    for line in stdout.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            yield data


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


def _android_state_problem(serial, state_name):
    """撮影できる状態ではない Android 端末について、ログに出す理由と対処を返す。

    仕様: docs/spec/device-selection.md（撮影できる状態ではない端末は、理由と対処をログに出す）
    """
    hint = ANDROID_STATE_HINTS.get(state_name, f"撮影できる状態ではありません（adbの状態: {state_name}）。")
    return f"⚠️ Android端末（…{serial[-6:]}）: {hint}"


class DeviceManager:
    def __init__(self):
        # 属性の定義は必ずここで行います
        self.processes = []
        # 仕様: docs/spec/device-selection.md
        # 直近の一覧の検出で見つかった、撮影できる状態ではない Android 端末の理由（ログ表示用）
        self.android_device_problems = []
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

    def adb_command(self, serial, *args):
        """指定した端末に対する adb のコマンドを組み立てる（serial が空なら端末を指定しない）。"""
        return [self.adb] + (["-s", serial] if serial else []) + list(args)

    # ------------------------------------------------------------------
    # 端末の一覧
    # ------------------------------------------------------------------
    def list_devices(self):
        """USB接続されている端末の一覧を返す。要素は {"id", "os", "name"}（nameは取得できなければNone）。"""
        return self._list_android_devices() + self._list_ios_devices()

    def _list_android_devices(self):
        devices = []
        problems = []
        try:
            res = self._adb_devices()
            # 仕様: docs/spec/native-window.md（終了時に adb サーバーを止めるため、次の起動時はサーバーが起動し直す）
            # サーバーを起動した直後は端末の認識が間に合わないことがあるため、1秒待って1回だけ検出し直す
            if "daemon started successfully" in res.stderr and len(res.stdout.strip().split('\n')) <= 1:
                time.sleep(1.0)
                res = self._adb_devices()
            # 2行目以降が端末。例: "<serial> device usb:1-1 product:x model:Pixel_7 ..."
            for line in res.stdout.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) < 2:
                    continue
                serial, adb_state = parts[0], parts[1]
                # 仕様: docs/spec/device-selection.md（USB接続の端末のみを対象にする）
                if not any(p.startswith("usb:") for p in parts[2:]):
                    continue
                if adb_state != "device":
                    problems.append(_android_state_problem(serial, "no permissions" if adb_state == "no" else adb_state))
                    continue
                model = next((p[len("model:"):] for p in parts if p.startswith("model:")), None)
                devices.append({"id": serial, "os": "android", "name": model.replace("_", " ") if model else None})
        except Exception as e:
            print(f"DEBUG: Android check failed: {e}")
        self.android_device_problems = problems
        return devices

    def _adb_devices(self):
        # サーバー起動を待つためタイムアウトを 5.0秒 に
        return _run([self.adb, "devices", "-l"], timeout=5.0, text=True)

    def _list_ios_devices(self):
        devices = []
        try:
            res = _run([self.ios, "list"], timeout=3.0, text=True)
            udids = []
            for data in _json_lines(res.stdout):
                udids = data.get("deviceList", udids)
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
            res = _run([self.ios, f"--udid={udid}", "info"], timeout=3.0, text=True)
            return next((data["DeviceName"] for data in _json_lines(res.stdout) if data.get("DeviceName")), None)
        except Exception:
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

    # ------------------------------------------------------------------
    # 自動撮影のストリーム
    # ------------------------------------------------------------------
    def start_stream(self, device_id=""):
        """選択された端末のストリームを開始する。成功時は ({"id", "os", "name"}, None)、失敗時は (None, メッセージ)。"""
        self.cleanup_all_processes()

        device, error_msg = self.resolve_device(device_id)
        if not device:
            return None, error_msg

        if device["os"] == "android":
            # Androidは AndroidScreencapReceiver が `adb exec-out screencap` を
            # 都度実行して取得するため、ここでの常駐プロセス起動は不要
            add_log("🤖 Android ストリーム接続を開始します...")
            return device, None

        add_log("📱 iOS ストリーム接続を開始します...")
        try:
            error_msg = self._start_ios_stream(device, timeout=5.0)
            # 仕様: docs/spec/bugs/LOCAL-025_iOSのトンネルに古い接続が残ると撮影を開始できず理由も表示されない.md
            # 仕様: docs/spec/native-window.md（トンネルが起動途中なら、準備ができるのを待つ）
            if error_msg and self.recover_ios_connection(device["id"], self.last_stream_error):
                error_msg = self._start_ios_stream(device, timeout=15.0)
        except Exception as e:
            add_log(f"詳細エラー: {type(e).__name__}: {str(e)}")
            return None, f"❌ ストリームの開始に失敗しました: {str(e)}"
        if error_msg:
            return None, error_msg
        return device, None

    def _start_ios_stream(self, device, timeout):
        """go-iosのストリーム（mjpegサーバー）を起動する。成功時はNone、失敗時はユーザー向けメッセージ。"""
        p = subprocess.Popen(
            [self.ios, f"--udid={device['id']}", "screenshot", "--stream", f"--port={IOS_STREAM_PORT}"],
            env=_go_ios_env(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            startupinfo=paths.get_startupinfo(), creationflags=paths.CREATE_NO_WINDOW,
        )
        self.processes.append(p)
        self.last_stream_error = None
        # 仕様: docs/spec/bugs/LOCAL-017_ストリーム接続の一時的な切断で自動撮影全体が停止する.md
        # go-ios の標準エラー出力は、以前は破棄していて失敗原因が分からなかったため、監視して切断理由を保持する
        stderr_thread = threading.Thread(target=self._watch_stream_stderr, args=(p.stderr,), daemon=True)
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

    def _watch_stream_stderr(self, pipe):
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

    # ------------------------------------------------------------------
    # 1回だけの画面取得
    # 仕様: docs/spec/manual-capture.md
    # 自動撮影が停止中の手動撮影は、常時ストリームを新規起動せず、1回分のコマンドだけで画面を取得する
    # （ストリームの起動・接続待ちを挟まないため、接続が不安定な状況でも失敗しにくい）。
    # ------------------------------------------------------------------
    def capture_single_frame(self, device):
        """指定端末の画面を1回だけ取得してフレーム（numpy配列）を返す。取得できなければNone。"""
        if device["os"] == "android":
            return self._android_screenshot_once(device)

        # iOS: 常時ストリームではなく、1回分の screenshot コマンドで一時ファイルに書き出す
        frame, reason = self._ios_screenshot_once(device)
        # 仕様: docs/spec/bugs/LOCAL-025_iOSのトンネルに古い接続が残ると撮影を開始できず理由も表示されない.md
        # 仕様: docs/spec/native-window.md（トンネルが起動途中なら、準備ができるのを待つ）
        # トンネルを整えられた場合だけ、1回だけやり直す
        if frame is None and self.recover_ios_connection(device["id"], reason):
            frame, reason = self._ios_screenshot_once(device)
        if frame is None:
            add_log(f"⚠️ iOS screenshot failed: {reason}")
        return frame

    def _android_screenshot_once(self, device):
        try:
            res = _run(self.adb_command(device["id"], "exec-out", "screencap", "-p"), timeout=10)
            if not res.stdout:
                add_log(f"⚠️ Android screenshot failed: {_stderr_text(res) or 'no output'}")
                return None
            return decode_image(res.stdout)
        except Exception as e:
            add_log(f"⚠️ Android screenshot failed: {e}")
            return None

    def _ios_screenshot_once(self, device):
        """iOSの画面を1回取得する。(フレーム, 失敗理由) を返す。成功時の失敗理由は None。"""
        fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            cmd = [self.ios, f"--udid={device['id']}", "screenshot", f"--output={tmp_path}"]
            res = _run(cmd, timeout=15, env=_go_ios_env())
            frame = cv2.imread(tmp_path)
            if frame is not None:
                return frame, None
            # 仕様: docs/spec/bugs/LOCAL-017_ストリーム接続の一時的な切断で自動撮影全体が停止する.md
            # 以前はgo-iosの出力を破棄しており、失敗原因が分からなかった
            stderr = _stderr_text(res)
            errors = [m for m in (go_ios_error_message(line) for line in stderr.splitlines()) if m]
            return None, errors[-1] if errors else (stderr or f"exit code {res.returncode}")
        except Exception as e:
            return None, str(e)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # ------------------------------------------------------------------
    # iOS のトンネル
    # ------------------------------------------------------------------
    def _ios_tunnel_endpoint(self, udid):
        """トンネルの一覧から、端末の接続先 (address, rsdPort) を返す。無ければNone。
        一覧を問い合わせると、トンネルが止まっていれば自動で起動する。"""
        try:
            res = _run([self.ios, "tunnel", "ls"], timeout=5, env=_go_ios_env(), text=True)
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
        if is_ios_tunnel_unreachable(reason):
            return self.restart_ios_tunnel(udid)
        if self._ios_tunnel_endpoint(udid) is None:
            add_log("⏳ iOSのトンネルの起動を待っています...")
            return self._wait_for_ios_tunnel(udid)
        return False

    def _wait_for_ios_tunnel(self, udid, exclude=None, timeout=10.0):
        """トンネルの一覧に、端末の接続（exclude と異なるもの）が載るまで待つ。載ればTrue。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            endpoint = self._ios_tunnel_endpoint(udid)
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
        old_endpoint = self._ios_tunnel_endpoint(udid)
        if not self.stop_ios_tunnel():
            return False
        if self._wait_for_ios_tunnel(udid, exclude=old_endpoint):
            return True
        add_log("⚠️ トンネルの起動を待ちましたが、端末の新しい接続を確認できませんでした")
        return False

    # ------------------------------------------------------------------
    # 終了時の後始末
    # 仕様: docs/spec/native-window.md（終了後も go-ios のトンネル・adb サーバーが動き続けないよう止める）
    # ------------------------------------------------------------------
    def stop_ios_tunnel(self):
        """go-iosの常駐トンネル（エージェント）を止める。止める命令を送れたらTrue。

        仕様: docs/spec/bugs/LOCAL-025_iOSのトンネルに古い接続が残ると撮影を開始できず理由も表示されない.md
        仕様: docs/spec/bugs/LOCAL-030_終了時にiOSのトンネルが動いていないとトンネルが起動して残る.md
        """
        try:
            _run([self.ios, "tunnel", "stopagent"], timeout=10, env=_go_ios_env(agent=False))
            return True
        except Exception as e:
            add_log(f"⚠️ トンネルの停止に失敗しました: {e}")
            return False

    def stop_adb_server(self):
        """adb サーバーを止める。"""
        try:
            _run([self.adb, "kill-server"], timeout=5)
        except Exception as e:
            print(f"⚠️ adb サーバーの停止に失敗しました: {e}")


dev_manager = DeviceManager()
