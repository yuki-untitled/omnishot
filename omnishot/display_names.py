# 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md
"""キャプチャファイルの表示名をファイル名キーで永続化する。

保存先を captures/ 配下に置くことで、キャプチャ削除・全消去（clear_all）・
アプリ終了時の captures/ 削除と表示名データのライフサイクルが自然に一致する。
"""
import json
import os
import threading

from .paths import SAVE_DIR

DISPLAY_NAMES_FILE = os.path.join(SAVE_DIR, 'display_names.json')
_lock = threading.Lock()


def _load_locked():
    if not os.path.exists(DISPLAY_NAMES_FILE):
        return {}
    try:
        with open(DISPLAY_NAMES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_locked(mapping):
    with open(DISPLAY_NAMES_FILE, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


def load_all():
    with _lock:
        return _load_locked()


def set_display_name(filename, display_name):
    """表示名を保存する。display_name が空なら紐付けを解除する。保存後の表示名を返す。"""
    display_name = (display_name or '').strip()
    with _lock:
        mapping = _load_locked()
        if display_name:
            mapping[filename] = display_name
        else:
            mapping.pop(filename, None)
        _save_locked(mapping)
        return mapping.get(filename)


def remove_display_names(filenames):
    """削除されたキャプチャファイルに対応する表示名を取り除く。"""
    with _lock:
        mapping = _load_locked()
        changed = False
        for filename in filenames:
            if filename in mapping:
                del mapping[filename]
                changed = True
        if changed:
            _save_locked(mapping)
