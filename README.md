# kintai

日本時間（JST）で動作する個人用勤怠管理CLIツール。出退勤の記録・修正・月次サマリー生成をターミナルから行えます。

## インストール

```bash
pipx install kintai
```

> `pipx` がない場合: `pip install pipx` または `brew install pipx`

## 使い方

```bash
kintai in        # 出勤打刻
kintai out       # 退勤打刻
kintai status    # 現在の勤務状態を確認
kintai summary   # 今月の勤怠サマリーを表示
```

### 記録の修正

```bash
kintai edit --date 2025-01-10 --in 09:30 --out 19:00
```

### 特定月のサマリー

```bash
kintai summary --month 2025-01
```

### クリップボードにコピー（Markdown形式）

```bash
kintai summary --copy
```

### 記録の削除

```bash
kintai delete --date 2025-01-10
```

## ブラウザで編集（kintai web）

```bash
kintai web
```

ローカルにWebサーバーが起動し、ブラウザで月次の勤怠テーブルが開きます。各日の行を「編集」してその場で出退勤時刻や休憩を直せるので、`edit`コマンドを何度も打つより手早く直せます。ポートは自動で空きポートが選ばれますが、`--port`で固定したり、`--no-browser`でブラウザの自動起動を止めることもできます。終了するには `Ctrl+C` を押してください。

## 複数セッション（分割勤務・副業対応）

1日の中で勤務が分割される場合（例: 副業で午前・夕方・深夜に分かれて稼働するケース）、`kintai in`/`kintai out`を複数回実行すると、その日に複数のセッションとして記録されます。

```bash
kintai in    # 10:00 に実行
kintai out   # 12:00 に実行
kintai in    # 17:00 に実行
kintai out   # 22:00 に実行
```

過去の記録をまとめて作成・修正する場合は `--session` オプションでカンマ区切りのセッション範囲を渡せます（`--session`を複数回指定することもできます）。

```bash
kintai new --date 2025-01-10 --session "10:00~12:00,17:00~22:00,22:30~23:30"
kintai edit --date 2025-01-10 --session "10:00-12:00" --session "17:00-22:00"
```

`--session`指定時はその日の全セッションが置き換わります。既存の `~/.kintai/records.json`（旧形式）は初回読み込み時に自動で複数セッション形式へ移行され、移行前のファイルは `records.json.v1.bak` として残ります。

## 休憩

```bash
kintai break
```

サブコマンドなしで実行すると休憩を開始してそのままブロック（フォアグラウンドで待機）し、`Ctrl+C`で休憩を終了して抜けます。スクリプトなど非対話的に使いたい場合は、従来通り `kintai break start` / `kintai break end` も使えます。

## データ保存先

勤怠データは `~/.kintai/records.json` に保存されます。

`KINTAI_DATA_DIR` 環境変数でパスを変更できます。

## 日またぎ勤務

深夜勤務など日付をまたぐ場合も自動で検出します（最大3日前まで未退勤の出勤記録を検索）。

```bash
kintai in    # 例: 22:00 に実行
# 翌日
kintai out   # 例: 07:00 に実行 → 9時間の勤務として記録
```

## 要件

- Python 3.10 以上
- `kintai web` を使う場合は Flask（インストール時に自動で入ります）

## ライセンス

MIT
