"""Registry of the company's calibration forms (cell maps + rules).

Every form has the same big header; only the body table(s) differ. A form is a list of tables;
each table has a `kind` (how the error is computed) and a cell map into the ORIGINAL Excel file.

kinds (error = standard's own error + deviation; pass when |error| <= tolerance):
  nominal  deviation = reading - standard                          (014, 016, 025, 015 table 1)
  offset   deviation = measured - (standard + fixed offset)        (015 table 2: +76 mm start gap)
  points   deviation = worst of 5 weighing positions vs standard   (026)
  compare  deviation = reading (display) - measured (reference)    (029, 030)
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

NOMINAL, OFFSET, POINTS, COMPARE = "nominal", "offset", "points", "compare"

FORMULAS = {
    NOMINAL: "ค่าผิดพลาด = ค่าผิดพลาดของเครื่องมือมาตรฐาน + (ค่าที่อ่านได้ − ค่ามาตรฐาน)",
    OFFSET: "ค่าผิดพลาด = ค่าผิดพลาดของเครื่องมือมาตรฐาน + (ค่าที่วัดได้ − (ระยะมาตรฐาน + {offset}))",
    POINTS: "ค่าผิดพลาด = ค่าผิดพลาดของลูกตุ้ม + ค่าเบี่ยงเบนสูงสุดของจุดที่อ่าน (1–5) จากน้ำหนักมาตรฐาน",
    COMPARE: "ค่าผิดพลาด = {std}(ค่าที่อ่านได้ − ค่าที่วัดได้)",
}


@dataclass(frozen=True)
class TableDef:
    title: str
    kind: str
    fields: tuple                  # row fields shown on the entry screen (in order)
    labels: dict                   # field -> column title
    unit: str                      # shown next to the tolerance, "" if unknown
    first_row: int                 # first data row in the Excel template
    max_rows: int
    cols: dict                     # key -> cell range ("{r}" = row). keys: no eq std std_err
                                   # b1..b5 b_meas b_err b_pass a1..a5 a_meas a_err a_pass
                                   # remark result_remark
    offset: Decimal = Decimal("0")
    add_std_error: bool = True
    value_min: Optional[Decimal] = None
    value_max: Optional[Decimal] = None
    default_tolerance: str = ""    # "" = user must enter it for every record

    @property
    def formula(self):
        std = "ค่าผิดพลาดเทอร์โมมิเตอร์ + " if self.add_std_error else ""
        return FORMULAS[self.kind].format(offset=self.offset, std=std if self.add_std_error else "")


@dataclass(frozen=True)
class FormDef:
    code: str
    title: str
    template: str = ""             # file in calibration/xlsx_templates/
    implemented: bool = False
    external: bool = False         # sent to an outside lab: certificate details, no Excel form
    batch: bool = False            # one sheet lists many equipment (each row names its equipment)
    copy_start_row: int = 0        # first row to delete (duplicate "copy" in template); 0 = none
    print_area: str = ""
    tables: tuple = ()
    header: tuple = ()             # ((range, "text with {name}{model}{code}{dept}{date}{serial}"), ...)
    page: str = ""                 # cell holding "หน้าที่ ..../...."
    summary: str = ""              # free row for "tolerance / result / note"
    signatures: tuple = ()         # name ranges: calibrator, reviewer, approver

    @property
    def table(self):               # first (main) table
        return self.tables[0] if self.tables else None


# ---------- shared pieces ----------
F_NOMINAL = ("std_value", "std_instr_error", "before_reading", "after_reading")
F_OFFSET = ("std_value", "std_instr_error", "before_reading", "before_measured",
            "after_reading", "after_measured")
F_POINTS = ("std_value", "std_instr_error", "before_reading", "before_p2", "before_p3", "before_p4",
            "before_p5", "after_reading", "after_p2", "after_p3", "after_p4", "after_p5")


def labels(std="ค่ามาตรฐาน", read="ค่าที่อ่านได้", meas="ค่าที่วัดได้", std_err="ผิดพลาดของเครื่องมือมาตรฐาน"):
    d = {"std_value": std, "std_instr_error": std_err, "equipment": "เครื่องมือ", "remark": "หมายเหตุ",
         "before_reading": f"ก่อนปรับ: {read}", "after_reading": f"หลังปรับ: {read}",
         "before_measured": f"ก่อนปรับ: {meas}", "after_measured": f"หลังปรับ: {meas}"}
    for i in range(2, 6):
        d[f"before_p{i}"] = f"ก่อนปรับ จุด {i}"
        d[f"after_p{i}"] = f"หลังปรับ จุด {i}"
    d["before_reading"] = f"ก่อนปรับ: {read}" if read != "จุด 1" else "ก่อนปรับ จุด 1"
    d["after_reading"] = f"หลังปรับ: {read}" if read != "จุด 1" else "หลังปรับ จุด 1"
    return d


def _cols(no=None, std=None, std_err=None, b1=None, b_meas=None, b_err=None, b_pass=None,
          a1=None, a_meas=None, a_err=None, a_pass=None, **extra):
    d = dict(no=no, std=std, std_err=std_err, b1=b1, b_meas=b_meas, b_err=b_err, b_pass=b_pass,
             a1=a1, a_meas=a_meas, a_err=a_err, a_pass=a_pass, **extra)
    return {k: v for k, v in d.items() if v}


def std_header(name, model, code, dept, date, serial):
    return ((name, " ชื่อเครื่องมือ  {name}"), (model, "ยี่ห้อ/รุ่น  {model}"),
            (code, "รหัสเครื่องมือ  {code}"), (dept, " หน่วยงาน  {dept}"),
            (date, "วันที่  {date}"), (serial, "SERIAL No. (S/N)  {serial}"))


FORMS = {f.code: f for f in [
    FormDef(
        "F-MTN-014", "เครื่องชั่งน้ำหนัก", template="F-MTN-014.xlsx", implemented=True,
        copy_start_row=28, print_area="C2:Q27",
        tables=(TableDef("น้ำหนัก", NOMINAL, F_NOMINAL, labels("น้ำหนักมาตรฐาน", "น้ำหนักที่อ่านได้"), "",
                         first_row=9, max_rows=15,
                         cols=_cols("C{r}", "D{r}", "E{r}", "F{r}:G{r}", None, "H{r}:I{r}", "J{r}:K{r}",
                                    "L{r}:M{r}", None, "N{r}:O{r}", "P{r}:Q{r}")),),
        header=std_header("C5:G5", "H5:L5", "M5:Q5", "C6:G6", "H6:L6", "M6:Q6"), page="N4",
        summary="C24:Q24", signatures=("D26:E26", "G26:K26", "M26:P26")),
    FormDef(
        "F-MTN-015", "เครื่อง Tensile", template="F-MTN-015.xlsx", implemented=True,
        print_area="B2:T40",
        tables=(
            TableDef("ตารางน้ำหนัก (Kg.)", NOMINAL, F_NOMINAL, labels("น้ำหนักมาตรฐาน (Kg.)", "น้ำหนักที่อ่านได้ (Kg.)"),
                     "Kg.", first_row=10, max_rows=11,
                     cols=_cols(None, "B{r}:C{r}", "D{r}", "E{r}:F{r}", None, "G{r}:H{r}", "I{r}:L{r}",
                                "M{r}:N{r}", None, "O{r}:P{r}", "Q{r}:T{r}")),
            TableDef("ตารางระยะ (mm.)", OFFSET, F_OFFSET,
                     labels("ระยะมาตรฐาน (mm.)", "ระยะที่อ่านได้ (mm.)", "ระยะที่วัดได้ (mm.)"),
                     "mm.", first_row=23, max_rows=11, offset=Decimal("76"),
                     cols=_cols(None, "B{r}:C{r}", "D{r}", "E{r}:F{r}", "G{r}:H{r}", "I{r}:J{r}", "K{r}:L{r}",
                                "M{r}:N{r}", "O{r}:P{r}", "Q{r}:R{r}", "S{r}:T{r}")),
        ),
        header=std_header("B5:H5", "I5:N5", "O5:T5", "B6:H6", "I6:N6", "O6:T6"), page="O4",
        summary="B34:T34", signatures=("D38:F38", "I38:L38", "O38:R38")),
    FormDef(
        "F-MTN-016", "เครื่องตัดยาง", template="F-MTN-016.xlsx", implemented=True,
        copy_start_row=21, print_area="A1:I20",
        tables=(TableDef("ระยะ", NOMINAL, F_NOMINAL, labels("ระยะมาตรฐาน (mm.)", "ระยะที่อ่านได้ (mm.)"), "mm.",
                         first_row=8, max_rows=8,
                         cols=_cols("A{r}", "B{r}", "C{r}", "D{r}", None, "E{r}", "F{r}",
                                    "G{r}", None, "H{r}", "I{r}")),),
        header=std_header("A4:D4", "E4:F4", "G4:I4", "A5:D5", "E5:F5", "G5:I5"), page="H3",
        summary="A16:I16", signatures=("B18:C18", "E18:F18", "H18:I18")),
    FormDef(
        "F-MTN-025", "เครื่องวัดค่า pH", template="F-MTN-025.xlsx", implemented=True,
        copy_start_row=22, print_area="B2:K21",
        tables=(TableDef("ค่า pH", NOMINAL, F_NOMINAL, labels("pH มาตรฐาน", "pH ที่วัดได้"), "pH",
                         first_row=9, max_rows=8,
                         cols=_cols("B{r}", "C{r}", "D{r}:E{r}", "F{r}", None, "G{r}", "H{r}",
                                    "I{r}", None, "J{r}", "K{r}"),
                         value_min=Decimal("0"), value_max=Decimal("14"), default_tolerance="0.05"),),
        header=std_header("B5:E5", "F5:H5", "I5:K5", "B6:E6", "F6:H6", "I6:K6"), page="I4",
        summary="B17:K17", signatures=("C19:D19", "F19:H19", "I19:K19")),
    FormDef(
        "F-MTN-026", "เครื่องชั่งน้ำหนักแบบละเอียด", template="F-MTN-026.xlsx", implemented=True,
        copy_start_row=28, print_area="C2:W27",
        tables=(TableDef("น้ำหนัก 5 จุด (1 = กลางจาน, 2–5 = มุม)", POINTS, F_POINTS,
                         labels("น้ำหนักมาตรฐาน", "จุด 1", std_err="ผิดพลาดของลูกตุ้ม"), "",
                         first_row=9, max_rows=15,
                         cols={**_cols("C{r}", "D{r}", "E{r}", "F{r}", None, "K{r}:L{r}", "M{r}:N{r}",
                                       "O{r}", None, "T{r}:U{r}", "V{r}:W{r}"),
                               "b2": "G{r}", "b3": "H{r}", "b4": "I{r}", "b5": "J{r}",
                               "a2": "P{r}", "a3": "Q{r}", "a4": "R{r}", "a5": "S{r}"}),),
        header=std_header("C5:J5", "K5:R5", "S5:W5", "C6:J6", "K6:R6", "S6:W6"), page="T4",
        summary="C24:W24", signatures=("D26:E26", "J26:N26", "S26:V26")),
    FormDef(
        "F-MTN-029", "อุณหภูมิเตาอบ ถาดน้ำ และถังคอมปาวด์", template="F-MTN-029.xlsx",
        implemented=True, batch=True, copy_start_row=25, print_area="B2:L24",
        tables=(TableDef("อุณหภูมิ (จอ / เกจ) — 1 แถวต่อ 1 เครื่อง", COMPARE,
                         ("equipment", "std_instr_error", "before_reading", "before_measured",
                          "after_reading", "after_measured", "remark"),
                         {**labels("", "จอ", "เกจ", "ผิดพลาดของเทอร์โมมิเตอร์")}, "°C",
                         first_row=9, max_rows=12,
                         cols=_cols(None, None, "D{r}:E{r}", "F{r}", "G{r}", None, None,
                                    "H{r}", "I{r}", None, None, eq="B{r}:C{r}", result_remark="J{r}:L{r}")),),
        header=(("B5:L5", "  วันที่  {date}"),), page="J4",
        summary="B21:L21", signatures=("B23:D23", "E23:G23", "H23:I23")),
    FormDef(
        "F-MTN-030", "อุณหภูมิตู้อบ ตู้แช่ ตู้ water bath", template="F-MTN-030.xlsx", implemented=True,
        copy_start_row=21, print_area="A1:I20",
        tables=(TableDef("อุณหภูมิ", COMPARE,
                         ("before_reading", "before_measured", "after_reading", "after_measured", "remark"),
                         labels("", "อุณหภูมิที่อ่านได้", "อุณหภูมิที่วัดได้"), "°C",
                         first_row=8, max_rows=9, add_std_error=False,
                         cols=_cols("A{r}", None, None, "B{r}", "C{r}", None, "D{r}",
                                    "E{r}", "F{r}", None, "G{r}", remark="H{r}:I{r}")),),
        header=((("A4:I4"), " ชื่อเครื่องมือ  {name}    รหัส  {code}"),
                (("A5:I5"), " หน่วยงาน  {dept}    วันที่  {date}")), page="G3",
        summary="A17:I17", signatures=("B19:C19", "E19:F19", "G19:H19")),
    FormDef("EXT-CAL", "สอบเทียบภายนอก", implemented=True, external=True),
]}

FORM_CHOICES = [(c, f"{c} {f.title}") for c, f in FORMS.items()]
IMPLEMENTED_CODES = [c for c, f in FORMS.items() if f.implemented]
