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

    def mtime(name):
        try:
            return os.path.getmtime(os.path.join(SAVE_DIR, name))
        except FileNotFoundError:
            return 0
    images.sort(key=mtime, reverse=True)
    return images


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
def build_zip(filenames, zip_name):
    """指定した画像をまとめた ZIP を作り、(ZIPのデータ, ダウンロードするファイル名) を返す。ファイル名は検証済みであること。"""
    names = display_names.load_all()
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for name in filenames:
            path = os.path.join(SAVE_DIR, name)
            if os.path.exists(path):
                zf.write(path, arcname=_arcname_for(name, names.get(name)))
    memory_file.seek(0)

    zip_name = _sanitize_zip_name(zip_name)
    if not zip_name:
        zip_name = f'captures_{time.strftime("%Y%m%d_%H%M%S")}.zip'
    return memory_file, zip_name
