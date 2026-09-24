"""画面からの要求を受け付ける（Flask のエンドポイント）。処理の本体は各モジュールに置く。"""
import os
import threading
import time

from flask import render_template, request, jsonify, send_from_directory, send_file, Response

from . import display_names, state, storage
from .capture import auto_capture_loop, manual_capture
from .cleanup import cleanup_on_exit
from .device_manager import DEVICE_NOT_CONNECTED_MESSAGE, dev_manager
from .logs import add_log, log_queue, log_condition
from .paths import SAVE_DIR


def _apply_config_from_args():
    """クエリ文字列の撮影設定を state.current_config に反映する。"""
    state.current_config["prefix"] = request.args.get('prefix', '')
    state.current_config["interval"] = float(request.args.get('interval', 0.2))
    state.current_config["settling"] = float(request.args.get('settling', 0.4))
    state.current_config["mode"] = request.args.get('mode', 'static')


def _sse_event(log_id, msg):
    safe_msg = msg.replace('\n', '\ndata: ')
    return f"id: {log_id}\ndata: {safe_msg}\n\n"


def _start_session():
    """撮影を開始する。

    仕様: docs/spec/session-grouping.md（開始のたびに新しいセッションを割り当てる）
    """
    state.is_running = True
    state.session_counter += 1
    state.current_session_id = state.session_counter
    state.sessions[state.current_session_id] = {"startedAt": time.strftime("%Y/%m/%d %H:%M:%S")}
    mode_text = "静的" if state.current_config["mode"] == "static" else "動的"
    add_log(f"📋 モード: {mode_text}")
    threading.Thread(target=auto_capture_loop, daemon=True).start()


def register(app):
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/help')
    def help_page():
        return render_template('help.html')

    # ------------------------------------------------------------------
    # 撮影
    # ------------------------------------------------------------------
    @app.route('/status')
    def get_status():
        return jsonify({
            "is_running": state.is_running,
            "error": state.last_error,
            # 仕様: docs/spec/device-selection.md（選択した端末が接続されていないときは、画面が一覧を検出し直す）
            "device_missing": state.last_error == DEVICE_NOT_CONNECTED_MESSAGE,
            "mode": state.current_config["mode"],
        })

    # 仕様: docs/spec/device-selection.md
    @app.route('/devices')
    def get_devices():
        devices = dev_manager.list_devices()
        # 仕様: docs/spec/device-selection.md（撮影できる状態ではない Android 端末の理由と対処をログに出す）
        for message in dev_manager.android_device_problems:
            add_log(message)
        return jsonify(devices)

    @app.route('/start')
    def start():
        _apply_config_from_args()
        state.current_config["device"] = request.args.get('device', '')
        if not state.is_running:
            _start_session()
        return "Started"

    @app.route('/stop')
    def stop():
        state.is_running = False
        return "Stopped"

    @app.route('/update_settings')
    def update_settings():
        # 入力のたびに呼ばれるため、ログには出さない（設定変更自体はstate.current_configに反映される）
        _apply_config_from_args()
        return "Updated"

    # 仕様: docs/spec/manual-capture.md
    @app.route('/manual_capture', methods=['POST'])
    def manual_capture_route():
        filename, error_msg = manual_capture(request.args.get('device', ''))
        if error_msg:
            # 仕様: docs/spec/device-selection.md（選択した端末が接続されていないときは、画面が一覧を検出し直す）
            return jsonify({"error": error_msg, "device_missing": error_msg == DEVICE_NOT_CONNECTED_MESSAGE}), 400
        return jsonify({"filename": filename})

    # 仕様: docs/spec/native-window.md
    @app.route('/shutdown', methods=['POST'])
    def shutdown():
        state.is_running = False
        dev_manager.stop_stream()
        add_log("🛑 システムを終了します。一時データを整理中...")

        def exit_after_cleanup():
            time.sleep(0.5)
            cleanup_on_exit()
            os._exit(0)

        threading.Thread(target=exit_after_cleanup, daemon=True).start()
        return "Shutdown"

    # ------------------------------------------------------------------
    # ギャラリー
    # 仕様: docs/spec/gallery.md
    # ------------------------------------------------------------------
    @app.route('/images')
    def get_images():
        return jsonify(storage.gallery_data())

    @app.route('/static/captures/<path:filename>')
    def serve_image(filename):
        return send_from_directory(SAVE_DIR, filename)

    # 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md
    @app.route('/rename', methods=['POST'])
    def rename():
        data = request.json or {}
        filename = data.get('filename', '')
        if not filename or os.path.basename(filename) != filename:
            return "Invalid filename", 400
        if not storage.exists(filename):
            return "File not found", 404

        saved_name = display_names.set_display_name(filename, data.get('displayName', ''))
        add_log(f"✏️ 表示名を変更しました: {filename} → {saved_name or filename}")
        return jsonify({"filename": filename, "displayName": saved_name})

    @app.route('/clear_all', methods=['POST'])
    def clear_all():
        try:
            storage.clear_all()
        except Exception as e:
            return str(e), 500
        add_log("🗑️ 全ての画像を削除しました")
        return "Cleared"

    @app.route('/delete_selected', methods=['POST'])
    def delete_selected():
        filenames = (request.json or {}).get('filenames', [])
        # 仕様: docs/spec/bugs/LOCAL-009_一括削除・ZIPダウンロードがキャプチャ保存先の外のファイルを扱える.md
        # 1件でも不正な名前を含む場合は、何も削除せずリクエスト全体を拒否する
        if not storage.all_plain_filenames(filenames):
            return "Invalid filename", 400
        storage.delete_images(filenames)
        add_log(f"🗑️ 選択された {len(filenames)} 件の画像を削除しました")
        return "Deleted"

    # 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md
    @app.route('/download_selected', methods=['POST'])
    def download_selected():
        data = request.json or {}
        filenames = data.get('filenames', [])
        if not filenames: return "No files selected", 400
        # 仕様: docs/spec/bugs/LOCAL-009_一括削除・ZIPダウンロードがキャプチャ保存先の外のファイルを扱える.md
        if not storage.all_plain_filenames(filenames):
            return "Invalid filename", 400

        memory_file, zip_name = storage.build_zip(filenames, data.get('zipName', ''))
        return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name=zip_name)

    # ------------------------------------------------------------------
    # ログ
    # ------------------------------------------------------------------
    @app.route('/logs/stream')
    def stream_logs():
        last_sent_id = int(request.headers.get('Last-Event-ID', '0') or 0)
        def event_stream(initial_id):
            last_sent_id = initial_id
            with log_condition:
                current_items = [item for item in log_queue if item[0] > last_sent_id]
            for log_id, msg in current_items:
                yield _sse_event(log_id, msg)
                last_sent_id = log_id
            while True:
                with log_condition:
                    log_condition.wait()
                    new_items = [item for item in log_queue if item[0] > last_sent_id]
                for log_id, msg in new_items:
                    yield _sse_event(log_id, msg)
                    last_sent_id = log_id
        return Response(event_stream(last_sent_id), mimetype='text/event-stream; charset=utf-8')

    @app.route('/logs')
    def get_logs():
        response = jsonify([msg for _, msg in list(log_queue)])
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response
