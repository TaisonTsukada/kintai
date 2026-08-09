"""CLI 統合テスト"""

import tempfile
from datetime import datetime

import pytz
from click.testing import CliRunner

from kintai import KintaiManager, cli


JST = pytz.timezone('Asia/Tokyo')


class TestCLIInterface:
    def test_in_command(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['in'], env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code == 0
            assert "出勤時刻を記録しました:" in result.output

    def test_out_command(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            result = runner.invoke(cli, ['out'], env=env)
            assert result.exit_code == 0
            assert "退勤時刻を記録しました:" in result.output
            assert "本日の勤務時間:" in result.output

    def test_help_command(self):
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])
        assert result.exit_code == 0
        assert "勤怠管理CLIツール" in result.output
        assert "Commands:" in result.output

    def test_in_out_integration(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            in_result = runner.invoke(cli, ['in'], env=env)
            out_result = runner.invoke(cli, ['out'], env=env)
            assert in_result.exit_code == 0
            assert out_result.exit_code == 0
            assert "本日の勤務時間:" in out_result.output


class TestMultiSessionCLI:
    def test_two_in_out_cycles_create_two_sessions(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            runner.invoke(cli, ['out'], env=env)
            runner.invoke(cli, ['in'], env=env)
            result = runner.invoke(cli, ['out'], env=env)

            assert result.exit_code == 0
            manager = KintaiManager(tmp)
            today = datetime.now(JST).date().isoformat()
            assert len(manager.records[today]['sessions']) == 2

    def test_second_in_same_day_without_out_is_blocked(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            result = runner.invoke(cli, ['in'], env=env)

            assert "既に出勤中です" in result.output
            manager = KintaiManager(tmp)
            today = datetime.now(JST).date().isoformat()
            assert len(manager.records[today]['sessions']) == 1


class TestBreakTimeCLI:
    def test_break_start_command(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            result = runner.invoke(cli, ['break', 'start'], env=env)
            assert result.exit_code == 0
            assert "休憩を開始しました" in result.output

    def test_break_end_command(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            runner.invoke(cli, ['break', 'start'], env=env)
            result = runner.invoke(cli, ['break', 'end'], env=env)
            assert result.exit_code == 0
            assert "休憩を終了しました" in result.output
            assert "休憩時間:" in result.output

    def test_break_no_subcommand_blocks_then_stops_on_interrupt(self, monkeypatch):
        # kintai.cli モジュール名と `from .cli import cli` で束縛される Group が
        # 同名のため、`import kintai.cli as x` は属性探索の都合で Group を返してしまう。
        # sys.modules から直接モジュールを取得する。
        import sys
        cli_module = sys.modules['kintai.cli']

        def fake_wait_forever():
            raise KeyboardInterrupt()

        monkeypatch.setattr(cli_module, '_wait_forever', fake_wait_forever)

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            result = runner.invoke(cli, ['break'], env=env)

            assert result.exit_code == 0
            assert "休憩を開始しました" in result.output
            assert "休憩中" in result.output
            assert "休憩を終了しました" in result.output

            manager = KintaiManager(tmp)
            today = datetime.now(JST).date().isoformat()
            breaks = manager.records[today]['breaks']
            assert len(breaks) == 1
            assert 'start' in breaks[0] and 'end' in breaks[0]

    def test_break_no_subcommand_without_clock_in_fails(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['break'], env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code != 0
            assert "本日の出勤記録がありません" in result.output


class TestEditCommandCLI:
    def test_edit_command_with_options(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            runner.invoke(cli, ['out'], env=env)
            today = datetime.now(JST).date().isoformat()
            result = runner.invoke(cli, ['edit', '--date', today, '--in', '09:30', '--out', '19:00'], env=env)
            assert result.exit_code == 0
            assert "記録を更新しました" in result.output

    def test_edit_invalid_date_format(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['edit', '--date', 'invalid', '--in', '09:00'],
                                   env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code != 0
            assert "日付の形式が正しくありません" in result.output

    def test_edit_nonexistent_record(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['edit', '--date', '2025-01-10', '--in', '09:00'],
                                   env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code != 0
            assert "指定された日付の記録が見つかりません" in result.output

    def test_edit_interactive_mode(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            runner.invoke(cli, ['out'], env=env)
            today = datetime.now(JST).date().isoformat()
            result = runner.invoke(cli, ['edit', '--date', today], input='10:00\n19:00\n', env=env)
            assert result.exit_code == 0
            assert "記録を更新しました" in result.output
            assert "現在の記録:" in result.output

    def test_edit_interactive_no_changes(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            today = datetime.now(JST).date().isoformat()
            result = runner.invoke(cli, ['edit', '--date', today], input='\n\n', env=env)
            assert result.exit_code == 0
            assert "変更はありませんでした" in result.output

    def test_edit_command_with_multiple_session_options(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['new', '--date', '2025-01-15', '--in', '09:00', '--out', '18:00'], env=env)
            result = runner.invoke(
                cli,
                ['edit', '--date', '2025-01-15', '--session', '10:00-12:00', '--session', '17:00-22:00'],
                env=env,
            )
            assert result.exit_code == 0

            manager = KintaiManager(tmp)
            sessions = manager.records['2025-01-15']['sessions']
            assert len(sessions) == 2


class TestDeleteCommandCLI:
    def test_delete_with_confirmation_yes(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            today = datetime.now(JST).date().isoformat()
            result = runner.invoke(cli, ['delete', '--date', today], input='y\n', env=env)
            assert result.exit_code == 0
            assert "記録を削除しました" in result.output

    def test_delete_with_confirmation_no(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            today = datetime.now(JST).date().isoformat()
            result = runner.invoke(cli, ['delete', '--date', today], input='n\n', env=env)
            assert result.exit_code == 0
            assert "削除をキャンセルしました" in result.output


class TestNewCommandCLI:
    def test_new_command_creates_record(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['new', '--date', '2025-01-15', '--in', '09:00', '--out', '18:00'],
                                   env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code == 0
            assert "2025-01-15の記録を作成しました" in result.output

    def test_new_command_invalid_date(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['new', '--date', 'bad-date', '--in', '09:00', '--out', '18:00'],
                                   env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code != 0
            assert "日付の形式が正しくありません" in result.output

    def test_new_command_invalid_time(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['new', '--date', '2025-01-15', '--in', 'bad', '--out', '18:00'],
                                   env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code != 0
            assert "時刻の形式が正しくありません" in result.output

    def test_new_command_duplicate_record(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['new', '--date', '2025-01-15', '--in', '09:00', '--out', '18:00'], env=env)
            result = runner.invoke(cli, ['new', '--date', '2025-01-15', '--in', '10:00', '--out', '19:00'], env=env)
            assert result.exit_code != 0
            assert "既に記録が存在します" in result.output

    def test_new_command_invalid_time_order(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['new', '--date', '2025-01-15', '--in', '18:00', '--out', '09:00'],
                                   env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code != 0
            assert "退勤時刻が出勤時刻より早くなっています" in result.output

    def test_new_command_missing_required_options(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['new', '--date', '2025-01-15'], env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code != 0
            assert "--in/--out または --session を指定してください" in result.output

    def test_new_command_with_comma_separated_sessions(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            result = runner.invoke(
                cli,
                ['new', '--date', '2025-01-15', '--session', '10:00~12:00,17:00~22:00, 22:30~23:30'],
                env=env,
            )
            assert result.exit_code == 0

            manager = KintaiManager(tmp)
            sessions = manager.records['2025-01-15']['sessions']
            assert len(sessions) == 3
            assert sessions[0]['check_in'].strftime('%H:%M') == '10:00'
            assert sessions[2]['check_out'].strftime('%H:%M') == '23:30'

    def test_new_command_with_session_option_rejects_existing_record(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['new', '--date', '2025-01-15', '--in', '09:00', '--out', '18:00'], env=env)
            result = runner.invoke(
                cli, ['new', '--date', '2025-01-15', '--session', '10:00-12:00'], env=env
            )
            assert result.exit_code != 0
            assert "既に記録が存在します" in result.output


class TestSummaryCommandCLI:
    def test_summary_command_displays_report(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            manager = KintaiManager(tmp)
            manager.records['2025-01-08'] = {
                'sessions': [{
                    'check_in': datetime(2025, 1, 8, 9, 0, 0, tzinfo=JST),
                    'check_out': datetime(2025, 1, 8, 18, 30, 0, tzinfo=JST),
                }],
            }
            manager.save_to_file()
            result = runner.invoke(cli, ['summary', '--month', '2025-01'], env=env)
            assert result.exit_code == 0
            assert "2025年1月の勤怠記録" in result.output
            assert "総勤務時間:" in result.output
            assert "勤務日数:" in result.output

    def test_summary_with_copy_flag(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['summary', '--month', '2025-01', '--copy'],
                                   env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code == 0
            assert "クリップボードにコピーしました" in result.output

    def test_summary_with_work_hours(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            manager = KintaiManager(tmp)
            manager.records['2025-01-08'] = {
                'sessions': [{
                    'check_in': datetime(2025, 1, 8, 9, 0, 0, tzinfo=JST),
                    'check_out': datetime(2025, 1, 8, 18, 0, 0, tzinfo=JST),
                }],
            }
            manager.save_to_file()
            result = runner.invoke(cli, ['summary', '--month', '2025-01', '--work-hours', '8'], env=env)
            assert result.exit_code == 0
            assert "残業時間:" in result.output


class TestTodayCommandCLI:
    def test_today_command_shows_state(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['today'], env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code == 0
            assert "状態:" in result.output

    def test_today_command_after_clock_in(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            result = runner.invoke(cli, ['today'], env=env)
            assert result.exit_code == 0
            assert "出勤中" in result.output
            assert "出勤時刻:" in result.output

    def test_today_command_shows_sessions_when_multiple(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            runner.invoke(cli, ['in'], env=env)
            runner.invoke(cli, ['out'], env=env)
            runner.invoke(cli, ['in'], env=env)
            result = runner.invoke(cli, ['today'], env=env)
            assert result.exit_code == 0
            assert "セッション:" in result.output


class TestWeekCommandCLI:
    def test_week_command(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['week'], env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code == 0

    def test_week_command_with_data(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            manager = KintaiManager(tmp)
            today = datetime.now(JST).date().isoformat()
            manager.records[today] = {
                'sessions': [{
                    'check_in': datetime.now(JST).replace(hour=9, minute=0, second=0),
                    'check_out': datetime.now(JST).replace(hour=18, minute=0, second=0),
                }],
            }
            manager.save_to_file()
            result = runner.invoke(cli, ['week'], env=env)
            assert result.exit_code == 0
            assert "勤務日数:" in result.output


class TestExportCommandCLI:
    def test_export_stdout(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            manager = KintaiManager(tmp)
            manager.records['2025-01-08'] = {
                'sessions': [{
                    'check_in': datetime(2025, 1, 8, 9, 0, 0, tzinfo=JST),
                    'check_out': datetime(2025, 1, 8, 18, 0, 0, tzinfo=JST),
                }],
            }
            manager.save_to_file()
            result = runner.invoke(cli, ['export', '--month', '2025-01'], env=env)
            assert result.exit_code == 0
            assert '日付' in result.output
            assert '2025-01-08' in result.output

    def test_export_to_file(self):
        import os
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {'KINTAI_DATA_DIR': tmp}
            manager = KintaiManager(tmp)
            manager.records['2025-01-08'] = {
                'sessions': [{
                    'check_in': datetime(2025, 1, 8, 9, 0, 0, tzinfo=JST),
                    'check_out': datetime(2025, 1, 8, 18, 0, 0, tzinfo=JST),
                }],
            }
            manager.save_to_file()
            out_path = os.path.join(tmp, 'output.csv')
            result = runner.invoke(cli, ['export', '--month', '2025-01', '--output', out_path], env=env)
            assert result.exit_code == 0
            assert "保存しました" in result.output
            assert os.path.exists(out_path)

    def test_export_invalid_month(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ['export', '--month', 'invalid'], env={'KINTAI_DATA_DIR': tmp})
            assert result.exit_code != 0
