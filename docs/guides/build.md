# パッケージ化（ビルド）手順

PyInstaller を使用して、配布用の単体アプリケーションを生成します。

## 🍏 Mac OS (.app 形式のビルド)

ターミナルでプロジェクトのルートディレクトリに移動し、以下のコマンドを実行します。
```bash
# 古いビルドキャッシュの削除
rm -rf build dist OmniShot.spec selfIdentity.plist

# ビルドの実行
python3 -m PyInstaller --onedir --windowed \
  --add-data "templates:templates" \
  --add-data "static:static" \
  --add-data "bin/mac:bin/mac" \
  --name "OmniShot" \
  --icon=myicon.icns \
  --clean \
  run.py
```
ビルド完了後、`dist/OmniShot.app` が生成されます。`pywebview`（ネイティブウィンドウ化）に関する追加の`--hidden-import`指定は、実測の結果不要でした。

### ⚠️ macOSで `.app` を実行する際の注意点

初回起動時にセキュリティの関係でエラーが出る場合があります。その場合は以下の操作を行なってください。

`設定 > プライパシーとセキュリティ > このまま開く`

## 💻 Windows (.exe 形式のビルド)

Windows環境のコマンドプロンプトまたは PowerShell で以下を実行します（※パスの区切り文字が `;` になります）。
```bash
:: 古いビルドキャッシュの削除
rmdir /s /q build dist OmniShot.spec selfIdentity.plist

:: ビルドの実行
python -m PyInstaller --onefile --windowed `
  --add-data "templates;templates" `
  --add-data "static;static" `
  --add-data "bin/win;bin/win" `
  --name "OmniShot" `
  --icon="static/favicon.ico" `
  --clean `
  run.py
```
ビルド完了後、`dist/OmniShot.exe` が生成されます。

### ⚠️ pywebview（ネイティブウィンドウ化）に関する注意点（Windows）

- `pywebview`のWindows版バックエンドはEdge WebView2を使用するため、実行端末にWebView2 Runtimeが必要です（Windows 10 21H2以降・Windows 11には標準搭載）。古いWindows環境向けに配布する場合は、[Microsoft公式のWebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)の配布を検討してください。
- Mac側の実ビルドでは追加の`--hidden-import`指定は不要でしたが、Windows側は未検証です。ビルド後に`OmniShot.exe`を起動し、ネイティブウィンドウが正しく開くか確認してください。

### ⚠️ Windowsで `.exe` を実行する際の注意点

- `OmniShot.exe` ファイルをダブルクリックすることで起動ができます。
  - 初回のみ、「WindowsによってPCが保護されました」と表示されることがあります。その場合は以下の操作を行なってください。

`詳細情報 > 実行`

- Androidデバイスを接続した状態で「自動撮影開始」ボタンをクリックすると、Windowsセキュリティによる許可を求められます。
- 同様に、iOSデバイスを接続した状態で「自動撮影開始」ボタンをクリックすると、Windowsセキュリティによる許可を求められます。
  - 「パブリック ネットワークとプライベート ネットワークにこのアプリへのアクセスを許可しますか？」と表示されたら、以下の操作を行なってください。

` 表示数を増やす > 「パブリック ネットワーク」と「プライベート ネットワーク」両方にチェックをつける > 許可`

## 関連ガイド
- 開発環境での実行方法: [development.md](development.md)
