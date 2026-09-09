from datetime import datetime, timezone

import worker


def test_daily_scan_runs_at_eight_lithuania_time_in_winter():
    result = worker.next_daily_scan(datetime(2026, 1, 15, 5, 0, tzinfo=timezone.utc))
    assert result == datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc)


def test_daily_scan_runs_at_eight_lithuania_time_in_summer():
    result = worker.next_daily_scan(datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc))
    assert result == datetime(2026, 7, 16, 5, 0, tzinfo=timezone.utc)
