import config
import db


def test_initial_daily_scan_subscribers_are_seeded():
    assert set(config.INITIAL_DAILY_SCAN_RECIPIENTS) == {"kaljuvee@gmail.com", "mj@1am.lt"}
    assert "newsletter_subscribers" in db.DDL
