"""CLI コマンド定義（Layer 3）"""

from pathlib import Path

import click

from .formatters import display_console_summary, generate_markdown_summary
from .manager import KintaiManager
from .models import ClockResult

WEEKDAY_JP = ['月', '火', '水', '木', '金', '土', '日']


@click.group()
def cli():
    """勤怠管理CLIツール"""
    pass


@cli.command()
def in_command():
    """出勤記録"""
    manager = KintaiManager()
    result = manager.clock_in()

    if result.success:
        click.echo(f"出勤時刻を記録しました: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    elif result.needs_confirmation:
        click.echo(result.message)
        if click.confirm("出勤を記録しますか？"):
            forced = manager.clock_in(force=True)
            if forced.success:
                click.echo(f"出勤時刻を記録しました: {forced.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        click.echo(result.message)
        if click.confirm("上書きしますか？"):
            forced = manager.clock_in(force=True)
            if forced.success:
                click.echo(f"出勤時刻を記録しました: {forced.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")


@cli.command()
def out():
    """退勤記録"""
    manager = KintaiManager()
    result = manager.clock_out()

    if result.success:
        for line in result.message.split('\n'):
            click.echo(line)
    else:
        click.echo(result.message, err=True)


@cli.command()
def status():
    """現在の勤務状態を確認"""
    manager = KintaiManager()
    info = manager.get_today_status()
    fmt = KintaiManager._format_duration_message

    click.echo(f"状態: {info['state']}")

    if info['check_in']:
        click.echo(f"出勤時刻: {info['check_in'].strftime('%Y-%m-%d %H:%M:%S')}")

    state = info['state']
    if state == '退勤済み':
        click.echo(f"退勤時刻: {info['check_out'].strftime('%Y-%m-%d %H:%M:%S')}")
        click.echo(f"総勤務時間: {fmt(info['elapsed_seconds'])}")
        if info['break_seconds'] > 0:
            click.echo(f"休憩時間: {fmt(info['break_seconds'])}")
            click.echo(f"実勤務時間: {fmt(info['work_seconds'])}")
    elif state == '休憩中':
        current_break = next(
            (b for b in info['breaks'] if 'start' in b and 'end' not in b), None
        )
        if current_break:
            click.echo(f"休憩開始: {current_break['start'].strftime('%Y-%m-%d %H:%M:%S')}")
        click.echo(f"総経過時間: {fmt(info['elapsed_seconds'])}")
        click.echo(f"休憩経過時間: {fmt(info['current_break_seconds'])}")
    elif state == '出勤中':
        click.echo(f"経過時間: {fmt(info['elapsed_seconds'])}")


@cli.command()
def today():
    """今日の勤怠記録をまとめて表示"""
    manager = KintaiManager()
    now = manager._get_current_jst_time()
    info = manager.get_today_status(reference_time=now)
    fmt = KintaiManager._format_duration_message

    weekday = WEEKDAY_JP[now.weekday()]
    click.echo(f"=== {now.strftime('%Y-%m-%d')}（{weekday}）===")
    click.echo(f"状態: {info['state']}")

    if info['check_in']:
        click.echo(f"出勤時刻: {info['check_in'].strftime('%H:%M:%S')}")

    if info['check_out']:
        click.echo(f"退勤時刻: {info['check_out'].strftime('%H:%M:%S')}")

    if info['elapsed_seconds'] is not None:
        label = "総勤務時間" if info['state'] == '退勤済み' else "経過時間"
        click.echo(f"{label}: {fmt(info['elapsed_seconds'])}")

    if info['break_seconds'] > 0:
        click.echo(f"休憩時間: {fmt(info['break_seconds'])}")

    if info['work_seconds'] is not None:
        click.echo(f"実労働時間: {fmt(info['work_seconds'])}")

    if info['current_break_seconds'] is not None:
        click.echo(f"現在の休憩時間: {fmt(info['current_break_seconds'])}")


@cli.command()
@click.option('--date', required=True, help='編集する日付 (YYYY-MM-DD)')
@click.option('--in', 'check_in', help='新しい出勤時刻 (HH:MM)')
@click.option('--out', 'check_out', help='新しい退勤時刻 (HH:MM)')
def edit(date, check_in, check_out):
    """勤怠記録の編集"""
    manager = KintaiManager()

    if not check_in and not check_out:
        result = _interactive_edit(manager, date)
    else:
        result = manager.edit_record(date, check_in, check_out)

    if result.success:
        click.echo(result.message)
    else:
        click.echo(result.message, err=True)
        click.get_current_context().exit(1)


def _interactive_edit(manager: KintaiManager, date_str: str) -> ClockResult:
    """対話形式での記録編集"""
    try:
        manager._validate_date_str(date_str)
    except ValueError as e:
        return ClockResult(success=False, message=str(e))

    if date_str not in manager.records:
        return ClockResult(success=False, message="指定された日付の記録が見つかりません。")

    record = manager.records[date_str]
    click.echo("現在の記録:")
    if 'check_in' in record:
        click.echo(f"  出勤: {record['check_in'].strftime('%H:%M:%S')}")
    else:
        click.echo("  出勤: 記録なし")
    if 'check_out' in record:
        click.echo(f"  退勤: {record['check_out'].strftime('%H:%M:%S')}")
    else:
        click.echo("  退勤: 記録なし")

    new_in = click.prompt("新しい出勤時刻 (HH:MM) [変更しない場合はEnter]", default="", show_default=False)
    new_out = click.prompt("新しい退勤時刻 (HH:MM) [変更しない場合はEnter]", default="", show_default=False)
    new_in = new_in.strip() or None
    new_out = new_out.strip() or None

    if not new_in and not new_out:
        return ClockResult(success=True, message="変更はありませんでした。")

    return manager.edit_record(date_str, new_in, new_out)


@cli.command()
@click.option('--date', required=True, help='削除する日付 (YYYY-MM-DD)')
def delete(date):
    """勤怠記録の削除"""
    manager = KintaiManager()
    if click.confirm(f"{date}の記録を削除しますか？"):
        result = manager.delete_record(date)
        if result.success:
            click.echo(result.message)
        else:
            click.echo(result.message, err=True)
            click.get_current_context().exit(1)
    else:
        click.echo("削除をキャンセルしました。")


@cli.command()
@click.option('--date', required=True, help='記録する日付 (YYYY-MM-DD)')
@click.option('--in', 'check_in', required=True, help='出勤時刻 (HH:MM)')
@click.option('--out', 'check_out', required=True, help='退勤時刻 (HH:MM)')
def new(date, check_in, check_out):
    """過去の勤怠記録を新規作成"""
    manager = KintaiManager()
    result = manager.create_new_record(date, check_in, check_out)
    if result.success:
        for line in result.message.split('\n'):
            click.echo(line)
    else:
        click.echo(result.message, err=True)
        click.get_current_context().exit(1)


@cli.group()
def break_group():
    """休憩時間管理"""
    pass


@break_group.command()
def start():
    """休憩開始"""
    manager = KintaiManager()
    result = manager.break_start()
    if result.success:
        click.echo(result.message)
    else:
        click.echo(result.message, err=True)
        click.get_current_context().exit(1)


@break_group.command()
def end():
    """休憩終了"""
    manager = KintaiManager()
    result = manager.break_end()
    if result.success:
        for line in result.message.split('\n'):
            click.echo(line)
    else:
        click.echo(result.message, err=True)
        click.get_current_context().exit(1)


cli.add_command(break_group, name='break')


@cli.command()
def week():
    """今週の勤怠サマリーを表示"""
    manager = KintaiManager()
    summary_data = manager.get_weekly_summary()
    display_console_summary(summary_data, summary_data['week_label'])


@cli.command()
@click.option('--month', required=True, help='対象の月 (YYYY-MM)')
@click.option('--output', '-o', default=None, help='出力ファイルパス（省略時は標準出力）')
def export(month, output):
    """勤怠データを CSV にエクスポート"""
    manager = KintaiManager()
    try:
        content = manager.export_monthly_csv(month)
    except ValueError as e:
        click.echo(str(e), err=True)
        click.get_current_context().exit(1)
        return

    if output:
        Path(output).write_text(content, encoding='utf-8-sig')
        click.echo(f"{output} に保存しました。")
    else:
        click.echo(content, nl=False)


@cli.command()
@click.option('--month', default=None, help='対象の月 (YYYY-MM)。省略時は現在月')
@click.option('--copy', is_flag=True, help='結果を Markdown 形式でクリップボードにコピー')
@click.option('--work-hours', type=float, default=8.0, show_default=True, help='所定労働時間（時間）')
def summary(month, copy, work_hours):
    """月次勤怠レポートを表示"""
    manager = KintaiManager()

    if not month:
        month = manager._get_current_jst_time().strftime('%Y-%m')

    summary_data = manager.get_monthly_summary(month, scheduled_hours=work_hours)

    if 'error' in summary_data:
        click.echo(summary_data['error'], err=True)
        click.get_current_context().exit(1)
        return

    year, month_num = summary_data['year_month'].split('-')
    display_month = f"{year}年{int(month_num)}月"

    if copy:
        markdown_content = generate_markdown_summary(summary_data, display_month)
        try:
            import pyperclip
            pyperclip.copy(markdown_content)
            click.echo("クリップボードにコピーしました。")
        except ImportError:
            click.echo(
                "エラー: pyperclipモジュールが見つかりません。", err=True
            )
            click.get_current_context().exit(1)
    else:
        display_console_summary(summary_data, display_month)


def main():
    cli()
