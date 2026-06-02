import atexit
import collections
import cv2
import io
import logging
import numpy as np
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import tempfile
import urllib.request
import webbrowser
import zipfile
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, Response

CREATE_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0

if getattr(sys, 'frozen', False):
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    EXE_DIR = os.path.dirname(sys.executable)
    if "MacOS" in EXE_DIR:
        EXE_DIR = os.path.abspath(os.path.join(EXE_DIR, "../../../"))
else:
    base_path = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))

SAVE_DIR = os.path.join(EXE_DIR, "captures")
os.makedirs(SAVE_DIR, exist_ok=True)

# 状態管理・ストリーム管理
is_running = False
stream_process = None
last_error = None
last_frame_data = None
bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=5, varThreshold=16, detectShadows=False)

log_queue = collections.deque(maxlen=100)
log_condition = threading.Condition()
log_counter = 0

current_config = {
    "interval": 0.2,
    "settling": 0.4,
    "prefix": "",
    "mode": "static"
}

app = Flask(__name__,
            template_folder=os.path.join(base_path, 'templates'),
            static_folder=os.path.join(base_path, 'static'))

logging.getLogger('werkzeug').setLevel(logging.ERROR)


def add_log(message):
    global log_counter
    timestamp = time.strftime("%H:%M:%S")
    full_msg = f"[{timestamp}] {message}"
    print(full_msg)
    with log_condition:
        log_counter += 1
        log_queue.append((log_counter, full_msg))
        log_condition.notify_all()


# ==========================================
# デバイス処理クラス（ストリーミング＋高画質スクショ）
# ==========================================
class DeviceManager:
    def __init__(self):
        # 属性の定義は必ずここで行います
        self.processes = [] 
        
        if platform.system() == "Windows":
            self.adb = os.path.join(base_path, "bin", "win", "adb.exe")
            self.ios = os.path.join(base_path, "bin", "win", "go-ios.exe")
        else:
            self.adb = os.path.join(base_path, "bin", "mac", "adb")
            self.ios = os.path.join(base_path, "bin", "mac", "go-ios")
            if os.path.exists(self.adb): os.chmod(self.adb, 0o755)
            if os.path.exists(self.ios): os.chmod(self.ios, 0o755)
            
        self.cached_device = None
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
                p = subprocess.Popen(
                    [self.ios, "screenshot", "--stream", "--port=3333"], 
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
                )
                self.processes.append(p)
                time.sleep(1.5)
                return "ios", None  # タプルで返す
            
            elif device == "android":
                add_log("🤖 Android ストリーム接続を開始します...")
                subprocess.run([self.adb, "forward", "--remove-all"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
                subprocess.run([self.adb, "forward", "tcp:3333", "tcp:3333"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)

                p = subprocess.Popen(
                    [self.adb, "shell", "screenrecord", "--output-format=h264", "-"], 
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
                )
                self.processes.append(p)
                return "android", None  # タプルで返す
                
        except Exception as e:
            add_log(f"詳細エラー: {type(e).__name__}: {str(e)}")
            return None, f"❌ ストリームの開始に失敗しました: {str(e)}"

    def capture_high_quality(self, output_path):
        """静止した瞬間のみ叩かれる、最高画質のロスレススクリーンショット"""
        if self.cached_device == "ios":
            env = os.environ.copy()
            env["ENABLE_GO_IOS_AGENT"] = "user"
            res = subprocess.run([self.ios, "screenshot", f"--output={output_path}"], env=env, capture_output=True, creationflags=CREATE_NO_WINDOW)
            return "iOS" if res.returncode == 0 else None
        elif self.cached_device == "android":
            with open(output_path, "wb") as f:
                res = subprocess.run([self.adb, "exec-out", "screencap", "-p"], stdout=f, capture_output=False, creationflags=CREATE_NO_WINDOW)
            return "Android" if res.returncode == 0 else None
        return None

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

class iOSStreamReceiver(threading.Thread):
    """iOS専用:バックグラウンドで常にストリームを読み込み、常に最新の1コマだけを保持するクラス"""
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.latest_frame = None
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
                            else:
                                break
            except Exception as e:
                # 接続が切れたらエラーを記録し、runningをFalseにしてループを終了させる
                print(f"Debug:⚠️ iOS device disconnected: {e}")
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
            except Exception as e:
                print(f"Debug:⚠️ Android device disconnected: {e}")
                self.last_error = f"⚠️ Androidデバイスとの接続が切れました"
                self.running = False
                break
            time.sleep(0.05)

    def stop(self):
        self.running = False
    
    def is_healthy(self):
        return self.is_alive() and self.running

dev_manager = DeviceManager()

# ==========================================
# 判定・メインループ処理
# ==========================================
def process_frame_changed(frame, is_static_mode=False):
    global last_frame_data
    if frame is None: return False
    
    # 1. 常に固定サイズ（ハーフ解像度）にリサイズ
    h, w = frame.shape[:2]
    target_w, target_h = w // 2, h // 2
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (target_w, target_h))
    
    # 2. 基準データが存在しない、またはサイズ不一致なら再初期化（エラー回避）
    if last_frame_data is None or last_frame_data.shape != gray.shape:
        last_frame_data = gray
        return False
    
    # 3. 差分計算
    diff = cv2.absdiff(last_frame_data, gray)
    score = np.mean(diff)
    
    # 4. 閾値判定
    threshold = 0.5 if is_static_mode else 0.25
    
    if score > threshold:
        last_frame_data = gray
        return True
    return False


def get_stream_frames(url, device_type):
    """HTTPストリームからバイナリを直接パースしてOpenCVフレームを切り出す"""
    try:
        stream = urllib.request.urlopen(url, timeout=5)
        bytes_data = b''
        
        while is_running:
            chunk = stream.read(4096)
            if not chunk:
                break
            bytes_data += chunk
            
            # JPEGデータの開始(0xffd8)と終了(0xffd9)のバイナリを高速検索
            while True:
                a = bytes_data.find(b'\xff\xd8')
                b = bytes_data.find(b'\xff\xd9')
                
                if a != -1 and b != -1 and a < b:
                    jpg = bytes_data[a:b+2]
                    bytes_data = bytes_data[b+2:]
                    
                    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        yield frame
                else:
                    break
    except Exception as e:
        if is_running:
            add_log(f"⚠️ ストリーム受信エラー (端末を再接続してください): {e}")


def auto_capture_loop():
    global is_running, last_error, last_frame_data
    
    last_error = None
    
    device_type, error_msg = dev_manager.start_stream()
    if not device_type:
        last_error = error_msg
        add_log(f"{error_msg}")
        is_running = False
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

    while is_running:
        if not receiver.is_healthy():
            last_error = receiver.last_error or "ストリームが切断されました。"
            add_log(f"{last_error}")
            is_running = False
            break
        start_time = time.time()
        conf = current_config

        # その瞬間の「最新の1コマ」を直接取得
        frame = receiver.latest_frame
        if frame is None:
            time.sleep(0.05)
            continue

        # 変化検知（仕様に沿った判定）
        changed = process_frame_changed(frame)

        # # デバッグ用：変化なしと判定された時のスコアを表示
        # if not changed:
        #     # gray画像を計算してscoreを再計算
        #     gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (frame.shape[1]//2, frame.shape[0]//2))
        #     score = np.mean(cv2.absdiff(last_frame_data, gray))
        #     if score > 0:
        #         print(f"DEBUG: score={score:.4f} (変化なし判定)")

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
                
                if is_running:
                    # 待機が明けた「その瞬間」の最新フレームを再度取得して保存
                    final_frame = receiver.latest_frame if receiver.latest_frame is not None else frame
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    final_name = f"{conf['prefix']}_{device_type}_{timestamp}.png" if conf['prefix'] else f"{device_type}_{timestamp}.png"
                    dest_path = os.path.join(SAVE_DIR, final_name)
                    
                    cv2.imwrite(dest_path, final_frame)
                    add_log(f"📸 撮影完了: {final_name}")
                    
                    # 撮影直後の状態を基準にする
                    last_frame_data = cv2.cvtColor(final_frame, cv2.COLOR_BGR2GRAY)
                    time.sleep(0.3)

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
                        if is_running:
                            timestamp = time.strftime("%Y%m%d_%H%M%S")
                            final_name = f"{conf['prefix']}_{device_type}_{timestamp}.png" if conf['prefix'] else f"{device_type}_{timestamp}.png"
                            dest_path = os.path.join(SAVE_DIR, final_name)
                            
                            cv2.imwrite(dest_path, frame)
                            add_log(f"📸 撮影完了: {final_name}")
                            
                            # 状態をロックし、カウントをクリア
                            already_captured = True
                            stable_count = 0

        # 指定されたチェック間隔（0.5秒など）になるよう正確にウェイトを入れる
        elapsed = time.time() - start_time
        sleep_time = max(0.01, conf["interval"] - elapsed)
        time.sleep(sleep_time)

    receiver.stop()
    dev_manager.stop_stream()


# --- Flask Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/help')
def help_page():
    return render_template('help.html')

@app.route('/status')
def get_status():
    return jsonify({
        "is_running": is_running,
        "error": last_error,
        "mode": current_config["mode"],
    })

@app.route('/start')
def start():
    global is_running
    current_config["prefix"] = request.args.get('prefix', '')
    current_config["interval"] = float(request.args.get('interval', 0.2))
    current_config["settling"] = float(request.args.get('settling', 0.4))
    current_config["mode"] = request.args.get('mode', 'static')

    if not is_running:
        is_running = True
        mode_text = "静的" if current_config["mode"] == "static" else "動的"
        add_log(f"📋 モード: {mode_text}")
        threading.Thread(target=auto_capture_loop, daemon=True).start()
    return "Started"

@app.route('/stop')
def stop():
    global is_running
    is_running = False
    return "Stopped"

@app.route('/shutdown', methods=['POST'])
def shutdown():
    global is_running
    is_running = False
    dev_manager.stop_stream()
    
    # 終了時の一般向けログ
    add_log("🛑 システムを終了します。一時データを整理中...")
    
    def kill_process():
        time.sleep(0.5)
        try:
            # 1. 保存フォルダの削除
            if os.path.exists(SAVE_DIR):
                shutil.rmtree(SAVE_DIR)
            
            # 2. iOSキャッシュ（selfidentity.plist）の削除
            home = os.path.expanduser("~")
            plist_path = os.path.join(home, "Library/Preferences/com.apple.selfidentity.plist")
            if os.path.exists(plist_path):
                os.remove(plist_path)
            
            # 3. Windows一時ファイルの削除（該当する場合）
            if platform.system() == "Windows":
                tmp = tempfile.gettempdir()
                for item in os.listdir(tmp):
                    if "ios" in item or "adb" in item:
                        shutil.rmtree(os.path.join(tmp, item), ignore_errors=True)
            
            print("🧹 終了処理が完了しました。")
        except Exception as e: 
            print(f"⚠️ クリーンアップ中にエラーが発生しました: {e}")
        
        os._exit(0)
        
    threading.Thread(target=kill_process, daemon=True).start()
    return "Shutdown"

@app.route('/images')
def get_images():
    images = [f for f in os.listdir(SAVE_DIR) if f.endswith('.png')]
    def get_mtime_safe(x):
        try: return os.path.getmtime(os.path.join(SAVE_DIR, x))
        except FileNotFoundError: return 0
    images.sort(key=get_mtime_safe, reverse=True)
    return jsonify(images)

@app.route('/update_settings')
def update_settings():
    current_config["interval"] = float(request.args.get('interval', 0.2))
    current_config["settling"] = float(request.args.get('settling', 0.4))
    current_config["prefix"] = request.args.get('prefix', '')
    current_config["mode"] = request.args.get('mode', 'static')
    add_log(f"📋 設定更新: {current_config}")
    return "Updated"

@app.route('/logs/stream')
def stream_logs():
    last_sent_id = int(request.headers.get('Last-Event-ID', '0') or 0)
    def event_stream(initial_id):
        last_sent_id = initial_id
        with log_condition:
            current_items = [item for item in log_queue if item[0] > last_sent_id]
        for log_id, msg in current_items:
            safe_msg = msg.replace('\n', '\ndata: ')
            yield f"id: {log_id}\ndata: {safe_msg}\n\n"
            last_sent_id = log_id
        while True:
            with log_condition:
                log_condition.wait()
                new_items = [item for item in log_queue if item[0] > last_sent_id]
            for log_id, msg in new_items:
                safe_msg = msg.replace('\n', '\ndata: ')
                yield f"id: {log_id}\ndata: {safe_msg}\n\n"
                last_sent_id = log_id
    return Response(event_stream(last_sent_id), mimetype='text/event-stream; charset=utf-8')

@app.route('/logs')
def get_logs():
    response = jsonify([msg for _, msg in list(log_queue)])
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.route('/static/captures/<path:filename>')
def serve_image(filename):
    return send_from_directory(SAVE_DIR, filename)

@app.route('/clear_all', methods=['POST'])
def clear_all():
    try:
        for filename in os.listdir(SAVE_DIR):
            file_path = os.path.join(SAVE_DIR, filename)
            if os.path.isfile(file_path): os.unlink(file_path)
        add_log("🗑️ 全ての画像を削除しました")
        return "Cleared"
    except Exception as e: return str(e), 500

@app.route('/delete_selected', methods=['POST'])
def delete_selected():
    data = request.json
    filenames = data.get('filenames', [])
    for name in filenames:
        path = os.path.join(SAVE_DIR, name)
        if os.path.exists(path): os.remove(path)
    add_log(f"🗑️ 選択された {len(filenames)} 件の画像を削除しました")
    return "Deleted"

@app.route('/download_selected', methods=['POST'])
def download_selected():
    data = request.json
    filenames = data.get('filenames', [])
    if not filenames: return "No files selected", 400

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for name in filenames:
            path = os.path.join(SAVE_DIR, name)
            if os.path.exists(path): zf.write(path, arcname=name)
    memory_file.seek(0)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name=f'captures_{timestamp}.zip')

if __name__ == '__main__':
    try:
        if platform.system() == "Windows":
            subprocess.run('cmd /c "for /f \"tokens=5\" %a in (\'netstat -aon ^| findstr 5001\') do taskkill /f /pid %a"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        else:
            subprocess.run("kill -9 $(lsof -t -i:5001)", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)
    except: pass

    threading.Timer(0.5, lambda: webbrowser.open('http://127.0.0.1:5001')).start()
    add_log("🚀 OmniShot を起動中...")
    app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False, threaded=True)