"""勤怠管理ビジネスロジック"""

import csv
import io
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

from .models import ClockResult

WEEKDAY_JP = ['月', '火', '水', '木', '金', '土', '日']


class KintaiManager:

    JST = pytz.timezone('Asia/Tokyo')
    SEARCH_DAYS_BACK = 3
    NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"

    def __init__(self, data_dir: Optional[str] = None):
        self.records: Dict[str, Dict[str, Any]] = {}

        if data_dir:
            base_dir = Path(data_dir)
        elif 'KINTAI_DATA_DIR' in os.environ:
            base_dir = Path(os.environ['KINTAI_DATA_DIR'])
        else:
            base_dir = Path.home() / '.kintai'

        self.data_file_path = base_dir / 'records.json'
        self.load_from_file()

    def _get_current_jst_time(self) -> datetime:
        return datetime.now(self.JST)

    def _get_date_key(self, dt: datetime) -> str:
        return dt.date().isoformat()

    def _calculate_duration_seconds(self, start: datetime, end: datetime) -> int:
        return int((end - start).total_seconds())

    @staticmethod
    def _format_duration_message(duration_seconds: int) -> str:
        """秒数を「XX時間XX分XX秒」形式に変換"""
        hours = duration_seconds // 3600
        minutes = (duration_seconds % 3600) // 60
        seconds = duration_seconds % 60
        return f"{hours}時間{minutes}分{seconds}秒"

    def _validate_date_str(self, date_str: str) -> None:
        """YYYY-MM-DD 形式を検証。不正な場合は ValueError を送出。"""
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            raise ValueError("日付の形式が正しくありません。YYYY-MM-DD形式で入力してください。")

    def _parse_time_hhmm(self, time_str: str, date_str: str) -> datetime:
        """HH:MM 形式の時刻文字列を JST の datetime に変換。不正な場合は ValueError を送出。"""
        parts = time_str.split(':')
        if len(parts) != 2:
            raise ValueError("時刻の形式が正しくありません。HH:MM形式で入力してください。")
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError("時刻の形式が正しくありません。HH:MM形式で入力してください。")
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("時刻の形式が正しくありません。HH:MM形式で入力してください。")
        target_date = datetime.fromisoformat(date_str).date()
        naive = datetime.combine(target_date, datetime.min.time().replace(hour=hour, minute=minute))
        return self.JST.localize(naive)

    def _find_open_check_in_record(self, current_time: datetime) -> Optional[tuple]:
        """退勤していない出勤記録を探す（日またぎ勤務対応）。
        Returns: (date_key, check_in_datetime) または None
        """
        for days_back in range(self.SEARCH_DAYS_BACK):
            check_date = current_time.date() - timedelta(days=days_back)
            date_key = check_date.isoformat()
            if date_key in self.records:
                record = self.records[date_key]
                if 'check_in' in record and 'check_out' not in record:
                    return (date_key, record['check_in'])
        return None

    def _summarize_records(self, daily_records: List[Dict], scheduled_hours: float = 8.0) -> Dict:
        """日次レコードのリストから集計統計を計算する。
        get_monthly_summary / get_weekly_summary の共通ロジック。
        """
        work_days = len(daily_records)
        total_seconds = sum(r['duration_seconds'] for r in daily_records)
        total_break_seconds = sum(r['break_seconds'] for r in daily_records)
        total_actual_work_seconds = sum(r['actual_work_seconds'] for r in daily_records)
        avg_seconds = total_seconds // work_days if work_days > 0 else 0
        avg_actual_work_seconds = total_actual_work_seconds // work_days if work_days > 0 else 0
        scheduled_seconds = int(scheduled_hours * 3600) * work_days
        overtime_seconds = total_actual_work_seconds - scheduled_seconds

        return {
            'records': daily_records,
            'work_days': work_days,
            'total_seconds': total_seconds,
            'total_break_seconds': total_break_seconds,
            'total_actual_work_seconds': total_actual_work_seconds,
            'avg_seconds': avg_seconds,
            'avg_actual_work_seconds': avg_actual_work_seconds,
            'scheduled_seconds': scheduled_seconds,
            'overtime_seconds': overtime_seconds,
            'scheduled_hours': scheduled_hours,
        }

    def _build_daily_record(self, date_key: str, record: Dict) -> Optional[Dict]:
        """1日分のレコード辞書から集計用の dict を構築する。退勤未記録は None を返す。"""
        if 'check_in' not in record or 'check_out' not in record:
            return None
        duration_seconds = self._calculate_duration_seconds(record['check_in'], record['check_out'])
        break_seconds = sum(
            self._calculate_duration_seconds(b['start'], b['end'])
            for b in record.get('breaks', [])
            if 'start' in b and 'end' in b
        )
        return {
            'date': date_key,
            'check_in': record['check_in'],
            'check_out': record['check_out'],
            'duration_seconds': duration_seconds,
            'break_seconds': break_seconds,
            'actual_work_seconds': duration_seconds - break_seconds,
        }

    def save_to_file(self) -> None:
        """勤怠記録を JSON ファイルに保存する"""
        self.data_file_path.parent.mkdir(parents=True, exist_ok=True)

        records_list = []
        for date_key, record in self.records.items():
            if 'check_in' not in record:
                continue
            entry: Dict[str, Any] = {
                'date': date_key,
                'check_in': record['check_in'].isoformat(),
            }
            if 'check_out' in record:
                entry['check_out'] = record['check_out'].isoformat()
                entry['duration_seconds'] = self._calculate_duration_seconds(
                    record['check_in'], record['check_out']
                )
            if 'breaks' in record:
                breaks_list = []
                for b in record['breaks']:
                    b_entry: Dict[str, Any] = {'start': b['start'].isoformat()}
                    if 'end' in b:
                        b_entry['end'] = b['end'].isoformat()
                        b_entry['duration_seconds'] = self._calculate_duration_seconds(b['start'], b['end'])
                    breaks_list.append(b_entry)
                entry['breaks'] = breaks_list
            records_list.append(entry)

        with open(self.data_file_path, 'w', encoding='utf-8') as f:
            json.dump({'records': records_list, 'version': '1.0.0'}, f, indent=2, ensure_ascii=False)

    def load_from_file(self) -> None:
        """JSON ファイルから勤怠記録を読み込む"""
        if not self.data_file_path.exists():
            return
        try:
            with open(self.data_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if 'records' not in data:
                return
            self.records = {}
            for entry in data['records']:
                date_key = entry['date']
                record: Dict[str, Any] = {}
                if 'check_in' in entry:
                    record['check_in'] = datetime.fromisoformat(entry['check_in'])
                if 'check_out' in entry:
                    record['check_out'] = datetime.fromisoformat(entry['check_out'])
                if 'breaks' in entry:
                    breaks = []
                    for b in entry['breaks']:
                        b_record: Dict[str, Any] = {'start': datetime.fromisoformat(b['start'])}
                        if 'end' in b:
                            b_record['end'] = datetime.fromisoformat(b['end'])
                        breaks.append(b_record)
                    record['breaks'] = breaks
                self.records[date_key] = record
        except (json.JSONDecodeError, ValueError, KeyError):
            self.records = {}

    def clock_in(self, force: bool = False) -> ClockResult:
        """出勤記録。

        force=False のとき:
          - 過去に未退勤の記録がある場合は needs_confirmation=True を返す（打刻忘れ検出）
          - 当日の出勤記録が既にある場合は needs_confirmation=False を返す（上書き確認）
        force=True のとき: 上記チェックをスキップして記録する。
        """
        now = self._get_current_jst_time()
        today = self._get_date_key(now)

        if today not in self.records:
            open_record = self._find_open_check_in_record(now)
            if open_record is not None and not force:
                open_date = open_record[0]
                return ClockResult(
                    success=False,
                    needs_confirmation=True,
                    message=f"{open_date}の退勤記録がありません。そのまま出勤記録しますか？",
                )
        elif not force:
            return ClockResult(
                success=False,
                needs_confirmation=False,
                message="既に本日の出勤記録があります。上書きしますか？ [y/N]",
            )

        self.records[today] = {'check_in': now}
        self.save_to_file()
        return ClockResult(success=True, message="出勤時刻を記録しました", timestamp=now)

    def clock_out(self) -> ClockResult:
        """退勤記録（日またぎ勤務対応）"""
        now = self._get_current_jst_time()
        open_record = self._find_open_check_in_record(now)
        if open_record is None:
            return ClockResult(success=False, message=self.NO_CHECK_IN_MESSAGE)

        check_in_date_key, check_in_time = open_record
        self.records[check_in_date_key]['check_out'] = now
        duration_seconds = self._calculate_duration_seconds(check_in_time, now)
        self.save_to_file()

        return ClockResult(
            success=True,
            message=(
                f"退勤時刻を記録しました: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"本日の勤務時間: {self._format_duration_message(duration_seconds)}"
            ),
            timestamp=now,
            duration_seconds=duration_seconds,
        )

    def get_today_status(self, reference_time: Optional[datetime] = None) -> Dict:
        """今日の勤怠状態を返す。

        Returns:
            state: '未出勤' | '出勤中' | '休憩中' | '退勤済み'
            check_in, check_out, breaks: 各記録
            elapsed_seconds: 出勤〜現在 or 出勤〜退勤（秒）
            break_seconds: 確定した休憩合計（秒）
            work_seconds: 退勤済みの実労働時間（秒）
            current_break_seconds: 休憩中の現在休憩経過（秒）
        """
        now = reference_time or self._get_current_jst_time()
        today = self._get_date_key(now)

        base: Dict[str, Any] = {
            'state': '未出勤',
            'check_in': None,
            'check_out': None,
            'breaks': [],
            'elapsed_seconds': None,
            'break_seconds': 0,
            'work_seconds': None,
            'current_break_seconds': None,
        }

        if today not in self.records or 'check_in' not in self.records[today]:
            return base

        record = self.records[today]
        check_in = record['check_in']
        breaks = record.get('breaks', [])
        break_seconds = sum(
            self._calculate_duration_seconds(b['start'], b['end'])
            for b in breaks if 'start' in b and 'end' in b
        )

        if 'check_out' in record:
            elapsed = self._calculate_duration_seconds(check_in, record['check_out'])
            return {
                'state': '退勤済み',
                'check_in': check_in,
                'check_out': record['check_out'],
                'breaks': breaks,
                'elapsed_seconds': elapsed,
                'break_seconds': break_seconds,
                'work_seconds': elapsed - break_seconds,
                'current_break_seconds': None,
            }

        elapsed = self._calculate_duration_seconds(check_in, now)
        current_break = next((b for b in breaks if 'start' in b and 'end' not in b), None)

        if current_break is not None:
            current_break_seconds = self._calculate_duration_seconds(current_break['start'], now)
            return {
                'state': '休憩中',
                'check_in': check_in,
                'check_out': None,
                'breaks': breaks,
                'elapsed_seconds': elapsed,
                'break_seconds': break_seconds,
                'work_seconds': None,
                'current_break_seconds': current_break_seconds,
            }

        return {
            'state': '出勤中',
            'check_in': check_in,
            'check_out': None,
            'breaks': breaks,
            'elapsed_seconds': elapsed,
            'break_seconds': break_seconds,
            'work_seconds': None,
            'current_break_seconds': None,
        }

    def edit_record(
        self,
        date_str: str,
        check_in_time: Optional[str] = None,
        check_out_time: Optional[str] = None,
    ) -> ClockResult:
        """指定日の出退勤時刻を編集する"""
        try:
            self._validate_date_str(date_str)
        except ValueError as e:
            return ClockResult(success=False, message=str(e))

        if date_str not in self.records:
            return ClockResult(success=False, message="指定された日付の記録が見つかりません。")

        record = self.records[date_str]

        if check_in_time:
            try:
                record['check_in'] = self._parse_time_hhmm(check_in_time, date_str)
            except ValueError as e:
                return ClockResult(success=False, message=str(e))

        if check_out_time:
            try:
                record['check_out'] = self._parse_time_hhmm(check_out_time, date_str)
            except ValueError as e:
                return ClockResult(success=False, message=str(e))

        self.save_to_file()
        return ClockResult(success=True, message="記録を更新しました。")

    def delete_record(self, date_str: str) -> ClockResult:
        """指定日の記録を削除する"""
        try:
            self._validate_date_str(date_str)
        except ValueError as e:
            return ClockResult(success=False, message=str(e))

        if date_str not in self.records:
            return ClockResult(success=False, message="指定された日付の記録が見つかりません。")

        del self.records[date_str]
        self.save_to_file()
        return ClockResult(success=True, message="記録を削除しました。")

    def create_new_record(self, date_str: str, check_in_time: str, check_out_time: str) -> ClockResult:
        """任意の日付の新規勤怠記録を作成する"""
        try:
            self._validate_date_str(date_str)
        except ValueError as e:
            return ClockResult(success=False, message=str(e))

        if date_str in self.records:
            return ClockResult(
                success=False,
                message="既に記録が存在します。編集するには edit コマンドを使用してください。",
            )

        try:
            check_in_dt = self._parse_time_hhmm(check_in_time, date_str)
            check_out_dt = self._parse_time_hhmm(check_out_time, date_str)
        except ValueError as e:
            return ClockResult(success=False, message=str(e))

        if check_out_dt <= check_in_dt:
            return ClockResult(
                success=False,
                message="退勤時刻が出勤時刻より早くなっています。日をまたぐ場合は別途対応が必要です。",
            )

        self.records[date_str] = {'check_in': check_in_dt, 'check_out': check_out_dt}
        self.save_to_file()

        duration_seconds = self._calculate_duration_seconds(check_in_dt, check_out_dt)
        return ClockResult(
            success=True,
            message=(
                f"{date_str}の記録を作成しました。\n"
                f"出勤: {check_in_dt.strftime('%H:%M:%S')}\n"
                f"退勤: {check_out_dt.strftime('%H:%M:%S')}\n"
                f"勤務時間: {self._format_duration_message(duration_seconds)}"
            ),
            timestamp=check_in_dt,
            duration_seconds=duration_seconds,
        )

    def break_start(self) -> ClockResult:
        """休憩開始記録"""
        now = self._get_current_jst_time()
        today = self._get_date_key(now)

        if today not in self.records or 'check_in' not in self.records[today]:
            return ClockResult(success=False, message=self.NO_CHECK_IN_MESSAGE)

        if 'check_out' in self.records[today]:
            return ClockResult(success=False, message="既に退勤済みです。休憩を開始できません。")

        breaks = self.records[today].setdefault('breaks', [])
        if any('start' in b and 'end' not in b for b in breaks):
            return ClockResult(
                success=False,
                message="既に休憩中です。先に 'kintai break end' を実行してください。",
            )

        breaks.append({'start': now})
        self.save_to_file()
        return ClockResult(
            success=True,
            message=f"休憩を開始しました: {now.strftime('%Y-%m-%d %H:%M:%S')}",
            timestamp=now,
        )

    def break_end(self) -> ClockResult:
        """休憩終了記録"""
        now = self._get_current_jst_time()
        today = self._get_date_key(now)

        if today not in self.records or 'check_in' not in self.records[today]:
            return ClockResult(success=False, message=self.NO_CHECK_IN_MESSAGE)

        breaks = self.records[today].get('breaks', [])
        current_break = next((b for b in breaks if 'start' in b and 'end' not in b), None)

        if current_break is None:
            return ClockResult(
                success=False,
                message="現在休憩中ではありません。先に 'kintai break start' を実行してください。",
            )

        current_break['end'] = now
        duration_seconds = self._calculate_duration_seconds(current_break['start'], now)
        self.save_to_file()

        return ClockResult(
            success=True,
            message=(
                f"休憩を終了しました: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"休憩時間: {self._format_duration_message(duration_seconds)}"
            ),
            timestamp=now,
            duration_seconds=duration_seconds,
        )

    def get_monthly_summary(self, year_month: str, scheduled_hours: float = 8.0) -> Dict:
        """指定月の勤怠集計を返す"""
        try:
            year, month = year_month.split('-')
            year, month = int(year), int(month)
            if not (1 <= month <= 12):
                raise ValueError()
        except (ValueError, AttributeError):
            return {'error': '日付の形式が正しくありません。YYYY-MM形式で入力してください。'}

        daily_records = []
        for date_key, record in self.records.items():
            if date_key.startswith(year_month):
                built = self._build_daily_record(date_key, record)
                if built is not None:
                    daily_records.append(built)

        daily_records.sort(key=lambda r: r['date'])
        result = self._summarize_records(daily_records, scheduled_hours)
        result['year_month'] = year_month
        return result

    def get_weekly_summary(self, date: Optional[datetime] = None) -> Dict:
        """指定日が属する週（月〜日）の勤怠集計を返す。月またぎ対応。"""
        now = date or self._get_current_jst_time()
        today = now.date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

        daily_records = []
        for date_key, record in self.records.items():
            record_date = datetime.fromisoformat(date_key).date()
            if week_start <= record_date <= week_end:
                built = self._build_daily_record(date_key, record)
                if built is not None:
                    daily_records.append(built)

        daily_records.sort(key=lambda r: r['date'])
        result = self._summarize_records(daily_records)
        result['week_start'] = week_start.isoformat()
        result['week_end'] = week_end.isoformat()
        result['week_label'] = f"{week_start.isoformat()} 〜 {week_end.isoformat()}"
        return result

    def export_monthly_csv(self, year_month: str) -> str:
        """月次データを CSV 文字列で返す（ヘッダー付き）"""
        summary = self.get_monthly_summary(year_month)
        if 'error' in summary:
            raise ValueError(summary['error'])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['日付', '曜日', '出勤時刻', '退勤時刻', '勤務時間', '休憩時間', '実労働時間'])

        for record in summary['records']:
            date_obj = datetime.fromisoformat(record['date']).date()
            writer.writerow([
                record['date'],
                WEEKDAY_JP[date_obj.weekday()],
                record['check_in'].strftime('%H:%M'),
                record['check_out'].strftime('%H:%M'),
                self._format_duration_message(record['duration_seconds']),
                self._format_duration_message(record['break_seconds']),
                self._format_duration_message(record['actual_work_seconds']),
            ])

        return output.getvalue()
