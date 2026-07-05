"""org.freedesktop.login1 adapter (system bus, via Gio/PyGObject).

Two jobs, both about never leaving the seat on a dead virtual display across
a suspend cycle:
- a *delay* inhibitor lock, so logind waits for us (up to InhibitDelayMaxSec,
  5 s by default) before actually sleeping;
- the PrepareForSleep signal, so the guard can tear the session down right
  before suspend and re-arm afterwards.
"""

from __future__ import annotations

import gi  # noqa: F401  (import order: gi must configure before Gio)
from gi.repository import Gio, GLib

_BUS_NAME = "org.freedesktop.login1"
_OBJ_PATH = "/org/freedesktop/login1"
_IFACE = "org.freedesktop.login1.Manager"


def system_bus() -> Gio.DBusConnection:
    return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


def take_sleep_inhibitor(bus: Gio.DBusConnection, why: str) -> int:
    """Returns an fd; sleep is delayed while it stays open. os.close() releases."""
    reply, fds = bus.call_with_unix_fd_list_sync(
        _BUS_NAME, _OBJ_PATH, _IFACE, "Inhibit",
        GLib.Variant("(ssss)", ("sleep", "proteo",
                                why, "delay")),
        GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE, -1, None, None)
    return fds.get(reply.unpack()[0])


def on_prepare_for_sleep(bus: Gio.DBusConnection, callback) -> int:
    """callback(going_to_sleep: bool); returns the subscription id."""
    return bus.signal_subscribe(
        _BUS_NAME, _IFACE, "PrepareForSleep", _OBJ_PATH, None,
        Gio.DBusSignalFlags.NONE,
        lambda _c, _s, _o, _i, _sig, params: callback(params.unpack()[0]))
