# 仕様: docs/spec/capture-metadata.md
"""画像ごとの撮影情報（撮影日時・端末名・OS・解像度・撮影の種類）をファイル名キーで永続化する。

保存先を captures/ 配下に置くことで、画像の削除・全消去・アプリ終了時の captures/ 削除と
撮影情報のライフサイクルが自然に一致する（表示名 display_names.py と同じ方針）。
画像ファイルの中身には書き込まない。
"""
import json
import os
import threading

from .paths import SAVE_DIR

CAPTURE_INFO_FILE = os.path.join(SAVE_DIR, 'capture_info.json')
_lock = threading.Lock()


def _load_locked():
    if not os.path.exists(CAPTURE_INFO_FILE):
        return {}
    try:
        with open(CAPTURE_INFO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_locked(mapping):
    with open(CAPTURE_INFO_FILE, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


def load_all():
    with _lock:
        return _load_locked()


def record(filename, info):
    """画像1枚分の撮影情報を保存する。"""
    with _lock:
        mapping = _load_locked()
        mapping[filename] = info
        _save_locked(mapping)


def remove(filenames):
    """削除された画像に対応する撮影情報を取り除く。"""
    with _lock:
        mapping = _load_locked()
        removed = [name for name in filenames if mapping.pop(name, None) is not None]
        if removed:
            _save_locked(mapping)
