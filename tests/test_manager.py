"""KintaiManager ユニットテスト"""

import json
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import pytest

from kintai import KintaiManager


def make_manager(temp_dir: str) -> KintaiManager:
    """テスト用の KintaiManager を作成する（~/.kintai には触れない）"""
    manager = KintaiManager.__new__(KintaiManager)
    manager.records = {}
    manager.data_file_path = Path(temp_dir) / 'records.json'
    manager.JST = pytz.timezone('Asia/Tokyo')
    manager.SEARCH_DAYS_BACK = 3
    manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
    return manager


JST = pytz.timezone('Asia/Tokyo')




class TestKintaiBasics:
    def test_clock_in_records_current_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            before = datetime.now(JST)
            result = manager.clock_in()
            after = datetime.now(JST)

            assert result.success is True
            assert result.message == "出勤時刻を記録しました"
            assert before <= result.timestamp <= after
            assert result.timestamp.tzinfo.zone == 'Asia/Tokyo'

    def test_clock_in_twice_same_day_shows_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            result = manager.clock_in()

            assert result.success is False
            assert result.needs_confirmation is False
            assert "既に本日の出勤記録があります" in result.message

    def test_clock_in_force_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            result = manager.clock_in(force=True)

            assert result.success is True




class TestClockOut:
    def test_clock_out_records_time_and_calculates_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            before = datetime.now(JST)
            result = manager.clock_out()
            after = datetime.now(JST)

            assert result.success is True
            assert "退勤時刻を記録しました" in result.message
            assert before <= result.timestamp <= after
            assert result.duration_seconds is not None and result.duration_seconds >= 0

    def test_clock_out_without_clock_in_shows_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.clock_out()

            assert result.success is False
            assert "本日の出勤記録がありません" in result.message

    def test_clock_out_calculates_correct_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            now = datetime.now(JST)
            start = now - timedelta(minutes=1)
            today = start.date().isoformat()
            manager.records[today] = {'check_in': start}

            result = manager.clock_out()

            assert result.success is True
            assert result.duration_seconds >= 60




class TestCrossDateWork:
    def test_cross_date_work(self):
        manager = KintaiManager()
        check_in = datetime(2025, 1, 10, 22, 0, 0, tzinfo=JST)
        manager.records['2025-01-10'] = {'check_in': check_in}
        original = manager._get_current_jst_time
        manager._get_current_jst_time = lambda: datetime(2025, 1, 11, 7, 0, 0, tzinfo=JST)
        result = manager.clock_out()
        manager._get_current_jst_time = original

        assert result.success is True
        assert result.duration_seconds == 9 * 3600
        assert "退勤時刻を記録しました" in result.message

    def test_cross_date_duration_calculation(self):
        manager = KintaiManager()
        ci = datetime(2025, 1, 10, 22, 0, 0, tzinfo=JST)
        co = datetime(2025, 1, 11, 7, 0, 0, tzinfo=JST)

        assert manager._calculate_duration_seconds(ci, co) == 9 * 3600
        assert manager._format_duration_message(9 * 3600) == "9時間0分0秒"




class TestJSONPersistence:
    def test_save_records_to_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            ci = datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST)
            co = datetime(2025, 1, 10, 18, 30, 0, tzinfo=JST)
            manager.records['2025-01-10'] = {'check_in': ci, 'check_out': co}
            manager.save_to_file()

            assert manager.data_file_path.exists()
            data = json.loads(manager.data_file_path.read_text())
            assert data['version'] == '1.0.0'
            assert len(data['records']) == 1
            r = data['records'][0]
            assert r['date'] == '2025-01-10'
            assert 'check_in' in r and 'check_out' in r and 'duration_seconds' in r

    def test_load_records_from_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'records.json'
            path.write_text(json.dumps({
                'records': [{
                    'date': '2025-01-10',
                    'check_in': '2025-01-10T09:00:15+09:00',
                    'check_out': '2025-01-10T18:30:45+09:00',
                    'duration_seconds': 34230,
                }],
                'version': '1.0.0',
            }))
            manager = make_manager(tmp)
            manager.load_from_file()

            assert '2025-01-10' in manager.records
            r = manager.records['2025-01-10']
            assert r['check_in'].hour == 9 and r['check_in'].minute == 0

    def test_manager_uses_home_directory_by_default(self):
        manager = KintaiManager()
        assert str(manager.data_file_path).endswith('.kintai/records.json')

    def test_auto_save_on_clock_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.clock_in()

            assert result.success is True
            assert manager.data_file_path.exists()
            data = json.loads(manager.data_file_path.read_text())
            assert len(data['records']) == 1

    def test_save_and_load_breaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            ci = datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST)
            bs = datetime(2025, 1, 10, 12, 0, 0, tzinfo=JST)
            be = datetime(2025, 1, 10, 13, 0, 0, tzinfo=JST)
            manager.records['2025-01-10'] = {
                'check_in': ci,
                'breaks': [{'start': bs, 'end': be}],
            }
            manager.save_to_file()

            manager2 = make_manager(tmp)
            manager2.load_from_file()

            assert '2025-01-10' in manager2.records
            assert 'breaks' in manager2.records['2025-01-10']
            b = manager2.records['2025-01-10']['breaks'][0]
            assert b['start'].hour == 12 and b['end'].hour == 13




class TestEditCommand:
    def test_edit_modifies_existing_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            ci = datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST)
            co = datetime(2025, 1, 10, 18, 0, 0, tzinfo=JST)
            manager.records['2025-01-10'] = {'check_in': ci, 'check_out': co}

            result = manager.edit_record('2025-01-10', '09:30', '19:00')

            assert result.success is True
            assert manager.records['2025-01-10']['check_in'].hour == 9
            assert manager.records['2025-01-10']['check_in'].minute == 30

    def test_edit_invalid_date_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.edit_record('invalid-date', '09:00')

            assert result.success is False
            assert "日付の形式が正しくありません" in result.message

    def test_edit_nonexistent_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.edit_record('2025-01-10', '09:00')

            assert result.success is False
            assert "指定された日付の記録が見つかりません" in result.message

    def test_edit_invalid_time_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            ci = datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST)
            manager.records['2025-01-10'] = {'check_in': ci}

            result = manager.edit_record('2025-01-10', 'bad-time')

            assert result.success is False
            assert "時刻の形式が正しくありません" in result.message




class TestDeleteCommand:
    def test_delete_removes_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2025-01-10'] = {
                'check_in': datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST)
            }
            result = manager.delete_record('2025-01-10')

            assert result.success is True
            assert '2025-01-10' not in manager.records

    def test_delete_nonexistent_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.delete_record('2025-01-10')

            assert result.success is False

    def test_delete_invalid_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.delete_record('not-a-date')

            assert result.success is False
            assert "日付の形式が正しくありません" in result.message




class TestSummaryLogic:
    def _make_manager_with_data(self, tmp):
        manager = make_manager(tmp)
        manager.records['2025-01-08'] = {
            'check_in': datetime(2025, 1, 8, 9, 0, 0, tzinfo=JST),
            'check_out': datetime(2025, 1, 8, 18, 30, 0, tzinfo=JST),
        }
        manager.records['2025-01-09'] = {
            'check_in': datetime(2025, 1, 9, 8, 45, 0, tzinfo=JST),
            'check_out': datetime(2025, 1, 9, 19, 15, 0, tzinfo=JST),
        }
        return manager

    def test_monthly_summary_returns_correct_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = self._make_manager_with_data(tmp)
            result = manager.get_monthly_summary('2025-01')

            assert result['work_days'] == 2
            assert result['total_seconds'] > 0

    def test_invalid_year_month_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.get_monthly_summary('invalid')

            assert 'error' in result




class TestBreakTime:
    def test_break_start_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            result = manager.break_start()

            assert result.success is True
            assert "休憩を開始しました" in result.message

    def test_break_end_calculates_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            manager.break_start()
            result = manager.break_end()

            assert result.success is True
            assert "休憩を終了しました" in result.message
            assert result.duration_seconds is not None

    def test_break_start_without_clock_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.break_start()

            assert result.success is False
            assert "本日の出勤記録がありません" in result.message

    def test_break_end_without_break_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            result = manager.break_end()

            assert result.success is False
            assert "現在休憩中ではありません" in result.message

    def test_multiple_breaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            assert manager.break_start().success is True
            assert manager.break_end().success is True
            assert manager.break_start().success is True
            assert manager.break_end().success is True

    def test_duplicate_break_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            manager.break_start()
            result = manager.break_start()

            assert result.success is False
            assert "既に休憩中です" in result.message




class TestNewCommandKintaiManager:
    def test_create_new_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.create_new_record('2025-01-15', '09:00', '18:00')

            assert result.success is True
            assert "2025-01-15の記録を作成しました" in result.message
            assert '2025-01-15' in manager.records

    def test_create_duplicate_record_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.create_new_record('2025-01-15', '09:00', '18:00')
            result = manager.create_new_record('2025-01-15', '10:00', '19:00')

            assert result.success is False
            assert "既に記録が存在します" in result.message

    def test_create_invalid_time_order_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.create_new_record('2025-01-15', '18:00', '09:00')

            assert result.success is False
            assert "退勤時刻が出勤時刻より早くなっています" in result.message


# ---------------------------------------------------------------------------
# TestTodayStatus (新機能)
# ---------------------------------------------------------------------------

class TestTodayStatus:
    def test_未出勤状態(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            ref = datetime(2026, 4, 4, 10, 0, 0, tzinfo=JST)
            result = manager.get_today_status(reference_time=ref)

            assert result['state'] == '未出勤'
            assert result['check_in'] is None
            assert result['break_seconds'] == 0

    def test_出勤中状態(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            ci = datetime(2026, 4, 4, 9, 0, 0, tzinfo=JST)
            manager.records['2026-04-04'] = {'check_in': ci}
            ref = datetime(2026, 4, 4, 11, 0, 0, tzinfo=JST)
            result = manager.get_today_status(reference_time=ref)

            assert result['state'] == '出勤中'
            assert result['elapsed_seconds'] == 7200
            assert result['work_seconds'] is None
            assert result['current_break_seconds'] is None

    def test_休憩中状態(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            ci = datetime(2026, 4, 4, 9, 0, 0, tzinfo=JST)
            bs = datetime(2026, 4, 4, 12, 0, 0, tzinfo=JST)
            manager.records['2026-04-04'] = {'check_in': ci, 'breaks': [{'start': bs}]}
            ref = datetime(2026, 4, 4, 12, 30, 0, tzinfo=JST)
            result = manager.get_today_status(reference_time=ref)

            assert result['state'] == '休憩中'
            assert result['current_break_seconds'] == 1800
            assert result['elapsed_seconds'] == 3 * 3600 + 1800  # 3.5h

    def test_退勤済み_休憩込み(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            ci = datetime(2026, 4, 4, 9, 0, 0, tzinfo=JST)
            co = datetime(2026, 4, 4, 18, 0, 0, tzinfo=JST)
            bs = datetime(2026, 4, 4, 12, 0, 0, tzinfo=JST)
            be = datetime(2026, 4, 4, 13, 0, 0, tzinfo=JST)
            manager.records['2026-04-04'] = {
                'check_in': ci, 'check_out': co,
                'breaks': [{'start': bs, 'end': be}],
            }
            ref = datetime(2026, 4, 4, 19, 0, 0, tzinfo=JST)
            result = manager.get_today_status(reference_time=ref)

            assert result['state'] == '退勤済み'
            assert result['break_seconds'] == 3600
            assert result['work_seconds'] == 8 * 3600  # 9h - 1h = 8h
            assert result['elapsed_seconds'] == 9 * 3600

    def test_reference_timeで時刻を固定できる(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            ci = datetime(2026, 4, 4, 9, 0, 0, tzinfo=JST)
            manager.records['2026-04-04'] = {'check_in': ci}
            ref = datetime(2026, 4, 4, 10, 30, 0, tzinfo=JST)
            result = manager.get_today_status(reference_time=ref)

            assert result['elapsed_seconds'] == 5400  # 1.5h exactly


# ---------------------------------------------------------------------------
# TestForgottenClockOut (新機能)
# ---------------------------------------------------------------------------

class TestForgottenClockOut:
    def test_昨日の未退勤がある場合にneeds_confirmationがTrue(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            yesterday = (datetime.now(JST) - timedelta(days=1)).date().isoformat()
            manager.records[yesterday] = {
                'check_in': datetime.now(JST) - timedelta(hours=14)
            }
            result = manager.clock_in()

            assert result.success is False
            assert result.needs_confirmation is True
            assert yesterday in result.message

    def test_force_Trueで未退勤があっても出勤記録される(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            yesterday = (datetime.now(JST) - timedelta(days=1)).date().isoformat()
            manager.records[yesterday] = {
                'check_in': datetime.now(JST) - timedelta(hours=14)
            }
            result = manager.clock_in(force=True)

            assert result.success is True

    def test_当日上書きはneeds_confirmation_False(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            result = manager.clock_in()

            assert result.success is False
            assert result.needs_confirmation is False

    def test_過去記録なし正常ケース(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.clock_in()

            assert result.success is True
            assert result.needs_confirmation is False


# ---------------------------------------------------------------------------
# TestWeeklySummary (新機能)
# ---------------------------------------------------------------------------

class TestWeeklySummary:
    def test_週の集計(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            # 2026-03-30 (月) の週に記録を追加
            manager.records['2026-03-30'] = {
                'check_in': datetime(2026, 3, 30, 9, 0, 0, tzinfo=JST),
                'check_out': datetime(2026, 3, 30, 18, 0, 0, tzinfo=JST),
            }
            manager.records['2026-03-31'] = {
                'check_in': datetime(2026, 3, 31, 9, 0, 0, tzinfo=JST),
                'check_out': datetime(2026, 3, 31, 18, 0, 0, tzinfo=JST),
            }
            ref = datetime(2026, 3, 30, 12, 0, 0, tzinfo=JST)
            result = manager.get_weekly_summary(date=ref)

            assert result['work_days'] == 2
            assert result['total_seconds'] == 2 * 9 * 3600

    def test_週の開始は月曜日(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            ref = datetime(2026, 4, 4, 12, 0, 0, tzinfo=JST)  # 土曜日
            result = manager.get_weekly_summary(date=ref)

            from datetime import date
            week_start = date.fromisoformat(result['week_start'])
            assert week_start.weekday() == 0  # 月曜日

    def test_月またぎの週(self):
        """2026-03-30 (月) 〜 2026-04-05 (日) の週：3月と4月にまたがる"""
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2026-03-31'] = {
                'check_in': datetime(2026, 3, 31, 9, 0, 0, tzinfo=JST),
                'check_out': datetime(2026, 3, 31, 18, 0, 0, tzinfo=JST),
            }
            manager.records['2026-04-01'] = {
                'check_in': datetime(2026, 4, 1, 9, 0, 0, tzinfo=JST),
                'check_out': datetime(2026, 4, 1, 18, 0, 0, tzinfo=JST),
            }
            ref = datetime(2026, 4, 1, 12, 0, 0, tzinfo=JST)
            result = manager.get_weekly_summary(date=ref)

            assert result['work_days'] == 2  # 3月と4月の両方が含まれる

    def test_date引数でその週を指定(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2026-03-30'] = {
                'check_in': datetime(2026, 3, 30, 9, 0, 0, tzinfo=JST),
                'check_out': datetime(2026, 3, 30, 18, 0, 0, tzinfo=JST),
            }
            # 2026-03-30 の週を指定 (水曜日で指定)
            ref = datetime(2026, 4, 1, 0, 0, 0, tzinfo=JST)  # 水曜日
            result = manager.get_weekly_summary(date=ref)

            assert result['work_days'] == 1
            assert result['week_start'] == '2026-03-30'

    def test_空データでゼロ集計(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.get_weekly_summary()

            assert result['work_days'] == 0
            assert result['total_seconds'] == 0


# ---------------------------------------------------------------------------
# TestOvertimeCalculation (新機能)
# ---------------------------------------------------------------------------

class TestOvertimeCalculation:
    def test_残業あり(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2025-01-10'] = {
                'check_in': datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST),
                'check_out': datetime(2025, 1, 10, 18, 0, 0, tzinfo=JST),  # 9時間勤務
            }
            result = manager.get_monthly_summary('2025-01', scheduled_hours=8.0)

            assert result['overtime_seconds'] == 3600  # 1時間残業

    def test_残業なし_マイナス(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2025-01-10'] = {
                'check_in': datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST),
                'check_out': datetime(2025, 1, 10, 16, 0, 0, tzinfo=JST),  # 7時間勤務
            }
            result = manager.get_monthly_summary('2025-01', scheduled_hours=8.0)

            assert result['overtime_seconds'] == -3600  # 1時間不足

    def test_scheduled_secondsは日数x所定時間(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            for day in ['2025-01-08', '2025-01-09']:
                manager.records[day] = {
                    'check_in': datetime(2025, 1, int(day[-2:]), 9, 0, 0, tzinfo=JST),
                    'check_out': datetime(2025, 1, int(day[-2:]), 18, 0, 0, tzinfo=JST),
                }
            result = manager.get_monthly_summary('2025-01', scheduled_hours=8.0)

            assert result['scheduled_seconds'] == 8 * 3600 * 2

    def test_デフォルト所定時間は8時間(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2025-01-10'] = {
                'check_in': datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST),
                'check_out': datetime(2025, 1, 10, 17, 0, 0, tzinfo=JST),
            }
            result = manager.get_monthly_summary('2025-01')

            assert result['scheduled_hours'] == 8.0


# ---------------------------------------------------------------------------
# TestExportCSV (新機能)
# ---------------------------------------------------------------------------

class TestExportCSV:
    def _make_manager_with_jan_data(self, tmp):
        manager = make_manager(tmp)
        manager.records['2025-01-08'] = {
            'check_in': datetime(2025, 1, 8, 9, 0, 0, tzinfo=JST),
            'check_out': datetime(2025, 1, 8, 18, 0, 0, tzinfo=JST),
        }
        return manager

    def test_ヘッダー行の確認(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = self._make_manager_with_jan_data(tmp)
            csv_str = manager.export_monthly_csv('2025-01')
            first_line = csv_str.splitlines()[0]

            assert '日付' in first_line
            assert '曜日' in first_line
            assert '出勤時刻' in first_line
            assert '退勤時刻' in first_line

    def test_データ行の内容確認(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = self._make_manager_with_jan_data(tmp)
            csv_str = manager.export_monthly_csv('2025-01')
            lines = csv_str.splitlines()

            assert len(lines) == 2  # ヘッダー + 1行
            assert '2025-01-08' in lines[1]
            assert '09:00' in lines[1]

    def test_曜日が日本語(self):
        """2025-01-08 は水曜日"""
        with tempfile.TemporaryDirectory() as tmp:
            manager = self._make_manager_with_jan_data(tmp)
            csv_str = manager.export_monthly_csv('2025-01')
            data_line = csv_str.splitlines()[1]

            assert '水' in data_line

    def test_記録なしでヘッダーのみ(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            csv_str = manager.export_monthly_csv('2025-01')
            lines = [l for l in csv_str.splitlines() if l]

            assert len(lines) == 1  # ヘッダーのみ

    def test_不正year_monthでValueError(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            with pytest.raises(ValueError):
                manager.export_monthly_csv('invalid')
