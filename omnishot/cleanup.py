# 仕様: docs/spec/native-window.md
"""アプリ終了時の後始末。"""
import os
import platform
import shutil
import tempfile

from .device_manager import dev_manager
from .paths import SAVE_DIR


def _cleanup_temp_data():
    """撮影データの保存先とiOS/Windowsの一時ファイルを削除する。"""
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


def cleanup_on_exit():
    """終了時の後始末をすべて行う。失敗しても例外は投げない。"""
    try:
        # 終了後も go-ios の常駐トンネル・adb サーバーが動き続けないよう止める
        dev_manager.stop_ios_tunnel()
        dev_manager.stop_adb_server()
        _cleanup_temp_data()
        print("🧹 終了処理が完了しました。")
    except Exception as e:
        print(f"⚠️ クリーンアップ中にエラーが発生しました: {e}")
