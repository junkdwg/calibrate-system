"""Annual calibration plan in ROUNDS (an equipment may need 1..12 calibrations a year).

For a year Y and one equipment with interval M months:
  done      = approved records dated in Y (internal, external or batch rows)
  remaining = due dates still ahead in Y, projected from next_due (+M months each);
              an overdue / never-calibrated one counts as 1 round due now, and later rounds
              are projected from today (assuming it gets calibrated now).
  rounds_total = done + remaining       ->  shown as "ครั้งที่ k/total" and "เหลืออีก n ครั้ง"
"""
from collections import Counter, OrderedDict, defaultdict
from datetime import date

from django.conf import settings
from django.utils import timezone

from .formdefs import FORMS
from .models import CalibrationRecord, Equipment
from .utils import add_months

MONTHS_TH = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
             "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

STATE_LABEL = {"done": "สอบเทียบแล้ว", "overdue": "เกินกำหนด", "never": "ยังไม่เคยสอบเทียบ",
               "soon": "ใกล้ครบกำหนด", "pending": "รอดำเนินการ"}
STATE_ORDER = {"overdue": 0, "never": 1, "soon": 2, "pending": 3, "done": 4}


def _done_in_year(year):
    done = defaultdict(list)                          # equipment id -> [(date, record)]
    qs = CalibrationRecord.objects.filter(status=CalibrationRecord.APPROVED, cal_date__year=year)
    for rec in qs.prefetch_related("rows"):
        ids = [rec.equipment_id] if rec.equipment_id else {r.equipment_id for r in rec.rows.all()
                                                           if r.equipment_id}
        for eid in ids:
            done[eid].append((rec.cal_date, rec))
    for lst in done.values():
        lst.sort(key=lambda x: (x[0], x[1].pk))
    return done


def _remaining_rounds(eq, year, today, soon_limit):
    """[(state, due_date_or_None)] still to do in `year` (empty for past years)."""
    if year < today.year:
        return []
    m, end, out = eq.interval_months, date(year, 12, 31), []
    nd = eq.next_due
    if nd is None:
        out.append(("never", None))
        cursor = add_months(today, m)
    elif nd < today:
        out.append(("overdue", nd))
        cursor = add_months(today, m)
    else:
        cursor = nd
    while cursor <= end:
        if cursor.year == year:
            out.append(("soon" if cursor.toordinal() <= soon_limit else "pending", cursor))
        cursor = add_months(cursor, m)
    return out


def build_plan(year, dept_code=""):
    today = timezone.localdate()
    soon_limit = today.toordinal() + settings.DUE_SOON_DAYS
    done_by_eq = _done_in_year(year)

    equipment = Equipment.objects.filter(active=True).select_related("department")
    if dept_code:
        equipment = equipment.filter(department__code=dept_code)

    items = []
    for e in equipment:
        form = FORMS.get(e.form_code)
        base = {"eq": e, "can_start": bool(form and form.implemented), "record": None}
        done = done_by_eq.get(e.id, [])
        rem = _remaining_rounds(e, year, today, soon_limit)
        total = len(done) + len(rem)
        for i, (d, rec) in enumerate(done, start=1):
            items.append({**base, "state": "done", "month": d.month, "due": d, "record": rec,
                          "round_no": i, "rounds_total": total, "remaining": len(rem)})
        for j, (state, due) in enumerate(rem, start=len(done) + 1):
            month = due.month if due and due.year == year else None
            items.append({**base, "state": state, "month": month, "due": due,
                          "round_no": j, "rounds_total": total, "remaining": len(rem)})

    items.sort(key=lambda i: (STATE_ORDER[i["state"]], i["month"] or 0, i["eq"].code, i["round_no"]))
    for i in items:
        i["label"] = STATE_LABEL[i["state"]]
    return items


def summarize(items):
    counts = Counter(i["state"] for i in items)
    total = len(items)
    done = counts["done"]
    return {
        "total": total, "done": done, "pending": total - done,
        "overdue": counts["overdue"], "never": counts["never"], "soon": counts["soon"],
        "percent": round(done * 100 / total) if total else 0,
        "equipment": len({i["eq"].pk for i in items}),
    }


def monthly_chart(items):
    """12 months + one 'carry-over' bucket (no month: missed earlier / never calibrated)."""
    buckets = OrderedDict((m, {"label": MONTHS_TH[m - 1], "done": 0, "todo": 0}) for m in range(1, 13))
    buckets[0] = {"label": "ค้าง", "done": 0, "todo": 0}
    for i in items:
        b = buckets[i["month"] or 0]
        b["done" if i["state"] == "done" else "todo"] += 1
    peak = max([b["done"] + b["todo"] for b in buckets.values()] + [1])
    out = list(buckets.values())
    for b in out:
        b["done_pct"] = b["done"] * 100 / peak
        b["todo_pct"] = b["todo"] * 100 / peak
        b["total"] = b["done"] + b["todo"]
    return out


def by_department(items):
    rows = OrderedDict()
    for i in items:
        d = i["eq"].department
        r = rows.setdefault(d.code, {"code": d.code, "name": d.name, "total": 0, "done": 0,
                                     "overdue": 0})
        r["total"] += 1
        r["done"] += i["state"] == "done"
        r["overdue"] += i["state"] in ("overdue", "never")
    return sorted(rows.values(), key=lambda r: r["code"])


def available_years():
    y = timezone.localdate().year
    return [y - 1, y, y + 1]
