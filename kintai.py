"""勤怠管理CLIツール"""

from datetime import datetime, timedelta
import pytz
import json
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any
import click
import calendar


@dataclass
class ClockResult:
    """出退勤記録の結果を格納するクラス"""
    success: bool
    message: str
    timestamp: Optional[datetime] = None
    duration_seconds: Optional[int] = None


class KintaiManager:
    """勤怠管理のメインクラス"""
    
    JST = pytz.timezone('Asia/Tokyo')
    SEARCH_DAYS_BACK = 3  # 退勤記録時に過去何日間を検索するか
    NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
    
    def __init__(self, data_dir: Optional[str] = None):
        self.records: Dict[str, Dict[str, Any]] = {}
        
        # データディレクトリの決定（環境変数 > 引数 > デフォルト）
        if data_dir:
            base_dir = Path(data_dir)
        elif 'KINTAI_DATA_DIR' in os.environ:
            base_dir = Path(os.environ['KINTAI_DATA_DIR'])
        else:
            base_dir = Path.home() / '.kintai'
        
        self.data_file_path = base_dir / 'records.json'
        self.load_from_file()
    
    def _get_current_jst_time(self) -> datetime:
        """現在のJST時刻を取得"""
        return datetime.now(self.JST)
    
    def _get_date_key(self, dt: datetime) -> str:
        """日付キーを取得"""
        return dt.date().isoformat()
    
    def _calculate_duration_seconds(self, start_time: datetime, end_time: datetime) -> int:
        """勤務時間を秒単位で計算"""
        duration = end_time - start_time
        return int(duration.total_seconds())
    
    def _format_duration_message(self, duration_seconds: int) -> str:
        """勤務時間を時分秒形式でフォーマット"""
        hours = duration_seconds // 3600
        minutes = (duration_seconds % 3600) // 60
        seconds = duration_seconds % 60
        return f"{hours}時間{minutes}分{seconds}秒"
    
    def _find_open_check_in_record(self, current_time: datetime) -> Optional[tuple[str, datetime]]:
        """退勤していない出勤記録を探す（日またぎ勤務対応）
        
        Args:
            current_time: 現在時刻
            
        Returns:
            (日付キー, 出勤時刻) のタプル、または見つからない場合はNone
        """
        # 現在時刻から過去SEARCH_DAYS_BACK日間を検索範囲とする
        for days_back in range(self.SEARCH_DAYS_BACK):
            check_date = current_time.date() - timedelta(days=days_back)
            date_key = check_date.isoformat()
            
            if date_key in self.records:
                record = self.records[date_key]
                # 出勤記録があり、かつ退勤記録がない場合
                if 'check_in' in record and 'check_out' not in record:
                    return (date_key, record['check_in'])
        
        return None
    
    def save_to_file(self) -> None:
        """勤怠記録をJSONファイルに保存"""
        # ディレクトリが存在しない場合は作成
        self.data_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # README.mdの仕様に従ったJSONフォーマットで保存
        records_list = []
        for date_key, record in self.records.items():
            if 'check_in' in record:
                record_data = {
                    "date": date_key,
                    "check_in": record['check_in'].isoformat(),
                }
                
                if 'check_out' in record:
                    record_data["check_out"] = record['check_out'].isoformat()
                    # 勤務時間を計算
                    duration_seconds = self._calculate_duration_seconds(
                        record['check_in'], record['check_out']
                    )
                    record_data["duration_seconds"] = duration_seconds
                
                # 休憩時間の保存
                if 'breaks' in record:
                    breaks_list = []
                    for break_record in record['breaks']:
                        break_data = {
                            "start": break_record['start'].isoformat()
                        }
                        if 'end' in break_record:
                            break_data["end"] = break_record['end'].isoformat()
                            break_data["duration_seconds"] = self._calculate_duration_seconds(
                                break_record['start'], break_record['end']
                            )
                        breaks_list.append(break_data)
                    record_data["breaks"] = breaks_list
                
                records_list.append(record_data)
        
        # バージョン情報を含むデータ構造
        data = {
            "records": records_list,
            "version": "1.0.0"
        }
        
        # JSONファイルに保存
        with open(self.data_file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def load_from_file(self) -> None:
        """JSONファイルから勤怠記録を読み込み"""
        if not self.data_file_path.exists():
            return
        
        try:
            with open(self.data_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # データの検証
            if 'records' not in data:
                return
            
            # 記録を復元
            self.records = {}
            for record_data in data['records']:
                date_key = record_data['date']
                record = {}
                
                # 出勤時刻の復元
                if 'check_in' in record_data:
                    record['check_in'] = datetime.fromisoformat(record_data['check_in'])
                
                # 退勤時刻の復元
                if 'check_out' in record_data:
                    record['check_out'] = datetime.fromisoformat(record_data['check_out'])
                
                # 休憩時間の復元
                if 'breaks' in record_data:
                    breaks = []
                    for break_data in record_data['breaks']:
                        break_record = {
                            'start': datetime.fromisoformat(break_data['start'])
                        }
                        if 'end' in break_data:
                            break_record['end'] = datetime.fromisoformat(break_data['end'])
                        breaks.append(break_record)
                    record['breaks'] = breaks
                
                self.records[date_key] = record
                
        except (json.JSONDecodeError, ValueError, KeyError):
            # ファイルが破損している場合は空の記録で開始
            self.records = {}
    
    def clock_in(self) -> ClockResult:
        """出勤記録"""
        now = self._get_current_jst_time()
        today = self._get_date_key(now)
        
        # 既に当日の出勤記録があるかチェック
        if today in self.records:
            return ClockResult(
                success=False,
                message="既に本日の出勤記録があります。上書きしますか？ [y/N]"
            )
        
        # 出勤記録を保存
        self.records[today] = {'check_in': now}
        
        # ファイルに保存
        self.save_to_file()
        
        return ClockResult(
            success=True,
            message="出勤時刻を記録しました",
            timestamp=now
        )
    
    def clock_out(self) -> ClockResult:
        """退勤記録（日またぎ勤務対応）"""
        now = self._get_current_jst_time()
        
        # 退勤していない出勤記録を探す
        open_record = self._find_open_check_in_record(now)
        
        if open_record is None:
            return ClockResult(
                success=False,
                message=self.NO_CHECK_IN_MESSAGE
            )
        
        # 出勤記録が見つかった場合
        check_in_date_key, check_in_time = open_record
        
        # 退勤記録を保存
        self.records[check_in_date_key]['check_out'] = now
        
        # 勤務時間を計算
        duration_seconds = self._calculate_duration_seconds(check_in_time, now)
        duration_message = self._format_duration_message(duration_seconds)
        
        # ファイルに保存
        self.save_to_file()
        
        return ClockResult(
            success=True,
            message=f"退勤時刻を記録しました: {now.strftime('%Y-%m-%d %H:%M:%S')}\n本日の勤務時間: {duration_message}",
            timestamp=now,
            duration_seconds=duration_seconds
        )
    
    def edit_record(self, date_str: str, check_in_time: Optional[str] = None, 
                   check_out_time: Optional[str] = None) -> ClockResult:
        """勤怠記録の編集"""
        try:
            # 日付形式の検証
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return ClockResult(
                success=False,
                message="日付の形式が正しくありません。YYYY-MM-DD形式で入力してください。"
            )
        
        # 記録の存在確認
        if date_str not in self.records:
            return ClockResult(
                success=False,
                message="指定された日付の記録が見つかりません。"
            )
        
        record = self.records[date_str]
        
        # 出勤時刻の更新
        if check_in_time:
            try:
                # HH:MM形式をパース
                time_parts = check_in_time.split(':')
                if len(time_parts) != 2:
                    raise ValueError("Invalid time format")
                
                hour, minute = map(int, time_parts)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("Invalid time values")
                
                # 元の日付を維持して時刻のみ更新
                original_date = datetime.fromisoformat(date_str).date()
                new_check_in = datetime.combine(original_date, datetime.min.time().replace(hour=hour, minute=minute))
                new_check_in = self.JST.localize(new_check_in)
                record['check_in'] = new_check_in
                
            except (ValueError, TypeError):
                return ClockResult(
                    success=False,
                    message="出勤時刻の形式が正しくありません。HH:MM形式で入力してください。"
                )
        
        # 退勤時刻の更新
        if check_out_time:
            try:
                # HH:MM形式をパース
                time_parts = check_out_time.split(':')
                if len(time_parts) != 2:
                    raise ValueError("Invalid time format")
                
                hour, minute = map(int, time_parts)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("Invalid time values")
                
                # 元の日付を維持して時刻のみ更新
                original_date = datetime.fromisoformat(date_str).date()
                new_check_out = datetime.combine(original_date, datetime.min.time().replace(hour=hour, minute=minute))
                new_check_out = self.JST.localize(new_check_out)
                record['check_out'] = new_check_out
                
            except (ValueError, TypeError):
                return ClockResult(
                    success=False,
                    message="退勤時刻の形式が正しくありません。HH:MM形式で入力してください。"
                )
        
        # ファイルに保存
        self.save_to_file()
        
        return ClockResult(
            success=True,
            message="記録を更新しました。"
        )
    
    def delete_record(self, date_str: str) -> ClockResult:
        """勤怠記録の削除"""
        try:
            # 日付形式の検証
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return ClockResult(
                success=False,
                message="日付の形式が正しくありません。YYYY-MM-DD形式で入力してください。"
            )
        
        # 記録の存在確認
        if date_str not in self.records:
            return ClockResult(
                success=False,
                message="指定された日付の記録が見つかりません。"
            )
        
        # 記録を削除
        del self.records[date_str]
        
        # ファイルに保存
        self.save_to_file()
        
        return ClockResult(
            success=True,
            message="記録を削除しました。"
        )
    
    def get_monthly_summary(self, year_month: str) -> dict:
        """月次サマリーを取得"""
        try:
            # YYYY-MM形式の検証
            year, month = year_month.split('-')
            year, month = int(year), int(month)
            if not (1 <= month <= 12):
                raise ValueError("Invalid month")
        except (ValueError, IndexError):
            return {"error": "日付の形式が正しくありません。YYYY-MM形式で入力してください。"}
        
        # 指定月の記録を抽出
        monthly_records = []
        for date_key, record in self.records.items():
            if date_key.startswith(year_month):
                if 'check_in' in record and 'check_out' in record:
                    # 総滞在時間を計算
                    duration_seconds = self._calculate_duration_seconds(
                        record['check_in'], record['check_out']
                    )
                    
                    # 休憩時間の合計を計算
                    total_break_seconds = 0
                    if 'breaks' in record:
                        for break_record in record['breaks']:
                            if 'start' in break_record and 'end' in break_record:
                                break_duration = self._calculate_duration_seconds(
                                    break_record['start'], break_record['end']
                                )
                                total_break_seconds += break_duration
                    
                    # 実勤務時間（休憩時間を除く）
                    actual_work_seconds = duration_seconds - total_break_seconds
                    
                    monthly_records.append({
                        'date': date_key,
                        'check_in': record['check_in'],
                        'check_out': record['check_out'],
                        'duration_seconds': duration_seconds,
                        'break_seconds': total_break_seconds,
                        'actual_work_seconds': actual_work_seconds
                    })
        
        # 日付順でソート
        monthly_records.sort(key=lambda x: x['date'])
        
        # 統計を計算
        total_seconds = sum(record['duration_seconds'] for record in monthly_records)
        total_break_seconds = sum(record['break_seconds'] for record in monthly_records)
        total_actual_work_seconds = sum(record['actual_work_seconds'] for record in monthly_records)
        work_days = len(monthly_records)
        avg_seconds = total_seconds // work_days if work_days > 0 else 0
        avg_actual_work_seconds = total_actual_work_seconds // work_days if work_days > 0 else 0
        
        return {
            'year_month': year_month,
            'records': monthly_records,
            'total_seconds': total_seconds,
            'total_break_seconds': total_break_seconds,
            'total_actual_work_seconds': total_actual_work_seconds,
            'work_days': work_days,
            'avg_seconds': avg_seconds,
            'avg_actual_work_seconds': avg_actual_work_seconds
        }
    
    def break_start(self) -> ClockResult:
        """休憩開始"""
        now = self._get_current_jst_time()
        today = self._get_date_key(now)
        
        # 出勤記録があるかチェック
        if today not in self.records or 'check_in' not in self.records[today]:
            return ClockResult(
                success=False,
                message=self.NO_CHECK_IN_MESSAGE
            )
        
        # 既に退勤済みでないかチェック
        if 'check_out' in self.records[today]:
            return ClockResult(
                success=False,
                message="既に退勤済みです。休憩を開始できません。"
            )
        
        # breaks リストが存在しない場合は初期化
        if 'breaks' not in self.records[today]:
            self.records[today]['breaks'] = []
        
        # 現在休憩中でないかチェック
        for break_record in self.records[today]['breaks']:
            if 'start' in break_record and 'end' not in break_record:
                return ClockResult(
                    success=False,
                    message="既に休憩中です。先に 'kintai break end' を実行してください。"
                )
        
        # 休憩開始を記録
        self.records[today]['breaks'].append({'start': now})
        
        # ファイルに保存
        self.save_to_file()
        
        return ClockResult(
            success=True,
            message=f"休憩を開始しました: {now.strftime('%Y-%m-%d %H:%M:%S')}",
            timestamp=now
        )
    
    def break_end(self) -> ClockResult:
        """休憩終了"""
        now = self._get_current_jst_time()
        today = self._get_date_key(now)
        
        # 出勤記録があるかチェック
        if today not in self.records or 'check_in' not in self.records[today]:
            return ClockResult(
                success=False,
                message=self.NO_CHECK_IN_MESSAGE
            )
        
        # 休憩記録があるかチェック
        if 'breaks' not in self.records[today]:
            return ClockResult(
                success=False,
                message="現在休憩中ではありません。先に 'kintai break start' を実行してください。"
            )
        
        # 現在進行中の休憩を探す
        current_break = None
        for break_record in self.records[today]['breaks']:
            if 'start' in break_record and 'end' not in break_record:
                current_break = break_record
                break
        
        if current_break is None:
            return ClockResult(
                success=False,
                message="現在休憩中ではありません。先に 'kintai break start' を実行してください。"
            )
        
        # 休憩終了を記録
        current_break['end'] = now
        
        # 休憩時間を計算
        duration_seconds = self._calculate_duration_seconds(current_break['start'], now)
        duration_message = self._format_duration_message(duration_seconds)
        
        # ファイルに保存
        self.save_to_file()
        
        return ClockResult(
            success=True,
            message=f"休憩を終了しました: {now.strftime('%Y-%m-%d %H:%M:%S')}\n休憩時間: {duration_message}",
            timestamp=now,
            duration_seconds=duration_seconds
        )
    
    def create_new_record(self, date_str: str, check_in_time: str, check_out_time: str) -> ClockResult:
        """任意の日付の新規勤怠記録を作成"""
        try:
            # 日付形式の検証
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return ClockResult(
                success=False,
                message="日付の形式が正しくありません。YYYY-MM-DD形式で入力してください。"
            )
        
        # 既存記録の存在確認
        if date_str in self.records:
            return ClockResult(
                success=False,
                message="既に記録が存在します。編集するには edit コマンドを使用してください。"
            )
        
        # 時刻形式の検証とパース
        try:
            # HH:MM形式をパース
            in_parts = check_in_time.split(':')
            out_parts = check_out_time.split(':')
            
            if len(in_parts) != 2 or len(out_parts) != 2:
                raise ValueError("Invalid time format")
            
            in_hour, in_minute = map(int, in_parts)
            out_hour, out_minute = map(int, out_parts)
            
            if not (0 <= in_hour <= 23 and 0 <= in_minute <= 59):
                raise ValueError("Invalid check-in time values")
            if not (0 <= out_hour <= 23 and 0 <= out_minute <= 59):
                raise ValueError("Invalid check-out time values")
            
            # 指定日付で datetime オブジェクトを作成
            target_date = datetime.fromisoformat(date_str).date()
            
            check_in_dt = datetime.combine(target_date, datetime.min.time().replace(hour=in_hour, minute=in_minute))
            check_out_dt = datetime.combine(target_date, datetime.min.time().replace(hour=out_hour, minute=out_minute))
            
            # JST タイムゾーンを適用
            check_in_dt = self.JST.localize(check_in_dt)
            check_out_dt = self.JST.localize(check_out_dt)
            
            # 時刻の順序チェック（同日の場合）
            if check_out_dt <= check_in_dt:
                return ClockResult(
                    success=False,
                    message="退勤時刻が出勤時刻より早くなっています。日をまたぐ場合は別途対応が必要です。"
                )
            
        except (ValueError, TypeError):
            return ClockResult(
                success=False,
                message="時刻の形式が正しくありません。HH:MM形式で入力してください。"
            )
        
        # 新規記録を作成
        self.records[date_str] = {
            'check_in': check_in_dt,
            'check_out': check_out_dt
        }
        
        # ファイルに保存
        self.save_to_file()
        
        # 勤務時間を計算
        duration_seconds = self._calculate_duration_seconds(check_in_dt, check_out_dt)
        duration_message = self._format_duration_message(duration_seconds)
        
        return ClockResult(
            success=True,
            message=f"{date_str}の記録を作成しました。\n出勤: {check_in_dt.strftime('%H:%M:%S')}\n退勤: {check_out_dt.strftime('%H:%M:%S')}\n勤務時間: {duration_message}",
            timestamp=check_in_dt,
            duration_seconds=duration_seconds
        )


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
        timestamp_str = result.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        click.echo(f"出勤時刻を記録しました: {timestamp_str}")
    else:
        click.echo(result.message)
        if click.confirm("上書きしますか？"):
            # 強制的に出勤記録を更新
            today = manager._get_date_key(manager._get_current_jst_time())
            now = manager._get_current_jst_time()
            manager.records[today] = {'check_in': now}
            manager.save_to_file()
            timestamp_str = now.strftime('%Y-%m-%d %H:%M:%S')
            click.echo(f"出勤時刻を記録しました: {timestamp_str}")


@cli.command()
def out():
    """退勤記録"""
    manager = KintaiManager()
    result = manager.clock_out()
    
    if result.success:
        lines = result.message.split('\n')
        for line in lines:
            click.echo(line)
    else:
        click.echo(result.message, err=True)


@cli.command()
def status():
    """現在の勤務状態を確認"""
    manager = KintaiManager()
    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst)
    today = now.date().isoformat()
    
    if today in manager.records and 'check_in' in manager.records[today]:
        record = manager.records[today]
        check_in_time = record['check_in']
        
        if 'check_out' in record:
            # 退勤済み
            check_out_time = record['check_out']
            duration_seconds = int((check_out_time - check_in_time).total_seconds())
            
            # 休憩時間の合計を計算
            total_break_seconds = 0
            if 'breaks' in record:
                for break_record in record['breaks']:
                    if 'start' in break_record and 'end' in break_record:
                        break_duration = int((break_record['end'] - break_record['start']).total_seconds())
                        total_break_seconds += break_duration
            
            # 実勤務時間（休憩時間を除く）
            actual_work_seconds = duration_seconds - total_break_seconds
            
            hours = duration_seconds // 3600
            minutes = (duration_seconds % 3600) // 60
            seconds = duration_seconds % 60
            
            work_hours = actual_work_seconds // 3600
            work_minutes = (actual_work_seconds % 3600) // 60
            work_secs = actual_work_seconds % 60
            
            break_hours = total_break_seconds // 3600
            break_minutes = (total_break_seconds % 3600) // 60
            break_secs = total_break_seconds % 60
            
            click.echo("状態: 退勤済み")
            click.echo(f"出勤時刻: {check_in_time.strftime('%Y-%m-%d %H:%M:%S')}")
            click.echo(f"退勤時刻: {check_out_time.strftime('%Y-%m-%d %H:%M:%S')}")
            click.echo(f"総勤務時間: {hours}時間{minutes}分{seconds}秒")
            if total_break_seconds > 0:
                click.echo(f"休憩時間: {break_hours}時間{break_minutes}分{break_secs}秒")
                click.echo(f"実勤務時間: {work_hours}時間{work_minutes}分{work_secs}秒")
        else:
            # 出勤中 - 休憩中かどうかもチェック
            is_on_break = False
            current_break_start = None
            
            if 'breaks' in record:
                for break_record in record['breaks']:
                    if 'start' in break_record and 'end' not in break_record:
                        is_on_break = True
                        current_break_start = break_record['start']
                        break
            
            elapsed = now - check_in_time
            elapsed_seconds = int(elapsed.total_seconds())
            hours = elapsed_seconds // 3600
            minutes = (elapsed_seconds % 3600) // 60
            seconds = elapsed_seconds % 60
            
            if is_on_break:
                break_elapsed = now - current_break_start
                break_elapsed_seconds = int(break_elapsed.total_seconds())
                break_hours = break_elapsed_seconds // 3600
                break_minutes = (break_elapsed_seconds % 3600) // 60
                break_secs = break_elapsed_seconds % 60
                
                click.echo("状態: 休憩中")
                click.echo(f"出勤時刻: {check_in_time.strftime('%Y-%m-%d %H:%M:%S')}")
                click.echo(f"休憩開始: {current_break_start.strftime('%Y-%m-%d %H:%M:%S')}")
                click.echo(f"総経過時間: {hours}時間{minutes}分{seconds}秒")
                click.echo(f"休憩経過時間: {break_hours}時間{break_minutes}分{break_secs}秒")
            else:
                click.echo("状態: 出勤中")
                click.echo(f"出勤時刻: {check_in_time.strftime('%Y-%m-%d %H:%M:%S')}")
                click.echo(f"経過時間: {hours}時間{minutes}分{seconds}秒")
    else:
        click.echo("状態: 未出勤")


@cli.command()
@click.option('--date', required=True, help='編集する日付 (YYYY-MM-DD)')
@click.option('--in', 'check_in', help='新しい出勤時刻 (HH:MM)')
@click.option('--out', 'check_out', help='新しい退勤時刻 (HH:MM)')
def edit(date, check_in, check_out):
    """勤怠記録の編集"""
    manager = KintaiManager()
    
    # オプションが指定されていない場合は対話形式
    if not check_in and not check_out:
        # 対話形式での編集
        result = _interactive_edit(manager, date)
        if not result.success:
            click.echo(result.message, err=True)
            click.get_current_context().exit(1)
        else:
            click.echo(result.message)
    else:
        # 直接指定での編集
        result = manager.edit_record(date, check_in, check_out)
        
        if result.success:
            click.echo(result.message)
        else:
            click.echo(result.message, err=True)
            click.get_current_context().exit(1)


def _interactive_edit(manager: KintaiManager, date_str: str) -> ClockResult:
    """対話形式での記録編集"""
    # まず記録の存在確認と日付形式検証
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return ClockResult(
            success=False,
            message="日付の形式が正しくありません。YYYY-MM-DD形式で入力してください。"
        )
    
    if date_str not in manager.records:
        return ClockResult(
            success=False,
            message="指定された日付の記録が見つかりません。"
        )
    
    record = manager.records[date_str]
    
    # 現在の記録を表示
    click.echo("現在の記録:")
    if 'check_in' in record:
        click.echo(f"  出勤: {record['check_in'].strftime('%H:%M:%S')}")
    else:
        click.echo("  出勤: 記録なし")
    
    if 'check_out' in record:
        click.echo(f"  退勤: {record['check_out'].strftime('%H:%M:%S')}")
    else:
        click.echo("  退勤: 記録なし")
    
    # 対話形式で新しい時刻を入力
    new_check_in = click.prompt(
        "新しい出勤時刻 (HH:MM) [変更しない場合はEnter]", 
        default="", 
        show_default=False
    )
    new_check_out = click.prompt(
        "新しい退勤時刻 (HH:MM) [変更しない場合はEnter]", 
        default="", 
        show_default=False
    )
    
    # 空文字列の場合はNoneに変換
    new_check_in = new_check_in.strip() if new_check_in.strip() else None
    new_check_out = new_check_out.strip() if new_check_out.strip() else None
    
    # 何も変更されていない場合
    if not new_check_in and not new_check_out:
        return ClockResult(
            success=True,
            message="変更はありませんでした。"
        )
    
    # 記録を更新
    return manager.edit_record(date_str, new_check_in, new_check_out)


@cli.command()
@click.option('--date', required=True, help='削除する日付 (YYYY-MM-DD)')
def delete(date):
    """勤怠記録の削除"""
    manager = KintaiManager()
    
    # 削除確認
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
    
    # パラメータの必須チェック
    if not check_in or not check_out:
        click.echo("--in と --out は必須です。", err=True)
        click.get_current_context().exit(1)
    
    result = manager.create_new_record(date, check_in, check_out)
    
    if result.success:
        lines = result.message.split('\n')
        for line in lines:
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
        lines = result.message.split('\n')
        for line in lines:
            click.echo(line)
    else:
        click.echo(result.message, err=True)
        click.get_current_context().exit(1)


# breakコマンドのエイリアス設定
cli.add_command(break_group, name='break')


@cli.command()
@click.option('--month', help='対象の月 (YYYY-MM)。省略時は現在月')
@click.option('--copy', is_flag=True, help='結果をMarkdown形式でクリップボードにコピー')
def summary(month, copy):
    """月次勤怠レポートを表示"""
    manager = KintaiManager()
    
    # 月の指定がない場合は現在月を使用
    if not month:
        jst = pytz.timezone('Asia/Tokyo')
        now = datetime.now(jst)
        month = now.strftime('%Y-%m')
    
    # 月次サマリーを取得
    summary_data = manager.get_monthly_summary(month)
    
    if 'error' in summary_data:
        click.echo(summary_data['error'], err=True)
        click.get_current_context().exit(1)
    
    # 年月の表示用文字列を作成
    year, month_num = summary_data['year_month'].split('-')
    display_month = f"{year}年{int(month_num)}月"
    
    if copy:
        # Markdown形式でクリップボードにコピー
        markdown_content = _generate_markdown_summary(summary_data, display_month)
        try:
            import pyperclip
            pyperclip.copy(markdown_content)
            click.echo("クリップボードにコピーしました。")
        except ImportError:
            click.echo("エラー: pyperclipモジュールが見つかりません。クリップボード機能を使用するにはpyperclipをインストールしてください。", err=True)
            click.get_current_context().exit(1)
    else:
        # コンソール出力
        _display_console_summary(summary_data, display_month)


def _display_console_summary(summary_data: dict, display_month: str):
    """コンソール用のサマリー表示"""
    click.echo(f"{display_month}の勤怠記録")
    click.echo("=" * 70)
    
    if not summary_data['records']:
        click.echo("記録がありません。")
        return
    
    # ヘッダー
    click.echo(f"{'日付':<12} {'出勤時刻':<10} {'退勤時刻':<10} {'総勤務':<10} {'休憩':<8} {'実勤務':<10}")
    click.echo("-" * 70)
    
    # 各日の記録
    for record in summary_data['records']:
        date_str = record['date']
        check_in_str = record['check_in'].strftime('%H:%M:%S')
        check_out_str = record['check_out'].strftime('%H:%M:%S')
        total_duration_str = _format_duration_from_seconds(record['duration_seconds'])
        break_duration_str = _format_duration_from_seconds(record['break_seconds'])
        actual_work_str = _format_duration_from_seconds(record['actual_work_seconds'])
        
        click.echo(f"{date_str:<12} {check_in_str:<10} {check_out_str:<10} {total_duration_str:<10} {break_duration_str:<8} {actual_work_str:<10}")
    
    # サマリー
    click.echo("=" * 70)
    total_duration_str = _format_duration_from_seconds(summary_data['total_seconds'])
    total_break_str = _format_duration_from_seconds(summary_data['total_break_seconds'])
    total_actual_work_str = _format_duration_from_seconds(summary_data['total_actual_work_seconds'])
    avg_duration_str = _format_duration_from_seconds(summary_data['avg_seconds'])
    avg_actual_work_str = _format_duration_from_seconds(summary_data['avg_actual_work_seconds'])
    
    click.echo(f"総勤務時間: {total_duration_str}")
    if summary_data['total_break_seconds'] > 0:
        click.echo(f"総休憩時間: {total_break_str}")
        click.echo(f"実勤務時間: {total_actual_work_str}")
    click.echo(f"勤務日数: {summary_data['work_days']}日")
    click.echo(f"平均勤務時間: {avg_duration_str}")
    if summary_data['total_break_seconds'] > 0:
        click.echo(f"平均実勤務時間: {avg_actual_work_str}")


def _generate_markdown_summary(summary_data: dict, display_month: str) -> str:
    """Markdown形式のサマリーを生成"""
    lines = []
    lines.append(f"# {display_month} 勤怠記録")
    lines.append("")
    lines.append("## 勤務詳細")
    lines.append("")
    
    if not summary_data['records']:
        lines.append("記録がありません。")
        return "\n".join(lines)
    
    # テーブルヘッダー
    lines.append("| 日付 | 曜日 | 出勤時刻 | 退勤時刻 | 総勤務時間 | 休憩時間 | 実勤務時間 |")
    lines.append("|------|------|----------|----------|------------|----------|------------|")
    
    # 各日の記録
    for record in summary_data['records']:
        date_obj = datetime.fromisoformat(record['date']).date()
        weekday = calendar.day_name[date_obj.weekday()]
        weekday_jp = {
            'Monday': '月', 'Tuesday': '火', 'Wednesday': '水', 
            'Thursday': '木', 'Friday': '金', 'Saturday': '土', 'Sunday': '日'
        }[weekday]
        
        date_str = record['date']
        check_in_str = record['check_in'].strftime('%H:%M:%S')
        check_out_str = record['check_out'].strftime('%H:%M:%S')
        total_duration_str = _format_duration_from_seconds(record['duration_seconds'])
        break_duration_str = _format_duration_from_seconds(record['break_seconds'])
        actual_work_str = _format_duration_from_seconds(record['actual_work_seconds'])
        
        lines.append(f"| {date_str} | {weekday_jp} | {check_in_str} | {check_out_str} | {total_duration_str} | {break_duration_str} | {actual_work_str} |")
    
    # サマリー
    lines.append("")
    lines.append("## 月次サマリー")
    lines.append("")
    total_duration_str = _format_duration_from_seconds(summary_data['total_seconds'])
    total_break_str = _format_duration_from_seconds(summary_data['total_break_seconds'])
    total_actual_work_str = _format_duration_from_seconds(summary_data['total_actual_work_seconds'])
    avg_duration_str = _format_duration_from_seconds(summary_data['avg_seconds'])
    avg_actual_work_str = _format_duration_from_seconds(summary_data['avg_actual_work_seconds'])
    
    lines.append(f"- **総勤務時間**: {total_duration_str}")
    if summary_data['total_break_seconds'] > 0:
        lines.append(f"- **総休憩時間**: {total_break_str}")
        lines.append(f"- **実勤務時間**: {total_actual_work_str}")
    lines.append(f"- **勤務日数**: {summary_data['work_days']}日")
    lines.append(f"- **平均勤務時間**: {avg_duration_str}")
    if summary_data['total_break_seconds'] > 0:
        lines.append(f"- **平均実勤務時間**: {avg_actual_work_str}")
    
    return "\n".join(lines)


def _format_duration_from_seconds(duration_seconds: int) -> str:
    """秒数から時分秒形式に変換"""
    hours = duration_seconds // 3600
    minutes = (duration_seconds % 3600) // 60
    seconds = duration_seconds % 60
    return f"{hours}時間{minutes}分{seconds}秒"


# inコマンドのエイリアス設定
cli.add_command(in_command, name='in')


def main():
    """CLIのエントリーポイント"""
    cli()


if __name__ == "__main__":
    main()