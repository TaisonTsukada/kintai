"""CLI 表示ヘルパー（Layer 3 補助）"""

import calendar
from datetime import datetime
from typing import Dict

import click

from .manager import KintaiManager

fmt = KintaiManager._format_duration_message


def display_console_summary(summary_data: Dict, display_label: str) -> None:
    """コンソール用サマリー表示"""
    click.echo(f"{display_label}の勤怠記録")
    click.echo("=" * 70)

    if not summary_data['records']:
        click.echo("記録がありません。")
        return

    click.echo(f"{'日付':<12} {'出勤時刻':<10} {'退勤時刻':<10} {'総勤務':<10} {'休憩':<8} {'実勤務':<10}")
    click.echo("-" * 70)

    for record in summary_data['records']:
        click.echo(
            f"{record['date']:<12} "
            f"{record['check_in'].strftime('%H:%M:%S'):<10} "
            f"{record['check_out'].strftime('%H:%M:%S'):<10} "
            f"{fmt(record['duration_seconds']):<10} "
            f"{fmt(record['break_seconds']):<8} "
            f"{fmt(record['actual_work_seconds']):<10}"
        )

    click.echo("=" * 70)
    click.echo(f"総勤務時間: {fmt(summary_data['total_seconds'])}")
    if summary_data['total_break_seconds'] > 0:
        click.echo(f"総休憩時間: {fmt(summary_data['total_break_seconds'])}")
        click.echo(f"実勤務時間: {fmt(summary_data['total_actual_work_seconds'])}")
    click.echo(f"勤務日数: {summary_data['work_days']}日")
    click.echo(f"平均勤務時間: {fmt(summary_data['avg_seconds'])}")
    if summary_data['total_break_seconds'] > 0:
        click.echo(f"平均実勤務時間: {fmt(summary_data['avg_actual_work_seconds'])}")

    overtime = summary_data.get('overtime_seconds', 0)
    if overtime > 0:
        click.echo(f"残業時間: {fmt(overtime)}")
    elif overtime < 0:
        click.echo(f"不足時間: {fmt(-overtime)}")


def generate_markdown_summary(summary_data: Dict, display_month: str) -> str:
    """Markdown 形式のサマリー文字列を生成"""
    WEEKDAY_JP = {
        'Monday': '月', 'Tuesday': '火', 'Wednesday': '水',
        'Thursday': '木', 'Friday': '金', 'Saturday': '土', 'Sunday': '日',
    }

    lines = [f"# {display_month} 勤怠記録", "", "## 勤務詳細", ""]

    if not summary_data['records']:
        lines.append("記録がありません。")
        return "\n".join(lines)

    lines.append("| 日付 | 曜日 | 出勤時刻 | 退勤時刻 | 総勤務時間 | 休憩時間 | 実勤務時間 |")
    lines.append("|------|------|----------|----------|------------|----------|------------|")

    for record in summary_data['records']:
        date_obj = datetime.fromisoformat(record['date']).date()
        weekday_jp = WEEKDAY_JP[calendar.day_name[date_obj.weekday()]]
        lines.append(
            f"| {record['date']} | {weekday_jp} "
            f"| {record['check_in'].strftime('%H:%M:%S')} "
            f"| {record['check_out'].strftime('%H:%M:%S')} "
            f"| {fmt(record['duration_seconds'])} "
            f"| {fmt(record['break_seconds'])} "
            f"| {fmt(record['actual_work_seconds'])} |"
        )

    lines += ["", "## 月次サマリー", ""]
    lines.append(f"- **総勤務時間**: {fmt(summary_data['total_seconds'])}")
    if summary_data['total_break_seconds'] > 0:
        lines.append(f"- **総休憩時間**: {fmt(summary_data['total_break_seconds'])}")
        lines.append(f"- **実勤務時間**: {fmt(summary_data['total_actual_work_seconds'])}")
    lines.append(f"- **勤務日数**: {summary_data['work_days']}日")
    lines.append(f"- **平均勤務時間**: {fmt(summary_data['avg_seconds'])}")
    if summary_data['total_break_seconds'] > 0:
        lines.append(f"- **平均実勤務時間**: {fmt(summary_data['avg_actual_work_seconds'])}")

    overtime = summary_data.get('overtime_seconds', 0)
    if overtime > 0:
        lines.append(f"- **残業時間**: {fmt(overtime)}")
    elif overtime < 0:
        lines.append(f"- **不足時間**: {fmt(-overtime)}")

    return "\n".join(lines)
