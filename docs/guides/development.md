# 開発環境ガイド

## プロジェクト構造

```tree
.
├── run.py                # エントリーポイント（開発サーバー起動）
├── requirements.txt      # 依存ライブラリ一覧
├── requirements-dev.txt  # 開発用の依存ライブラリ（テスト）
├── omnishot/             # Flask バックエンド & 制御ロジック（パッケージ）
│   ├── routes.py         # 画面からの要求の受け付け（処理の本体は各モジュール）
│   ├── capture.py        # 変化の判定・自動撮影のループ・手動撮影・画像の保存
│   ├── device_manager.py # 端末（adb・go-ios）とのやり取り
│   ├── stream_receivers.py # 自動撮影中の画面の受信
│   ├── storage.py        # 保存した画像の一覧・削除・ZIP の作成
│   ├── display_names.py  # 表示名の保存
│   ├── cleanup.py        # 終了時の後始末
│   ├── state.py / logs.py / paths.py # 共有状態・ログ・パス
├── tests/                # pytest のテスト
├── myicon.icns           # Mac用アプリケーションアイコン
├── README.md             # プロジェクト概要
├── docs/                 # 仕様・ガイド
├── bin/                  # コア・バイナリ（Git管理対象）
│   ├── mac/              # Mac用 (adb, go-ios)
│   └── win/              # Windows用 (adb.exe, go-ios.exe, DLL類)
├── static/               # フロントエンド静的アセット
│   ├── css/style.css     # スタイルシート
│   ├── js/               # フロントエンド（ES モジュール。ビルド不要）
│   │   ├── main.js       # 画面の初期化
│   │   ├── capture.js    # 撮影の設定・操作・状態の監視
│   │   ├── devices.js    # 撮影端末の選択
│   │   ├── gallery.js    # ギャラリー・選択・表示名の変更
│   │   ├── preview.js    # 画像のプレビュー
│   │   ├── logs.js       # Live Logs
│   │   ├── guide.js      # 設定ガイド
│   │   └── state.js / util.js # 共有状態・共通処理
│   └── favicon.ico       # ブラウザタブ用アイコン
└── templates/
    ├── index.html        # Web UI メイン画面
    └── help.html         # 使い方
```

## 開発環境での実行方法

1. 仮想環境の作成・依存ライブラリのインストール
```bash
python3 -m venv .venv
source .venv/bin/activate  # Windowsは .venv\Scripts\activate
python3 -m pip install -r requirements.txt
```
Homebrew版Pythonなど`pip`コマンドが無い環境では、`pip install ...`ではなく`python3 -m pip install ...`を使用してください。

2. アプリケーションの起動
```bash
python3 run.py
```
起動後、`pywebview`によるネイティブウィンドウが開き、`http://127.0.0.1:5001` のWeb UIが表示されます。

## テストの実行

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```
テストは端末を接続せずに実行できます（adb・go-ios の出力は模擬したものを使います）。画面（JS）のテストは無いため、画面の変更はアプリ上で確認してください。

## 推奨される .gitignore

ビルド時に生成される一時フォルダや環境依存ファイルは Git に含めないよう、`.gitignore` ファイルを作成して以下を記述することを推奨します。
```text
build/
dist/
*.spec
.DS_Store
__pycache__/
*.pyc
captures/
```

## 関連仕様
- 自動撮影機能: [../spec/screenshot-capture.md](../spec/screenshot-capture.md)
- Web UI ギャラリー: [../spec/gallery.md](../spec/gallery.md)
- 配布用パッケージのビルド手順: [build.md](build.md)
