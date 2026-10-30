"""Turns a record's tables into plain (header, rows) for the detail page — one generic template."""
from .utils import fmt_dec


def _pf(flag):
    return ("ผ่าน", "ok") if flag is True else ("ไม่ผ่าน", "bad-t") if flag is False else ("", "")


def table_blocks(record):
    blocks = []
    for idx, t in enumerate(record.form.tables, start=1):
        rows = [r for r in record.rows.all() if r.table_no == idx]
        headers = []
        if "equipment" in t.fields:
            headers.append("เครื่องมือ")
        if "std_value" in t.fields:
            headers.append(t.labels["std_value"])
        if "std_instr_error" in t.fields:
            headers.append(t.labels["std_instr_error"])
        phase_fields = {p: [f for f in t.fields if f.startswith(p + "_")] for p in ("before", "after")}
        for p, word in (("before", "ก่อนปรับ"), ("after", "หลังปรับ")):
            headers += [t.labels[f] for f in phase_fields[p]]
            headers += [f"{word}: ผิดพลาด", f"{word}: ผล"]
        if "remark" in t.fields:
            headers.append("หมายเหตุ")

        body = []
        for r in rows:
            cells = []
            if "equipment" in t.fields:
                cells.append((r.equipment.code if r.equipment else "", ""))
            if "std_value" in t.fields:
                cells.append((fmt_dec(r.std_value), ""))
            if "std_instr_error" in t.fields:
                cells.append((fmt_dec(r.std_instr_error, 3), ""))
            for p in ("before", "after"):
                for f in phase_fields[p]:
                    cells.append((fmt_dec(getattr(r, f)), ""))
                cells.append((fmt_dec(getattr(r, f"{p}_error")), ""))
                cells.append(_pf(getattr(r, f"{p}_pass")))
            if "remark" in t.fields:
                cells.append((r.remark, ""))
            body.append(cells)
        tol = record.tolerance_for(idx)
        blocks.append({"title": t.title, "headers": headers, "rows": body, "formula": t.formula,
                       "tolerance": fmt_dec(tol, 0) if tol is not None else "", "unit": t.unit,
                       "show_title": len(record.form.tables) > 1 or record.form.batch})
    return blocks
