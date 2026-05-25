# 📱 OmniShot

OmniShot は、iOS および Android 端末の画面変化を検知し、自動でスクリーンショットをキャプチャ・保存するマルチプラットフォーム対応のデスクトップアプリケーションです。スマートフォンの操作マニュアル作成や、アプリのエビデンス自動採取に最適です。

## ✨ 主な機能

* **クロスプラットフォーム対応:** Mac OS（Apple Silicon/Intel）および Windows 環境に両対応。
* **マルチOSキャプチャ:** 1つのアプリで iPhone (iOS) と Android 両方の画面キャプチャが可能。
* **2つの自動撮影モード:**
  * **静的モード:** 画面の変化を検知した後、指定した静止時間を待ってから撮影。
  * **動的モード:** 画面が動いている間は待機し、ピタッと止まった瞬間を狙って自動撮影。
* **Web UI ギャラリー:** キャプチャした画像をブラウザ上でリアルタイムに確認・管理（全選択、一括ダウンロード、一括削除）。

## 🗂️ プロジェクト構造

```tree
.
├── app.py                # Flask バックエンド & 制御ロジック
├── myicon.icns           # Mac用アプリケーションアイコン
├── README.md             # 本ドキュメント
├── bin/                  # コア・バイナリ（Git管理対象）
│   ├── mac/              # Mac用 (adb, go-ios)
│   └── win/              # Windows用 (adb.exe, go-ios.exe, DLL類)
├── static/               # フロントエンド静的アセット
│   ├── css/style.css     # スタイルシート
│   ├── js/main.js        # フロントエンド制御ロジック
│   └── favicon.ico       # ブラウザタブ用アイコン
└── templates/
    └── index.html        # Web UI メイン画面
```

## 🚀 開発環境での実行方法

1. 依存ライブラリのインストール
```bash
pip install flask opencv-python numpy pyinstaller
```

2. アプリケーションの起動
```bash
python3 app.py
```
起動後、自動的にブラウザが立ち上がり、`http://127.0.0.1:5001` にアクセスします。

## 🛠️ パッケージ化（ビルド）手順
PyInstaller を使用して、配布用の単体アプリケーションを生成します。

### 🍏 Mac OS (.app 形式のビルド)
ターミナルでプロジェクトのルートディレクトリに移動し、以下のコマンドを実行します。
```bash
# 古いビルドキャッシュの削除
rm -rf build dist

# ビルドの実行
python3 -m PyInstaller --onedir --windowed \
  --add-data "templates:templates" \
  --add-data "static:static" \
  --add-data "bin/mac:bin/mac" \
  --name "OmniShot" \
  --icon=myicon.icns \
  --clean \
  app.py
```
ビルド完了後、`dist/OmniShot.app` が生成されます。

### 💻 Windows (.exe 形式のビルド)
Windows環境のコマンドプロンプトまたは PowerShell で以下を実行します（※パスの区切り文字が `;` になります）。
```bash
:: 古いビルドキャッシュの削除
rmdir /s /q build dist

:: ビルドの実行
python -m PyInstaller --onefile --windowed `
  --add-data "templates;templates" `
  --add-data "static;static" `
  --add-data "bin/win;bin/win" `
  --name "OmniShot" `
  --icon="static/favicon.ico" `
  --clean `
  app.py
```
ビルド完了後、`dist/OmniShot.exe` が生成されます。

### 📝 推奨される .gitignore
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

## ⚖️ 免責事項 / ライセンス
本アプリケーションに含まれる `adb` および `go-ios` バイナリの著作権は、それぞれのオープンソースプロジェクトのライセンスに準拠します。