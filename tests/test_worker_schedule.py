from datetime import datetime, timezone

import worker


def test_daily_scan_runs_at_eight_lithuania_time_in_winter():
    result = worker.next_daily_scan(datetime(2026, 1, 15, 5, 0, tzinfo=timezone.utc))
    assert result == datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc)


def test_daily_scan_runs_at_eight_lithuania_time_in_summer():
    result = worker.next_daily_scan(datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc))
    assert result == datetime(2026, 7, 16, 5, 0, tzinfo=timezone.utc)


def test_weekly_scan_runs_next_monday_at_eight_lithuania_time():
    # Monday 2026-11-09 07:00 UTC is after 08:00 Vilnius (06:00 UTC) -> next Monday
    result = worker.next_daily_scan(datetime(2026, 11, 9, 7, 0, tzinfo=timezone.utc), "weekly", 0)
    assert result == datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)


def test_weekly_scan_same_monday_when_before_send_hour():
    result = worker.next_daily_scan(datetime(2026, 11, 9, 5, 0, tzinfo=timezone.utc), "weekly", 0)
    assert result == datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc)
