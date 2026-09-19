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


# --------------------------------------------------------------------------
# Steam quiet watcher — when it is safe to rewrite launch options
# --------------------------------------------------------------------------

def test_steam_watcher_waits_out_the_delay():
    from proteo.core.guard import SteamQuietWatcher
    w = SteamQuietWatcher(delay=20)
    assert w.update(True, 0) is False          # Steam running
    assert w.update(False, 100) is False       # just closed: its exit write
    assert w.update(False, 115) is False       # still inside the delay
    assert w.update(False, 120) is True        # safe now


def test_steam_watcher_fires_once_per_session():
    from proteo.core.guard import SteamQuietWatcher
    w = SteamQuietWatcher(delay=10)
    w.update(False, 0)
    assert w.update(False, 10) is True
    assert w.update(False, 20) is False        # no rewrite loop
    # a new Steam session re-arms it: games may have been installed
    w.update(True, 30)
    w.update(False, 40)
    assert w.update(False, 50) is True


def test_steam_watcher_starts_with_steam_already_closed():
    from proteo.core.guard import SteamQuietWatcher
    w = SteamQuietWatcher(delay=5)
    assert w.update(False, 1000) is False      # clock starts at first sighting
    assert w.update(False, 1005) is True


def test_steam_watcher_rejects_a_negative_delay():
    import pytest

    from proteo.core.guard import SteamQuietWatcher
    with pytest.raises(ValueError):
        SteamQuietWatcher(delay=-1)
