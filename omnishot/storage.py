# 仕様: docs/spec/gallery.md
"""保存した画像（captures/）の一覧・削除・ZIP の作成。"""
import io
import os
import re
import time
import zipfile

from . import display_names, state
from .paths import SAVE_DIR

_UNSAFE_CHARS = re.compile(r'[\\/\x00-\x1f]')
# 仕様: docs/spec/session-grouping.md（ZIPのファイル名に使えない文字）
_ZIP_NAME_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _sanitize_filename_component(name):
    """パス区切り文字・制御文字を取り除く（ZIPエントリ名・ダウンロードファイル名の共通処理）。"""
    return _UNSAFE_CHARS.sub('', name or '').strip()


# 仕様: docs/spec/bugs/LOCAL-009_一括削除・ZIPダウンロードがキャプチャ保存先の外のファイルを扱える.md
def is_plain_filename(name):
    """保存先フォルダ直下の単純なファイル名（ディレクトリ区切り・制御文字を含まない）かどうか。"""
    return isinstance(name, str) and name not in ('', '.', '..') and not _UNSAFE_CHARS.search(name)


def all_plain_filenames(filenames):
    return isinstance(filenames, list) and all(is_plain_filename(n) for n in filenames)


def exists(filename):
    return os.path.exists(os.path.join(SAVE_DIR, filename))


def list_images():
    """保存した画像のファイル名を、新しい順に返す。"""
    images = [f for f in os.listdir(SAVE_DIR) if f.endswith('.png')]
    # 撮影した時刻が同じ画像は、ファイル名の順に並べる（並びが更新のたびに入れ替わらないようにする）
    images.sort(key=lambda name: (_mtime(name), name), reverse=True)
    return images


def _mtime(name):
    try:
        return os.path.getmtime(os.path.join(SAVE_DIR, name))
    except FileNotFoundError:
        return 0


def gallery_data():
    """ギャラリーの表示に使う、画像・表示名・セッションの情報を返す。"""
    images = list_images()
    # 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md
    # 存在するキャプチャファイルの分だけ表示名を返す（削除済みファイルの表示名は含めない）
    names = display_names.load_all()
    # 仕様: docs/spec/session-grouping.md
    # 存在するキャプチャファイルの分だけセッションIDを返す（未登録＝未分類のファイルは含めない）
    return {
        "images": images,
        "displayNames": {name: names[name] for name in images if name in names},
        "imageSessions": {name: state.image_sessions[name] for name in images if name in state.image_sessions},
        "sessions": state.sessions,
    }


# 仕様: docs/spec/session-grouping.md（セッション名の変更）
SESSION_NAME_MAX_LENGTH = 50
_CONTROL_CHARS = re.compile(r'[\x00-\x1f]')
UNCLASSIFIED_NAME = "未分類"


def is_session_id(session_id):
    return isinstance(session_id, int) and not isinstance(session_id, bool) and session_id in state.sessions


def set_session_name(session_id, name):
    """セッション名を設定し、保存した名前を返す。空にすると未設定に戻す。1〜50文字を超える名前は ValueError。"""
    cleaned = _CONTROL_CHARS.sub('', name).strip() if isinstance(name, str) else None
    if cleaned is None or len(cleaned) > SESSION_NAME_MAX_LENGTH:
        raise ValueError("Invalid session name")
    if cleaned:
        state.sessions[session_id]["name"] = cleaned
    else:
        state.sessions[session_id].pop("name", None)
    return cleaned


# 仕様: docs/spec/session-grouping.md（セッション単位のダウンロード）
def session_members(session_id):
    """セッションの画像を撮影の古い順に返す。session_id が None のときは「未分類」の画像。"""
    images = [n for n in list_images()
              if (n not in state.image_sessions if session_id is None else state.image_sessions.get(n) == session_id)]
    return sorted(images, key=lambda n: (_mtime(n), n))


def order_session_images(members, order):
    """並べ替えた順序（order）を members に適用する。order にない画像は、末尾に撮影の古い順で並べる。"""
    member_set = set(members)
    ordered = []
    for name in order or []:
        if name in member_set and name not in ordered:
            ordered.append(name)
    return ordered + [n for n in members if n not in ordered]


def session_zip_name(session_id):
    """セッション単位のZIPのファイル名（拡張子なし）。ファイル名に使えない文字は _ に置き換える。"""
    if session_id is None:
        name = UNCLASSIFIED_NAME
    else:
        name = state.sessions[session_id].get("name") or f"セッション{session_id}"
    return _ZIP_NAME_FORBIDDEN.sub('_', name)


def delete_images(filenames):
    """指定した画像と、その表示名・セッションの対応づけを削除する。ファイル名は検証済みであること。"""
    for name in filenames:
        path = os.path.join(SAVE_DIR, name)
        if os.path.exists(path): os.remove(path)
    # 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md（削除との整合性）
    display_names.remove_display_names(filenames)
    # 仕様: docs/spec/session-grouping.md（削除済みファイルのセッション対応づけは残さない）
    for name in filenames:
        state.image_sessions.pop(name, None)


def clear_all():
    """保存先のファイルをすべて削除する。"""
    for filename in os.listdir(SAVE_DIR):
        file_path = os.path.join(SAVE_DIR, filename)
        if os.path.isfile(file_path): os.unlink(file_path)
    # 仕様: docs/spec/session-grouping.md（削除済みファイルのセッション対応づけは残さない）
    state.image_sessions.clear()


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


# 仕様: docs/spec/bugs/LOCAL-001_表示名機能の未整合.md（ZIP内のファイル名は表示名を使う）
def build_zip(filenames, zip_name, numbered=False):
    """指定した画像をまとめた ZIP を作り、(ZIPのデータ, ダウンロードするファイル名) を返す。ファイル名は検証済みであること。

    numbered が True のときは、ZIP 内のファイル名の前に、並び順どおりの3桁の連番と _ を付ける。
    """
    names = display_names.load_all()
    memory_file = io.BytesIO()
    number = 0
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for name in filenames:
            path = os.path.join(SAVE_DIR, name)
            if os.path.exists(path):
                number += 1
                arcname = _arcname_for(name, names.get(name))
                zf.write(path, arcname=f"{number:03d}_{arcname}" if numbered else arcname)
    memory_file.seek(0)

    zip_name = _sanitize_zip_name(zip_name)
    if not zip_name:
        zip_name = f'captures_{time.strftime("%Y%m%d_%H%M%S")}.zip'
    return memory_file, zip_name
