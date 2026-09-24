# 📱 OmniShot

OmniShot は、iOS および Android 端末の画面変化を検知し、自動でスクリーンショットをキャプチャ・保存するマルチプラットフォーム対応のデスクトップアプリケーションです。スマートフォンの操作マニュアル作成や、アプリのエビデンス自動採取に最適です。

## ✨ 主な機能

* **クロスプラットフォーム対応:** Mac OS（Apple Silicon/Intel）および Windows 環境に両対応。
* **マルチOSキャプチャ:** 1つのアプリで iPhone (iOS) と Android 両方の画面キャプチャが可能。
* **2つの自動撮影モード:** 静的モード／動的モードで、画面の変化や静止を検知して自動撮影。
* **手動撮影:** 自動検知に加えて、任意のタイミングでシャッターを切ることも可能。
* **Web UI ギャラリー:** キャプチャした画像をブラウザ上でリアルタイムに確認・管理。
* **表示名の編集:** ギャラリー上で任意の表示名に変更可能。サーバー側に永続化される。

詳細な機能仕様は以下を参照してください。

* [docs/spec/screenshot-capture.md](docs/spec/screenshot-capture.md) — 自動スクリーンショットキャプチャ
* [docs/spec/device-selection.md](docs/spec/device-selection.md) — 撮影端末の選択
* [docs/spec/manual-capture.md](docs/spec/manual-capture.md) — 手動撮影
* [docs/spec/gallery.md](docs/spec/gallery.md) — Web UI ギャラリー・表示名編集
* [docs/spec/native-window.md](docs/spec/native-window.md) — ネイティブウィンドウ化

## 📚 ドキュメント

* [docs/guides/development.md](docs/guides/development.md) — プロジェクト構造・開発環境での実行方法
* [docs/guides/build.md](docs/guides/build.md) — Mac / Windows 向けパッケージ化（ビルド）手順

## ⚖️ 免責事項 / ライセンス
本アプリケーションに含まれる `adb` および `go-ios` バイナリの著作権は、それぞれのオープンソースプロジェクトのライセンスに準拠します。