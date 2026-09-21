import io
import os
import platform
import re
import shutil
import tempfile
import threading
import time
import zipfile

from flask import render_template, request, jsonify, send_from_directory, send_file, Response

from . import display_names, state
from .capture import auto_capture_loop
from .device_manager import dev_manager
from .logs import add_log, log_queue, log_condition
from .paths import SAVE_DIR


def _sanitize_filename_component(name):
    """パス区切り文字・制御文字を取り除く（ZIPエントリ名・ダウンロードファイル名の共通処理）。"""
    return re.sub(r'[\\/\x00-\x1f]', '', name or '').strip()


# 仕様: docs/spec/bugs/LOCAL-009_一括削除・ZIPダウンロードがキャプチャ保存先の外のファイルを扱える.md
def _is_plain_filename(name):
    """保存先フォルダ直下の単純なファイル名（ディレクトリ区切り・制御文字を含まない）かどうか。"""
    return (
        isinstance(name, str)
        and name not in ('', '.', '..')
        and not re.search(r'[\\/\x00-\x1f]', name)
    )


def _all_plain_filenames(filenames):
    return isinstance(filenames, list) and all(_is_plain_filename(n) for n in filenames)


def _arcname_for(filename, display_name):
    """ZIP内のファイル名を決定する。表示名が未設定ならキャプチャの元ファイル名を使う。"""
    if not display_name:
        return filename
    base = _sanitize_filename_component(display_name)
    base = re.sub(r'\.png$', '', base, flags=re.IGNORECASE)
    return f"{base}.png" if base else filename


def _sanitize_zip_name(name):
    """ダウンロードするZIPファイル名を検証する。空・不正な場合は空文字を返す。"""
    cleaned = _sanitize_filename_component(name)
    if not cleaned:
        return ''
    if not cleaned.lower().endswith('.zip'):
        cleaned += '.zip'
    return cleaned


def register(app):
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/help')
    def help_page():
        return render_template('help.html')

    @app.route('/status')
    def get_status():
        return jsonify({
            "is_running": state.is_running,
            "error": state.last_error,
            "mode": state.current_config["mode"],
        })

    @app.route('/start')
    def start():
        state.current_config["prefix"] = request.args.get('prefix', '')
        state.current_config["interval"] = float(request.args.get('interval', 0.2))
        state.current_config["settling"] = float(request.args.get('settling', 0.4))
        state.current_config["mode"] = request.args.get('mode', 'static')

        if not state.is_running:
            state.is_running = True
            mode_text = "静的" if state.current_config["mode"] == "static" else "動的"
            add_log(f"📋 モード: {mode_text}")
            threading.Thread(target=auto_capture_loop, daemon=True).start()
        return "Started"

    @app.route('/stop')
    def stop():
        state.is_running = False
        return "Stopped"

    @app.route('/shutdown', methods=['POST'])
    def shutdown():
        state.is_running = False
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
        # 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md
        # 存在するキャプチャファイルの分だけ表示名を返す（削除済みファイルの表示名は含めない）
        names = display_names.load_all()
        return jsonify({
            "images": images,
            "displayNames": {name: names[name] for name in images if name in names},
        })

    # 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md
    @app.route('/rename', methods=['POST'])
    def rename():
        data = request.json or {}
        filename = data.get('filename', '')
        if not filename or os.path.basename(filename) != filename:
            return "Invalid filename", 400
        if not os.path.exists(os.path.join(SAVE_DIR, filename)):
            return "File not found", 404

        saved_name = display_names.set_display_name(filename, data.get('displayName', ''))
        add_log(f"✏️ 表示名を変更しました: {filename} → {saved_name or filename}")
        return jsonify({"filename": filename, "displayName": saved_name})

    @app.route('/update_settings')
    def update_settings():
        state.current_config["interval"] = float(request.args.get('interval', 0.2))
        state.current_config["settling"] = float(request.args.get('settling', 0.4))
        state.current_config["prefix"] = request.args.get('prefix', '')
        state.current_config["mode"] = request.args.get('mode', 'static')
        add_log(f"📋 設定更新: {state.current_config}")
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
        data = request.json or {}
        filenames = data.get('filenames', [])
        # 仕様: docs/spec/bugs/LOCAL-009_一括削除・ZIPダウンロードがキャプチャ保存先の外のファイルを扱える.md
        # 1件でも不正な名前を含む場合は、何も削除せずリクエスト全体を拒否する
        if not _all_plain_filenames(filenames):
            return "Invalid filename", 400
        for name in filenames:
            path = os.path.join(SAVE_DIR, name)
            if os.path.exists(path): os.remove(path)
        # 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md（削除との整合性）
        display_names.remove_display_names(filenames)
        add_log(f"🗑️ 選択された {len(filenames)} 件の画像を削除しました")
        return "Deleted"

    # 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md
    @app.route('/download_selected', methods=['POST'])
    def download_selected():
        data = request.json or {}
        filenames = data.get('filenames', [])
        if not filenames: return "No files selected", 400
        # 仕様: docs/spec/bugs/LOCAL-009_一括削除・ZIPダウンロードがキャプチャ保存先の外のファイルを扱える.md
        if not _all_plain_filenames(filenames):
            return "Invalid filename", 400

        names = display_names.load_all()
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w') as zf:
            for name in filenames:
                path = os.path.join(SAVE_DIR, name)
                if os.path.exists(path):
                    zf.write(path, arcname=_arcname_for(name, names.get(name)))
        memory_file.seek(0)

        zip_name = _sanitize_zip_name(data.get('zipName', ''))
        if not zip_name:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            zip_name = f'captures_{timestamp}.zip'
        return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name=zip_name)
