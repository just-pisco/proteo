#!/bin/bash
# Watchdog launcher for Steam Big Picture, meant as the "detached" command of
# Sunshine's "Steam Big Picture" app entry (see README).
#
# Why: Sunshine fires "steam steam://open/bigpicture" exactly once, blind. The
# Steam client intermittently ignores that URL (long-standing upstream flakiness,
# worse right after a steam://close/bigpicture and around display reconfigurations,
# both of which happen at every stream reconnect). Result: the stream shows a bare
# desktop and Big Picture never comes up.
#
# This script re-asserts the URL until the Big Picture window actually exists,
# checking via Xwayland (Steam is an X11 app; the window title contains
# "Big Picture" in every locale). Cold Steam start takes ~45 s, warm reopen
# ~10-15 s; we allow up to ~2 minutes before giving up.

export DISPLAY="${DISPLAY:-:0}"

bp_window_present() {
    xwininfo -root -tree 2>/dev/null | grep -qi 'big picture'
}

for attempt in 1 2 3 4 5 6; do
    setsid steam steam://open/bigpicture >/dev/null 2>&1 &
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        sleep 2
        if bp_window_present; then
            exit 0
        fi
    done
done

echo "steam-bigpicture: Big Picture window never appeared after ${attempt} attempts" >&2
exit 1
