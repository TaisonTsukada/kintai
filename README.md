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

## ライセンス

MIT
