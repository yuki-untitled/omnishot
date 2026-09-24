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

- iOS 端末とのトンネル用の識別情報（`selfIdentity.plist`）は `~/Library/Application Support/OmniShot` に保存されます（開発時の実行も同じ）。ビルド前の削除は不要ですが、以前の開発時の実行でリポジトリ直下に作られたものが残っていても、ビルドには含まれません。

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

- Androidデバイスを接続した状態で「自動撮影」ボタンをクリックすると、Windowsセキュリティによる許可を求められます。
- 同様に、iOSデバイスを接続した状態で「自動撮影」ボタンをクリックすると、Windowsセキュリティによる許可を求められます。
  - 「パブリック ネットワークとプライベート ネットワークにこのアプリへのアクセスを許可しますか？」と表示されたら、以下の操作を行なってください。

` 表示数を増やす > 「パブリック ネットワーク」と「プライベート ネットワーク」両方にチェックをつける > 許可`

## リリース手順

GitHub Actions（[.github/workflows/release.yml](../../.github/workflows/release.yml)）で Mac 版・Windows 版をビルドし、GitHub Releases の下書きに添付します。

1. リリースノートを `docs/releases/<バージョン>.md`（例: `docs/releases/v1.0.0.md`）に書き、develop にコミットして push する
2. タグを付けて push する
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
3. GitHub の Actions タブで、ワークフロー「Release」が成功したことを確認する
4. GitHub の Releases に下書きができているので、添付されたファイルをダウンロードして動作を確かめてから「Publish release」を押す

- ライブラリの版は [constraints.txt](../../constraints.txt) で固定しています。ライブラリを更新したら、手元で動作を確かめてから constraints.txt も更新してください。
- Mac 版は Apple Silicon のランナーでビルドするため、Apple Silicon の Mac でのみ動作します。Apple の署名・公証は受けていません。
- ビルドに失敗した場合は、タグを消して（`git push origin :refs/tags/v1.0.0` と `git tag -d v1.0.0`）修正後に付け直します。下書きが作られていれば、Releases の画面から削除します。

## 関連ガイド
- 開発環境での実行方法: [development.md](development.md)
