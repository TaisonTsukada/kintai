"""KintaiManager ユニットテスト"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import pytest

from kintai import KintaiManager
from kintai.manager import _migrate_entry


def make_manager(temp_dir: str) -> KintaiManager:
    """テスト用の KintaiManager を作成する（~/.kintai には触れない）"""
    manager = KintaiManager.__new__(KintaiManager)
    manager.records = {}
    manager.data_file_path = Path(temp_dir) / 'records.json'
    manager.JST = pytz.timezone('Asia/Tokyo')
    manager.SEARCH_DAYS_BACK = 3
    manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
    return manager


def make_day(pairs, breaks=None):
    """[(check_in, check_out_or_None), ...] から sessions 形式のレコード dict を作る"""
    sessions = []
    for ci, co in pairs:
        session = {'check_in': ci}
        if co is not None:
            session['check_out'] = co
        sessions.append(session)
    record = {'sessions': sessions}
    if breaks:
        record['breaks'] = breaks
    return record


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
            assert "既に出勤中です" in result.message

    def test_clock_in_force_does_not_bypass_same_day_open_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            result = manager.clock_in(force=True)

            assert result.success is False

    def test_clock_in_after_clock_out_appends_new_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            manager.clock_out()
            result = manager.clock_in()

            assert result.success is True
            today = manager._get_date_key(manager._get_current_jst_time())
            assert len(manager.records[today]['sessions']) == 2


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
            manager.records[today] = make_day([(start, None)])

            result = manager.clock_out()

            assert result.success is True
            assert result.duration_seconds >= 60


class TestCrossDateWork:
    def test_cross_date_work(self):
        manager = KintaiManager()
        check_in = datetime(2025, 1, 10, 22, 0, 0, tzinfo=JST)
        manager.records['2025-01-10'] = make_day([(check_in, None)])
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
            manager.records['2025-01-10'] = make_day([(ci, co)])
            manager.save_to_file()

            assert manager.data_file_path.exists()
            data = json.loads(manager.data_file_path.read_text())
            assert data['version'] == '2.0.0'
            assert len(data['records']) == 1
            r = data['records'][0]
            assert r['date'] == '2025-01-10'
            assert 'sessions' in r
            assert len(r['sessions']) == 1
            assert 'check_in' in r['sessions'][0] and 'check_out' in r['sessions'][0]
            assert 'duration_seconds' in r['sessions'][0]

    def test_load_records_from_json_file(self):
        """v1.0.0形式のファイルを読み込むと自動的にsessions形式へ移行される"""
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
            assert len(r['sessions']) == 1
            assert r['sessions'][0]['check_in'].hour == 9 and r['sessions'][0]['check_in'].minute == 0

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
            manager.records['2025-01-10'] = make_day([(ci, None)], breaks=[{'start': bs, 'end': be}])
            manager.save_to_file()

            manager2 = make_manager(tmp)
            manager2.load_from_file()

            assert '2025-01-10' in manager2.records
            assert 'breaks' in manager2.records['2025-01-10']
            b = manager2.records['2025-01-10']['breaks'][0]
            assert b['start'].hour == 12 and b['end'].hour == 13


class TestMigration:
    def test_migrate_entry_converts_single_session(self):
        entry = {
            'date': '2025-01-10',
            'check_in': '2025-01-10T09:00:00+09:00',
            'check_out': '2025-01-10T18:00:00+09:00',
            'duration_seconds': 32400,
        }
        migrated = _migrate_entry(entry)

        assert 'check_in' not in migrated
        assert 'check_out' not in migrated
        assert 'duration_seconds' not in migrated
        assert migrated['sessions'] == [{
            'check_in': '2025-01-10T09:00:00+09:00',
            'check_out': '2025-01-10T18:00:00+09:00',
        }]

    def test_migrate_entry_is_idempotent(self):
        entry = {'date': '2025-01-10', 'sessions': [{'check_in': '...', 'check_out': '...'}]}
        assert _migrate_entry(entry) is entry

    def test_migrate_entry_handles_open_session(self):
        entry = {'date': '2025-01-10', 'check_in': '2025-01-10T09:00:00+09:00'}
        migrated = _migrate_entry(entry)
        assert migrated['sessions'] == [{'check_in': '2025-01-10T09:00:00+09:00'}]

    def test_load_creates_v1_backup_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'records.json'
            v1_data = {
                'records': [{
                    'date': '2025-01-10',
                    'check_in': '2025-01-10T09:00:00+09:00',
                    'check_out': '2025-01-10T18:00:00+09:00',
                }],
                'version': '1.0.0',
            }
            path.write_text(json.dumps(v1_data))

            manager = make_manager(tmp)
            manager.load_from_file()

            backup_path = Path(tmp) / 'records.json.v1.bak'
            assert backup_path.exists()
            assert json.loads(backup_path.read_text()) == v1_data

            saved = json.loads(path.read_text())
            assert saved['version'] == '2.0.0'

            backup_mtime = backup_path.stat().st_mtime
            manager2 = make_manager(tmp)
            manager2.load_from_file()
            assert backup_path.stat().st_mtime == backup_mtime


class TestEditCommand:
    def test_edit_modifies_existing_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            ci = datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST)
            co = datetime(2025, 1, 10, 18, 0, 0, tzinfo=JST)
            manager.records['2025-01-10'] = make_day([(ci, co)])

            result = manager.edit_record('2025-01-10', '09:30', '19:00')

            assert result.success is True
            assert manager.records['2025-01-10']['sessions'][0]['check_in'].hour == 9
            assert manager.records['2025-01-10']['sessions'][0]['check_in'].minute == 30

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
            manager.records['2025-01-10'] = make_day([(ci, None)])

            result = manager.edit_record('2025-01-10', 'bad-time')

            assert result.success is False
            assert "時刻の形式が正しくありません" in result.message


class TestDeleteCommand:
    def test_delete_removes_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2025-01-10'] = make_day([(datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST), None)])
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
        manager.records['2025-01-08'] = make_day([
            (datetime(2025, 1, 8, 9, 0, 0, tzinfo=JST), datetime(2025, 1, 8, 18, 30, 0, tzinfo=JST)),
        ])
        manager.records['2025-01-09'] = make_day([
            (datetime(2025, 1, 9, 8, 45, 0, tzinfo=JST), datetime(2025, 1, 9, 19, 15, 0, tzinfo=JST)),
        ])
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


class TestBreakSessionAware:
    def test_break_start_on_second_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            manager.clock_out()
            manager.clock_in()
            result = manager.break_start()

            assert result.success is True

    def test_break_start_after_day_closed_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            manager.clock_out()
            result = manager.break_start()

            assert result.success is False
            assert "既に退勤済みです" in result.message


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


class TestSetDaySessions:
    def test_set_day_sessions_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.set_day_sessions('2025-01-15', [
                {'check_in': '09:00', 'check_out': '12:00'},
                {'check_in': '13:00', 'check_out': '18:00'},
            ])

            assert result.success is True
            sessions = manager.records['2025-01-15']['sessions']
            assert len(sessions) == 2
            built = manager._build_daily_record('2025-01-15', manager.records['2025-01-15'])
            assert built['duration_seconds'] == 3 * 3600 + 5 * 3600

    def test_set_day_sessions_rejects_invalid_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.set_day_sessions('2025-01-15', [
                {'check_in': '18:00', 'check_out': '09:00'},
            ])
            assert result.success is False

    def test_set_day_sessions_allows_one_open_trailing_session(self):
        """出勤中でも保存できる: 進行中セッションは1件までなら受け入れる"""
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.set_day_sessions('2025-01-15', [
                {'check_in': '09:00', 'check_out': None},
            ])
            assert result.success is True
            sessions = manager.records['2025-01-15']['sessions']
            assert len(sessions) == 1
            assert 'check_out' not in sessions[0]

    def test_set_day_sessions_rejects_two_open_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.set_day_sessions('2025-01-15', [
                {'check_in': '09:00', 'check_out': None},
                {'check_in': '17:00', 'check_out': None},
            ])
            assert result.success is False

    def test_set_day_sessions_can_edit_closed_session_while_one_is_open(self):
        """午前中に確定したセッションを、夕方の進行中セッションを保持したまま編集できる"""
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.set_day_sessions('2025-01-15', [
                {'check_in': '10:00', 'check_out': '12:00'},
                {'check_in': '17:00', 'check_out': None},
            ])

            result = manager.set_day_sessions('2025-01-15', [
                {'check_in': '10:30', 'check_out': '12:30'},  # 修正
                {'check_in': '17:00', 'check_out': None},      # 進行中はそのまま
            ])

            assert result.success is True
            sessions = manager.records['2025-01-15']['sessions']
            assert len(sessions) == 2
            assert sessions[0]['check_in'].strftime('%H:%M') == '10:30'
            assert sessions[0]['check_out'].strftime('%H:%M') == '12:30'
            assert 'check_out' not in sessions[1]
            assert sessions[1]['check_in'].strftime('%H:%M') == '17:00'

    def test_set_day_sessions_next_day_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            result = manager.set_day_sessions('2025-01-15', [
                {'check_in': '22:00', 'check_out': '07:00', 'check_out_next_day': True},
            ])

            assert result.success is True
            session = manager.records['2025-01-15']['sessions'][0]
            assert session['check_out'].date().isoformat() == '2025-01-16'

    def test_set_day_sessions_replaces_breaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.set_day_sessions(
                '2025-01-15',
                [{'check_in': '09:00', 'check_out': '18:00'}],
                breaks=[{'start': '12:00', 'end': '13:00'}],
            )
            result = manager.set_day_sessions(
                '2025-01-15',
                [{'check_in': '09:00', 'check_out': '18:00'}],
            )
            assert result.success is True
            assert 'breaks' not in manager.records['2025-01-15']


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
            manager.records['2026-04-04'] = make_day([(ci, None)])
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
            manager.records['2026-04-04'] = make_day([(ci, None)], breaks=[{'start': bs}])
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
            manager.records['2026-04-04'] = make_day([(ci, co)], breaks=[{'start': bs, 'end': be}])
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
            manager.records['2026-04-04'] = make_day([(ci, None)])
            ref = datetime(2026, 4, 4, 10, 30, 0, tzinfo=JST)
            result = manager.get_today_status(reference_time=ref)

            assert result['elapsed_seconds'] == 5400  # 1.5h exactly


class TestMultiSession:
    def test_second_clock_in_after_out_appends_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.clock_in()
            manager.clock_out()
            manager.clock_in()
            result = manager.clock_out()

            today = manager._get_date_key(manager._get_current_jst_time())
            assert result.success is True
            assert len(manager.records[today]['sessions']) == 2
            assert all('check_out' in s for s in manager.records[today]['sessions'])

    def test_find_open_session_returns_correct_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            now = datetime(2025, 1, 10, 20, 0, 0, tzinfo=JST)
            manager.records['2025-01-10'] = make_day([
                (datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST), datetime(2025, 1, 10, 12, 0, 0, tzinfo=JST)),
                (datetime(2025, 1, 10, 17, 0, 0, tzinfo=JST), None),
            ])

            found = manager._find_open_session(now)

            assert found is not None
            date_key, idx, check_in_time = found
            assert date_key == '2025-01-10'
            assert idx == 1
            assert check_in_time.hour == 17

    def test_get_today_status_multi_session_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2026-04-04'] = make_day([
                (datetime(2026, 4, 4, 10, 0, 0, tzinfo=JST), datetime(2026, 4, 4, 12, 0, 0, tzinfo=JST)),
                (datetime(2026, 4, 4, 17, 0, 0, tzinfo=JST), datetime(2026, 4, 4, 22, 0, 0, tzinfo=JST)),
            ])
            ref = datetime(2026, 4, 4, 23, 0, 0, tzinfo=JST)
            result = manager.get_today_status(reference_time=ref)

            assert result['state'] == '退勤済み'
            assert result['elapsed_seconds'] == 2 * 3600 + 5 * 3600
            assert result['check_in'].hour == 10
            assert result['check_out'].hour == 22

    def test_get_today_status_multi_session_open_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2026-04-04'] = make_day([
                (datetime(2026, 4, 4, 10, 0, 0, tzinfo=JST), datetime(2026, 4, 4, 12, 0, 0, tzinfo=JST)),
                (datetime(2026, 4, 4, 17, 0, 0, tzinfo=JST), None),
            ])
            ref = datetime(2026, 4, 4, 18, 0, 0, tzinfo=JST)
            result = manager.get_today_status(reference_time=ref)

            assert result['state'] == '出勤中'
            assert result['elapsed_seconds'] == 2 * 3600 + 1 * 3600


# ---------------------------------------------------------------------------
# TestForgottenClockOut (新機能)
# ---------------------------------------------------------------------------

class TestForgottenClockOut:
    def test_昨日の未退勤がある場合にneeds_confirmationがTrue(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            yesterday = (datetime.now(JST) - timedelta(days=1)).date().isoformat()
            manager.records[yesterday] = make_day([(datetime.now(JST) - timedelta(hours=14), None)])
            result = manager.clock_in()

            assert result.success is False
            assert result.needs_confirmation is True
            assert yesterday in result.message

    def test_force_Trueで未退勤があっても出勤記録される(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            yesterday = (datetime.now(JST) - timedelta(days=1)).date().isoformat()
            manager.records[yesterday] = make_day([(datetime.now(JST) - timedelta(hours=14), None)])
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
            manager.records['2026-03-30'] = make_day([
                (datetime(2026, 3, 30, 9, 0, 0, tzinfo=JST), datetime(2026, 3, 30, 18, 0, 0, tzinfo=JST)),
            ])
            manager.records['2026-03-31'] = make_day([
                (datetime(2026, 3, 31, 9, 0, 0, tzinfo=JST), datetime(2026, 3, 31, 18, 0, 0, tzinfo=JST)),
            ])
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
            manager.records['2026-03-31'] = make_day([
                (datetime(2026, 3, 31, 9, 0, 0, tzinfo=JST), datetime(2026, 3, 31, 18, 0, 0, tzinfo=JST)),
            ])
            manager.records['2026-04-01'] = make_day([
                (datetime(2026, 4, 1, 9, 0, 0, tzinfo=JST), datetime(2026, 4, 1, 18, 0, 0, tzinfo=JST)),
            ])
            ref = datetime(2026, 4, 1, 12, 0, 0, tzinfo=JST)
            result = manager.get_weekly_summary(date=ref)

            assert result['work_days'] == 2  # 3月と4月の両方が含まれる

    def test_date引数でその週を指定(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2026-03-30'] = make_day([
                (datetime(2026, 3, 30, 9, 0, 0, tzinfo=JST), datetime(2026, 3, 30, 18, 0, 0, tzinfo=JST)),
            ])
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
            manager.records['2025-01-10'] = make_day([
                (datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST), datetime(2025, 1, 10, 18, 0, 0, tzinfo=JST)),  # 9時間勤務
            ])
            result = manager.get_monthly_summary('2025-01', scheduled_hours=8.0)

            assert result['overtime_seconds'] == 3600  # 1時間残業

    def test_残業なし_マイナス(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2025-01-10'] = make_day([
                (datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST), datetime(2025, 1, 10, 16, 0, 0, tzinfo=JST)),  # 7時間勤務
            ])
            result = manager.get_monthly_summary('2025-01', scheduled_hours=8.0)

            assert result['overtime_seconds'] == -3600  # 1時間不足

    def test_scheduled_secondsは日数x所定時間(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            for day in ['2025-01-08', '2025-01-09']:
                manager.records[day] = make_day([
                    (
                        datetime(2025, 1, int(day[-2:]), 9, 0, 0, tzinfo=JST),
                        datetime(2025, 1, int(day[-2:]), 18, 0, 0, tzinfo=JST),
                    ),
                ])
            result = manager.get_monthly_summary('2025-01', scheduled_hours=8.0)

            assert result['scheduled_seconds'] == 8 * 3600 * 2

    def test_デフォルト所定時間は8時間(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2025-01-10'] = make_day([
                (datetime(2025, 1, 10, 9, 0, 0, tzinfo=JST), datetime(2025, 1, 10, 17, 0, 0, tzinfo=JST)),
            ])
            result = manager.get_monthly_summary('2025-01')

            assert result['scheduled_hours'] == 8.0


# ---------------------------------------------------------------------------
# TestExportCSV (新機能)
# ---------------------------------------------------------------------------

class TestExportCSV:
    def _make_manager_with_jan_data(self, tmp):
        manager = make_manager(tmp)
        manager.records['2025-01-08'] = make_day([
            (datetime(2025, 1, 8, 9, 0, 0, tzinfo=JST), datetime(2025, 1, 8, 18, 0, 0, tzinfo=JST)),
        ])
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


class TestExportCSVMultiSession:
    def test_export_includes_sessions_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2025-01-08'] = make_day([
                (datetime(2025, 1, 8, 10, 0, 0, tzinfo=JST), datetime(2025, 1, 8, 12, 0, 0, tzinfo=JST)),
                (datetime(2025, 1, 8, 17, 0, 0, tzinfo=JST), datetime(2025, 1, 8, 22, 0, 0, tzinfo=JST)),
            ])
            csv_str = manager.export_monthly_csv('2025-01')
            data_line = csv_str.splitlines()[1]

            assert '10:00-12:00' in data_line
            assert '17:00-22:00' in data_line


class TestGetMonthDays:
    def test_includes_all_days_and_open_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = make_manager(tmp)
            manager.records['2025-02-10'] = make_day([
                (datetime(2025, 2, 10, 9, 0, 0, tzinfo=JST), None),
            ])
            days = manager.get_month_days('2025-02')

            assert len(days) == 28  # 2025年2月は28日
            day10 = next(d for d in days if d['date'] == '2025-02-10')
            assert day10['is_open'] is True
            assert day10['duration_seconds'] is None

            day01 = next(d for d in days if d['date'] == '2025-02-01')
            assert day01['sessions'] == []
