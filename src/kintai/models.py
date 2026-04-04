"""データモデル定義"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ClockResult:
    """出退勤・休憩操作の結果を格納するデータクラス"""
    success: bool
    message: str
    timestamp: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    needs_confirmation: bool = False
