"""clock.epoch: local stamps without an offset, read back in the hour that repeats when daylight saving ends (2026-11-01)."""
import time

import pytest

from gameanything import clock


@pytest.fixture
def los_angeles(monkeypatch):
    if not hasattr(time, "tzset"): pytest.skip("time.tzset is POSIX only")
    monkeypatch.setenv("TZ", "America/Los_Angeles"); time.tzset()
    if time.timezone != 8 * 3600:                     # no time zone database here (a slim container): TZ fell back to UTC
        monkeypatch.undo(); time.tzset(); pytest.skip("America/Los_Angeles is not in this system's time zone database")
    yield
    monkeypatch.undo(); time.tzset()


def test_offset_stamps_are_exact():
    assert clock.epoch("2026-11-01T09:12:39+00:00") == 1793524359


def test_the_repeated_hour_reads_as_the_recent_moment(los_angeles):
    pst = 1793524359                                           # 2026-11-01 01:12:39 PST, the second pass of 01:00-02:00
    assert clock.epoch("2026-11-01T01:12:30", now=pst) == pst - 9                 # written 9 s ago, not an hour and 9 s
    assert clock.epoch("2026-11-01T01:12:30", now=pst - 3600) == pst - 3609       # during the first pass (PDT): the PDT moment
    assert clock.epoch("2026-11-01T03:00:00", now=pst) == clock.epoch("2026-11-01T03:00:00", now=0)   # not ambiguous: `now` plays no part


def test_not_a_stamp():
    for bad in (None, "", "yesterday"):
        with pytest.raises(ValueError): clock.epoch(bad)
