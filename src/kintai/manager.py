"""勤怠管理ビジネスロジック"""

import calendar
import csv
import io
import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

from .models import ClockResult

WEEKDAY_JP = ['月', '火', '水', '木', '金', '土', '日']


def _migrate_entry(entry: Dict) -> Dict:
    """v1.0.0 の単一 check_in/check_out エントリを v2.0.0 の sessions 形式に変換する（冪等）。"""
    if 'sessions' in entry or 'check_in' not in entry:
        return entry
    session: Dict[str, Any] = {'check_in': entry['check_in']}
    if 'check_out' in entry:
        session['check_out'] = entry['check_out']
    migrated = {k: v for k, v in entry.items() if k not in ('check_in', 'check_out', 'duration_seconds')}
    migrated['sessions'] = [session]
    return migrated


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

    def _find_open_session(self, current_time: datetime) -> Optional[tuple]:
        """未クローズのセッションを探す（日またぎ勤務対応）。
        全レコード中で未クローズのセッションは最大1つという不変条件を前提にする。
        Returns: (date_key, session_index, check_in_datetime) または None
        """
        for days_back in range(self.SEARCH_DAYS_BACK):
            check_date = current_time.date() - timedelta(days=days_back)
            date_key = check_date.isoformat()
            if date_key in self.records:
                sessions = self.records[date_key].get('sessions', [])
                for idx, s in enumerate(sessions):
                    if 'check_in' in s and 'check_out' not in s:
                        return (date_key, idx, s['check_in'])
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
        """1日分のレコード辞書から集計用の dict を構築する。進行中の日は None を返す。"""
        sessions = record.get('sessions', [])
        if not sessions or any('check_out' not in s for s in sessions):
            return None
        duration_seconds = sum(
            self._calculate_duration_seconds(s['check_in'], s['check_out']) for s in sessions
        )
        break_seconds = sum(
            self._calculate_duration_seconds(b['start'], b['end'])
            for b in record.get('breaks', [])
            if 'start' in b and 'end' in b
        )
        return {
            'date': date_key,
            'check_in': sessions[0]['check_in'],
            'check_out': sessions[-1]['check_out'],
            'sessions': sessions,
            'sessions_label': '; '.join(
                f"{s['check_in'].strftime('%H:%M')}-{s['check_out'].strftime('%H:%M')}" for s in sessions
            ),
            'duration_seconds': duration_seconds,
            'break_seconds': break_seconds,
            'actual_work_seconds': duration_seconds - break_seconds,
        }

    def _backup_v1_file(self) -> None:
        """移行前の records.json をバックアップする（初回のみ）"""
        backup_path = Path(str(self.data_file_path) + '.v1.bak')
        if not backup_path.exists():
            shutil.copy2(self.data_file_path, backup_path)

    def save_to_file(self) -> None:
        """勤怠記録を JSON ファイルに保存する"""
        self.data_file_path.parent.mkdir(parents=True, exist_ok=True)

        records_list = []
        for date_key, record in self.records.items():
            sessions = record.get('sessions', [])
            if not sessions:
                continue
            sessions_list = []
            for s in sessions:
                s_entry: Dict[str, Any] = {'check_in': s['check_in'].isoformat()}
                if 'check_out' in s:
                    s_entry['check_out'] = s['check_out'].isoformat()
                    s_entry['duration_seconds'] = self._calculate_duration_seconds(
                        s['check_in'], s['check_out']
                    )
                sessions_list.append(s_entry)

            entry: Dict[str, Any] = {'date': date_key, 'sessions': sessions_list}
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
            json.dump({'records': records_list, 'version': '2.0.0'}, f, indent=2, ensure_ascii=False)

    def load_from_file(self) -> None:
        """JSON ファイルから勤怠記録を読み込む（v1.0.0形式は自動的にsessions形式へ移行する）"""
        if not self.data_file_path.exists():
            return
        try:
            with open(self.data_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if 'records' not in data:
                return

            migrated_any = False
            entries = []
            for entry in data['records']:
                migrated = _migrate_entry(entry)
                if migrated is not entry:
                    migrated_any = True
                entries.append(migrated)

            if migrated_any:
                self._backup_v1_file()

            self.records = {}
            for entry in entries:
                date_key = entry['date']
                record: Dict[str, Any] = {}

                sessions = []
                for s in entry.get('sessions', []):
                    session: Dict[str, Any] = {'check_in': datetime.fromisoformat(s['check_in'])}
                    if 'check_out' in s:
                        session['check_out'] = datetime.fromisoformat(s['check_out'])
                    sessions.append(session)
                if sessions:
                    record['sessions'] = sessions

                if 'breaks' in entry:
                    breaks = []
                    for b in entry['breaks']:
                        b_record: Dict[str, Any] = {'start': datetime.fromisoformat(b['start'])}
                        if 'end' in b:
                            b_record['end'] = datetime.fromisoformat(b['end'])
                        breaks.append(b_record)
                    record['breaks'] = breaks

                self.records[date_key] = record

            if migrated_any:
                self.save_to_file()
        except (json.JSONDecodeError, ValueError, KeyError):
            self.records = {}

    def clock_in(self, force: bool = False) -> ClockResult:
        """出勤記録（複数セッション対応）。

        - 当日すでに未クローズのセッションがある場合はハードブロック（forceでも記録しない）。
        - 過去日に未クローズのセッションがある場合（打刻忘れ）は force=False だと確認を要求する。
        - それ以外は当日のセッションリストに新しいセッションを追記する。
        """
        now = self._get_current_jst_time()
        today = self._get_date_key(now)
        open_session = self._find_open_session(now)

        if open_session is not None:
            open_date, _, _ = open_session
            if open_date == today:
                return ClockResult(
                    success=False,
                    needs_confirmation=False,
                    message="既に出勤中です。'kintai out' で退勤してください。",
                )
            if not force:
                return ClockResult(
                    success=False,
                    needs_confirmation=True,
                    message=f"{open_date}の退勤記録がありません。そのまま出勤記録しますか？",
                )

        sessions = self.records.setdefault(today, {}).setdefault('sessions', [])
        sessions.append({'check_in': now})
        self.save_to_file()
        return ClockResult(success=True, message="出勤時刻を記録しました", timestamp=now)

    def clock_out(self) -> ClockResult:
        """退勤記録（日またぎ勤務対応）"""
        now = self._get_current_jst_time()
        open_session = self._find_open_session(now)
        if open_session is None:
            return ClockResult(success=False, message=self.NO_CHECK_IN_MESSAGE)

        date_key, idx, check_in_time = open_session
        self.records[date_key]['sessions'][idx]['check_out'] = now
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
        """今日の勤怠状態を返す（複数セッション対応、当日分のみ）。

        Returns:
            state: '未出勤' | '出勤中' | '休憩中' | '退勤済み'
            check_in, check_out: 最初のセッションのcheck_in / 最後のセッションのcheck_out（表示互換用）
            sessions: 当日の生セッションリスト
            breaks: 各記録
            elapsed_seconds: 出勤〜現在 or 全セッション合計（秒）
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
            'sessions': [],
            'breaks': [],
            'elapsed_seconds': None,
            'break_seconds': 0,
            'work_seconds': None,
            'current_break_seconds': None,
        }

        sessions = self.records.get(today, {}).get('sessions', [])
        if not sessions:
            return base

        breaks = self.records[today].get('breaks', [])
        break_seconds = sum(
            self._calculate_duration_seconds(b['start'], b['end'])
            for b in breaks if 'start' in b and 'end' in b
        )

        last_session = sessions[-1]

        if 'check_out' in last_session:
            elapsed = sum(
                self._calculate_duration_seconds(s['check_in'], s['check_out']) for s in sessions
            )
            return {
                'state': '退勤済み',
                'check_in': sessions[0]['check_in'],
                'check_out': last_session['check_out'],
                'sessions': sessions,
                'breaks': breaks,
                'elapsed_seconds': elapsed,
                'break_seconds': break_seconds,
                'work_seconds': elapsed - break_seconds,
                'current_break_seconds': None,
            }

        elapsed = sum(
            self._calculate_duration_seconds(s['check_in'], s.get('check_out', now)) for s in sessions
        )
        current_break = next((b for b in breaks if 'start' in b and 'end' not in b), None)

        if current_break is not None:
            current_break_seconds = self._calculate_duration_seconds(current_break['start'], now)
            return {
                'state': '休憩中',
                'check_in': sessions[0]['check_in'],
                'check_out': None,
                'sessions': sessions,
                'breaks': breaks,
                'elapsed_seconds': elapsed,
                'break_seconds': break_seconds,
                'work_seconds': None,
                'current_break_seconds': current_break_seconds,
            }

        return {
            'state': '出勤中',
            'check_in': sessions[0]['check_in'],
            'check_out': None,
            'sessions': sessions,
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
        session_index: int = 0,
    ) -> ClockResult:
        """指定日のセッションの出退勤時刻を編集する（デフォルトは最初のセッション）"""
        try:
            self._validate_date_str(date_str)
        except ValueError as e:
            return ClockResult(success=False, message=str(e))

        if date_str not in self.records:
            return ClockResult(success=False, message="指定された日付の記録が見つかりません。")

        sessions = self.records[date_str].get('sessions', [])
        if session_index < 0 or session_index >= len(sessions):
            return ClockResult(success=False, message="指定されたセッションが見つかりません。")

        session = sessions[session_index]

        if check_in_time:
            try:
                session['check_in'] = self._parse_time_hhmm(check_in_time, date_str)
            except ValueError as e:
                return ClockResult(success=False, message=str(e))

        if check_out_time:
            try:
                session['check_out'] = self._parse_time_hhmm(check_out_time, date_str)
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
        """任意の日付の新規勤怠記録を作成する（1セッション）"""
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

        self.records[date_str] = {'sessions': [{'check_in': check_in_dt, 'check_out': check_out_dt}]}
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

    def set_day_sessions(
        self,
        date_str: str,
        sessions: List[Dict[str, Any]],
        breaks: Optional[List[Dict[str, str]]] = None,
    ) -> ClockResult:
        """指定日のセッション・休憩を丸ごと置き換える（Web UI の保存アクション用）。

        sessions: [{'check_in': 'HH:MM', 'check_out': 'HH:MM' or None, 'check_out_next_day': bool}]
        breaks: [{'start': 'HH:MM', 'end': 'HH:MM'}]

        check_out を持たない（進行中の）セッションは、この日全体で最大1件まで許容する
        （出勤中の日でも、既に確定している他のセッションだけを編集して保存できるようにするため）。
        2件以上が進行中の場合は拒否する。進行中セッションは末尾に並べ替えて保存する。
        breaks を省略した場合はこの日の休憩なしとして扱う（Web UI は常に現在の休憩を
        GET で取得してから POST するため、意図せず消えることはない）。
        """
        try:
            self._validate_date_str(date_str)
        except ValueError as e:
            return ClockResult(success=False, message=str(e))

        if not sessions:
            return ClockResult(success=False, message="少なくとも1つのセッションが必要です。")

        closed_sessions = []
        open_session = None
        for s in sessions:
            check_in_str = s.get('check_in')
            check_out_str = s.get('check_out')
            if not check_in_str:
                return ClockResult(success=False, message="出勤時刻が入力されていないセッションがあります。")

            if not check_out_str:
                if open_session is not None:
                    return ClockResult(
                        success=False,
                        message="進行中（退勤未記録）のセッションは1日に1件までです。",
                    )
                try:
                    check_in_dt = self._parse_time_hhmm(check_in_str, date_str)
                except ValueError as e:
                    return ClockResult(success=False, message=str(e))
                open_session = {'check_in': check_in_dt}
                continue

            try:
                check_in_dt = self._parse_time_hhmm(check_in_str, date_str)
                if s.get('check_out_next_day'):
                    next_day = (datetime.fromisoformat(date_str) + timedelta(days=1)).date().isoformat()
                    check_out_dt = self._parse_time_hhmm(check_out_str, next_day)
                else:
                    check_out_dt = self._parse_time_hhmm(check_out_str, date_str)
            except ValueError as e:
                return ClockResult(success=False, message=str(e))

            if check_out_dt <= check_in_dt:
                return ClockResult(
                    success=False,
                    message=f"セッション {check_in_str}-{check_out_str} の退勤時刻が出勤時刻より早くなっています。",
                )
            closed_sessions.append({'check_in': check_in_dt, 'check_out': check_out_dt})

        parsed_sessions = closed_sessions + ([open_session] if open_session else [])

        parsed_breaks = []
        for b in (breaks or []):
            start_str = b.get('start')
            end_str = b.get('end')
            if not start_str or not end_str:
                return ClockResult(success=False, message="休憩時刻の形式が正しくありません。")
            try:
                start_dt = self._parse_time_hhmm(start_str, date_str)
                end_dt = self._parse_time_hhmm(end_str, date_str)
            except ValueError as e:
                return ClockResult(success=False, message=str(e))
            if end_dt <= start_dt:
                return ClockResult(success=False, message="休憩の終了時刻が開始時刻より早くなっています。")
            parsed_breaks.append({'start': start_dt, 'end': end_dt})

        record: Dict[str, Any] = {'sessions': parsed_sessions}
        if parsed_breaks:
            record['breaks'] = parsed_breaks
        self.records[date_str] = record
        self.save_to_file()

        return ClockResult(success=True, message=f"{date_str}の記録を保存しました。")

    def break_start(self) -> ClockResult:
        """休憩開始記録（未クローズのセッションがあることを要求）"""
        now = self._get_current_jst_time()
        today = self._get_date_key(now)
        sessions = self.records.get(today, {}).get('sessions', [])

        if not sessions:
            return ClockResult(success=False, message=self.NO_CHECK_IN_MESSAGE)

        open_session = next((s for s in sessions if 'check_out' not in s), None)
        if open_session is None:
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
        sessions = self.records.get(today, {}).get('sessions', [])

        if not sessions:
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

    def get_month_days(self, year_month: str) -> List[Dict]:
        """指定月の全カレンダー日について、未クローズのセッションも含めた生データを返す（Web UI用）。"""
        try:
            year_str, month_str = year_month.split('-')
            year, month = int(year_str), int(month_str)
            if not (1 <= month <= 12):
                raise ValueError()
        except (ValueError, AttributeError):
            raise ValueError("日付の形式が正しくありません。YYYY-MM形式で入力してください。")

        num_days = calendar.monthrange(year, month)[1]
        days = []
        for day in range(1, num_days + 1):
            date_key = f"{year}-{month:02d}-{day:02d}"
            record = self.records.get(date_key, {})
            sessions = record.get('sessions', [])
            breaks = record.get('breaks', [])
            is_open = any('check_out' not in s for s in sessions)

            duration_seconds = None
            break_seconds = None
            actual_work_seconds = None
            if sessions and not is_open:
                duration_seconds = sum(
                    self._calculate_duration_seconds(s['check_in'], s['check_out']) for s in sessions
                )
                break_seconds = sum(
                    self._calculate_duration_seconds(b['start'], b['end'])
                    for b in breaks if 'start' in b and 'end' in b
                )
                actual_work_seconds = duration_seconds - break_seconds

            days.append({
                'date': date_key,
                'weekday': WEEKDAY_JP[datetime(year, month, day).weekday()],
                'sessions': sessions,
                'breaks': breaks,
                'is_open': is_open,
                'duration_seconds': duration_seconds,
                'break_seconds': break_seconds,
                'actual_work_seconds': actual_work_seconds,
            })
        return days

    def export_monthly_csv(self, year_month: str) -> str:
        """月次データを CSV 文字列で返す（ヘッダー付き）"""
        summary = self.get_monthly_summary(year_month)
        if 'error' in summary:
            raise ValueError(summary['error'])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['日付', '曜日', '出勤時刻', '退勤時刻', '勤務時間', '休憩時間', '実労働時間', 'セッション'])

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
                record['sessions_label'],
            ])

        return output.getvalue()
