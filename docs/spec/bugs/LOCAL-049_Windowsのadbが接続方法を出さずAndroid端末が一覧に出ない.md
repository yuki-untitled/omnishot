# バグ修正: Windows の adb が接続方法（usb:）を出さず、Android 端末が一覧に出ない

## Issue
#LOCAL-049

## 不具合現象と再現手順（Why）
### 発生している現象
Windows 版の OmniShot で、USB デバッグを許可した Android 端末を USB で接続しても、一覧に表示されない。[LOCAL-048](LOCAL-048_Windowsでadbサーバーの起動時に固まり端末が一覧に出ない.md) の修正（v1.4.2）後も変わらない。

### 再現手順
1. Windows で、同梱の adb（バージョン 37.0.1）の `adb devices -l` を実行する
2. 出力に `usb:` の項目が無い（例: `ZT322V4N35 device product:fogorow_gn model:moto_g24 device:fogorow transport_id:1`）
3. 期待値・実際の差異
   - 期待値: USB 接続の端末として一覧に表示される
   - 実際: `usb:` が無いため、USB 以外の接続（Wi-Fi など）と判定され、一覧から除外される

## 修正内容（What）
### 根本原因
- 端末の一覧は、`adb devices -l` の行に `usb:` を含むものだけを USB 接続とみなしていた（[device-selection.md](../device-selection.md)）。Mac の adb は `usb:` を出すが、Windows の adb は出さない

### 修正方針
- 行に `usb:` があるときは、従来どおり USB とみなす
- `usb:` が無いときは、識別子が Wi-Fi（`IPアドレス:ポート`、ワイヤレスデバッグの `…_adb-tls-connect._tcp`）・エミュレータ（`emulator-…`）の形でなければ USB とみなす
- Wi-Fi 経由でだけ見える端末は、従来どおり一覧に載せない

## 受入基準（再発防止・回帰テスト）
1. **再現手順の検証**: `usb:` を出さない adb でも、接続して許可済みの Android 端末が一覧に表示されること（Windows 実機で確認）。
2. **USB の判定**: `usb:` がある行は USB、`usb:` が無く識別子が通常のシリアルの行も USB とみなされること。
3. **Wi-Fi・エミュレータの除外**: `usb:` が無く、識別子が `IPアドレス:ポート`・`…_tcp`・`emulator-…` の端末は一覧に載らないこと。`usb:` がある行は、識別子の形によらず USB とみなされること。
4. **回帰**: `usb:` を出す adb（Mac）で、従来の一覧・撮影できない端末の理由の表示が変わらないこと。

## 関連するコンポーネント・機能
- [device-selection.md](../device-selection.md) — 一覧に載せるのは USB 接続の端末のみ
- [LOCAL-048](LOCAL-048_Windowsでadbサーバーの起動時に固まり端末が一覧に出ない.md) — 同じ症状で、先に疑った原因

## 変更・追記理由（更新時のみ）
- 2026-10-06: 初版作成。Windows 実機で `adb devices -l` の出力を確認し、`usb:` が無いことを発見（`device_manager.py` の `_android_usb_entries`）。
