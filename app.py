import subprocess
import time
import threading
import platform
import cv2
import numpy as np
import collections
import zipfile
import io
import os
import sys
import webbrowser
import shutil
import logging
import json
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, Response
from werkzeug.utils import secure_filename

# Windows用にウインドウ非表示フラグを定義
CREATE_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0

# PyInstallerパッケージ化時と通常実行時のパス解決を完全に統一
if getattr(sys, 'frozen', False):
    # Macの .app 内の一時展開先（_MEIPASS）を最優先で取得
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    # 成果物（captures）の保存先は、.app の外（ユーザーに見える場所）に固定
    EXE_DIR = os.path.dirname(sys.executable)
    if "MacOS" in EXE_DIR:
        # .app/Contents/MacOS/ の中に入ってしまっている場合は .app の外に出す
        EXE_DIR = os.path.abspath(os.path.join(EXE_DIR, "../../../"))
else:
    base_path = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))

SAVE_DIR = os.path.join(EXE_DIR, "captures")
os.makedirs(SAVE_DIR, exist_ok=True)

# ==========================================
# 1. 共通インターフェース（設計図）
# ==========================================
class BaseCapturer:
    def get_current_device(self):
        raise NotImplementedError
    
    def initialize_devices(self):
        "デバイス認識と信頼確認ダイアログを促す"
        raise NotImplementedError
        
    def capture(self, output_path):
        raise NotImplementedError

# ==========================================
# 2. Mac専用の処理クラス
# ==========================================
class MacCapturer(BaseCapturer):
    def __init__(self):
        self.adb = os.path.join(base_path, "bin", "mac", "adb")
        self.ios = os.path.join(base_path, "bin", "mac", "go-ios")
        
        for bin_path in [self.adb, self.ios]:
            if os.path.exists(bin_path):
                os.chmod(bin_path, 0o755)
    
    def initialize_devices(self):
        try:
            if os.path.exists(self.ios):
                subprocess.run(
                    [self.ios, "list"],
                    capture_output=True,
                    timeout=3,
                    creationflags=CREATE_NO_WINDOW
                )
        except:
            pass
        try:
            if os.path.exists(self.adb):
                subprocess.run(
                    [self.adb, "devices"],
                    capture_output=True,
                    timeout=3,
                    creationflags=CREATE_NO_WINDOW
                )
        except:
            pass

    def get_current_device(self):
        try:
            res = subprocess.run(
                [self.ios, "list"],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=CREATE_NO_WINDOW
            )
            if "0000" in res.stdout: return "ios"
        except: pass
        try:
            res = subprocess.run(
                [self.adb, "devices"],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=CREATE_NO_WINDOW
            )
            lines = res.stdout.strip().split('\n')
            if len(lines) > 1 and "device" in lines[1]: return "android"
        except: pass
        return None

    def capture(self, output_path):
        device = self.get_current_device()
        if device == "ios":
            env = os.environ.copy()
            env["ENABLE_GO_IOS_AGENT"] = "user"
            res = subprocess.run(
                [self.ios, "screenshot", f"--output={output_path}"],
                env=env,
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW
            )
            if res.returncode != 0:
                add_log(f"⚠️ iOS screenshot failed: {res.stderr.strip()}")
                return None
            return "iOS"
        elif device == "android":
            with open(output_path, "wb") as f:
                res = subprocess.run(
                    [self.adb, "exec-out", "screencap", "-p"],
                    stdout=f,
                    stderr=subprocess.PIPE,
                    creationflags=CREATE_NO_WINDOW
                )
            if res.returncode != 0:
                add_log(f"⚠️ Android screenshot failed: {res.stderr.decode().strip()}")
                return None
            return "Android"
        return None

# ==========================================
# 3. Windows専用の処理クラス
# ==========================================
class WindowsCapturer(BaseCapturer):
    def __init__(self):
        self.adb = os.path.join(base_path, "bin", "win", "adb.exe")
        self.ios = os.path.join(base_path, "bin", "win", "go-ios.exe")
        
        self._init_windows_firewall()

    def _init_windows_firewall(self):
        try:
            if os.path.exists(self.adb):
                subprocess.run(
                    [self.adb, "start-server"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=CREATE_NO_WINDOW
                )
                subprocess.run(
                    [self.adb, "devices"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=CREATE_NO_WINDOW
                )
            if os.path.exists(self.ios):
                subprocess.run(
                    [self.ios, "list"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=CREATE_NO_WINDOW
                )
        except Exception as e:
            print(f"Windows Firewall initialization failed: {e}")
    
    def initialize_devices(self):
        try:
            if os.path.exists(self.ios):
                subprocess.run(
                    [self.ios, "list"],
                    capture_output=True,
                    timeout=3,
                    creationflags=CREATE_NO_WINDOW
                )
        except:
            pass
        try:
            if os.path.exists(self.adb):
                subprocess.run(
                    [self.adb, "devices"],
                    capture_output=True,
                    timeout=3,
                    creationflags=CREATE_NO_WINDOW
                )
        except:
            pass

    def get_current_device(self):
        try:
            res = subprocess.run(
                [self.ios, "list"],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=CREATE_NO_WINDOW
            )
            if "0000" in res.stdout: return "ios"
        except: pass
        try:
            res = subprocess.run(
                [self.adb, "devices"],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=CREATE_NO_WINDOW
            )
            lines = res.stdout.strip().split('\n')
            if len(lines) > 1 and "device" in lines[1]: return "android"
        except: pass
        return None

    def capture(self, output_path):
        device = self.get_current_device()
        if device == "ios":
            env = os.environ.copy()
            env["ENABLE_GO_IOS_AGENT"] = "user"
            res = subprocess.run(
                [self.ios, "screenshot", f"--output={output_path}"],
                env=env,
                creationflags=CREATE_NO_WINDOW,
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                add_log(f"⚠️ iOS screenshot failed: {res.stderr.strip()}")
                return None
            return "iOS"
        elif device == "android":
            with open(output_path, "wb") as f:
                res = subprocess.run(
                    [self.adb, "exec-out", "screencap", "-p"],
                    stdout=f,
                    creationflags=CREATE_NO_WINDOW,
                    stderr=subprocess.PIPE,
                )
            if res.returncode != 0:
                add_log(f"⚠️ Android screenshot failed: {res.stderr.decode().strip()}")
                return None
            return "Android"
        return None

# ==========================================
# 4. 起動時にOSを自動判別して実体を確定
# ==========================================
def get_capturer():
    if platform.system() == "Windows":
        return WindowsCapturer()
    else:
        return MacCapturer()

capturer = get_capturer()

# 状態管理
is_running = False
last_frame_data = None
log_queue = collections.deque(maxlen=100)
log_condition = threading.Condition()
log_counter = 0

# 現在の設定値を保持する共通辞書
current_config = {
    "interval": 1.0,
    "settling": 2.0,
    "prefix": "",
    "mode": "static"
}

# Flaskのテンプレートとスタティックの場所を固定
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

def has_screen_changed(new_image_path):
    global last_frame_data
    new_frame = cv2.imread(new_image_path)
    if new_frame is None: return False
    gray = cv2.cvtColor(new_frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (200, 400)) 
    if last_frame_data is None:
        last_frame_data = gray
        return True
    diff = cv2.absdiff(last_frame_data, gray)
    score = np.mean(diff)
    
    threshold = 0.4
    if score > threshold:
        last_frame_data = gray
        return True
    return False

def auto_capture_loop():
    global is_running
    add_log("▶️ 撮影ループ開始")
    
    while is_running:
        conf = current_config
        mode = conf["mode"]
        
        if mode == "static":
            auto_capture_static_mode()
        else:
            auto_capture_dynamic_mode()

def auto_capture_static_mode():
    "静的モード: 変化を検知してから固定時間待つ"
    conf = current_config
    check_interval = conf["interval"]
    settling_time = conf["settling"]
    
    temp_file = os.path.join(SAVE_DIR, "temp_check.png")
    # 💡 OS判別済みの capturer インスタンスから呼び出し
    device_type = capturer.capture(temp_file)
    
    if device_type and os.path.exists(temp_file):
        if has_screen_changed(temp_file):
            add_log(f"🎬 変化検知... 静止待機中 ({settling_time}s)")
            
            if settling_time > 0:
                start_wait = time.time()
                while time.time() - start_wait < settling_time and is_running:
                    time.sleep(check_interval)
                    capturer.capture(temp_file)
            
            if is_running and os.path.exists(temp_file):
                prefix = current_config["prefix"]
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                prefix_part = f"{prefix}_" if prefix else ""
                final_name = f"{prefix_part}{device_type}_{timestamp}.png"
                
                save_path = os.path.join(SAVE_DIR, final_name)
                os.rename(temp_file, save_path)
                add_log(f"✅ 保存完了: {final_name}")
                time.sleep(1.0)
        else:
            if os.path.exists(temp_file):
                os.remove(temp_file)
    
    time.sleep(check_interval)

def auto_capture_dynamic_mode():
    "動的モード: 画面が止まった瞬間だけ撮影（1回のみ）"
    conf = current_config
    check_interval = conf["interval"]
    settling_time = conf["settling"]
    
    if not hasattr(auto_capture_dynamic_mode, 'already_captured'):
        auto_capture_dynamic_mode.already_captured = False
        auto_capture_dynamic_mode.stable_count = 0
    
    frames_needed = max(1, int(settling_time / check_interval))
    
    temp_file = os.path.join(SAVE_DIR, "temp_check.png")
    # 💡 OS判別済みの capturer インスタンスから呼び出し
    device_type = capturer.capture(temp_file)
    
    if device_type and os.path.exists(temp_file):
        if has_screen_changed(temp_file):
            auto_capture_dynamic_mode.already_captured = False
            auto_capture_dynamic_mode.stable_count = 0
            add_log("🎬 画面動作中...")
        else:
            auto_capture_dynamic_mode.stable_count += 1
            
            if auto_capture_dynamic_mode.stable_count <= frames_needed:
                add_log(f"📊 静止確認: {auto_capture_dynamic_mode.stable_count}/{frames_needed}")
            
            if auto_capture_dynamic_mode.stable_count >= frames_needed and not auto_capture_dynamic_mode.already_captured and is_running:
                prefix = current_config["prefix"]
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                prefix_part = f"{prefix}_" if prefix else ""
                final_name = f"{prefix_part}{device_type}_{timestamp}.png"
                
                save_path = os.path.join(SAVE_DIR, final_name)
                os.rename(temp_file, save_path)
                add_log(f"✅ 撮影完了: {final_name}")
                auto_capture_dynamic_mode.already_captured = True
                time.sleep(1.0)
    
    time.sleep(check_interval)

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start')
def start():
    global is_running
    current_config["prefix"] = request.args.get('prefix', '')
    current_config["interval"] = float(request.args.get('interval', 0.5))
    current_config["settling"] = float(request.args.get('settling', 1.0))
    current_config["mode"] = request.args.get('mode', 'static')

    if not is_running:
        is_running = True
        # デバイス認識を実行（信頼確認ダイアログを促す）
        capturer.initialize_devices()
        mode_text = "静的" if current_config["mode"] == "static" else "動的"
        add_log(f"📋 モード: {mode_text}")
        threading.Thread(target=auto_capture_loop, daemon=True).start()
    return "Started"

@app.route('/help')
def help_page():
    return render_template('help.html')

@app.route('/stop')
def stop():
    global is_running
    is_running = False
    return "Stopped"

@app.route('/shutdown', methods=['POST'])
def shutdown():
    add_log("🛑 サーバー終了リクエストを受信。一時データを削除してアプリを閉じます。")
    
    def kill_process():
        time.sleep(0.5)
        try:
            if os.path.exists(SAVE_DIR):
                shutil.rmtree(SAVE_DIR)
                print("🧹 captures フォルダを正常に削除しました。")
        except Exception as e:
            print(f"⚠️ フォルダ削除中にエラーが発生: {e}")
            
        os._exit(0)
        
    threading.Thread(target=kill_process).start()
    return "Shutdown"

@app.route('/images')
def get_images():
    # ファイル一覧を撮影時間（ファイル名のタイムスタンプ部分）でソート
    # ファイル名フォーマット: [prefix_]Device_YYYYMMDD_HHMMSS_microseconds.png
    images = [f for f in os.listdir(SAVE_DIR) if f.endswith('.png') and f != 'temp_check.png']
    # タイムスタンプをキーにして最新順でソート
    images.sort(key=lambda x: os.path.getmtime(os.path.join(SAVE_DIR, x)), reverse=True)
    return jsonify(images)

@app.route('/update_settings')
def update_settings():
    current_config["interval"] = float(request.args.get('interval', 0.5))
    current_config["settling"] = float(request.args.get('settling', 1.0))
    current_config["prefix"] = request.args.get('prefix', '')
    current_config["mode"] = request.args.get('mode', 'static')
    print(f"Config updated: {current_config}")
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
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/static/captures/<path:filename>')
def serve_image(filename):
    return send_from_directory(SAVE_DIR, filename)

@app.route('/clear_all', methods=['POST'])
def clear_all():
    try:
        for filename in os.listdir(SAVE_DIR):
            file_path = os.path.join(SAVE_DIR, filename)
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
        add_log("🗑️ 全ての画像を削除しました")
        return "Cleared"
    except Exception as e:
        return str(e), 500

@app.route('/delete_selected', methods=['POST'])
def delete_selected():
    data = request.json
    filenames = data.get('filenames', [])
    
    # 💡 captures フォルダ内の本物のファイル名リストを事前取得
    actual_files = [f for f in os.listdir(SAVE_DIR) if f.endswith('.png')]
    
    deleted_count = 0
    for name in filenames:
        # 1. 本物のファイル名がそのまま届いた場合は直接削除
        path = os.path.join(SAVE_DIR, name)
        if os.path.exists(path):
            os.remove(path)
            deleted_count += 1
            continue
            
        # 2. 💡 日本語名（表示名）が届いた場合、フォルダ内のファイル群から前方一致で本物を探して削除
        # 例: 「ようこそ.png」が届いたら、「iOS_20260528_105154」のような本物を特定する
        target_base = name.replace('.png', '').strip()
        for actual_name in actual_files:
            if actual_name.replace('.png', '') == target_base:
                actual_path = os.path.join(SAVE_DIR, actual_name)
                if os.path.exists(actual_path):
                    os.remove(actual_path)
                    deleted_count += 1
                    break

    add_log(f"🗑️ 選択された {deleted_count} 件の画像をフォルダから削除しました")
    return "Deleted"

@app.route('/download_selected', methods=['POST'])
def download_selected():
    data = request.json
    filenames = data.get('filenames', [])
    zip_name = data.get('zipName', 'captures') # JS側のキー名 'zipName' に合わせる
    name_map = data.get('nameMap', [])        # 💡 JS側から届く名前の対応表を取得
    
    if not filenames:
        return "No files selected", 400

    # 💡 内部ファイル名から、ユーザーが変更した表示名（日本語名）を引ける辞書を作る
    output_names = {item['file']: item['outputName'] for item in name_map}

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for name in filenames:
            path = os.path.join(SAVE_DIR, name)
            if os.path.exists(path):
                # 💡 変更後の名前（日本語）があればそれを使い、なければ元の名前でZIPに保存する
                arcname = output_names.get(name, name)
                zf.write(path, arcname=arcname)
    
    memory_file.seek(0)
    
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_name if zip_name.endswith('.zip') else f"{zip_name}.zip"
    )

@app.route('/rename', methods=['POST'])
def rename_image():
    data = request.json
    old_display = data.get('oldDisplay', '')  # 変更前の表示名
    new_display = data.get('newDisplay', '')  # 変更後の表示名（空欄時はオリジナル名）
    
    if new_display:
        # 💡 名前が新しく設定された場合のログ
        add_log(f"🔁 表示名変更: {old_display} → {new_display}")
    else:
        # 💡 空欄リセットされた場合のログ
        add_log(f"🔄 表示名を元のファイル名にリセットしました: {old_display}")
        
    return jsonify({"ok": True})

if __name__ == '__main__':
    # 💡 既存のサーバー（ポート5001）が起動している場合は強制終了する
    try:
        if platform.system() == "Windows":
            subprocess.run(
                'cmd /c "for /f \"tokens=5\" %a in (\'netstat -aon ^| findstr 5001\') do taskkill /f /pid %a"',
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
            )
        else:
            # Mac用のプロセス終了コマンド
            subprocess.run(
                "kill -9 $(lsof -t -i:5001)",
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        time.sleep(0.5)  # ポートが解放されるのを少し待つ
    except:
        pass

    threading.Timer(0.5, lambda: webbrowser.open('http://127.0.0.1:5001')).start()
    add_log("🚀 OmniShot を起動中...")
    app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False, threaded=True)