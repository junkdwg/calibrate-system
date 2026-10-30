# ระบบสอบเทียบเครื่องมือ (Phase 1: F-MTN-025 pH)

Django + PostgreSQL + Nginx (Docker Compose) — ใช้ภายในบริษัทเท่านั้น

## ติดตั้ง (Ubuntu + Docker)
```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # นำไปใส่ DJANGO_SECRET_KEY
nano .env                                                       # แก้ SECRET_KEY, รหัสผ่าน DB, HOST/IP
scripts/make_cert.sh calib.company.local                        # หรือใส่ IP เซิร์ฟเวอร์
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```
เปิด `https://<host>/` (ครั้งแรกเบราว์เซอร์จะเตือน cert แบบ self-signed — ติดตั้ง `certs/server.crt` เป็น trusted บนเครื่องผู้ใช้ได้)

## เริ่มใช้งาน
1. เข้า `/admin/` → สร้างแผนก (Department) และเครื่องมือ (Equipment, ฟอร์ม F-MTN-025)
2. สร้างผู้ใช้ แล้วใส่ Group: `Technician` (ช่างกรอก) / `Reviewer` (หัวหน้า MTN) / `Approver` (หัวหน้าแผนกเจ้าของเครื่อง)
3. ช่างกด "สร้างใบสอบเทียบ" → ส่งทบทวน → ทบทวน → อนุมัติ → ดาวน์โหลด PDF/Excel

## ทดลองบนเครื่องตัวเอง (ไม่ใช้ Docker)
```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
export DJANGO_DEBUG=1
python manage.py migrate && python manage.py seed_demo   # สร้าง user ตัวอย่าง (รหัสผ่านสุ่มแสดงในหน้าจอ)
python manage.py runserver
python manage.py test calibration
```
(PDF ต้องมี LibreOffice: `soffice` ใน PATH)

## กติกาและฟีเจอร์ (v2)
- **ผู้ลงข้อมูล (Technician) มีได้สูงสุด 2 คน** (ปรับที่ `MAX_DATA_ENTRY_USERS` ใน `.env`) — ระบบกันที่หน้า Admin และทุกช่องทาง; superuser ไม่ได้สิทธิ์ลงข้อมูลอัตโนมัติ (ต้องอยู่ในกลุ่มเอง)
- **Dashboard** (หน้าแรก): สรุปปีนี้ต้องสอบเทียบอะไรบ้าง ทำแล้ว/เหลือ/เกินกำหนด/ใกล้ครบ/ยังไม่เคย, กราฟรายเดือน, แยกแผนก, รายการทั้งปี, งานค้างทบทวน/อนุมัติ; เลือกปีและแผนกได้
- **ฟอร์ม**: ทะเบียนฟอร์มอยู่ที่ `calibration/formdefs.py` — เปิดใช้ครบ: 014 (ชั่ง), 015 (Tensile 2 ตาราง Kg./mm.), 016 (ตัดยาง), 025 (pH), 026 (ชั่งละเอียด 5 จุด), 029 (อุณหภูมิ เตาอบ/ถาด/ถัง — ใบเดียวบันทึกหลายเครื่อง), 030 (อุณหภูมิตู้อบ/ตู้แช่/water bath) และ **EXT-CAL สอบเทียบภายนอก** (บันทึกห้องปฏิบัติการ/เลขใบรับรอง/ผล)
- **สูตร**: ค่าผิดพลาด = ค่าผิดพลาดของเครื่องมือมาตรฐาน (ลูกตุ้ม/เทอร์โมมิเตอร์) + ค่าเบี่ยงเบน; ผ่านเมื่อ |ค่าผิดพลาด| ≤ เกณฑ์ที่กรอกต่อใบ — เบี่ยงเบนของแต่ละฟอร์ม: 014/016/025/015(Kg.) = อ่านได้ − มาตรฐาน; 015(mm.) = วัดได้ − (มาตรฐาน + 76); 026 = ค่าเบี่ยงเบนสูงสุดของจุด 1–5; 029/030 = อ่านได้ − วัดได้ (030 ไม่มีค่าผิดพลาดมาตรฐาน)
- **รอบสอบเทียบเป็นเดือน** (ต่อเครื่องมือ): กำหนดครั้งถัดไป = วันที่สอบเทียบล่าสุด + N เดือน วันเดิม (27/10/2026 + 2 เดือน = 27/12/2026; + 6 เดือน = 27/4/2027) Dashboard นับ**รอบ**ต่อปี: "ครั้งที่ k/n ของปี" และ "เหลืออีก m ครั้ง"
- **PDF/Excel**: ออกใบเดียว ฟอนต์ AngsanaUPC ขนาด 16 ทั้งใบ

## เพิ่มฟอร์มใหม่ (ทำต่อ)
1. วางไฟล์ Excel **ต้นฉบับของบริษัทตามเดิม** ใน `calibration/xlsx_templates/` (ห้ามเปิดแล้วบันทึกด้วยโปรแกรมอื่นก่อน — โลโก้และช่องติ๊กอยู่ในไฟล์ ระบบดึงกลับมาให้ครบเอง)
2. ใน `formdefs.py` ใส่ `template`, `implemented=True`, `copy_start_row`, `print_area`
3. ฟอร์มแบบ "ตารางค่ามาตรฐาน/ค่าที่อ่านได้" (เหมือน 014/016/025) ไม่ต้องเขียนโค้ดเพิ่ม แค่ระบุตำแหน่งเซลล์ (`header`, `table.cols`, `summary`, `signatures`) ใน `formdefs.py` แล้วตั้ง `implemented=True`
4. ฟอร์มที่โครงต่างออกไป (หลายตาราง, อ่านหลายจุด, อุณหภูมิ) ต้องขยายโมเดลแถวข้อมูลและหน้ากรอกเพิ่ม

## อัปเกรดจากเวอร์ชันก่อน
`docker compose up -d --build` (migrate รันอัตโนมัติ)

## เริ่มระบบแบบปลอดภัย
`scripts/up.sh` — ตรวจ `.env`, ใบรับรอง (มี SAN/ไม่หมดอายุ) แล้วค่อย `docker compose up -d --build`
มี healthcheck: web ตรวจ `/healthz/` (เช็กแอป+ฐานข้อมูล), nginx ตรวจ `/nginx-health`; nginx รอให้ web พร้อมก่อนเสมอ ดูสถานะ: `docker compose ps`

## Troubleshooting: container รันซ้ำไม่หยุด (restart loop)
ดูสาเหตุก่อนเสมอ: `sh scripts/diagnose.sh > diagnose.txt` (สรุปสถานะ, log, ผลทดสอบล็อกอินฐานข้อมูล, ใบรับรอง — ไม่พิมพ์รหัสผ่าน) หรือ `docker compose logs --tail=50 web nginx db`

| อาการใน log | สาเหตุ | วิธีแก้ |
|---|---|---|
| `DATABASE CONNECTION FAILED ... role "x" does not exist` / `password authentication failed` | ค่า `POSTGRES_*` ใน `.env` ไม่ตรงกับ volume ฐานข้อมูลที่สร้างไว้ก่อนหน้า (Postgres อ่านค่าเหล่านี้ครั้งแรกที่สร้าง volume เท่านั้น) | คืนค่าเดิมใน `.env` หรือสร้าง/แก้ role ในคอนเทนเนอร์ db (ข้อมูลไม่หาย) — **ห้าม** `down -v` |
| nginx: `cannot load certificate` / `No such file` | `certs/server.crt`/`server.key` ไม่มี | `scripts/make_cert.sh <host-หรือ-IP>` แล้ว `docker compose restart nginx` |
| web: `exec ./entrypoint.sh: no such file` / `^M` | ไฟล์ .sh เป็น CRLF (แก้บน Windows) | ใช้ `.gitattributes` ในโปรเจกต์ (บังคับ LF) แล้วแปลงไฟล์เป็น LF |

## ใบรับรองสำหรับใช้งานจริง
- ใบรับรอง self-signed ต้องมี SAN ตรงกับที่ใช้เข้า (ชื่อหรือ IP) ไม่งั้นเบราว์เซอร์ปฏิเสธ → `scripts/make_cert.sh <host>`
- ใช้จริงแนะนำให้ CA ของบริษัทเซ็น: `scripts/make_csr.sh calib.company.local` → ส่ง `certs/server.csr` ให้ IT → วางไฟล์ที่เซ็นแล้วเป็น `certs/server.crt` (ใบของเรา แล้วตามด้วย chain) → `docker compose restart nginx`
- ถ้าใช้ self-signed ต่อ ให้ IT ติดตั้ง `server.crt` เป็น Trusted Root ให้เครื่องผู้ใช้ (GPO) จะไม่มีคำเตือน

## ข้อมูลอยู่ที่ไหน / ล้างข้อมูลทดสอบ
- ข้อมูลทั้งหมดอยู่ในฐานข้อมูล **PostgreSQL** ใน Docker volume `pgdata` (ไม่ใช่ไฟล์ในโฟลเดอร์โปรเจกต์) ใบสอบเทียบอยู่ตาราง `calibration_calibrationrecord` (หัวใบ) และ `calibration_calibrationrow` (แถวข้อมูล), ประวัติการกระทำ `calibration_auditlog`, เครื่องมือ `calibration_equipment`; ไฟล์ PDF/Excel สร้างสดตอนกดดาวน์โหลด ไม่ได้เก็บไว้
- ดูข้อมูล: หน้า `/admin/` (ดูอย่างเดียว) หรือ `docker compose exec db psql -U <POSTGRES_USER> -d <POSTGRES_DB>`
- ล้างข้อมูลทดสอบ: `scripts/backup.sh` ก่อนเสมอ แล้ว `docker compose exec web python manage.py purge_records` (พรีวิว ไม่ลบ) ตามด้วย `--apply` เพื่อลบจริง; ตัวเลือก `--include-approved`, `--before 2026-11-01`, `--equipment รหัส`, `--id N`, `--with-audit`
- ห้ามใช้ `docker compose down -v` (ลบฐานข้อมูลทั้งหมดรวมเครื่องมือและผู้ใช้)

## ความปลอดภัยที่ทำไว้แล้ว
- ต้อง login ทุกหน้า, สิทธิ์ตามบทบาท, ผู้ทบทวน/อนุมัติต้องไม่ใช่คนเดียวกับผู้สอบเทียบ
- อนุมัติ/ส่งแล้วล็อกแก้ไขไม่ได้ (ส่งกลับแก้ไขได้ พร้อมเหตุผลใน Audit log)
- Audit log ทุกการกระทำ (Admin ดูได้อย่างเดียว) และใบสอบเทียบแก้ผ่าน Admin ไม่ได้
- HTTPS, cookie secure, session หมดอายุ 8 ชม., DB ไม่เปิดพอร์ตออกนอก Docker network
- Secret/รหัสผ่านอยู่ใน `.env` (ไม่เข้า git/image), container รันด้วย user ที่ไม่ใช่ root
- สำรองข้อมูล: `scripts/backup.sh` (ตั้ง cron รายวัน และคัดลอกไปเครื่องอื่น)

## สิ่งที่ต้องยืนยัน / ทำต่อ
- **เกณฑ์ผ่าน ± 0.05 pH เป็นค่าสมมติ** → ยืนยันกับ QA (แก้ได้ต่อใบ หรือ `DEFAULT_PH_TOLERANCE`)
- รหัสเครื่องมือใน `seed_demo` เป็นค่าสมมติ → ใช้รหัสจริงตอนนำเข้า
- ตรวจ PDF ใน Docker (มีฟอนต์ไทย TLWG) ว่าตรงฟอร์มจริงหรือไม่
- เฟสถัดไป: จำกัดการ login ผิดซ้ำ (django-axes), ฟอร์มอื่น, นำเข้ารายการเครื่องมือ, แจ้งเตือนอีเมล, ลายเซ็นภาพ
