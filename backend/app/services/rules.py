"""The rules that turn an upload date into Month, Year and Mid Month.

Written once, here, because the three distributors differ only in the cut-off
day. Getting this wrong produces a file that looks perfectly correct and is
wrong, so it is also the most heavily tested part of the system.
"""
from __future__ import annotations

from datetime import date

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


class Refused(ValueError):
    """A rule refuses the request. The API turns this into a 409."""


def period(as_of: date, cutoff_day: int, mid_cutoff_day: int | None = None) -> dict:
    """Month, Year and Mid Month for a batch uploaded on `as_of`.

    On or before the cut-off: the month steps back one and Mid Month is N.
    After it: the current month, and Y.

    Mid Month can have its own cut-off (Pharmachem: the month steps back on the
    1st-10th, Mid Month is N on the 1st-11th). Without one it is the same day.

    Year is the current year, as the rule says, even in the one case where the
    month steps back past January. The caller is warned rather than corrected,
    because silently changing a stated rule is worse than an odd-looking year.
    """
    mid_cut = mid_cutoff_day or cutoff_day
    m = as_of.month - 1                      # to 0-based
    early = as_of.day <= cutoff_day
    if early:
        m -= 1
    wrapped = m < 0
    if wrapped:
        m = 11
    mid_early = as_of.day <= mid_cut
    return {"month": MONTHS[m], "year": as_of.year, "mid_month": "N" if mid_early else "Y",
            "early": early, "wrapped": wrapped, "cutoff_day": cutoff_day,
            "mid_cutoff_day": mid_cut}
