"""kintai web コマンドの Flask アプリ本体。既存の KintaiManager を呼び出す薄いクライアント。"""

import socket
import webbrowser

import click
from flask import Flask, jsonify, render_template, request

from ..manager import KintaiManager


def _serialize_day(manager: KintaiManager, date_str: str) -> dict:
    """1日分の記録を、Web UI編集フォーム用の HH:MM 文字列表現に整形する。"""
    record = manager.records.get(date_str, {})
    sessions = record.get('sessions', [])
    breaks = record.get('breaks', [])
    return {
        'date': date_str,
        'sessions': [
            {
                'check_in': s['check_in'].strftime('%H:%M'),
                'check_out': s['check_out'].strftime('%H:%M') if 'check_out' in s else None,
                'check_out_next_day': (
                    'check_out' in s and s['check_out'].date() != s['check_in'].date()
                ),
            }
            for s in sessions
        ],
        'breaks': [
            {
                'start': b['start'].strftime('%H:%M'),
                'end': b['end'].strftime('%H:%M') if 'end' in b else None,
            }
            for b in breaks
        ],
        'is_open': any('check_out' not in s for s in sessions),
    }


def _shift_month(year_month: str, delta: int) -> str:
    year, month = int(year_month[:4]), int(year_month[5:7])
    month += delta
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return f"{year}-{month:02d}"


def create_app(manager: KintaiManager) -> Flask:
    app = Flask(__name__)
    app.jinja_env.filters['duration'] = KintaiManager._format_duration_message

    @app.get('/')
    def index():
        year_month = request.args.get('month') or manager._get_current_jst_time().strftime('%Y-%m')
        days = manager.get_month_days(year_month)
        return render_template(
            'month.html',
            days=days,
            year_month=year_month,
            prev_month=_shift_month(year_month, -1),
            next_month=_shift_month(year_month, 1),
        )

    @app.get('/api/day/<date_str>')
    def get_day(date_str):
        return jsonify(_serialize_day(manager, date_str))

    @app.post('/api/day/<date_str>')
    def save_day(date_str):
        payload = request.get_json(silent=True) or {}
        result = manager.set_day_sessions(
            date_str,
            payload.get('sessions', []),
            breaks=payload.get('breaks'),
        )
        status_code = 200 if result.success else 400
        return jsonify({'success': result.success, 'message': result.message}), status_code

    return app


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def run_web_server(manager: KintaiManager, port=None, open_browser=True) -> None:
    """Flask開発サーバーをフォアグラウンドで起動する（Ctrl+Cで終了）。"""
    app = create_app(manager)
    port = port or _find_free_port()
    url = f"http://127.0.0.1:{port}/"

    if open_browser:
        webbrowser.open(url)

    click.echo(f"kintai web を起動しました: {url}")
    click.echo("Ctrl+C で終了します。")
    try:
        app.run(host='127.0.0.1', port=port, use_reloader=False)
    except KeyboardInterrupt:
        pass
