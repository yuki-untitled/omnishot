# 仕様: docs/spec/native-window.md
"""アプリ終了時の後始末。"""
import os
import shutil

from .device_manager import dev_manager
from .paths import SAVE_DIR


def _cleanup_temp_data():
    """撮影データの保存先を削除する。

    仕様: docs/spec/bugs/LOCAL-042_起動時と終了時の後始末がアプリが作っていないファイルやプロセスに影響する.md
    消すのは、アプリ自身が作ったものだけ。OS の設定ファイルや、一時フォルダの、他のアプリのものは消さない
    （iOS の画面取得に使う一時ファイルは、使い終わったときに、その場で削除している）。
    go-ios の識別情報（アプリ用フォルダ）も消さない。
    """
    if os.path.exists(SAVE_DIR):
        shutil.rmtree(SAVE_DIR)


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
