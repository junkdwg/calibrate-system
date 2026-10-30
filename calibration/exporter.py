"""Fill the company's original Excel form and optionally convert it to PDF.

All forms: one copy only, font AngsanaUPC 16, common header filled the same way.
Only the body filler differs per form (see FILLERS).
"""
import posixpath
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.properties import PageSetupProperties

from .formdefs import FORMS
from .utils import fmt_dec

TEMPLATE_DIR = Path(__file__).parent / "xlsx_templates"
FONT_NAME, FONT_SIZE = "AngsanaUPC", 16
MIN_ROW_HEIGHT = 24
CENTER = Alignment(horizontal="center", vertical="center", shrink_to_fit=True)  # long numbers/names shrink, never spill
LEFT = Alignment(horizontal="left", vertical="center")


# ---------- keep logo + check-box shapes ----------
# openpyxl keeps pictures only, and drops text boxes / lines. The company forms contain
# both, so after saving we put the ORIGINAL drawing part of the first sheet back.
ANCHOR_RE = re.compile(r"<xdr:(twoCellAnchor|oneCellAnchor|absoluteAnchor)\b.*?</xdr:\1>", re.S)
FROM_ROW_RE = re.compile(r"<xdr:from>.*?<xdr:row>(\d+)</xdr:row>", re.S)


def _first_sheet_drawing(z):
    rels = "xl/worksheets/_rels/sheet1.xml.rels"
    if rels not in z.namelist():
        return None
    for rel in ET.fromstring(z.read(rels)):
        if rel.get("Type", "").endswith("/drawing"):
            t = rel.get("Target")
            return t.lstrip("/") if t.startswith("/") else posixpath.normpath(
                posixpath.join("xl/worksheets", t))
    return None


def _rels_path(part):
    d, n = posixpath.split(part)
    return posixpath.join(d, "_rels", n + ".rels")


def _drop_anchors_from_row(xml, first_row0):
    """Remove drawing objects that sit in the removed duplicate copy (0-based row index)."""
    def keep(m):
        r = FROM_ROW_RE.search(m.group(0))
        return m.group(0) if not r or int(r.group(1)) < first_row0 else ""
    return ANCHOR_RE.sub(keep, xml)


def restore_drawings(template_path, out_bytes, form):
    zo = zipfile.ZipFile(template_path)
    zn = zipfile.ZipFile(BytesIO(out_bytes))
    od, nd = _first_sheet_drawing(zo), _first_sheet_drawing(zn)
    if not od or not nd:
        return out_bytes
    xml = zo.read(od).decode("utf-8")
    if form.copy_start_row:
        xml = _drop_anchors_from_row(xml, form.copy_start_row)
    replace = {nd: xml.encode("utf-8")}
    extra_ext = set()
    orels, nrels = _rels_path(od), _rels_path(nd)
    if orels in zo.namelist():
        replace[nrels] = zo.read(orels)
        for rel in ET.fromstring(zo.read(orels)):
            t = rel.get("Target")
            media = t.lstrip("/") if t.startswith("/") else posixpath.normpath(
                posixpath.join(posixpath.dirname(od), t))
            replace[media] = zo.read(media)
            extra_ext.add(media.rsplit(".", 1)[-1].lower())

    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zw:
        for item in zn.infolist():
            data = replace.pop(item.filename, None)
            if data is None:
                data = zn.read(item.filename)
            if item.filename == "[Content_Types].xml":
                ct = data.decode("utf-8")
                for ext in extra_ext:
                    if f'Extension="{ext}"' not in ct:
                        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(
                            ext, "application/octet-stream")
                        ct = ct.replace("</Types>", f'<Default Extension="{ext}" ContentType="{mime}"/></Types>')
                data = ct.encode("utf-8")
            zw.writestr(item.filename, data)
        for name, data in replace.items():      # parts that were not in the openpyxl output
            zw.writestr(name, data)
    return out.getvalue()


def _load(form):
    """Open the original template, keep only its first sheet (later sheets are sample copies)."""
    wb = load_workbook(TEMPLATE_DIR / form.template)
    for name in wb.sheetnames[1:]:
        del wb[name]
    return wb, wb.worksheets[0]


def _save(wb, form) -> bytes:
    buf = BytesIO()
    wb.save(buf)
    return restore_drawings(TEMPLATE_DIR / form.template, buf.getvalue(), form)


# ---------- helpers ----------
def _pf(flag):
    return "" if flag is None else ("ผ่าน" if flag else "ไม่ผ่าน")


def _person(user):
    return (user.get_full_name() or user.get_username()) if user else ""


def _overlaps(ws, rng):
    from openpyxl.worksheet.cell_range import CellRange
    target = CellRange(rng)
    return any(not target.isdisjoint(m) for m in ws.merged_cells.ranges)


def _put(ws, rng, text, align=LEFT, force=False):
    """Write text in a cell/range; merge a multi-cell range unless it overlaps an existing merge
    (force=True first removes the overlapping merges)."""
    first = rng.split(":")[0]
    if force and ":" in rng:
        from openpyxl.worksheet.cell_range import CellRange
        target = CellRange(rng)
        for m in [m for m in ws.merged_cells.ranges if not target.isdisjoint(m) and str(m) != rng]:
            ws.unmerge_cells(str(m))
    if ":" in rng and rng not in {str(m) for m in ws.merged_cells.ranges} and not _overlaps(ws, rng):
        ws.merge_cells(rng)
    ws[first].value = text
    ws[first].alignment = align


def _strip_copy(ws, form):
    """The company template holds the form twice (original + copy). Keep only one."""
    if not form.copy_start_row:
        return
    for m in [m for m in ws.merged_cells.ranges if m.min_row >= form.copy_start_row]:
        ws.unmerge_cells(str(m))
    ws.delete_rows(form.copy_start_row, ws.max_row - form.copy_start_row + 1)
    ws.print_area = form.print_area


def _apply_font(ws, form):
    """AngsanaUPC 16 on every cell of the printed area (keeps bold)."""
    last_row = int(re.findall(r"\d+", form.print_area)[-1]) if form.print_area else ws.max_row
    data_rows = {r for t in form.tables for r in range(t.first_row, t.first_row + t.max_rows)}
    for row in ws.iter_rows(min_row=1, max_row=last_row):
        for c in row:
            if isinstance(c, MergedCell):
                continue
            bold = False if c.row in data_rows else c.font.b
            c.font = Font(name=FONT_NAME, size=FONT_SIZE, bold=bold, italic=c.font.i)
    for r in range(2, last_row + 1):
        h = ws.row_dimensions[r].height
        if h is None or h < MIN_ROW_HEIGHT:
            ws.row_dimensions[r].height = MIN_ROW_HEIGHT


def _page_setup(ws):
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.scale = None
    ws.page_setup.fitToWidth = ws.page_setup.fitToHeight = 1
    ws.page_setup.orientation = "portrait"


# ---------- common header, tables, summary, signatures (one engine for every form) ----------
def fill_header(ws, form, record):
    eq = record.equipment
    values = {"name": eq.name if eq else "", "model": eq.brand_model if eq else "",
              "code": eq.code if eq else "", "dept": eq.department.name if eq else "",
              "date": f"{record.cal_date:%d/%m/%Y}", "serial": eq.serial_no if eq else ""}
    for rng, text in form.header:
        _put(ws, rng, text.format(**values))
    ws[form.page].value = "  หน้าที่ 1 / 1"


def _row_values(row, i):
    v = {"no": i + 1, "eq": row.equipment.code if row.equipment else "",
         "std": fmt_dec(row.std_value), "std_err": fmt_dec(row.std_instr_error, 3),
         "b_meas": fmt_dec(row.before_measured), "b_err": fmt_dec(row.before_error),
         "b_pass": _pf(row.before_pass),
         "a_meas": fmt_dec(row.after_measured), "a_err": fmt_dec(row.after_error),
         "a_pass": _pf(row.after_pass), "remark": row.remark,
         "result_remark": f"{_pf(row.final_pass)}  {row.remark}".strip()}
    for k, field in (("b1", "before_reading"), ("b2", "before_p2"), ("b3", "before_p3"),
                     ("b4", "before_p4"), ("b5", "before_p5"), ("a1", "after_reading"),
                     ("a2", "after_p2"), ("a3", "after_p3"), ("a4", "after_p4"), ("a5", "after_p5")):
        v[k] = fmt_dec(getattr(row, field))
    return v


def fill_tables(ws, form, record):
    for idx, t in enumerate(form.tables, start=1):
        rows = [r for r in record.rows.all() if r.table_no == idx][:t.max_rows]
        for i, row in enumerate(rows):
            r = t.first_row + i
            values = _row_values(row, i)
            for key, rng in t.cols.items():
                _put(ws, rng.format(r=r), values[key], CENTER)


def fill_summary(ws, form, record):
    parts = []
    for idx, t in enumerate(form.tables, start=1):
        tol = record.tolerance_for(idx)
        if tol is None:
            continue
        unit = f" {t.unit}" if t.unit else ""
        prefix = f"{t.title}: " if len(form.tables) > 1 else ""
        parts.append(f"{prefix}เกณฑ์ผ่าน ± {fmt_dec(tol, 0)}{unit}")
    overall = record.overall_pass
    text = ("   ".join(parts) + "   ผลรวม: " +
            ("ผ่าน" if overall else "ไม่ผ่าน" if overall is False else "-"))
    if record.note:
        text += f"   หมายเหตุ: {record.note}"
    _put(ws, form.summary, text, force=True)
    first = form.summary.split(":")[0]
    ws[first].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    row = int(re.findall(r"\d+", first)[0])
    ws.row_dimensions[row].height = MIN_ROW_HEIGHT * (1 + len(text) // 75)


def fill_signatures(ws, form, record):
    for rng, user in zip(form.signatures, (record.calibrator, record.reviewer, record.approver)):
        if user:
            _put(ws, rng, _person(user), CENTER)


# ---------- public API ----------
def build_xlsx(record) -> bytes:
    form = FORMS[record.form_code]
    if not form.implemented or form.external:
        raise ValueError(f"{form.code} has no Excel form")
    wb, ws = _load(form)
    _strip_copy(ws, form)
    fill_header(ws, form, record)
    fill_tables(ws, form, record)
    fill_signatures(ws, form, record)
    _apply_font(ws, form)       # before the summary: it sets its own (taller) row height
    fill_summary(ws, form, record)
    _page_setup(ws)
    return _save(wb, form)


def build_blank_xlsx(form_code) -> bytes:
    """The whole empty company form (same font/page rules). Used to preview/verify a template."""
    form = FORMS[form_code]
    wb, ws = _load(form)
    _strip_copy(ws, form)          # no-op for forms without a duplicate copy
    _apply_font(ws, form)
    _page_setup(ws)
    return _save(wb, form)


def build_pdf(record) -> bytes:
    xlsx = build_xlsx(record)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "form.xlsx"
        src.write_bytes(xlsx)
        subprocess.run(
            ["soffice", "--headless", "--norestore",
             f"-env:UserInstallation=file://{tmp}/profile",
             "--convert-to", "pdf", "--outdir", tmp, str(src)],
            check=True, timeout=90, capture_output=True,
        )
        return (Path(tmp) / "form.pdf").read_bytes()


def safe_filename(record, ext):
    code = re.sub(r"[^A-Za-z0-9_-]+", "_", record.equipment.code if record.equipment else "batch") or "equipment"
    return f"{record.form_code}_{code}_{record.cal_date:%Y%m%d}.{ext}"
