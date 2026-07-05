import pytest

from proteo.core.guard import Debouncer, Observation, decide


def test_no_session_never_restores():
    assert decide(Observation(session=False, hold_active=False,
                              host_active=False)) is None


def test_healthy_session_left_alone():
    assert decide(Observation(session=True, hold_active=True,
                              host_active=True)) is None


def test_dead_hold_restores():
    assert decide(Observation(session=True, hold_active=False,
                              host_active=True)) is not None


def test_dead_host_restores():
    assert decide(Observation(session=True, hold_active=True,
                              host_active=False)) is not None


def test_debouncer_requires_consecutive_hits():
    d = Debouncer(2)
    assert d.update(True) is False     # first hit: could be a reshape window
    assert d.update(True) is True      # second consecutive: act
    assert d.update(False) is False    # reset
    assert d.update(True) is False     # streak starts over


def test_debouncer_threshold_one_acts_immediately():
    assert Debouncer(1).update(True) is True


def test_debouncer_rejects_bad_threshold():
    with pytest.raises(ValueError):
        Debouncer(0)
