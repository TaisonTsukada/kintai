import pytest
from datetime import datetime, timedelta
import pytz
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from kintai import KintaiManager


class TestKintaiBasics:
    def test_clock_in_records_current_time(self):
        """出勤記録が現在時刻（JST）で記録されることをテスト"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # 空のマネージャーを作成
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = Path(temp_dir) / "test.json"
            manager.JST = pytz.timezone('Asia/Tokyo')
            manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
            
            # テスト実行前の時刻を記録
            before_time = datetime.now(pytz.timezone('Asia/Tokyo'))
            
            # 出勤記録を実行
            result = manager.clock_in()
            
            # テスト実行後の時刻を記録
            after_time = datetime.now(pytz.timezone('Asia/Tokyo'))
            
            # 結果の検証
            assert result.success is True
            assert result.message == "出勤時刻を記録しました"
            assert before_time <= result.timestamp <= after_time
            assert result.timestamp.tzinfo.zone == 'Asia/Tokyo'
    
    def test_clock_in_twice_same_day_shows_warning(self):
        """同日に2回出勤記録した場合の警告テスト"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # 空のマネージャーを作成
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = Path(temp_dir) / "test.json"
            manager.JST = pytz.timezone('Asia/Tokyo')
            manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
            
            # 1回目の出勤記録
            first_result = manager.clock_in()
            assert first_result.success is True
            
            # 2回目の出勤記録（同日）
            second_result = manager.clock_in()
            assert second_result.success is False
            assert "既に本日の出勤記録があります" in second_result.message


class TestClockOut:
    def test_clock_out_records_current_time_and_calculates_duration(self):
        """退勤記録が現在時刻で記録され、勤務時間が計算されることをテスト"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # 空のマネージャーを作成
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = Path(temp_dir) / "test.json"
            manager.JST = pytz.timezone('Asia/Tokyo')
            manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
            manager.SEARCH_DAYS_BACK = 3
            
            # 先に出勤記録
            clock_in_result = manager.clock_in()
            assert clock_in_result.success is True
            
            # 少し時間を空けて退勤記録
            before_time = datetime.now(pytz.timezone('Asia/Tokyo'))
            clock_out_result = manager.clock_out()
            after_time = datetime.now(pytz.timezone('Asia/Tokyo'))
            
            # 結果の検証
            assert clock_out_result.success is True
            assert "退勤時刻を記録しました" in clock_out_result.message
            assert before_time <= clock_out_result.timestamp <= after_time
            assert clock_out_result.timestamp.tzinfo.zone == 'Asia/Tokyo'
            
            # 勤務時間が計算されていることを確認
            assert clock_out_result.duration_seconds is not None
            assert clock_out_result.duration_seconds >= 0
    
    def test_clock_out_without_clock_in_shows_error(self):
        """出勤記録なしで退勤記録した場合のエラーテスト"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # 空のマネージャーを作成
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = Path(temp_dir) / "test.json"
            manager.JST = pytz.timezone('Asia/Tokyo')
            manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
            manager.SEARCH_DAYS_BACK = 3
            
            # 出勤記録なしで退勤記録
            result = manager.clock_out()
            
            assert result.success is False
            assert "本日の出勤記録がありません。先に 'kintai in' を実行してください。" in result.message
    
    def test_clock_out_calculates_correct_duration(self):
        """退勤時に正確な勤務時間が計算されることをテスト"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # 空のマネージャーを作成
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = Path(temp_dir) / "test.json"
            manager.JST = pytz.timezone('Asia/Tokyo')
            manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
            manager.SEARCH_DAYS_BACK = 3
            
            jst = pytz.timezone('Asia/Tokyo')
            
            # 現在日付で出勤記録をシミュレート（1分前に出勤したことにする）
            now = datetime.now(jst)
            start_time = now - timedelta(minutes=1)
            today = start_time.date().isoformat()
            manager.records[today] = {'check_in': start_time}
            
            # 退勤記録
            result = manager.clock_out()
            
            # 勤務時間が計算されていることを確認
            assert result.success is True
            assert result.duration_seconds is not None
            assert result.duration_seconds >= 60  # 少なくとも60秒（1分）


class TestCrossDateWork:
    def test_cross_date_work_implementation_works(self):
        """日またぎ勤務の実装が正しく動作することをテスト（Green段階）"""
        manager = KintaiManager()
        jst = pytz.timezone('Asia/Tokyo')
        
        # 前日の22:00に出勤記録
        check_in_time = datetime(2025, 1, 10, 22, 0, 0, tzinfo=jst)
        manager.records['2025-01-10'] = {'check_in': check_in_time}
        
        # 現在時刻を翌日の7:00に設定（モック）
        original_method = manager._get_current_jst_time
        manager._get_current_jst_time = lambda: datetime(2025, 1, 11, 7, 0, 0, tzinfo=jst)
        
        # 退勤記録を試行
        result = manager.clock_out()
        
        # 元のメソッドを復元
        manager._get_current_jst_time = original_method
        
        # 実装後は成功するはず
        assert result.success is True
        assert result.duration_seconds == 9 * 3600  # 9時間
        assert "退勤時刻を記録しました" in result.message
    
    def test_cross_date_duration_calculation_works(self):
        """日またぎ勤務の勤務時間計算が正確であることをテスト"""
        manager = KintaiManager()
        jst = pytz.timezone('Asia/Tokyo')
        
        # 22:00に出勤（2025-01-10）
        check_in_time = datetime(2025, 1, 10, 22, 0, 0, tzinfo=jst)
        # 翌日の7:00に退勤（2025-01-11）
        check_out_time = datetime(2025, 1, 11, 7, 0, 0, tzinfo=jst)
        
        # 勤務時間の直接計算をテスト（9時間 = 32400秒）
        duration_seconds = manager._calculate_duration_seconds(check_in_time, check_out_time)
        expected_seconds = 9 * 3600  # 9時間
        assert duration_seconds == expected_seconds
        
        # フォーマットされたメッセージをテスト
        duration_message = manager._format_duration_message(duration_seconds)
        assert duration_message == "9時間0分0秒"
    
    def test_cross_date_work_should_work_after_implementation(self):
        """日またぎ勤務が正しく動作することをテスト（実装後に通るべきテスト）"""
        manager = KintaiManager()
        jst = pytz.timezone('Asia/Tokyo')
        
        # 前日の22:00に出勤記録
        check_in_time = datetime(2025, 1, 10, 22, 0, 0, tzinfo=jst)
        manager.records['2025-01-10'] = {'check_in': check_in_time}
        
        # 現在時刻を翌日の7:00に設定（モック）
        original_method = manager._get_current_jst_time
        manager._get_current_jst_time = lambda: datetime(2025, 1, 11, 7, 0, 0, tzinfo=jst)
        
        # 退勤記録を試行（現在は失敗するが、実装後は成功するべき）
        result = manager.clock_out()
        
        # 元のメソッドを復元
        manager._get_current_jst_time = original_method
        
        # 実装後はこれらのアサーションが通るようになる（Green段階）
        assert result.success is True
        assert result.duration_seconds == 9 * 3600  # 9時間
        assert "退勤時刻を記録しました" in result.message
        
        # 元々は失敗していたが、今は成功するはず


class TestJSONPersistence:
    def test_save_records_to_json_file(self):
        """勤怠記録がJSONファイルに保存されることをテスト（Red段階）"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # テスト用の一時ディレクトリを使用
            test_file_path = Path(temp_dir) / "test_records.json"
            
            # 空のマネージャーを作成
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = test_file_path
            
            jst = pytz.timezone('Asia/Tokyo')
            check_in_time = datetime(2025, 1, 10, 9, 0, 0, tzinfo=jst)
            check_out_time = datetime(2025, 1, 10, 18, 30, 0, tzinfo=jst)
            
            # 出勤記録
            manager.records['2025-01-10'] = {
                'check_in': check_in_time,
                'check_out': check_out_time
            }
            
            # JSONファイルに保存（実装後は成功するはず）
            manager.save_to_file()
            
            # ファイルが作成されていることを確認
            assert test_file_path.exists()
            
            # ファイルの内容を確認
            with open(test_file_path, 'r') as f:
                saved_data = json.load(f)
            
            assert 'records' in saved_data
            assert 'version' in saved_data
            assert saved_data['version'] == '1.0.0'
            assert len(saved_data['records']) == 1
            
            record = saved_data['records'][0]
            assert record['date'] == '2025-01-10'
            assert 'check_in' in record
            assert 'check_out' in record
            assert 'duration_seconds' in record
    
    def test_load_records_from_json_file(self):
        """JSONファイルから勤怠記録が読み込まれることをテスト（Green段階）"""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file_path = Path(temp_dir) / "test_records.json"
            
            # README.mdの仕様に従ったJSONデータを作成
            test_data = {
                "records": [
                    {
                        "date": "2025-01-10",
                        "check_in": "2025-01-10T09:00:15+09:00",
                        "check_out": "2025-01-10T18:30:45+09:00",
                        "duration_seconds": 34230
                    }
                ],
                "version": "1.0.0"
            }
            
            # テストファイルを作成
            with open(test_file_path, 'w') as f:
                json.dump(test_data, f)
            
            # 空のマネージャーを作成（自動読み込みを回避）
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = test_file_path
            
            # JSONファイルから読み込み（実装後は成功するはず）
            manager.load_from_file()
            
            # 記録が正しく読み込まれていることを確認
            assert '2025-01-10' in manager.records
            record = manager.records['2025-01-10']
            assert 'check_in' in record
            assert 'check_out' in record
            
            # 時刻が正しく復元されていることを確認
            assert record['check_in'].year == 2025
            assert record['check_in'].month == 1
            assert record['check_in'].day == 10
            assert record['check_in'].hour == 9
            assert record['check_in'].minute == 0
    
    def test_manager_uses_home_directory_by_default(self):
        """KintaiManagerがデフォルトで~/.kintai/records.jsonを使用することをテスト"""
        manager = KintaiManager()
        
        # ファイルパスが設定されていることを確認（実装後は成功するはず）
        assert manager.data_file_path is not None
        assert str(manager.data_file_path).endswith('.kintai/records.json')
    
    def test_auto_save_on_clock_operations(self):
        """出退勤操作時に自動保存されることをテスト"""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file_path = Path(temp_dir) / "test_records.json"
            
            # 空のマネージャーを作成
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = test_file_path
            # 必要な属性を初期化
            manager.JST = pytz.timezone('Asia/Tokyo')
            manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
            
            # 出勤記録後にファイルが作成されることを確認（まだ実装されていない）
            result = manager.clock_in()
            assert result.success is True
            
            # 実装後はファイルが作成される（Green段階）
            assert test_file_path.exists()
            
            # ファイルの内容を確認
            with open(test_file_path, 'r') as f:
                saved_data = json.load(f)
            
            assert len(saved_data['records']) == 1
            assert saved_data['records'][0]['date'] == result.timestamp.date().isoformat()


class TestEditCommand:
    def test_edit_command_modifies_existing_record(self):
        """編集コマンドが既存の記録を修正することをテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            import pytz
            
            # 先に出勤・退勤記録を作成
            runner.invoke(cli, ['in'], env=env)
            runner.invoke(cli, ['out'], env=env)
            
            # 今日の日付を取得
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst).date().isoformat()
            
            # 編集コマンドを実行（実装後は成功するはず）
            result = runner.invoke(cli, ['edit', '--date', today, '--in', '09:30', '--out', '19:00'], env=env)
            
            assert result.exit_code == 0
            assert "記録を更新しました" in result.output
    
    def test_edit_command_with_invalid_date_format(self):
        """無効な日付形式でのエラーテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # 無効な日付形式で編集コマンドを実行（--inオプション付き）
            result = runner.invoke(cli, ['edit', '--date', 'invalid-date', '--in', '09:00'], env=env)
            
            assert result.exit_code != 0
            assert "日付の形式が正しくありません" in result.output
    
    def test_edit_command_for_nonexistent_record(self):
        """存在しない記録の編集エラーテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # 存在しない日付の編集を試行（--inまたは--outオプションも必要）
            result = runner.invoke(cli, ['edit', '--date', '2025-01-10', '--in', '09:00'], env=env)
            
            assert result.exit_code != 0
            assert "指定された日付の記録が見つかりません" in result.output
    
    def test_edit_command_interactive_mode(self):
        """対話形式での編集コマンドテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            import pytz
            
            # 先に出勤・退勤記録を作成
            runner.invoke(cli, ['in'], env=env)
            runner.invoke(cli, ['out'], env=env)
            
            # 今日の日付を取得
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst).date().isoformat()
            
            # 対話形式で編集（新しい時刻を入力）
            result = runner.invoke(cli, ['edit', '--date', today], input='10:00\n19:00\n', env=env)
            
            assert result.exit_code == 0
            assert "記録を更新しました" in result.output
            assert "現在の記録:" in result.output
    
    def test_edit_command_interactive_mode_no_changes(self):
        """対話形式で変更なしの場合のテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            import pytz
            
            # 先に出勤記録を作成
            runner.invoke(cli, ['in'], env=env)
            
            # 今日の日付を取得
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst).date().isoformat()
            
            # 対話形式で編集（何も入力しない = 変更なし）
            result = runner.invoke(cli, ['edit', '--date', today], input='\n\n', env=env)
            
            assert result.exit_code == 0
            assert "変更はありませんでした" in result.output


class TestDeleteCommand:
    def test_delete_command_removes_record(self):
        """削除コマンドが記録を削除することをテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            import pytz
            
            # 先に出勤記録を作成
            runner.invoke(cli, ['in'], env=env)
            
            # 今日の日付を取得
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst).date().isoformat()
            
            # 削除コマンドを実行（確認プロンプトをyで回答）
            result = runner.invoke(cli, ['delete', '--date', today], input='y\n', env=env)
            
            assert result.exit_code == 0
            assert "記録を削除しました" in result.output
    
    def test_delete_command_with_confirmation_no(self):
        """削除コマンドでNoを選択した場合のテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            import pytz
            
            # 先に出勤記録を作成
            runner.invoke(cli, ['in'], env=env)
            
            # 今日の日付を取得
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst).date().isoformat()
            
            # 削除コマンドを実行（確認プロンプトをnで回答）
            result = runner.invoke(cli, ['delete', '--date', today], input='n\n', env=env)
            
            assert result.exit_code == 0
            assert "削除をキャンセルしました" in result.output


class TestSummaryCommand:
    def test_summary_command_displays_monthly_report(self):
        """サマリーコマンドが月次レポートを表示することをテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # 複数日の出勤・退勤記録を作成（簡略化のため直接マネージャーを使用）
            from kintai import KintaiManager
            manager = KintaiManager(temp_dir)
            jst = manager.JST
            
            # テストデータを作成
            manager.records['2025-01-08'] = {
                'check_in': datetime(2025, 1, 8, 9, 0, 0, tzinfo=jst),
                'check_out': datetime(2025, 1, 8, 18, 30, 0, tzinfo=jst)
            }
            manager.records['2025-01-09'] = {
                'check_in': datetime(2025, 1, 9, 8, 45, 0, tzinfo=jst),
                'check_out': datetime(2025, 1, 9, 19, 15, 0, tzinfo=jst)
            }
            manager.save_to_file()
            
            # サマリーコマンドを実行
            result = runner.invoke(cli, ['summary', '--month', '2025-01'], env=env)
            
            assert result.exit_code == 0
            assert "2025年1月の勤怠記録" in result.output
            assert "総勤務時間:" in result.output
            assert "勤務日数:" in result.output
    
    def test_summary_command_with_copy_flag(self):
        """サマリーコマンドでコピーフラグが動作することをテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # サマリーコマンドをコピーフラグ付きで実行
            result = runner.invoke(cli, ['summary', '--month', '2025-01', '--copy'], env=env)
            
            assert result.exit_code == 0
            assert "クリップボードにコピーしました" in result.output


class TestBreakTime:
    def test_break_start_records_break_time(self):
        """休憩開始が正しく記録されることをテスト（Red段階）"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = Path(temp_dir) / "test.json"
            manager.JST = pytz.timezone('Asia/Tokyo')
            manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
            
            # 先に出勤記録
            clock_in_result = manager.clock_in()
            assert clock_in_result.success is True
            
            # 休憩開始
            break_start_result = manager.break_start()
            
            assert break_start_result.success is True
            assert "休憩を開始しました" in break_start_result.message
            assert break_start_result.timestamp is not None
    
    def test_break_end_calculates_break_duration(self):
        """休憩終了時に休憩時間が計算されることをテスト（Red段階）"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = Path(temp_dir) / "test.json"
            manager.JST = pytz.timezone('Asia/Tokyo')
            manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
            
            # 出勤→休憩開始の流れ
            manager.clock_in()
            manager.break_start()
            
            # 休憩終了
            break_end_result = manager.break_end()
            
            assert break_end_result.success is True
            assert "休憩を終了しました" in break_end_result.message
            assert break_end_result.duration_seconds is not None
            assert break_end_result.duration_seconds >= 0
    
    def test_break_start_without_clock_in_shows_error(self):
        """出勤記録なしで休憩開始した場合のエラーテスト（Red段階）"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = Path(temp_dir) / "test.json"
            manager.JST = pytz.timezone('Asia/Tokyo')
            manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
            
            # 出勤記録なしで休憩開始
            result = manager.break_start()
            
            assert result.success is False
            assert "本日の出勤記録がありません" in result.message
    
    def test_break_end_without_break_start_shows_error(self):
        """休憩開始なしで休憩終了した場合のエラーテスト（Red段階）"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = Path(temp_dir) / "test.json"
            manager.JST = pytz.timezone('Asia/Tokyo')
            manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
            
            # 出勤記録のみ
            manager.clock_in()
            
            # 休憩開始なしで休憩終了
            result = manager.break_end()
            
            assert result.success is False
            assert "現在休憩中ではありません" in result.message
    
    def test_multiple_breaks_in_single_day(self):
        """一日に複数回の休憩を取る場合のテスト（Red段階）"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = Path(temp_dir) / "test.json"
            manager.JST = pytz.timezone('Asia/Tokyo')
            manager.NO_CHECK_IN_MESSAGE = "本日の出勤記録がありません。先に 'kintai in' を実行してください。"
            
            # 出勤
            manager.clock_in()
            
            # 1回目の休憩
            break1_start = manager.break_start()
            break1_end = manager.break_end()
            
            # 2回目の休憩
            break2_start = manager.break_start()
            break2_end = manager.break_end()
            
            assert break1_start.success is True
            assert break1_end.success is True
            assert break2_start.success is True
            assert break2_end.success is True


class TestBreakTimeCLI:
    def test_break_start_command(self):
        """kintai break start コマンドのテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # 先に出勤記録
            runner.invoke(cli, ['in'], env=env)
            
            # 休憩開始コマンドを実行
            result = runner.invoke(cli, ['break', 'start'], env=env)
            
            assert result.exit_code == 0
            assert "休憩を開始しました" in result.output
    
    def test_break_end_command(self):
        """kintai break end コマンドのテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # 出勤→休憩開始の流れ
            runner.invoke(cli, ['in'], env=env)
            runner.invoke(cli, ['break', 'start'], env=env)
            
            # 休憩終了コマンドを実行
            result = runner.invoke(cli, ['break', 'end'], env=env)
            
            assert result.exit_code == 0
            assert "休憩を終了しました" in result.output
            assert "休憩時間:" in result.output


class TestNewCommand:
    def test_new_command_creates_past_record(self):
        """過去の日付の勤怠記録を作成するテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # 過去の日付で新しい記録を作成
            result = runner.invoke(cli, [
                'new', 
                '--date', '2025-01-15', 
                '--in', '09:00', 
                '--out', '18:00'
            ], env=env)
            
            assert result.exit_code == 0
            assert "2025-01-15の記録を作成しました" in result.output
    
    def test_new_command_with_invalid_date_format(self):
        """無効な日付形式でのエラーテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # 無効な日付形式
            result = runner.invoke(cli, [
                'new', 
                '--date', 'invalid-date', 
                '--in', '09:00', 
                '--out', '18:00'
            ], env=env)
            
            assert result.exit_code != 0
            assert "日付の形式が正しくありません" in result.output
    
    def test_new_command_with_invalid_time_format(self):
        """無効な時刻形式でのエラーテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # 無効な時刻形式
            result = runner.invoke(cli, [
                'new', 
                '--date', '2025-01-15', 
                '--in', 'invalid-time', 
                '--out', '18:00'
            ], env=env)
            
            assert result.exit_code != 0
            assert "時刻の形式が正しくありません" in result.output
    
    def test_new_command_with_existing_record_conflict(self):
        """既存記録との競合テスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # 最初の記録を作成
            runner.invoke(cli, [
                'new', 
                '--date', '2025-01-15', 
                '--in', '09:00', 
                '--out', '18:00'
            ], env=env)
            
            # 同じ日付で再度作成を試行
            result = runner.invoke(cli, [
                'new', 
                '--date', '2025-01-15', 
                '--in', '10:00', 
                '--out', '19:00'
            ], env=env)
            
            assert result.exit_code != 0
            assert "既に記録が存在します" in result.output
    
    def test_new_command_with_invalid_time_order(self):
        """退勤時刻が出勤時刻より早い場合のエラーテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # 退勤時刻が出勤時刻より早い
            result = runner.invoke(cli, [
                'new', 
                '--date', '2025-01-15', 
                '--in', '18:00', 
                '--out', '09:00'
            ], env=env)
            
            assert result.exit_code != 0
            assert "退勤時刻が出勤時刻より早くなっています" in result.output
    
    def test_new_command_missing_required_parameters(self):
        """必須パラメータ不足のエラーテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # --date のみ指定（Click が自動でエラーを返す）
            result = runner.invoke(cli, ['new', '--date', '2025-01-15'], env=env)
            
            assert result.exit_code != 0
            assert "Missing option" in result.output


class TestNewCommandKintaiManager:
    def test_create_new_record_method(self):
        """KintaiManagerの新規記録作成メソッドテスト（Red段階）"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = Path(temp_dir) / "test.json"
            manager.JST = pytz.timezone('Asia/Tokyo')
            
            # 新規記録作成
            result = manager.create_new_record('2025-01-15', '09:00', '18:00')
            
            assert result.success is True
            assert "2025-01-15の記録を作成しました" in result.message
            assert '2025-01-15' in manager.records
            assert 'check_in' in manager.records['2025-01-15']
            assert 'check_out' in manager.records['2025-01-15']
    
    def test_create_new_record_with_existing_record(self):
        """既存記録がある場合のエラーテスト（Red段階）"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = KintaiManager.__new__(KintaiManager)
            manager.records = {}
            manager.data_file_path = Path(temp_dir) / "test.json"
            manager.JST = pytz.timezone('Asia/Tokyo')
            
            # 最初の記録を作成
            manager.create_new_record('2025-01-15', '09:00', '18:00')
            
            # 同じ日付で再度作成を試行
            result = manager.create_new_record('2025-01-15', '10:00', '19:00')
            
            assert result.success is False
            assert "既に記録が存在します" in result.message


class TestCLIInterface:
    def test_kintai_in_command(self):
        """kintai in コマンドのテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # 環境変数でテスト用ディレクトリを指定
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            # kintai in コマンドを実行（実装後は成功するはず）
            from kintai import cli
            result = runner.invoke(cli, ['in'], env=env)
            
            # 正常に実行されることを確認
            assert result.exit_code == 0
            assert "出勤時刻を記録しました:" in result.output
    
    def test_kintai_out_command(self):
        """kintai out コマンドのテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # 環境変数でテスト用ディレクトリを指定
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            # kintai out コマンドを実行（実装後は成功するはず）
            from kintai import cli
            
            # 先に出勤記録
            in_result = runner.invoke(cli, ['in'], env=env)
            assert in_result.exit_code == 0
            
            # 退勤記録
            out_result = runner.invoke(cli, ['out'], env=env)
            assert out_result.exit_code == 0
            assert "退勤時刻を記録しました:" in out_result.output
            assert "本日の勤務時間:" in out_result.output
    
    def test_kintai_help_command(self):
        """kintai --help コマンドのテスト（Red段階）"""
        runner = CliRunner()
        
        # ヘルプコマンドを実行（実装後は成功するはず）
        from kintai import cli
        result = runner.invoke(cli, ['--help'])
        
        assert result.exit_code == 0
        assert "勤怠管理CLIツール" in result.output
        assert "Commands:" in result.output
    
    def test_cli_output_format_matches_readme_spec(self):
        """CLI出力がREADME仕様に合致することをテスト（Red段階）"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            # 実装後は成功するはず
            from kintai import cli
            
            # 出勤コマンドの出力をテスト
            result = runner.invoke(cli, ['in'], env=env)
            
            # README.mdの仕様: "出勤時刻を記録しました: 2025-01-10 09:00:15"
            assert result.exit_code == 0
            assert "出勤時刻を記録しました:" in result.output
            assert "2025-" in result.output  # 年が含まれている
            assert ":" in result.output  # 時刻形式
    
    def test_cli_integration_with_manager(self):
        """CLIコマンドがKintaiManagerと正しく連携することをテスト"""
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {'KINTAI_DATA_DIR': temp_dir}
            
            from kintai import cli
            
            # 出勤→退勤の一連の流れをテスト
            in_result = runner.invoke(cli, ['in'], env=env)
            assert in_result.exit_code == 0
            
            out_result = runner.invoke(cli, ['out'], env=env)
            assert out_result.exit_code == 0
            assert "本日の勤務時間:" in out_result.output