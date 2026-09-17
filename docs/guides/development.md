# 開発環境ガイド

## プロジェクト構造

```tree
.
├── run.py                # エントリーポイント（開発サーバー起動）
├── requirements.txt      # 依存ライブラリ一覧
├── omnishot/              # Flask バックエンド & 制御ロジック（パッケージ）
├── myicon.icns           # Mac用アプリケーションアイコン
├── README.md             # プロジェクト概要
├── docs/                 # 仕様・ガイド
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
