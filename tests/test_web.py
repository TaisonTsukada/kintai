"""Flask Web UI 統合テスト"""

from datetime import datetime

import pytz

from kintai import KintaiManager
from kintai.web.app import _serialize_day, create_app

JST = pytz.timezone('Asia/Tokyo')


def test_index_shows_all_days_including_open_session(tmp_path):
    manager = KintaiManager(str(tmp_path))
    manager.set_day_sessions('2025-01-08', [{'check_in': '09:00', 'check_out': '18:00'}])
    manager.records['2025-01-09'] = {
        'sessions': [{'check_in': datetime(2025, 1, 9, 9, 0, 0, tzinfo=JST)}],
    }
    manager.save_to_file()

    client = create_app(manager).test_client()
    resp = client.get('/?month=2025-01')

    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert '2025-01-08' in body
    assert '2025-01-09' in body
    assert '進行中' in body  # 未退勤のセッションも表示される


def test_get_day_returns_next_day_flag_for_overnight_session(tmp_path):
    manager = KintaiManager(str(tmp_path))
    manager.records['2025-01-10'] = {
        'sessions': [{
            'check_in': datetime(2025, 1, 10, 22, 0, 0, tzinfo=JST),
            'check_out': datetime(2025, 1, 11, 7, 0, 0, tzinfo=JST),
        }],
    }
    manager.save_to_file()

    client = create_app(manager).test_client()
    resp = client.get('/api/day/2025-01-10')

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['sessions'][0]['check_out'] == '07:00'
    assert data['sessions'][0]['check_out_next_day'] is True


def test_save_day_endpoint_persists_sessions(tmp_path):
    manager = KintaiManager(str(tmp_path))
    client = create_app(manager).test_client()

    resp = client.post('/api/day/2025-01-08', json={
        'sessions': [
            {'check_in': '10:00', 'check_out': '12:00'},
            {'check_in': '17:00', 'check_out': '22:00'},
        ],
        'breaks': [],
    })

    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    assert len(manager.records['2025-01-08']['sessions']) == 2


def test_overnight_session_round_trips_through_save(tmp_path):
    """GETで得たcheck_out_next_dayフラグ付きのセッションをそのままPOSTしても、
    日をまたぐ退勤時刻が消えたりずれたりしないことを確認する（保存の全置換契約の検証）。"""
    manager = KintaiManager(str(tmp_path))
    manager.set_day_sessions('2025-01-15', [
        {'check_in': '22:00', 'check_out': '07:00', 'check_out_next_day': True},
    ])

    payload = _serialize_day(manager, '2025-01-15')
    assert payload['sessions'][0]['check_out_next_day'] is True

    result = manager.set_day_sessions(
        '2025-01-15', payload['sessions'], breaks=payload['breaks']
    )

    assert result.success is True
    session = manager.records['2025-01-15']['sessions'][0]
    assert session['check_out'].date().isoformat() == '2025-01-16'
    assert session['check_out'].strftime('%H:%M') == '07:00'


def test_save_day_allows_single_open_session(tmp_path):
    """出勤中の日でも保存できる（進行中セッションが1件までなら許容する）"""
    manager = KintaiManager(str(tmp_path))
    client = create_app(manager).test_client()

    resp = client.post('/api/day/2025-01-08', json={
        'sessions': [{'check_in': '10:00', 'check_out': None}],
    })

    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    assert 'check_out' not in manager.records['2025-01-08']['sessions'][0]


def test_save_day_rejects_two_open_sessions(tmp_path):
    manager = KintaiManager(str(tmp_path))
    client = create_app(manager).test_client()

    resp = client.post('/api/day/2025-01-08', json={
        'sessions': [
            {'check_in': '10:00', 'check_out': None},
            {'check_in': '17:00', 'check_out': None},
        ],
    })

    assert resp.status_code == 400
    assert resp.get_json()['success'] is False


def test_save_day_edits_closed_session_while_one_is_open(tmp_path):
    """出勤中の日でも、確定済みの過去セッションだけを直して保存できる"""
    manager = KintaiManager(str(tmp_path))
    manager.set_day_sessions('2025-01-08', [
        {'check_in': '10:00', 'check_out': '12:00'},
        {'check_in': '17:00', 'check_out': None},
    ])
    client = create_app(manager).test_client()

    resp = client.post('/api/day/2025-01-08', json={
        'sessions': [
            {'check_in': '10:30', 'check_out': '12:30'},
            {'check_in': '17:00', 'check_out': None},
        ],
    })

    assert resp.status_code == 200
    sessions = manager.records['2025-01-08']['sessions']
    assert sessions[0]['check_in'].strftime('%H:%M') == '10:30'
    assert 'check_out' not in sessions[1]


def test_index_shows_monthly_summary(tmp_path):
    manager = KintaiManager(str(tmp_path))
    manager.set_day_sessions(
        '2025-01-08',
        [{'check_in': '09:00', 'check_out': '18:00'}],
        breaks=[{'start': '12:00', 'end': '13:00'}],
    )
    manager.set_day_sessions('2025-01-09', [{'check_in': '10:00', 'check_out': '15:00'}])

    client = create_app(manager).test_client()
    body = client.get('/?month=2025-01').data.decode('utf-8')

    assert '月次サマリー' in body
    assert '2日' in body  # 勤務日数
    assert KintaiManager._format_duration_message(14 * 3600) in body  # 総勤務 9h + 5h
    assert KintaiManager._format_duration_message(3600) in body  # 総休憩
    assert KintaiManager._format_duration_message(13 * 3600) in body  # 実勤務
    assert '集計に含まれません' not in body  # 進行中の日がなければ注記は出ない


def test_index_notes_open_day_excluded_from_summary(tmp_path):
    manager = KintaiManager(str(tmp_path))
    manager.set_day_sessions('2025-01-08', [{'check_in': '09:00', 'check_out': '18:00'}])
    manager.records['2025-01-09'] = {
        'sessions': [{'check_in': datetime(2025, 1, 9, 9, 0, 0, tzinfo=JST)}],
    }
    manager.save_to_file()

    client = create_app(manager).test_client()
    body = client.get('/?month=2025-01').data.decode('utf-8')

    assert '集計に含まれません' in body
    assert '1日' in body  # 進行中の日は勤務日数に入らない
    assert KintaiManager._format_duration_message(9 * 3600) in body


def test_index_normalizes_unpadded_month(tmp_path):
    """'2025-1' が 2025-10〜12 まで巻き込んで集計しないこと。"""
    manager = KintaiManager(str(tmp_path))
    manager.set_day_sessions('2025-01-08', [{'check_in': '09:00', 'check_out': '18:00'}])
    manager.set_day_sessions('2025-10-08', [{'check_in': '09:00', 'check_out': '20:00'}])

    client = create_app(manager).test_client()
    body = client.get('/?month=2025-1').data.decode('utf-8')

    assert KintaiManager._format_duration_message(9 * 3600) in body
    assert KintaiManager._format_duration_message(20 * 3600) not in body  # 9h + 11h
