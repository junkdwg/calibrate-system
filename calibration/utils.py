def fmt_dec(v, min_dp=2):
    """Decimal -> text without trailing zeros, but at least `min_dp` decimals. None -> ''."""
    if v is None:
        return ""
    s = f"{v:f}"
    if "." in s:
        s = s.rstrip("0")
        dp = len(s) - s.index(".") - 1
        if dp < min_dp:
            s += "0" * (min_dp - dp)
        return s.rstrip(".") if min_dp == 0 else s
    return s + ("." + "0" * min_dp if min_dp else "")


def add_months(d, n):
    """Same day-of-month, n months later (clamped to month end). 27/10/2026 + 2 -> 27/12/2026."""
    import calendar
    from datetime import date
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))
