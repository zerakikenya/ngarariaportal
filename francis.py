"""MSU Portal - full single-file version
Includes: admin/teacher/student/furniture/finance portals, team chat, MCQ + written assignments,
teacher uploads, student library with likes and social sharing, parent login (phone), marking.
Run:  pip install flask   then   python app.py
"""
import os, sqlite3, time, json, random, string, re, csv, io
from datetime import datetime
from urllib.parse import quote
from functools import wraps
from werkzeug.security import generate_password_hash as _gen, check_password_hash
def generate_password_hash(p): return _gen(p, method="pbkdf2:sha256")
from flask import Flask, g, request, redirect, url_for, session, flash, render_template_string, send_from_directory, jsonify, Response, abort
from werkzeug.utils import secure_filename

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.path.join(BASE,"school.db")
UPLOADS=os.path.join(BASE,"uploads")
os.makedirs(UPLOADS,exist_ok=True)

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","change-this-secret-before-going-live")

import traceback
from markupsafe import escape
@app.errorhandler(500)
def server_error(e):
    # Shows the real error on the page while you are developing. Set SHOW_ERRORS=0 before going live.
    exc=getattr(e,"original_exception",None) or e
    tb="".join(traceback.format_exception(type(exc),exc,exc.__traceback__))
    print(tb)
    if os.environ.get("SHOW_ERRORS","1")=="1":
        return "<h3 style='font-family:sans-serif;padding:16px 16px 0'>Server error - copy this and send it to Claude</h3><pre style='white-space:pre-wrap;padding:16px;font-size:12px'>"+str(escape(tb))+"</pre>",500
    return "Something went wrong. Please try again.",500

SCHEMA="""
CREATE TABLE IF NOT EXISTS subjects(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS departments(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS teachers(id INTEGER PRIMARY KEY, name TEXT, code TEXT UNIQUE, phone TEXT, tsc_no TEXT, subject_id INTEGER, department_id INTEGER, classes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS students(id INTEGER PRIMARY KEY, name TEXT, adm_no TEXT UNIQUE, form INTEGER, stream TEXT, parent_phone TEXT, department_id INTEGER, chair_no TEXT, locker_no TEXT, books TEXT DEFAULT '', gender TEXT DEFAULT '', email TEXT, programme TEXT, wallet_balance REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, teacher_id INTEGER, subject_id INTEGER, department_id INTEGER, form INTEGER, kind TEXT, title TEXT, filename TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY, teacher_id INTEGER, subject_id INTEGER, form INTEGER, title TEXT, ts INTEGER, description TEXT);
CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, assignment_id INTEGER, qtype TEXT DEFAULT 'mcq', text TEXT, a TEXT, b TEXT, c TEXT, d TEXT, answer TEXT, marks INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS submissions(id INTEGER PRIMARY KEY, assignment_id INTEGER, student_id INTEGER, score INTEGER, total INTEGER, answers TEXT, ts INTEGER, UNIQUE(assignment_id, student_id));
CREATE TABLE IF NOT EXISTS fees(id INTEGER PRIMARY KEY, student_id INTEGER, form INTEGER, term INTEGER, amount REAL, ts INTEGER, note TEXT, type TEXT DEFAULT 'fee');
CREATE TABLE IF NOT EXISTS fee_structure(form INTEGER PRIMARY KEY, per_year REAL);
CREATE TABLE IF NOT EXISTS furniture(id INTEGER PRIMARY KEY, student_id INTEGER, locker_no TEXT, chair_no TEXT, books TEXT, assigned_by TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS dept_library(id INTEGER PRIMARY KEY, department_id INTEGER, uploader_id INTEGER, kind TEXT, title TEXT, filename TEXT, description TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS lab_equipment(id INTEGER PRIMARY KEY, department_id INTEGER, name TEXT, quantity INTEGER, available INTEGER, description TEXT);
CREATE TABLE IF NOT EXISTS virtual_classes(id INTEGER PRIMARY KEY, department_id INTEGER, teacher_id INTEGER, title TEXT, link TEXT, schedule TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS wallet_transactions(id INTEGER PRIMARY KEY, student_id INTEGER, phone TEXT, amount REAL, mpesa_code TEXT, status TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS team_discussions(id INTEGER PRIMARY KEY, student_id INTEGER, form INTEGER, subject_id INTEGER, msg_type TEXT, text TEXT, filename TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS dept_messages(id INTEGER PRIMARY KEY, department_id INTEGER, sender TEXT, role TEXT, body TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS dm(id INTEGER PRIMARY KEY, from_key TEXT, to_key TEXT, body TEXT, ts INTEGER);
"""

def db():
    if "db" not in g:
        g.db=sqlite3.connect(DB);g.db.row_factory=sqlite3.Row
    return g.db
@app.teardown_appcontext
def close(_):
    d=g.pop("db",None)
    if d:d.close()
def q(sql,args=(),one=False):
    try:
        cur=db().execute(sql,args);rows=cur.fetchall();db().commit();return (rows[0] if rows else None) if one else rows
    except Exception as e:
        print(f"SQL Error: {e} | SQL: {sql}")
        # If table missing, recreate
        with sqlite3.connect(DB) as c:
            c.executescript(SCHEMA)
        cur=db().execute(sql,args);rows=cur.fetchall();db().commit();return (rows[0] if rows else None) if one else rows

def get_setting(k, default=""):
    """Read the latest school branding from the expanded settings table first."""
    try:
        row=q("SELECT v FROM school_settings WHERE k=?",(k,),True)
        if row and row["v"] is not None:
            return row["v"]
    except Exception:
        pass
    try:
        row=q("SELECT v FROM settings WHERE k=?",(k,),True)
        return row["v"] if row and row["v"] is not None else default
    except Exception:
        return default

def init():
    try:
        with sqlite3.connect(DB) as c:
            c.executescript(SCHEMA)
            # Upgrade old DB - add missing columns
            mem=sqlite3.connect(":memory:")
            mem.executescript(SCHEMA)
            for (t,) in mem.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                try:
                    have={r[1] for r in c.execute(f"PRAGMA table_info({t})")}
                    for _cid, name, typ, _nn, dflt, pk in mem.execute(f"PRAGMA table_info({t})").fetchall():
                        if name not in have and not pk:
                            print(f"FIXING OLD DB: Adding {name} to {t}")
                            try: c.execute(f"ALTER TABLE {t} ADD COLUMN {name} {typ or 'TEXT'}")
                            except: pass
                except: pass
            mem.close()
            c.execute("INSERT OR IGNORE INTO departments(name) VALUES('Humanities'),('Science'),('Languages'),('Mathematics')")
            c.execute("INSERT OR IGNORE INTO subjects(name) VALUES('English'),('Mathematics'),('Biology'),('Chemistry'),('Physics')")
            c.execute("INSERT OR IGNORE INTO settings(k,v) VALUES('logo',''),('background','')")
            if not c.execute("SELECT 1 FROM students LIMIT 1").fetchone():
                print("Creating default student and teachers...")
                c.execute("INSERT INTO students(name,adm_no,form,stream,parent_phone,department_id,chair_no,locker_no,books,gender,wallet_balance) VALUES(?,?,?,?,?,?,?,?,?,?,?)",("ODIWUOR, Francis Okello","ED/00530/018",4,"Y4S2","0792239596",2,"CH-042","LK-118","Biology Textbook","Male",1250))
                c.execute("INSERT INTO teachers(name,code,phone,tsc_no,subject_id,department_id,classes) VALUES(?,?,?,?,?,?,?)",("Dr. Otieno - Biology","T001","0712345678","123",3,2,"Form 4 Y4S2"))
                c.execute("INSERT INTO teachers(name,code,phone,tsc_no,subject_id,department_id,classes) VALUES(?,?,?,?,?,?,?)",("Ms. Akinyi - English","T002","0722123456","123",1,3,"Form 4 Y4S2"))
                sid=c.execute("SELECT id FROM students WHERE adm_no='ED/00530/018'").fetchone()[0]
                c.execute("INSERT INTO furniture(student_id,locker_no,chair_no,books,assigned_by,ts) VALUES(?,?,?,?,?,?)",(sid,"LK-118","CH-042","Biology Textbook","Furniture Dept",int(time.time())))
                c.execute("INSERT INTO assignments(teacher_id,subject_id,form,title,description,ts) VALUES(?,?,?,?,?,?)",(1,3,4,"Biology CAT 1","Test",int(time.time())))
                aid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
                c.execute("INSERT INTO questions(assignment_id,qtype,text,a,b,c,d,answer,marks) VALUES(?,?,?,?,?,?,?,?,?)",(aid,"mcq","What is photosynthesis?","Making food","Respiration","Digestion","Excretion","A",2))
                c.execute("INSERT INTO questions(assignment_id,qtype,text,marks) VALUES(?,?,?,?)",(aid,"open","Explain photosynthesis in detail",10))
            c.execute("UPDATE teachers SET subject_id=3 WHERE code='T001' AND subject_id=4 AND name LIKE '%Biology%'")
            c.execute("UPDATE assignments SET subject_id=3 WHERE title='Biology CAT 1' AND subject_id=4")
            c.commit()
    except Exception as e:
        print(f"Init error: {e}")
        # If init fails, delete and recreate
        try: os.remove(DB)
        except: pass
        with sqlite3.connect(DB) as c:
            c.executescript(SCHEMA)

init()

def need(role):
    def deco(fn):
        @wraps(fn)
        def w(*a,**k):
            if session.get("role")=="admin": return fn(*a,**k)
            if session.get("role")!=role:
                flash(f"Please login as {role}")
                return redirect(url_for("login",role=role))
            return fn(*a,**k)
        return w
    return deco

# Secure admin credentials: username, password, and access code are stored only as salted hashes.
# These default credentials are created once for a fresh database; change them after first login.
with sqlite3.connect(DB) as _admin_db:
    _admin_db.execute("CREATE TABLE IF NOT EXISTS admin_credentials (id INTEGER PRIMARY KEY, username_hash TEXT NOT NULL, password_hash TEXT NOT NULL, auth_code_hash TEXT NOT NULL, created_at INTEGER NOT NULL)")
    _has_admin = _admin_db.execute("SELECT 1 FROM admin_credentials LIMIT 1").fetchone()
    if not _has_admin:
        _admin_db.execute(
            "INSERT INTO admin_credentials(username_hash,password_hash,auth_code_hash,created_at) VALUES(?,?,?,?)",
            (generate_password_hash("@admin"), generate_password_hash("@admin2030"), generate_password_hash("37302720"), int(time.time()))
        )
    else:
        # Upgrade the earlier default password only if it is still in use.
        # Custom passwords are not overwritten.
        _existing = _admin_db.execute("SELECT id, password_hash FROM admin_credentials").fetchall()
        for _row in _existing:
            try:
                if check_password_hash(_row[1], "br @admin2030"):
                    _admin_db.execute("UPDATE admin_credentials SET password_hash=? WHERE id=?",
                                      (generate_password_hash("@admin2030"), _row[0]))
            except Exception:
                pass
    _admin_db.commit()

def formnum(v):
    """'4', 4, 'Form 4', 'F4' -> 4 ; empty/unknown -> 0"""
    m=re.search(r"\d+",str(v if v is not None else ""))
    return int(m.group()) if m else 0

def visible_to(item_form, student_form):
    """A resource is visible if it is for all forms (0), the student's form is unknown, or the forms match."""
    f=formnum(item_form)
    return f==0 or student_form==0 or f==student_form

PAGE='''<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>MSU Portal</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
:root{--p1:#667eea;--p2:#764ba2;--green:#00a65a;--blue:#00c0ef;--bg:#f1f5f9;--ink:#1e293b;--muted:#64748b}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);font-size:13px;color:var(--ink)}
.topbar{background:linear-gradient(135deg,var(--p1),var(--p2));height:58px;display:flex;align-items:center;justify-content:space-between;color:#fff;padding:0 18px;position:sticky;top:0;z-index:100;box-shadow:0 2px 12px rgba(102,126,234,.35)}
.brand{font-weight:800;font-size:16px;display:flex;align-items:center;gap:10px}.logo{width:34px;height:34px;border-radius:10px;background:rgba(255,255,255,.2);display:grid;place-items:center}
.who{display:flex;align-items:center;gap:10px}.avatar{width:34px;height:34px;border-radius:50%;background:#fff;color:var(--p2);display:grid;place-items:center;font-weight:800}
.wn{display:flex;flex-direction:column;line-height:1.2;font-weight:600}.wn small{opacity:.8;font-weight:400;text-transform:capitalize}
.out{color:#fff;background:rgba(255,255,255,.18);width:34px;height:34px;border-radius:10px;display:grid;place-items:center;text-decoration:none}.out:hover{background:rgba(255,255,255,.3)}
.main{display:flex;min-height:calc(100vh - 58px)}
.sidebar{width:236px;background:#fff;flex-shrink:0;box-shadow:2px 0 14px rgba(15,23,42,.05);padding:14px 0}
.nav a{display:flex;gap:12px;align-items:center;padding:11px 16px;margin:3px 12px;border-radius:10px;color:#475569;text-decoration:none;font-weight:600;transition:all .15s}
.nav a i{width:18px;text-align:center}.nav a:hover{background:#eef2ff;color:var(--p1)}.nav a.on{background:linear-gradient(135deg,var(--p1),var(--p2));color:#fff;box-shadow:0 4px 12px rgba(102,126,234,.35)}
.content{flex:1;padding:22px;min-width:0}
.box{background:#fff;border-radius:14px;box-shadow:0 2px 8px rgba(15,23,42,.06);margin:14px 0}.box-header{padding:14px 18px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;align-items:center}.box-body{padding:18px}
.box h3{font-size:15px;margin-bottom:10px;color:#1e293b}
h2{font-size:20px;margin-bottom:4px}
.tbl{overflow-x:auto}table{width:100%;border-collapse:collapse}
th{background:#f8fafc;color:#475569;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
td,th{padding:11px 10px;border-bottom:1px solid #eef2f7;font-size:13px;text-align:left}tbody tr:hover td,table tr:hover td{background:#fafbff}
.btn{padding:8px 14px;border-radius:9px;border:0;cursor:pointer;font-weight:600;color:#fff;text-decoration:none;display:inline-flex;gap:6px;align-items:center;font-size:12px;transition:all .15s}
.btn:hover{filter:brightness(1.08);transform:translateY(-1px)}.btn[disabled]{opacity:.5;cursor:not-allowed;transform:none}
.btn-green{background:var(--green)}.btn-blue{background:#3498db}.btn-danger{background:#e74c3c}.btn-orange{background:#e67e22}.btn-ghost{background:#7f8c8d}
input,select,textarea{padding:10px 12px;border:1px solid #dbe3ee;border-radius:10px;width:100%;margin:4px 0 10px;font-family:inherit;font-size:13px;background:#fff}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--p1);box-shadow:0 0 0 3px rgba(102,126,234,.18)}
label{font-weight:600;color:#475569;font-size:12px}
#toasts{position:fixed;right:14px;top:70px;z-index:200}.toast{background:#1e293b;color:#fff;padding:12px 16px;border-radius:12px;font-size:12px;border-left:4px solid #f39c12;margin:6px 0;box-shadow:0 6px 18px rgba(0,0,0,.2);max-width:340px}
/* shared dashboard components */
.hero{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border-radius:16px;padding:24px 26px;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:center;box-shadow:0 8px 24px rgba(102,126,234,.3)}
.hero h1{font-size:23px;margin-bottom:6px}.hero p{opacity:.92}.chip{display:inline-block;background:rgba(255,255,255,.2);padding:4px 12px;border-radius:20px;font-size:12px;margin:6px 6px 0 0}
.h-teacher{background:linear-gradient(135deg,#0ea5e9,#2563eb)!important;box-shadow:0 8px 24px rgba(37,99,235,.3)!important}
.h-finance{background:linear-gradient(135deg,#8e44ad,#e84393)!important;box-shadow:0 8px 24px rgba(142,68,173,.3)!important}
.h-furn{background:linear-gradient(135deg,#f12711,#f5af19)!important;box-shadow:0 8px 24px rgba(241,39,17,.25)!important}
.h-lib{background:linear-gradient(135deg,#11998e,#2ecc71)!important;box-shadow:0 8px 24px rgba(17,153,142,.3)!important}
.h-parent{background:linear-gradient(135deg,#16a085,#27ae60)!important}
.hero .btn{background:#fff;color:#4c3fb5}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:16px 0}
.stat{background:#fff;border-radius:14px;padding:16px;display:flex;gap:12px;align-items:center;box-shadow:0 2px 8px rgba(15,23,42,.06)}
.stat i{width:46px;height:46px;border-radius:12px;display:grid;place-items:center;color:#fff;font-size:18px;flex-shrink:0}.stat b{font-size:22px;display:block}.stat span{color:var(--muted);font-size:12px}
.sec{display:flex;justify-content:space-between;align-items:center;margin:24px 0 10px}.sec h3{font-size:16px;color:#1e293b}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:16px}
.card{background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 8px rgba(15,23,42,.06);transition:transform .15s,box-shadow .15s}.card:hover{transform:translateY(-3px);box-shadow:0 10px 22px rgba(15,23,42,.1)}
.card video{width:100%;aspect-ratio:16/9;background:#111;display:block}.pad{padding:13px 15px}.pad h4{font-size:14px;margin-bottom:4px}.meta{color:var(--muted);font-size:12px;margin-bottom:8px}
.badge{padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;display:inline-block}.pending{background:#fff3cd;color:#92600a}.done{background:#dcfce7;color:#15803d}.bad{background:#fee2e2;color:#b91c1c}.info{background:#e0f2fe;color:#0369a1}
.empty{background:#fff;border-radius:14px;padding:28px;text-align:center;color:var(--muted);box-shadow:0 2px 8px rgba(15,23,42,.05)}.empty i{font-size:30px;color:#cbd5e1;display:block;margin-bottom:8px}
.acard{border-left:5px solid #667eea}.acard.isdone{border-left-color:#00a65a}
.row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.drow{display:flex;align-items:center;gap:12px;background:#fff;border-radius:12px;padding:12px 14px;margin:8px 0;box-shadow:0 2px 8px rgba(15,23,42,.05)}.drow i.ic{font-size:22px;color:#667eea;width:30px;text-align:center}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.tab{padding:9px 18px;border-radius:22px;background:#fff;text-decoration:none;font-weight:600;color:#475569;box-shadow:0 2px 6px rgba(15,23,42,.06);transition:all .15s}
.tab:hover{color:var(--p1)}.tab.on{background:linear-gradient(135deg,var(--p1),var(--p2));color:#fff}
.qa{display:flex;gap:14px;align-items:center;background:#fff;border-radius:14px;padding:16px;text-decoration:none;color:inherit;box-shadow:0 2px 8px rgba(15,23,42,.06);transition:all .15s}
.qa:hover{transform:translateY(-3px);box-shadow:0 10px 22px rgba(15,23,42,.1)}.qa i{width:46px;height:46px;border-radius:12px;display:grid;place-items:center;color:#fff;font-size:18px;flex-shrink:0}.qa b{display:block}.qa span{color:var(--muted);font-size:12px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}.progress{height:8px;background:#e2e8f0;border-radius:6px;overflow:hidden;min-width:90px}.progress>div{height:100%;background:linear-gradient(90deg,#00a65a,#2ecc71)}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.toolbar input,.toolbar select{margin:0;width:auto;min-width:150px}
.chips a{display:inline-flex;gap:6px;align-items:center;padding:8px 15px;border-radius:22px;background:#fff;text-decoration:none;color:#475569;font-weight:600;box-shadow:0 2px 6px rgba(15,23,42,.06);margin:0 6px 8px 0}.chips a.on{background:#11998e;color:#fff}
.lib{overflow:visible}.lib video,.lib img.pv{border-radius:14px 14px 0 0}.lib .tile{height:150px;display:grid;place-items:center;background:linear-gradient(135deg,#eef2ff,#e0e7ff);border-radius:14px 14px 0 0;color:#667eea;font-size:46px}
.lib img.pv{width:100%;height:170px;object-fit:cover;display:block}
.share{position:relative}.share summary{list-style:none;cursor:pointer}.share summary::-webkit-details-marker{display:none}
.sharebox{position:absolute;bottom:115%;left:0;background:#fff;border-radius:12px;box-shadow:0 10px 28px rgba(15,23,42,.22);padding:10px;display:flex;flex-direction:column;gap:6px;z-index:30;min-width:170px}
@media(max-width:800px){.main{flex-direction:column}.sidebar{width:100%;padding:6px 0;overflow-x:auto}.nav{display:flex}.nav a{white-space:nowrap;margin:2px 4px}.two{grid-template-columns:1fr}.wn{display:none}.content{padding:14px}}
@media print{.topbar,.sidebar,form,#toasts,.hero .btn,.tabs{display:none!important}.content{padding:0}}
</style></head><body>
{% if session.role %}
<header class=topbar><div class=brand><span class=logo><i class="fa fa-graduation-cap"></i></span> {{portal_school_name}}</div>
<div class=who><span class=avatar>{{(session.name or 'U')[:1]}}</span><span class=wn>{{session.name}}<small>{{session.role}}</small></span><a href="/logout" class=out title="Log out"><i class="fa fa-power-off"></i></a></div></header>
<div class=main><aside class=sidebar><nav class=nav>
{% set menus={
'student':[('/student','fa-house','Dashboard'),('/library','fa-photo-film','Library'),('/team_chat','fa-users','Team Chat')],
'parent':[('/parent','fa-people-roof','Parent Home'),('/library','fa-photo-film','Library')],
'teacher':[('/teacher','fa-chalkboard-teacher','Teacher Home'),('/teacher/content','fa-cloud-arrow-up','Upload &amp; Written Work'),('/library','fa-photo-film','Library'),('/team_chat','fa-users','Team Chat')],
'admin':[('/admin','fa-shield-halved','Admin Home'),('/admin/content','fa-cloud-arrow-up','Upload Videos / Files'),('/teacher','fa-chalkboard-teacher','Teacher view'),('/student','fa-graduation-cap','Student view'),('/library','fa-photo-film','Library'),('/furniture','fa-chair','Furniture'),('/finance','fa-calculator','Finance'),('/team_chat','fa-users','Team Chat')],
'finance':[('/finance','fa-calculator','Finance')],
'furniture':[('/furniture','fa-chair','Furniture')]} %}
{% for href,icon,label in menus.get(session.role,[]) %}<a href="{{href}}" class="{{'on' if request.path==href else ''}}"><i class="fa {{icon}}"></i> <span>{{label|safe}}</span></a>{% endfor %}
</nav></aside><div class=content>{{body|safe}}</div></div>
{% else %}{{body|safe}}{% endif %}
<div id=toasts>{% for m in get_flashed_messages() %}<div class=toast>{{m}}</div>{% endfor %}</div>
<script>
function filterRows(inp,id){var v=inp.value.toLowerCase();document.querySelectorAll('#'+id+' tbody tr').forEach(function(r){r.style.display=r.textContent.toLowerCase().indexOf(v)>-1?'':'none'})}
setTimeout(function(){var t=document.getElementById('toasts');if(t)t.style.display='none'},7000);
</script>
</body></html>'''

def page(body_tpl, **ctx):
    body = render_template_string(body_tpl, **ctx)
    return render_template_string(PAGE, body=body, **ctx)

@app.route("/")
def home():
    if session.get("role"): return redirect(url_for("dash"))
    school_name = get_setting("school_name", "MSU Portal")
    logo = get_setting("logo", "")
    logo_html = (f'<img src="/school-logo" alt="School logo" style="width:96px;height:96px;object-fit:contain;border-radius:18px;background:#fff;padding:6px;margin-bottom:12px">' if logo else '<div style="font-size:54px;color:#667eea;margin-bottom:12px"><i class="fa fa-graduation-cap"></i></div>')
    return page(f'''<div style="min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#667eea,#764ba2);padding:20px"><div class=box style="max-width:500px;width:100%"><div class=box-body style="text-align:center">{logo_html}<h1>{{{{portal_school_name}}}}</h1><p style="color:#64748b">School Portal — please choose your login type.</p><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px"><a href="/login/admin" class="btn" style="justify-content:center;padding:14px;background:#2c3e50;font-size:14px"><i class="fa fa-shield-halved"></i> Admin</a><a href="/login/teacher" class="btn" style="justify-content:center;padding:12px;background:#3498db">Teacher</a><a href="/login/student" class="btn btn-green" style="justify-content:center;padding:12px">Student</a><a href="/login/parent" class="btn" style="justify-content:center;padding:12px;background:#16a085">Parent</a><a href="/login/furniture" class="btn" style="justify-content:center;padding:12px;background:#e67e22">Furniture</a><a href="/login/finance" class="btn" style="justify-content:center;padding:12px;background:#8e44ad">Finance</a></div></div></div></div>''')

@app.route("/login/<role>",methods=["GET","POST"])
def login(role):
    if role not in ("admin","teacher","student","furniture","finance"):
        return redirect("/")

    if request.method=="POST":
        try:
            if role=="admin":
                user=request.form.get("user","").strip()
                pw=request.form.get("pw","")
                auth_code=request.form.get("auth_code","").strip()
                admin_rows=q("SELECT username_hash,password_hash,auth_code_hash FROM admin_credentials")
                valid=False
                for row in admin_rows:
                    try:
                        if (check_password_hash(row["username_hash"], user)
                            and check_password_hash(row["password_hash"], pw)
                            and check_password_hash(row["auth_code_hash"], auth_code)):
                            valid=True
                            break
                    except Exception:
                        continue
                if valid:
                    session.clear()
                    session["role"]="admin"
                    session["uid"]=0
                    session["name"]="School Administrator"
                    return redirect("/admin")
                else:
                    flash("Admin sign-in failed. Check username, password and authentication code.")
            elif role=="furniture":
                user=request.form.get("user","").strip()
                pw=request.form.get("pw","").strip()
                if user=="furniture" and pw=="furniture123":
                    session.clear()
                    session["role"]="furniture"
                    session["uid"]=0
                    session["name"]="Furniture Dept"
                    return redirect("/furniture")
                else:
                    flash("Wrong! Use furniture / furniture123")
            elif role=="finance":
                user=request.form.get("user","").strip()
                pw=request.form.get("pw","").strip()
                if user=="finance" and pw=="finance123":
                    session.clear()
                    session["role"]="finance"
                    session["uid"]=0
                    session["name"]="Finance Officer"
                    return redirect("/finance")
                else:
                    flash("Wrong! Use finance / finance123")
            elif role=="student":
                name=request.form.get("name","").strip()
                adm=request.form.get("adm_no","").strip()
                u=q("SELECT * FROM students WHERE adm_no=? AND lower(name)=lower(?)",(adm,name),True)
                if u:
                    session.clear()
                    session["role"]="student"
                    session["uid"]=u["id"]
                    session["name"]=u["name"]
                    return redirect("/student")
                else:
                    flash("Student not found! Try ODIWUOR, Francis Okello / ED/00530/018")
            elif role=="teacher":
                code=request.form.get("code","").strip()
                u=q("SELECT * FROM teachers WHERE code=?",(code,),True)
                if u or code=="teacher":
                    session.clear()
                    session["role"]="teacher"
                    session["uid"]=u["id"] if u else 1
                    session["name"]=u["name"] if u else "Teacher"
                    return redirect("/teacher")
                else:
                    flash("Teacher code not found! Try T001")
        except Exception as e:
            print(f"Login error: {e}")
            flash(f"Login error: {e} - Try deleting school.db and run again")

    if role=="student":
        fields=[("name","Full Name e.g ODIWUOR, Francis Okello"),("adm_no","Adm No e.g ED/00530/018")]
    elif role=="teacher":
        fields=[("code","Teacher Code e.g T001"),("phone","Phone (optional)")]
    else:
        fields=[("user","Username"),("pw","Password")]

    return page('''
<div style="min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#667eea,#764ba2);padding:18px">
<div class=box style="max-width:420px;width:92%"><div class=box-body>
<div style="text-align:center;margin-bottom:16px">{% if portal_logo %}<img src="/school-logo" alt="School logo" style="width:82px;height:82px;object-fit:contain;border-radius:16px;background:#fff;padding:5px">{% else %}<div style="font-size:42px;color:#667eea"><i class="fa fa-graduation-cap"></i></div>{% endif %}<h2>{{portal_school_name}}</h2><p>{{role.title()}} Login</p></div>
{% if role=='furniture' %}<p style="background:#fff3cd;padding:8px;border-radius:6px;font-size:12px">Use: <b>furniture</b> / <b>furniture123</b></p>{% endif %}
<form method=post>
{% for k,l in fields %}<label>{{l}}</label><input name={{k}} {{'type=password' if k=='pw' else ''}} {{'' if k=='phone' else 'required'}}>{% endfor %}
{% if role=='admin' %}<label>Authentication code</label><input name=auth_code type=password inputmode=numeric autocomplete=one-time-code required>{% endif %}
<button class="btn btn-green" style="width:100%;padding:12px;margin-top:10px"><i class="fa fa-sign-in-alt"></i> Sign In as {{role.title()}}</button>
</form>
<p style="margin-top:12px;font-size:11px;text-align:center"><a href="/">&larr; Back to Home</a></p>
</div></div></div>
''',role=role,fields=fields,portal_logo=get_setting('logo',''))

@app.route("/logout")
def logout():session.clear();return redirect("/")
@app.route("/dash")
def dash():
    r=session.get("role")
    return redirect({ "student":"/student","teacher":"/teacher","admin":"/admin","finance":"/finance","furniture":"/furniture","parent":"/parent"}.get(r,"/"))

def fdate(ts):
    try: return datetime.fromtimestamp(int(ts)).strftime("%d %b %Y")
    except Exception: return ""
app.jinja_env.filters["fdate"]=fdate

def count(sql,args=()):
    try:
        r=q(sql,args,True); return r[0] if r else 0
    except Exception: return 0

@app.route("/admin",methods=["GET","POST"])
def admin():
    if session.get("role")!="admin":
        flash("Please login as Admin - admin / admin123")
        return redirect("/login/admin")
    tab=request.args.get("tab","overview")
    if request.method=="POST":
        action=request.form.get("action","")
        try:
            if action=="teacher":
                q("INSERT INTO teachers(name,code,phone,subject_id,department_id,classes) VALUES(?,?,?,?,?,?)",(request.form["name"],request.form["code"],request.form["phone"],int(request.form.get("subject_id",1)),int(request.form.get("department_id",2)),request.form["classes"]))
                flash("Teacher added!")
            elif action=="student":
                q("INSERT INTO students(name,adm_no,form,parent_phone,department_id,gender) VALUES(?,?,?,?,?,?)",(request.form["name"],request.form["adm_no"],formnum(request.form["form"]) or 4,request.form["parent_phone"],int(request.form.get("department_id",2)),request.form["gender"]))
                flash("Student added!")
        except Exception as e:
            flash(f"Error: {e}")
        return redirect(f"/admin?tab={tab}")
    teachers=q("SELECT t.*, d.name dname, s.name sname FROM teachers t LEFT JOIN departments d ON d.id=t.department_id LEFT JOIN subjects s ON s.id=t.subject_id ORDER BY t.name")
    students=q("SELECT s.*, d.name dname FROM students s LEFT JOIN departments d ON d.id=s.department_id ORDER BY s.id DESC")
    subjects=q("SELECT * FROM subjects ORDER BY name")
    stats=dict(students=count("SELECT COUNT(*) FROM students"),teachers=count("SELECT COUNT(*) FROM teachers"),
               files=count("SELECT COUNT(*) FROM files"),assignments=count("SELECT COUNT(*) FROM assignments"),
               submissions=count("SELECT COUNT(*) FROM submissions"),messages=count("SELECT COUNT(*) FROM team_discussions"))
    recent_files=q("SELECT f.title,f.kind,f.ts, CASE WHEN f.teacher_id=0 THEN 'Admin' ELSE t.name END who FROM files f LEFT JOIN teachers t ON t.id=f.teacher_id ORDER BY f.id DESC LIMIT 5")
    recent_asg=q("SELECT a.title, subj.name sub, a.ts, (SELECT COUNT(*) FROM submissions WHERE assignment_id=a.id) ns FROM assignments a LEFT JOIN subjects subj ON subj.id=a.subject_id ORDER BY a.id DESC LIMIT 5")
    return page("""
<div class="hero"><div><h1><i class="fa fa-shield-halved"></i> Admin Control Centre</h1><p>Manage teachers, students, files, fees and furniture from one place.</p>
<span class=chip><i class="fa fa-calendar"></i> {{today}}</span></div>
<div class=row><a href="/admin/content" class=btn><i class="fa fa-cloud-arrow-up"></i> Upload files</a> <a href="/library" class=btn><i class="fa fa-photo-film"></i> Library</a></div></div>
<div class=tabs>
<a class="tab {{'on' if tab=='overview'}}" href="/admin?tab=overview"><i class="fa fa-gauge"></i> Overview</a>
<a class="tab {{'on' if tab=='teachers'}}" href="/admin?tab=teachers"><i class="fa fa-chalkboard-user"></i> Teachers</a>
<a class="tab {{'on' if tab=='students'}}" href="/admin?tab=students"><i class="fa fa-user-graduate"></i> Students</a></div>

{% if tab=='teachers' %}
<div class=two>
<div class=box><div class=box-body><h3><i class="fa fa-user-plus"></i> Add teacher</h3><form method=post><input type=hidden name=action value=teacher>
<input name=name placeholder="Full name" required><input name=code placeholder="Teacher code e.g T003" required><input name=phone placeholder="Phone">
<select name=subject_id>{% for s in subjects %}<option value={{s.id}}>{{s.name}}</option>{% endfor %}</select>
<select name=department_id><option value=1>Humanities</option><option value=2 selected>Science</option><option value=3>Languages</option><option value=4>Mathematics</option></select>
<input name=classes placeholder="Classes e.g Form 4 Y4S2"><button class="btn btn-green" style="width:100%;justify-content:center"><i class="fa fa-plus"></i> Add teacher</button></form></div></div>
<div class=box><div class=box-body><div class=row style="justify-content:space-between"><h3>Teachers ({{teachers|length}})</h3><input placeholder="Search..." oninput="filterRows(this,'tbl-t')" style="width:180px;margin:0"></div>
<div class=tbl><table id=tbl-t><thead><tr><th>Name</th><th>Code</th><th>Subject</th><th>Dept</th><th>Phone</th></tr></thead><tbody>
{% for t in teachers %}<tr><td><b>{{t.name}}</b></td><td><span class="badge info">{{t.code}}</span></td><td>{{t.sname or '-'}}</td><td>{{t.dname or '-'}}</td><td>{{t.phone}}</td></tr>{% endfor %}</tbody></table></div></div></div></div>

{% elif tab=='students' %}
<div class=two>
<div class=box><div class=box-body><h3><i class="fa fa-user-plus"></i> Register student</h3><form method=post><input type=hidden name=action value=student>
<input name=name placeholder="Name e.g ODIWUOR, Francis Okello" required><input name=adm_no placeholder="Admission no" required>
<input name=form placeholder="Form (1-4)" value=4><input name=parent_phone placeholder="Parent phone (used for parent login)" required>
<select name=department_id><option value=2>Science</option><option value=1>Humanities</option><option value=3>Languages</option><option value=4>Mathematics</option></select>
<input name=gender placeholder="Gender"><button class="btn btn-green" style="width:100%;justify-content:center"><i class="fa fa-plus"></i> Register student</button></form></div></div>
<div class=box><div class=box-body><div class=row style="justify-content:space-between"><h3>Students ({{students|length}})</h3><input placeholder="Search..." oninput="filterRows(this,'tbl-s')" style="width:180px;margin:0"></div>
<div class=tbl><table id=tbl-s><thead><tr><th>Name</th><th>Adm</th><th>Form</th><th>Parent phone</th><th>Dept</th></tr></thead><tbody>
{% for s in students %}<tr><td><b>{{s.name}}</b></td><td>{{s.adm_no}}</td><td><span class="badge info">Form {{s.form}}</span></td><td>{{s.parent_phone}}</td><td>{{s.dname or '-'}}</td></tr>{% endfor %}</tbody></table></div></div></div></div>

{% else %}
<div class=stats>
<div class=stat><i class="fa fa-user-graduate" style="background:#667eea"></i><div><b>{{stats.students}}</b><span>Students</span></div></div>
<div class=stat><i class="fa fa-chalkboard-user" style="background:#0ea5e9"></i><div><b>{{stats.teachers}}</b><span>Teachers</span></div></div>
<div class=stat><i class="fa fa-folder-open" style="background:#e74c3c"></i><div><b>{{stats.files}}</b><span>Files uploaded</span></div></div>
<div class=stat><i class="fa fa-pen-to-square" style="background:#f39c12"></i><div><b>{{stats.assignments}}</b><span>Assignments</span></div></div>
<div class=stat><i class="fa fa-circle-check" style="background:#00a65a"></i><div><b>{{stats.submissions}}</b><span>Submissions</span></div></div>
<div class=stat><i class="fa fa-comments" style="background:#8e44ad"></i><div><b>{{stats.messages}}</b><span>Team messages</span></div></div></div>
<div class=sec><h3>Quick actions</h3></div>
<div class=grid>
<a class=qa href="/admin?tab=teachers"><i class="fa fa-chalkboard-user" style="background:#0ea5e9"></i><div><b>Teachers</b><span>Add and view teachers</span></div></a>
<a class=qa href="/admin?tab=students"><i class="fa fa-user-graduate" style="background:#667eea"></i><div><b>Students</b><span>Register learners and parent phones</span></div></a>
<a class=qa href="/admin/content"><i class="fa fa-cloud-arrow-up" style="background:#e74c3c"></i><div><b>Upload videos / files</b><span>Share with students</span></div></a>
<a class=qa href="/library"><i class="fa fa-photo-film" style="background:#11998e"></i><div><b>Library</b><span>Everything uploaded</span></div></a>
<a class=qa href="/finance"><i class="fa fa-calculator" style="background:#8e44ad"></i><div><b>Finance</b><span>Fees and bursary</span></div></a>
<a class=qa href="/furniture"><i class="fa fa-chair" style="background:#f39c12"></i><div><b>Furniture</b><span>Lockers, chairs, books</span></div></a>
<a class=qa href="/team_chat"><i class="fa fa-comments" style="background:#00a65a"></i><div><b>Team chat</b><span>Text, voice and video</span></div></a></div>
<div class=two>
<div class=box><div class=box-body><h3><i class="fa fa-clock-rotate-left"></i> Recent uploads</h3><div class=tbl><table><thead><tr><th>Title</th><th>Type</th><th>By</th><th>Date</th></tr></thead><tbody>
{% for f in recent_files %}<tr><td>{{f.title}}</td><td><span class="badge info">{{f.kind}}</span></td><td>{{f.who or 'Teacher'}}</td><td>{{f.ts|fdate}}</td></tr>{% else %}<tr><td colspan=4>Nothing uploaded yet</td></tr>{% endfor %}</tbody></table></div></div></div>
<div class=box><div class=box-body><h3><i class="fa fa-clock-rotate-left"></i> Recent assignments</h3><div class=tbl><table><thead><tr><th>Title</th><th>Subject</th><th>Done by</th><th>Date</th></tr></thead><tbody>
{% for a in recent_asg %}<tr><td>{{a.title}}</td><td>{{a.sub or '-'}}</td><td>{{a.ns}}</td><td>{{a.ts|fdate}}</td></tr>{% else %}<tr><td colspan=4>No assignments yet</td></tr>{% endfor %}</tbody></table></div></div></div></div>
{% endif %}
""",tab=tab,teachers=teachers,students=students,subjects=subjects,stats=stats,recent_files=recent_files,recent_asg=recent_asg,today=datetime.now().strftime("%A, %d %B %Y"))

@app.route("/furniture",methods=["GET","POST"])
def furniture_portal():
    if session.get("role") not in ("furniture","admin"):
        flash("Please login as Furniture - furniture / furniture123")
        return redirect("/login/furniture")
    if request.method=="POST":
        try:
            s=q("SELECT id FROM students WHERE adm_no=?",(request.form["adm_no"].strip(),),True)
            if not s:
                flash(f"Student Adm {request.form['adm_no']} not found!")
            else:
                q("INSERT INTO furniture(student_id,locker_no,chair_no,books,assigned_by,ts) VALUES(?,?,?,?,?,?)",(s["id"],request.form["locker_no"],request.form["chair_no"],request.form["books"],session["name"],int(time.time())))
                q("UPDATE students SET locker_no=?, chair_no=?, books=? WHERE id=?",(request.form["locker_no"],request.form["chair_no"],request.form["books"],s["id"]))
                flash(f"Furniture assigned to {request.form['adm_no']}: Locker {request.form['locker_no']}, Chair {request.form['chair_no']}")
        except Exception as e:
            flash(f"Error: {e}")
        return redirect("/furniture")
    furniture_list=q("SELECT f.*, s.name, s.adm_no FROM furniture f JOIN students s ON s.id=f.student_id ORDER BY f.id DESC LIMIT 15")
    students=q("SELECT * FROM students ORDER BY name")
    total=len(students)
    assigned=len([s for s in students if (s["locker_no"] or "").strip() or (s["chair_no"] or "").strip()])
    return page("""
<div class="hero h-furn"><div><h1><i class="fa fa-chair"></i> Furniture Department</h1><p>Assign lockers, chairs and books to learners.</p>
<span class=chip>Logged in as {{session.name}}</span></div></div>
<div class=stats>
<div class=stat><i class="fa fa-user-graduate" style="background:#667eea"></i><div><b>{{total}}</b><span>Students</span></div></div>
<div class=stat><i class="fa fa-circle-check" style="background:#00a65a"></i><div><b>{{assigned}}</b><span>With furniture</span></div></div>
<div class=stat><i class="fa fa-hourglass-half" style="background:#f39c12"></i><div><b>{{total-assigned}}</b><span>Still to assign</span></div></div></div>
<div class=box><div class=box-body><h3><i class="fa fa-pen-ruler"></i> Assign furniture</h3>
<form method=post style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;align-items:end">
<div><label>Admission no</label><input id=f_adm name=adm_no list=adms placeholder="Start typing..." required autocomplete=off></div>
<div><label>Locker</label><input id=f_lk name=locker_no placeholder="e.g LK-118" required></div>
<div><label>Chair</label><input id=f_ch name=chair_no placeholder="e.g CH-042" required></div>
<div><label>Books</label><input id=f_bk name=books placeholder="e.g Biology Textbook" required></div>
<div><button class="btn btn-green" style="width:100%;justify-content:center;padding:11px;margin-bottom:10px"><i class="fa fa-check"></i> Assign</button></div></form>
<datalist id=adms>{% for s in students %}<option value="{{s.adm_no}}">{{s.name}}</option>{% endfor %}</datalist></div></div>
<div class=box><div class=box-body><div class=row style="justify-content:space-between"><h3><i class="fa fa-users"></i> All students</h3><input placeholder="Search name or adm..." oninput="filterRows(this,'tbl-f')" style="width:220px;margin:0"></div>
<div class=tbl><table id=tbl-f><thead><tr><th>Name</th><th>Adm</th><th>Form</th><th>Locker</th><th>Chair</th><th>Books</th><th>Status</th><th></th></tr></thead><tbody>
{% for s in students %}<tr><td><b>{{s.name}}</b></td><td>{{s.adm_no}}</td><td>{{s.form}}</td><td>{{s.locker_no or '-'}}</td><td>{{s.chair_no or '-'}}</td><td>{{s.books or '-'}}</td>
<td>{% if s.locker_no or s.chair_no %}<span class="badge done">Assigned</span>{% else %}<span class="badge pending">Pending</span>{% endif %}</td>
<td><button class="btn btn-blue" type=button data-adm="{{s.adm_no}}" data-lk="{{s.locker_no or ''}}" data-ch="{{s.chair_no or ''}}" data-bk="{{s.books or ''}}" onclick="fillAssign(this)"><i class="fa fa-pen"></i> Edit</button></td></tr>
{% else %}<tr><td colspan=8>No students yet - the admin registers them first</td></tr>{% endfor %}</tbody></table></div></div></div>
<div class=box><div class=box-body><h3><i class="fa fa-clock-rotate-left"></i> Recent assignments</h3><div class=tbl><table><thead><tr><th>Student</th><th>Adm</th><th>Locker</th><th>Chair</th><th>Books</th><th>By</th><th>Date</th></tr></thead><tbody>
{% for f in furniture_list %}<tr><td>{{f.name}}</td><td>{{f.adm_no}}</td><td><b>{{f.locker_no}}</b></td><td><b>{{f.chair_no}}</b></td><td>{{f.books}}</td><td>{{f.assigned_by}}</td><td>{{f.ts|fdate}}</td></tr>{% else %}<tr><td colspan=7>No assignments yet</td></tr>{% endfor %}</tbody></table></div></div></div>
<script>function fillAssign(b){document.getElementById('f_adm').value=b.dataset.adm;document.getElementById('f_lk').value=b.dataset.lk;document.getElementById('f_ch').value=b.dataset.ch;document.getElementById('f_bk').value=b.dataset.bk;window.scrollTo({top:0,behavior:'smooth'});document.getElementById('f_lk').focus()}</script>
""",furniture_list=furniture_list,students=students,total=total,assigned=assigned)

BILLED_PER_YEAR=155750

@app.route("/finance",methods=["GET","POST"])
def finance():
    if session.get("role") not in ("finance","admin"):
        flash("Please login as Finance - finance / finance123")
        return redirect("/login/finance")
    if request.method=="POST":
        try:
            s=q("SELECT id,form FROM students WHERE adm_no=?",(request.form["adm_no"].strip(),),True)
            if s:
                typ=request.form.get("type","fee")
                if typ not in ("fee","bursary"): typ="fee"
                q("INSERT INTO fees(student_id,form,term,amount,ts,note,type) VALUES(?,?,?,?,?,?,?)",(s["id"],s["form"],1,float(request.form["amount"]),int(time.time()),request.form.get("note",""),typ))
                flash(f"{typ.title()} of Ksh {request.form['amount']} recorded for {request.form['adm_no']}")
            else:
                flash("Admission number not found")
        except Exception as e: flash(f"Error: {e}")
        return redirect("/finance")
    all_students=q("""
        SELECT s.id, s.name, s.adm_no, s.form, s.parent_phone,
        (SELECT COALESCE(SUM(amount),0) FROM fees WHERE student_id=s.id AND type='fee') total_fee,
        (SELECT COALESCE(SUM(amount),0) FROM fees WHERE student_id=s.id AND type='bursary') total_bursary
        FROM students s ORDER BY s.name""")
    collected=sum(s["total_fee"] for s in all_students); bursary=sum(s["total_bursary"] for s in all_students)
    outstanding=max(0,BILLED_PER_YEAR*len(all_students)-collected-bursary)
    students=list(all_students)
    filter_form=request.args.get("form","")
    filter_search=request.args.get("search","")
    sort_by=request.args.get("sort","name")
    if filter_form: students=[s for s in students if str(formnum(s["form"]))==filter_form]
    if filter_search: students=[s for s in students if filter_search.lower() in s["name"].lower() or filter_search.lower() in s["adm_no"].lower()]
    if sort_by=="form": students=sorted(students, key=lambda x: formnum(x["form"]))
    if request.args.get("download")=="csv":
        buf=io.StringIO();w=csv.writer(buf)
        w.writerow(["Name","Adm","Form","Parent phone","Total fee","Bursary","Balance"])
        for s in students:
            w.writerow([s["name"],s["adm_no"],s["form"],s["parent_phone"],s["total_fee"],s["total_bursary"],BILLED_PER_YEAR-s["total_fee"]-s["total_bursary"]])
        return Response(buf.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment;filename=students_fees.csv"})
    return page("""
<div class="hero h-finance"><div><h1><i class="fa fa-calculator"></i> Finance Office</h1><p>Record fees, deposit bursaries, and print or download balances.</p>
<span class=chip>Annual fee billed: Ksh {{'{:,.0f}'.format(billed)}} per learner</span></div></div>
<div class=stats>
<div class=stat><i class="fa fa-user-graduate" style="background:#667eea"></i><div><b>{{all_count}}</b><span>Learners</span></div></div>
<div class=stat><i class="fa fa-coins" style="background:#00a65a"></i><div><b>{{'{:,.0f}'.format(collected)}}</b><span>Fees collected (Ksh)</span></div></div>
<div class=stat><i class="fa fa-hand-holding-heart" style="background:#0ea5e9"></i><div><b>{{'{:,.0f}'.format(bursary)}}</b><span>Bursary (Ksh)</span></div></div>
<div class=stat><i class="fa fa-triangle-exclamation" style="background:#e74c3c"></i><div><b>{{'{:,.0f}'.format(outstanding)}}</b><span>Outstanding (Ksh)</span></div></div></div>
<div class=two>
<div class=box><div class=box-body><h3><i class="fa fa-money-bill-wave" style="color:#00a65a"></i> Record fee payment</h3><form method=post><input type=hidden name=type value=fee>
<input name=adm_no placeholder="Admission no" required><input name=amount type=number step=any min=1 placeholder="Amount (Ksh)" required><input name=note placeholder="Note e.g M-Pesa code">
<button class="btn btn-green" style="width:100%;justify-content:center;padding:11px"><i class="fa fa-check"></i> Save payment</button></form></div></div>
<div class=box><div class=box-body><h3><i class="fa fa-hand-holding-heart" style="color:#0ea5e9"></i> Deposit bursary</h3><form method=post><input type=hidden name=type value=bursary>
<input name=adm_no placeholder="Admission no" required><input name=amount type=number step=any min=1 placeholder="Bursary amount (Ksh)" required><input name=note placeholder="Bursary source e.g CDF">
<button class="btn btn-blue" style="width:100%;justify-content:center;padding:11px"><i class="fa fa-check"></i> Deposit bursary</button></form></div></div></div>
<div class=box><div class=box-body><h3><i class="fa fa-filter"></i> Filter, sort, download, print</h3>
<form method=get class=toolbar><select name=form><option value="">All forms</option>{% for n in [1,2,3,4] %}<option value={{n}} {{'selected' if request.args.get('form')==n|string}}>Form {{n}}</option>{% endfor %}</select>
<input name=search placeholder="Search name or adm" value="{{request.args.get('search','')}}"><select name=sort><option value=name>Sort by name</option><option value=form {{'selected' if request.args.get('sort')=='form'}}>Sort by form</option></select>
<button class="btn btn-green"><i class="fa fa-magnifying-glass"></i> Apply</button>
<a href="/finance?download=csv&form={{request.args.get('form','')}}&search={{request.args.get('search','')}}&sort={{request.args.get('sort','name')}}" class="btn btn-blue"><i class="fa fa-download"></i> Download CSV</a>
<button type=button onclick="window.print()" class="btn" style="background:#8e44ad"><i class="fa fa-print"></i> Print list</button></form></div></div>
<div class=box><div class=box-body><h3>Fee balances &middot; {{students|length}} learner{{'' if students|length==1 else 's'}}</h3><div class=tbl><table><thead><tr><th>Name</th><th>Adm</th><th>Form</th><th>Parent phone</th><th>Paid</th><th>Bursary</th><th>Progress</th><th>Balance</th></tr></thead><tbody>
{% for s in students %}{% set bal=billed-s.total_fee-s.total_bursary %}{% set pct=[((s.total_fee+s.total_bursary)/billed*100)|round|int,100]|min %}
<tr><td><b>{{s.name}}</b></td><td>{{s.adm_no}}</td><td>{{s.form}}</td><td>{{s.parent_phone}}</td><td>{{'{:,.0f}'.format(s.total_fee)}}</td><td>{{'{:,.0f}'.format(s.total_bursary)}}</td>
<td><div class=progress title="{{pct}}% cleared"><div style="width:{{pct}}%"></div></div></td>
<td>{% if bal<=0 %}<span class="badge done">Cleared</span>{% else %}<span class="badge bad">Ksh {{'{:,.0f}'.format(bal)}}</span>{% endif %}</td></tr>
{% else %}<tr><td colspan=8>No learners match</td></tr>{% endfor %}</tbody></table></div></div></div>
""",students=students,billed=BILLED_PER_YEAR,collected=collected,bursary=bursary,outstanding=outstanding,all_count=len(all_students))

@app.route("/team_chat",methods=["GET","POST"])
def team_chat():
    if not session.get("role"): return redirect("/")
    if request.method=="POST":
        try:
            msg_type=request.form["msg_type"];text=request.form.get("text","")[:1000];filename=""
            f=request.files.get("file")
            if f and f.filename:
                filename=f"{int(time.time())}_{secure_filename(f.filename)}";f.save(os.path.join(UPLOADS,filename))
            sid=session["uid"] if session.get("role")=="student" else 0
            form=4
            if sid:
                s=q("SELECT form FROM students WHERE id=?",(sid,),True)
                if s: form=s["form"]
            q("INSERT INTO team_discussions(student_id,form,subject_id,msg_type,text,filename,ts) VALUES(?,?,?,?,?,?,?)",(sid,form,1,msg_type,text,filename,int(time.time())))
            flash("Team message sent! Saved in admin DB for filtering.")
        except Exception as e: flash(f"Error: {e}")
        return redirect("/team_chat")
    filter_form=request.args.get("form","");filter_type=request.args.get("type","");filter_search=request.args.get("search","")
    sql="SELECT td.*, s.name, s.adm_no FROM team_discussions td LEFT JOIN students s ON s.id=td.student_id WHERE 1=1";args=[]
    if filter_form: sql+=" AND td.form=?";args.append(filter_form)
    if filter_type: sql+=" AND td.msg_type=?";args.append(filter_type)
    if filter_search: sql+=" AND td.text LIKE?";args.append(f"%{filter_search}%")
    sql+=" ORDER BY td.id DESC LIMIT 100"
    try: discussions=q(sql,args)
    except: discussions=[]
    return page("""
<h2><i class="fa fa-users"></i> Team Discussion - Voice Note, Video, Text</h2>
<div style="display:grid;grid-template-columns:1fr 300px;gap:12px">
<div class=box><div class=box-body><h3>Send Message</h3><form method=post enctype=multipart/form-data><select name=msg_type required><option value=text>Text</option><option value=voice>Voice Note</option><option value=video>Video</option></select><textarea name=text placeholder="Ask question..."></textarea><input type=file name=file><button class="btn btn-green" style="width:100%">Send to Team Chat</button></form></div></div>
<div class=box><div class=box-header><h3>Admin Filter</h3></div><div class=box-body><form method=get><select name=form><option value="">All Forms</option><option value=4>Form 4</option></select><select name=type><option value="">All Types</option><option value=text>Text</option><option value=voice>Voice</option><option value=video>Video</option></select><input name=search placeholder="Search"><button class="btn btn-blue" style="width:100%">Filter</button></form></div></div>
</div>
<div class=box><div class=box-body><h3>Team Chat - {{discussions|length}} messages</h3>{% for d in discussions %}<div style="border:1px solid #eee;padding:10px;margin:8px 0;border-radius:8px"><b>{{d.name or 'Staff'}}</b> - Form {{d.form}} - <span style="background:#e0f2fe;padding:2px 6px;border-radius:10px">{{d.msg_type}}</span><p>{{d.text}}</p>{% if d.filename %}{% if d.msg_type=='voice' %}<audio controls src="/file/{{d.filename}}" style="width:100%"></audio>{% elif d.msg_type=='video' %}<video controls src="/file/{{d.filename}}" style="width:100%;max-width:300px"></video>{% else %}<a href="/file/{{d.filename}}" download>Download</a>{% endif %}{% endif %}</div>{% else %}No discussions yet{% endfor %}</div></div>
""",discussions=discussions)

@app.route("/teacher")
@need("teacher")
def teacher():
    tid=session["uid"] if session.get("role")=="teacher" else 1
    t=q("SELECT t.*, s.name sub, d.name dname FROM teachers t LEFT JOIN subjects s ON s.id=t.subject_id LEFT JOIN departments d ON d.id=t.department_id WHERE t.id=?",(tid,),True)
    if not t: t={"id":1,"name":"Teacher","sub":"","dname":"","department_id":2,"classes":""}
    asg=q("SELECT a.*, (SELECT COUNT(*) FROM questions WHERE assignment_id=a.id) nq, (SELECT COUNT(*) FROM questions WHERE assignment_id=a.id AND qtype='open') nopen, (SELECT COUNT(*) FROM submissions WHERE assignment_id=a.id) ns, s.name sub FROM assignments a LEFT JOIN subjects s ON s.id=a.subject_id WHERE a.teacher_id=? ORDER BY a.id DESC",(t["id"],))
    myfiles=q("SELECT f.*, (SELECT COUNT(*) FROM file_likes WHERE file_id=f.id) likes FROM files f WHERE f.teacher_id=? ORDER BY f.id DESC",(t["id"],))
    stats=dict(asg=len(asg),subs=sum(a["ns"] for a in asg),files=len(myfiles),likes=sum(f["likes"] for f in myfiles))
    return page("""
<div class="hero h-teacher"><div><h1><i class="fa fa-chalkboard-user"></i> Welcome, {{t.name}}</h1><p>Share lessons, set work and mark your learners.</p>
{% if t.sub %}<span class=chip><i class="fa fa-book"></i> {{t.sub}}</span>{% endif %}{% if t.dname %}<span class=chip><i class="fa fa-building-columns"></i> {{t.dname}}</span>{% endif %}{% if t.classes %}<span class=chip><i class="fa fa-people-group"></i> {{t.classes}}</span>{% endif %}</div>
<a href="/teacher/content" class=btn><i class="fa fa-cloud-arrow-up"></i> Upload videos &amp; files</a></div>
<div class=stats>
<div class=stat><i class="fa fa-pen-to-square" style="background:#f39c12"></i><div><b>{{stats.asg}}</b><span>Assignments</span></div></div>
<div class=stat><i class="fa fa-inbox" style="background:#00a65a"></i><div><b>{{stats.subs}}</b><span>Submissions received</span></div></div>
<div class=stat><i class="fa fa-folder-open" style="background:#e74c3c"></i><div><b>{{stats.files}}</b><span>Files shared</span></div></div>
<div class=stat><i class="fa fa-heart" style="background:#e84393"></i><div><b>{{stats.likes}}</b><span>Likes from students</span></div></div></div>
<div class=sec><h3>Quick actions</h3></div>
<div class=grid>
<a class=qa href="/teacher/content"><i class="fa fa-cloud-arrow-up" style="background:#e74c3c"></i><div><b>Upload content</b><span>Videos, documents, audio</span></div></a>
<a class=qa href="/teacher/content"><i class="fa fa-file-pen" style="background:#2563eb"></i><div><b>Written assignment</b><span>Non-multiple-choice questions</span></div></a>
<a class=qa href="/library"><i class="fa fa-photo-film" style="background:#11998e"></i><div><b>Library</b><span>See what students see</span></div></a>
<a class=qa href="/team_chat"><i class="fa fa-comments" style="background:#8e44ad"></i><div><b>Team chat</b><span>Talk to learners</span></div></a></div>
<div class=box><div class=box-body><h3><i class="fa fa-circle-plus" style="color:#00a65a"></i> Create assignment (MCQ + written questions)</h3>
<form method=post action="/teacher/create_assignment" style="display:grid;grid-template-columns:2fr 1fr auto;gap:10px;align-items:start">
<input name=title placeholder="Assignment title" required><select name=form><option value=0>All forms</option><option value=1>Form 1</option><option value=2>Form 2</option><option value=3>Form 3</option><option value=4>Form 4</option></select>
<button class="btn btn-green" style="padding:11px 18px;margin-top:4px"><i class="fa fa-plus"></i> Create</button>
<textarea name=description placeholder="Instructions for students (optional)" style="grid-column:1/-1"></textarea></form></div></div>
<div class=sec><h3><i class="fa fa-pen-to-square" style="color:#f39c12"></i> My assignments</h3></div>
{% if asg %}<div class=grid>{% for a in asg %}<div class="card acard"><div class=pad>
<div class=row style="justify-content:space-between"><h4>{{a.title}}</h4><span class="badge {{'done' if a.ns else 'pending'}}">{{a.ns}} submitted</span></div>
<div class=meta>{{a.sub or 'General'}} &middot; {{'All forms' if a.form==0 else 'Form '~a.form}} &middot; {{a.nq}} question{{'' if a.nq==1 else 's'}} ({{a.nopen}} written)</div>
<div class=row><a href="/teacher/assignment/{{a.id}}" class="btn btn-blue"><i class="fa fa-list-check"></i> Questions</a> <a href="/teacher/assignment/{{a.id}}/edit" class="btn btn-orange"><i class="fa fa-pen"></i> Edit</a> <a href="/teacher/submissions/{{a.id}}" class="btn btn-green"><i class="fa fa-check-double"></i> Mark</a> <a href="/assignment/preview/{{a.id}}" class="btn btn-ghost"><i class="fa fa-eye"></i></a></div></div></div>{% endfor %}</div>
{% else %}<div class=empty><i class="fa fa-clipboard-list"></i>No assignments yet. Create one above.</div>{% endif %}
<div class=sec><h3><i class="fa fa-folder-open" style="color:#e74c3c"></i> My latest uploads</h3><a href="/teacher/content">Manage all &rarr;</a></div>
{% if myfiles %}{% for f in myfiles[:5] %}<div class=drow><i class="fa {{icons.get(f.kind,'fa-file')}} ic"></i><div style="flex:1"><b>{{f.title}}</b><div class=meta style="margin:0">{{f.kind}} &middot; {{'All forms' if f.form==0 else 'Form '~f.form}} &middot; {{f.ts|fdate}}</div></div><span class="badge info"><i class="fa fa-heart"></i> {{f.likes}}</span></div>{% endfor %}
{% else %}<div class=empty><i class="fa fa-cloud-arrow-up"></i>You haven't uploaded anything yet.</div>{% endif %}
""",t=t,asg=asg,myfiles=myfiles,stats=stats,icons=FILE_ICONS)

@app.route("/teacher/create_assignment",methods=["POST"])
@need("teacher")
def create_assignment():
    tid=session["uid"] if session.get("role")=="teacher" else 1
    try: t=q("SELECT subject_id FROM teachers WHERE id=?",(tid,),True)
    except: t=None
    subj=t["subject_id"] if t else 3
    cur=db().execute("INSERT INTO assignments(teacher_id,subject_id,form,title,description,ts) VALUES(?,?,?,?,?,?)",(tid,subj,formnum(request.form.get("form","0")),request.form["title"],request.form.get("description",""),int(time.time())));db().commit()
    flash("Assignment created!")
    return redirect(f"/teacher/assignment/{cur.lastrowid}")

@app.route("/teacher/assignment/<int:aid>",methods=["GET","POST"])
@need("teacher")
def edit_assignment(aid):
    try: a=q("SELECT a.*, s.name sub FROM assignments a LEFT JOIN subjects s ON s.id=a.subject_id WHERE a.id=?",(aid,),True)
    except: a=None
    if not a: abort(404)
    if session.get("role")!="admin" and a["teacher_id"]!=session["uid"]: abort(403)
    if request.method=="POST":
        try:
            if request.form["action"]=="add_mcq":
                q("INSERT INTO questions(assignment_id,qtype,text,a,b,c,d,answer,marks) VALUES(?,?,?,?,?,?,?,?,?)",(aid,"mcq",request.form["text"],request.form["a"],request.form["b"],request.form["c"],request.form["d"],request.form["answer"],int(request.form.get("marks",1))))
                flash("MCQ added!")
            elif request.form["action"]=="add_open":
                q("INSERT INTO questions(assignment_id,qtype,text,marks) VALUES(?,?,?,?)",(aid,"open",request.form["text"],int(request.form.get("marks",5))))
                flash("Open question added!")
            elif request.form["action"]=="del":
                q("DELETE FROM questions WHERE id=? AND assignment_id=?",(request.form["id"],aid))
        except Exception as e: flash(f"Error: {e}")
        return redirect(f"/teacher/assignment/{aid}")
    try: qs=q("SELECT * FROM questions WHERE assignment_id=?",(aid,))
    except: qs=[]
    return page("""
<h2>Edit Assignment: {{a.title}} - Add MCQ &amp; Open Questions</h2><a href="/teacher" class="btn btn-ghost">&larr; Back</a> <a href="/teacher/assignment/{{a.id}}/edit" class="btn btn-orange">Edit details / written questions</a> <a href="/teacher/submissions/{{a.id}}" class="btn btn-green">See who took &amp; mark</a>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px">
<div class=box><div class=box-body><h3>Add MCQ Question</h3><form method=post><input type=hidden name=action value=add_mcq><textarea name=text placeholder="MCQ Question" required></textarea><div style="display:grid;grid-template-columns:1fr 1fr;gap:6px"><input name=a placeholder="A" required><input name=b placeholder="B" required><input name=c placeholder="C" required><input name=d placeholder="D" required></div><select name=answer><option>A</option><option>B</option><option>C</option><option>D</option></select><input name=marks type=number value=1><button class="btn btn-green" style="width:100%">Add MCQ</button></form></div></div>
<div class=box><div class=box-body><h3>Add Open/Essay Question (Not MCQ)</h3><form method=post><input type=hidden name=action value=add_open><textarea name=text placeholder="Open question e.g Explain photosynthesis..." required></textarea><input name=marks type=number value=5><button class="btn btn-blue" style="width:100%">Add Open/Essay Question</button></form></div></div>
</div>
<div class=box><div class=box-body><h3>Questions ({{qs|length}})</h3>{% for x in qs %}<div style="border:1px solid #eee;padding:10px;margin:6px 0"><b>Q{{loop.index}} [{{x.qtype.upper()}} {{x.marks}} marks]</b> {{x.text}} {% if x.qtype=='mcq' %}<br>A){{x.a}} B){{x.b}} C){{x.c}} D){{x.d}} Answer:{{x.answer}}{% endif %}<form method=post style="display:inline"><input type=hidden name=action value=del><input type=hidden name=id value={{x.id}}><button class="btn btn-danger" style="padding:2px 6px">Delete</button></form></div>{% endfor %}</div></div>
""",a=a,qs=qs)

@app.route("/teacher/results/<int:aid>")
@need("teacher")
def teacher_results(aid):
    return redirect(f"/teacher/submissions/{aid}")

@app.route("/assignment/preview/<int:aid>")
def assignment_preview(aid):
    if not session.get("role"): return redirect("/")
    try:
        a=q("SELECT a.*, s.name sub, t.name tname FROM assignments a LEFT JOIN subjects s ON s.id=a.subject_id LEFT JOIN teachers t ON t.id=a.teacher_id WHERE a.id=?",(aid,),True)
        qs=q("SELECT * FROM questions WHERE assignment_id=?",(aid,))
    except: return redirect("/")
    if not a: return redirect("/")
    if request.args.get("download")=="1":
        content=f"Assignment: {a['title']}\nSubject: {a['sub']}\nTeacher: {a['tname']}\n\n"
        for i,x in enumerate(qs,1):
            content+=f"Q{i} [{x['qtype']} {x['marks']}m]: {x['text']}\n"
            if x['qtype']=='mcq': content+=f"A){x['a']} B){x['b']} C){x['c']} D){x['d']}\n"
            content+="\n"
        return Response(content, mimetype="text/plain", headers={"Content-Disposition":f"attachment;filename=assignment_{aid}.txt"})
    return page("""
<div class=box><div class=box-body><h2>Assignment Preview - {{a.title}} - {{a.sub}}</h2><p>Teacher: {{a.tname}}</p><a href="/assignment/preview/{{a.id}}?download=1" class="btn btn-green">Download Preview</a> <a href="javascript:window.print()" class="btn btn-blue">Print</a> {% if session.role in ('student','admin') %}<a href="/take/{{a.id}}" class="btn btn-orange">Take Now</a>{% endif %}</div></div>
<div class=box><div class=box-body>{% for x in qs %}<div style="border:1px solid #eee;padding:10px;margin:6px 0"><b>Q{{loop.index}} [{{x.qtype.upper()}} {{x.marks}}m]</b> {{x.text}}{% if x.qtype=='mcq' %}<br>A){{x.a}} B){{x.b}} C){{x.c}} D){{x.d}}{% endif %}</div>{% endfor %}</div></div>
""",a=a,qs=qs)

@app.route("/take/<int:aid>",methods=["GET","POST"])
def take(aid):
    if session.get("role") not in ("student","admin"): return redirect("/")
    sid=session["uid"] if session.get("role")!="admin" else q("SELECT id FROM students LIMIT 1",one=True)["id"]
    if q("SELECT 1 FROM submissions WHERE assignment_id=? AND student_id=?",(aid,sid),True):
        flash("Already submitted");return redirect("/student")
    try: qs=q("SELECT * FROM questions WHERE assignment_id=?",(aid,));a=q("SELECT * FROM assignments WHERE id=?",(aid,),True)
    except: qs=[];a={"title":"Assignment"}
    if request.method=="POST":
        score=0;total=0;answers={}
        for x in qs:
            total+=x["marks"] or 1;ans=request.form.get(f"q{x['id']}","").strip();answers[str(x["id"])]=ans
            if x["qtype"]=="mcq" and ans.upper()==(x["answer"] or "").upper(): score+=x["marks"] or 1
            # written (open) answers are marked by the teacher
        q("INSERT INTO submissions(assignment_id,student_id,score,total,answers,ts) VALUES(?,?,?,?,?,?)",(aid,sid,score,total,json.dumps(answers),int(time.time())))
        flash(f"Submitted! Auto score so far: {score}/{total} (written answers are marked by your teacher)");return redirect("/student")
    return page("""
<div class=box><div class=box-body><h2>Take {{a.title}}</h2><form method=post>{% for x in qs %}<div style="border:1px solid #eee;padding:12px;margin:8px 0"><b>Q{{loop.index}} [{{x.qtype.upper()}} {{x.marks}}m]</b> {{x.text}}{% if x.qtype=='mcq' %}{% for l in 'abcd' %}<label style="display:flex;gap:8px;padding:6px;border:1px solid #eee;margin:4px 0"><input type=radio name=q{{x.id}} value={{l|upper}} required style="width:auto;margin:0"> {{l|upper}}. {{x[l]}}</label>{% endfor %}{% else %}<textarea name=q{{x.id}} placeholder="Write your answer" style="height:110px" required></textarea>{% endif %}</div>{% endfor %}<button class="btn btn-green" style="width:100%;padding:12px">Submit</button></form></div></div>
""",a=a,qs=qs)

FILE_ICONS={"video":"fa-circle-play","audio":"fa-music","document":"fa-file-lines","image":"fa-image","file":"fa-file-zipper"}

@app.route("/student")
def student():
    if session.get("role") not in ("student","admin"): return redirect("/")
    if session.get("role")=="admin":
        first_s=q("SELECT id FROM students LIMIT 1",one=True)
        if not first_s:
            flash("Add a student first (Admin > Manage Students)"); return redirect("/admin?tab=students")
        sid=first_s["id"]
    else:
        sid=session["uid"]
    s=q("SELECT s.*, d.name dname FROM students s LEFT JOIN departments d ON d.id=s.department_id WHERE s.id=?",(sid,),True)
    if not s:
        flash("Student record not found - please log in again"); return redirect("/logout")
    s=dict(s); sform=formnum(s["form"])
    parts=(s["name"] or "Student").split(",")
    first=(parts[1].strip().split()[0] if len(parts)>1 and parts[1].strip() else parts[0].strip().split()[0])
    files=[]
    for r in q("""SELECT f.*, CASE WHEN f.teacher_id=0 THEN 'Admin' ELSE t.name END tname, t.phone tphone, subj.name sub,
                  (SELECT COUNT(*) FROM file_likes WHERE file_id=f.id) likes,
                  (SELECT COUNT(*) FROM file_likes WHERE file_id=f.id AND student_id=?) liked
                  FROM files f LEFT JOIN teachers t ON t.id=f.teacher_id LEFT JOIN subjects subj ON subj.id=f.subject_id
                  ORDER BY f.id DESC""",(sid,)):
        if visible_to(r["form"],sform):
            d=dict(r); d["share"]=request.url_root+f"share/{r['id']}"; files.append(d)
    asg=[dict(r) for r in q("""SELECT a.*, subj.name sub, CASE WHEN a.teacher_id=0 THEN 'Admin' ELSE t.name END tname,
                  sub2.score, sub2.total, (SELECT COUNT(*) FROM questions WHERE assignment_id=a.id) nq
                  FROM assignments a LEFT JOIN subjects subj ON subj.id=a.subject_id LEFT JOIN teachers t ON t.id=a.teacher_id
                  LEFT JOIN submissions sub2 ON sub2.assignment_id=a.id AND sub2.student_id=?
                  ORDER BY a.id DESC""",(sid,)) if visible_to(r["form"],sform)]
    videos=[f for f in files if f["kind"]=="video"]
    docs=[f for f in files if f["kind"]!="video"]
    pending=[a for a in asg if a["score"] is None]
    return page("""
<style>
.hero{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border-radius:16px;padding:26px;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:center;box-shadow:0 8px 24px rgba(102,126,234,.35)}
.hero h1{font-size:24px;margin-bottom:6px}.chip{display:inline-block;background:rgba(255,255,255,.2);padding:4px 12px;border-radius:20px;font-size:12px;margin:4px 6px 0 0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin:16px 0}
.stat{background:#fff;border-radius:14px;padding:16px;display:flex;gap:12px;align-items:center;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.stat i{width:44px;height:44px;border-radius:12px;display:grid;place-items:center;color:#fff;font-size:18px;flex-shrink:0}.stat b{font-size:22px;display:block}.stat span{color:#64748b;font-size:12px}
.sec{display:flex;justify-content:space-between;align-items:center;margin:24px 0 10px}.sec h3{font-size:16px;color:#2c3e50}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:16px}
.card{background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.06);transition:transform .15s,box-shadow .15s}.card:hover{transform:translateY(-3px);box-shadow:0 8px 20px rgba(0,0,0,.1)}
.card video{width:100%;aspect-ratio:16/9;background:#111;display:block}.pad{padding:12px 14px}.pad h4{font-size:14px;margin-bottom:4px;color:#1e293b}.meta{color:#64748b;font-size:12px;margin-bottom:8px}
.badge{padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;display:inline-block}.pending{background:#fff3cd;color:#92600a}.done{background:#dcfce7;color:#15803d}
.empty{background:#fff;border-radius:14px;padding:28px;text-align:center;color:#64748b;box-shadow:0 2px 8px rgba(0,0,0,.05)}.empty i{font-size:30px;color:#cbd5e1;display:block;margin-bottom:8px}
.acard{border-left:5px solid #667eea}.acard.isdone{border-left-color:#00a65a}
.row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.drow{display:flex;align-items:center;gap:12px;background:#fff;border-radius:12px;padding:12px 14px;margin:8px 0;box-shadow:0 2px 8px rgba(0,0,0,.05)}.drow i.ic{font-size:22px;color:#667eea;width:30px;text-align:center}
</style>
<div class=hero><div><h1>Welcome back, {{first}}! &#128075;</h1><div>Ready to learn something new today?</div>
<span class=chip><i class="fa fa-id-card"></i> {{s.adm_no}}</span><span class=chip><i class="fa fa-layer-group"></i> Form {{sform or '-'}}</span>{% if s.dname %}<span class=chip><i class="fa fa-flask"></i> {{s.dname}}</span>{% endif %}</div>
<a href="/library" class="btn" style="background:#fff;color:#5b4bc4;padding:12px 18px;font-size:13px"><i class="fa fa-photo-film"></i> Open Library</a></div>
<div class=stats>
<div class=stat><i class="fa fa-circle-play" style="background:#e74c3c"></i><div><b>{{videos|length}}</b><span>Videos</span></div></div>
<div class=stat><i class="fa fa-file-lines" style="background:#3498db"></i><div><b>{{docs|length}}</b><span>Files &amp; documents</span></div></div>
<div class=stat><i class="fa fa-pen-to-square" style="background:#f39c12"></i><div><b>{{pending|length}}</b><span>Assignments to do</span></div></div>
<div class=stat><i class="fa fa-circle-check" style="background:#00a65a"></i><div><b>{{asg|length - pending|length}}</b><span>Completed</span></div></div>
<div class=stat><i class="fa fa-wallet" style="background:#8e44ad"></i><div><b>{{'%.0f'|format(s.wallet_balance or 0)}}</b><span>Wallet (Ksh)</span></div></div>
</div>

<div class=sec><h3><i class="fa fa-circle-play" style="color:#e74c3c"></i> Video lessons</h3>{% if videos|length>6 %}<a href="/library?kind=video">See all {{videos|length}} &rarr;</a>{% endif %}</div>
{% if videos %}<div class=grid>{% for f in videos[:6] %}<div class=card>
<video controls preload=metadata src="/file/{{f.filename}}#t=0.5">Your browser cannot play this video - use Download.</video>
<div class=pad><h4>{{f.title}}</h4><div class=meta>{{f.sub or 'General'}} &middot; {{f.tname or 'Teacher'}}</div>
<div class=row><a class="btn btn-green" href="/file/{{f.filename}}?dl=1"><i class="fa fa-download"></i> Download</a>
<button class=btn id="like-{{f.id}}" onclick="likeFile({{f.id}})" style="background:{{'#e74c3c' if f.liked else '#95a5a6'}}"><i class="fa fa-heart"></i> <span id="lc-{{f.id}}">{{f.likes}}</span></button>
<button class=btn style="background:#8e44ad" data-title="{{f.title}}" data-url="{{f.share}}" onclick="shareIt(this)"><i class="fa fa-share-nodes"></i> Share</button></div></div></div>{% endfor %}</div>
{% else %}<div class=empty><i class="fa fa-film"></i>No videos for Form {{sform or ''}} yet.<br>When your teacher uploads one it will appear here.</div>{% endif %}

<div class=sec><h3><i class="fa fa-pen-to-square" style="color:#f39c12"></i> My assignments</h3></div>
{% if asg %}<div class=grid>{% for a in asg %}<div class="card acard {{'isdone' if a.score is not none}}"><div class=pad>
<div class=row style="justify-content:space-between"><h4>{{a.title}}</h4>{% if a.score is not none %}<span class="badge done">Score {{a.score}}/{{a.total}}</span>{% else %}<span class="badge pending">To do</span>{% endif %}</div>
<div class=meta>{{a.sub or 'General'}} &middot; {{a.tname or 'Teacher'}} &middot; {{a.nq}} question{{'' if a.nq==1 else 's'}}</div>
{% if a.description %}<p style="font-size:12px;color:#475569;margin-bottom:8px">{{a.description[:120]}}</p>{% endif %}
<div class=row>{% if a.score is none %}<a class="btn btn-green" href="/take/{{a.id}}"><i class="fa fa-pen"></i> Take now</a>{% endif %}
<a class="btn btn-orange" href="/assignment/preview/{{a.id}}"><i class="fa fa-eye"></i> Preview</a>
<a class="btn btn-blue" href="/assignment/preview/{{a.id}}?download=1"><i class="fa fa-download"></i> Download</a></div></div></div>{% endfor %}</div>
{% else %}<div class=empty><i class="fa fa-clipboard-list"></i>No assignments yet.<br>New assignments from your teachers will show up here.</div>{% endif %}

<div class=sec><h3><i class="fa fa-folder-open" style="color:#3498db"></i> Notes, documents &amp; audio</h3></div>
{% if docs %}{% for f in docs[:10] %}<div class=drow><i class="fa {{icons.get(f.kind,'fa-file')}} ic"></i><div style="flex:1"><b>{{f.title}}</b><div class=meta style="margin:0">{{f.sub or 'General'}} &middot; {{f.tname or 'Teacher'}}</div></div>
<a class="btn btn-green" href="/file/{{f.filename}}?dl=1"><i class="fa fa-download"></i> Download</a></div>{% endfor %}
{% else %}<div class=empty><i class="fa fa-folder-open"></i>No documents yet.</div>{% endif %}

<div class=sec><h3><i class="fa fa-chair" style="color:#e67e22"></i> My school items</h3></div>
<div class=stats><div class=stat><i class="fa fa-lock" style="background:#34495e"></i><div><b style="font-size:16px">{{s.locker_no or 'N/A'}}</b><span>Locker</span></div></div>
<div class=stat><i class="fa fa-chair" style="background:#e67e22"></i><div><b style="font-size:16px">{{s.chair_no or 'N/A'}}</b><span>Chair</span></div></div>
<div class=stat><i class="fa fa-book" style="background:#16a085"></i><div><b style="font-size:16px">{{s.books or 'None'}}</b><span>Books</span></div></div></div>
<script>
function likeFile(id){fetch('/like/'+id,{method:'POST'}).then(function(r){return r.json()}).then(function(d){if(d.error){alert(d.error);return}document.getElementById('lc-'+id).textContent=d.likes;document.getElementById('like-'+id).style.background=d.liked?'#e74c3c':'#95a5a6'})}
function shareIt(b){if(navigator.share){navigator.share({title:b.dataset.title,url:b.dataset.url})}else{window.location='/library'}}
</script>
""",s=s,sform=sform,first=first,files=files,videos=videos,docs=docs,asg=asg,pending=pending,icons=FILE_ICONS)

@app.route("/file/<path:name>")
def file(name):
    if not session.get("role"): return redirect("/")
    if request.args.get("dl")=="1":
        nice=re.sub(r"^\d+_","",os.path.basename(name))
        return send_from_directory(UPLOADS,name,as_attachment=True,download_name=nice)
    return send_from_directory(UPLOADS, name)



# ======================= LIBRARY / UPLOADS / WRITTEN WORK / PARENTS =======================
import os, re, time, json, sqlite3
from datetime import datetime
from urllib.parse import quote
from flask import request, redirect, session, flash, jsonify, abort
from werkzeug.utils import secure_filename

REQUIRE_ADM = True          # True: parent enters phone + child's admission no. False: phone only (less secure)
BILLED_PER_YEAR = 155750    # same figure used on your finance page

KIND_BY_EXT = {
    "video": {".mp4", ".webm", ".mov", ".mkv"},
    "audio": {".mp3", ".wav", ".m4a", ".ogg"},
    "document": {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt"},
    "image": {".png", ".jpg", ".jpeg", ".gif"},
    "file": {".zip"},
}
ALLOWED = set().union(*KIND_BY_EXT.values())

EXT_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_likes(id INTEGER PRIMARY KEY, file_id INTEGER, student_id INTEGER, ts INTEGER, UNIQUE(file_id, student_id));
CREATE TABLE IF NOT EXISTS file_shares(id INTEGER PRIMARY KEY, file_id INTEGER, student_id INTEGER, channel TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS open_marks(submission_id INTEGER, question_id INTEGER, marks INTEGER, PRIMARY KEY(submission_id, question_id));
"""


def kind_of(ext):
    for k, exts in KIND_BY_EXT.items():
        if ext in exts:
            return k
    return "file"


def toint(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def last9(p):
    d = re.sub(r"\D", "", p or "")
    return d[-9:] if len(d) >= 9 else ""


def share_links(title, url):
    t, u, m = quote(title), quote(url, safe=""), quote(f"{title} {url}")
    return [
        ("WhatsApp", f"https://wa.me/?text={m}", "fa-brands fa-whatsapp", "#25D366"),
        ("Facebook", f"https://www.facebook.com/sharer/sharer.php?u={u}", "fa-brands fa-facebook", "#1877f2"),
        ("X", f"https://twitter.com/intent/tweet?text={t}&url={u}", "fa-brands fa-x-twitter", "#111"),
        ("Telegram", f"https://t.me/share/url?url={u}&text={t}", "fa-brands fa-telegram", "#0088cc"),
        ("Email", f"mailto:?subject={t}&body={m}", "fa fa-envelope", "#7f8c8d"),
    ]


def register(app, q, db, page, need, DB, UPLOADS):
    app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB uploads
    with sqlite3.connect(DB) as c:
        c.executescript(EXT_SCHEMA)

    def tid_now():
        return session["uid"] if session.get("role") == "teacher" else 1

    def own_assignment(aid):
        a = q("SELECT * FROM assignments WHERE id=?", (aid,), True)
        if not a:
            abort(404)
        if session.get("role") != "admin" and a["teacher_id"] != tid_now():
            abort(403)
        return a

    # ------------------------------------------------------------------ PARENT
    @app.route("/login/parent", methods=["GET", "POST"])
    def parent_login():
        if request.method == "POST":
            phone = last9(request.form.get("phone", ""))
            adm = request.form.get("adm_no", "").strip().lower()
            kids = []
            if phone:
                kids = [s for s in q("SELECT id,name,adm_no,parent_phone FROM students")
                        if last9(s["parent_phone"]) == phone]
                if REQUIRE_ADM:
                    kids = [s for s in kids if s["adm_no"].lower() == adm]
            if kids:
                session.clear()
                session["role"] = "parent"
                session["children"] = [k["id"] for k in kids]
                session["uid"] = kids[0]["id"]
                session["name"] = "Parent of " + ", ".join(k["name"].split(",")[0] for k in kids)
                return redirect("/parent")
            flash("No learner found with that phone number" + (" and admission number." if REQUIRE_ADM else "."))
        return page('''
<div style="min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#667eea,#764ba2)">
<div class=box style="max-width:380px;width:90%"><div class=box-body>
<h2>Parent Login</h2>
<p style="font-size:12px;color:#64748b">Use the phone number you gave the school at registration.</p>
<form method=post>
<label>Phone number</label><input name=phone placeholder="e.g 0792239596" required>
{% if req_adm %}<label>Learner admission no</label><input name=adm_no placeholder="e.g ED/00530/018" required>{% endif %}
<button class="btn btn-green" style="width:100%;padding:12px;margin-top:10px">Sign in as Parent</button>
</form><p style="margin-top:12px;font-size:11px;text-align:center"><a href="/">&larr; Back to Home</a></p>
</div></div></div>''', req_adm=REQUIRE_ADM)

    @app.route("/parent")
    def parent_home():
        if session.get("role") != "parent":
            return redirect("/login/parent")
        ids = session.get("children", [])
        kids = [k for k in (q("SELECT * FROM students WHERE id=?", (i,), True) for i in ids) if k]
        if not kids:
            session.clear()
            return redirect("/login/parent")
        cur = toint(request.args.get("child"), session["uid"])
        if cur not in [k["id"] for k in kids]:
            cur = kids[0]["id"]
        session["uid"] = cur
        kid = next(k for k in kids if k["id"] == cur)
        results = [r for r in q("""SELECT a.title, a.form, subj.name sub, sub2.score, sub2.total FROM assignments a
                       LEFT JOIN subjects subj ON subj.id=a.subject_id
                       LEFT JOIN submissions sub2 ON sub2.assignment_id=a.id AND sub2.student_id=?
                       ORDER BY a.id DESC""", (cur,)) if visible_to(r["form"], formnum(kid["form"]))]
        paid = q("SELECT COALESCE(SUM(amount),0) v FROM fees WHERE student_id=? AND type='fee'", (cur,), True)["v"]
        burs = q("SELECT COALESCE(SUM(amount),0) v FROM fees WHERE student_id=? AND type='bursary'", (cur,), True)["v"]
        return page('''
<div class="hero h-parent"><div><h1><i class="fa fa-people-roof"></i> Parent Portal</h1><p>Follow your child's fees, work and results.</p></div></div>
{% if kids|length>1 %}<div class=box><div class=box-body>Your children: {% for k in kids %}<a href="/parent?child={{k.id}}" class="btn" style="background:{{'#00a65a' if k.id==kid.id else '#95a5a6'}}">{{k.name}}</a> {% endfor %}</div></div>{% endif %}
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px">
<div class=box><div class=box-body><b>{{kid.name}}</b><br>Adm {{kid.adm_no}} &middot; Form {{kid.form}}</div></div>
<div class=box><div class=box-body><b>Fees paid</b><br>Ksh {{paid}}</div></div>
<div class=box><div class=box-body><b>Bursary</b><br>Ksh {{burs}}</div></div>
<div class=box><div class=box-body><b>Fee balance</b><br>Ksh {{billed - paid}}</div></div>
<div class=box><div class=box-body><b>Locker / Chair</b><br>{{kid.locker_no or 'N/A'}} / {{kid.chair_no or 'N/A'}}</div></div>
</div>
<div class=box><div class=box-body><h3>Assignment results</h3><table><tr><th>Subject</th><th>Assignment</th><th>Score</th></tr>
{% for r in results %}<tr><td>{{r.sub}}</td><td>{{r.title}}</td><td>{% if r.score is not none %}<b>{{r.score}}/{{r.total}}</b>{% else %}Not done{% endif %}</td></tr>{% else %}<tr><td colspan=3>No assignments yet</td></tr>{% endfor %}
</table></div></div>''', kids=kids, kid=kid, results=results, paid=paid, burs=burs, billed=BILLED_PER_YEAR)

    # ------------------------------------------------------- TEACHER CONTENT
    @app.route("/teacher/content", methods=["GET", "POST"])
    @need("teacher")
    def teacher_content():
        tid = tid_now()
        t = q("SELECT * FROM teachers WHERE id=?", (tid,), True)
        subj = t["subject_id"] if t else 3
        dept = t["department_id"] if t else 2
        if request.method == "POST":
            act = request.form.get("action")
            if act == "upload":
                f = request.files.get("file")
                if not f or not f.filename:
                    flash("Choose a file first")
                else:
                    ext = os.path.splitext(f.filename)[1].lower()
                    if ext not in ALLOWED:
                        flash("File type not allowed: " + ext)
                    else:
                        name = secure_filename(f.filename) or ("file" + ext)
                        fn = f"{int(time.time())}_{name}"
                        f.save(os.path.join(UPLOADS, fn))
                        title = request.form.get("title", "").strip() or f.filename
                        q("INSERT INTO files(teacher_id,subject_id,department_id,form,kind,title,filename,ts) VALUES(?,?,?,?,?,?,?,?)",
                          (tid, subj, dept, toint(request.form.get("form")), kind_of(ext), title, fn, int(time.time())))
                        flash("Uploaded! Students can now view, download, like and share it.")
            elif act in ("rename", "delete_file"):
                fid = toint(request.form.get("id"))
                row = q("SELECT * FROM files WHERE id=?", (fid,), True)
                if row and (session.get("role") == "admin" or row["teacher_id"] == tid):
                    if act == "rename":
                        q("UPDATE files SET title=?, form=? WHERE id=?",
                          (request.form.get("title", row["title"]).strip() or row["title"], toint(request.form.get("form")), fid))
                        flash("Updated")
                    else:
                        try:
                            os.remove(os.path.join(UPLOADS, row["filename"]))
                        except OSError:
                            pass
                        q("DELETE FROM file_likes WHERE file_id=?", (fid,))
                        q("DELETE FROM files WHERE id=?", (fid,))
                        flash("Deleted")
            elif act == "written":
                lines = [l.strip() for l in request.form.get("questions", "").splitlines() if l.strip()]
                title = request.form.get("title", "").strip()
                if not title or not lines:
                    flash("Give a title and at least one question")
                else:
                    cur = db().execute("INSERT INTO assignments(teacher_id,subject_id,form,title,description,ts) VALUES(?,?,?,?,?,?)",
                                       (tid, subj, toint(request.form.get("form"), 0), title,
                                        request.form.get("description", ""), int(time.time())))
                    aid = cur.lastrowid
                    for l in lines:
                        text, _, m = l.partition("|")
                        db().execute("INSERT INTO questions(assignment_id,qtype,text,marks) VALUES(?,?,?,?)",
                                     (aid, "open", text.strip(), toint(m.strip(), 5)))
                    db().commit()
                    flash("Written assignment created")
                    return redirect(f"/teacher/assignment/{aid}/edit")
            return redirect("/teacher/content")
        files = q("""SELECT f.*, (SELECT COUNT(*) FROM file_likes WHERE file_id=f.id) likes,
                     (SELECT COUNT(*) FROM file_shares WHERE file_id=f.id) shares
                     FROM files f WHERE f.teacher_id=? ORDER BY f.id DESC""", (tid,))
        asg = q("""SELECT a.*, (SELECT COUNT(*) FROM questions WHERE assignment_id=a.id) nq,
                   (SELECT COUNT(*) FROM questions WHERE assignment_id=a.id AND qtype='open') nopen,
                   (SELECT COUNT(*) FROM submissions WHERE assignment_id=a.id) ns
                   FROM assignments a WHERE a.teacher_id=? ORDER BY a.id DESC""", (tid,))
        return page('''
<div class="hero h-teacher"><div><h1><i class="fa fa-cloud-arrow-up"></i> My Content &amp; Written Assignments</h1><p>Upload videos, notes and documents, and set written work.</p></div><a href="/teacher" class=btn>&larr; Teacher home</a></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
<div class=box><div class=box-body><h3>Upload video / audio / document</h3>
<form method=post enctype=multipart/form-data><input type=hidden name=action value=upload>
<input name=title placeholder="Title" required>
<select name=form><option value=0 selected>All forms</option><option value=1>Form 1</option><option value=2>Form 2</option><option value=3>Form 3</option><option value=4>Form 4</option></select>
<input type=file name=file required>
<p style="font-size:11px;color:#64748b">Allowed: mp4, webm, mov, mkv, mp3, wav, m4a, ogg, pdf, doc(x), ppt(x), xls(x), txt, png, jpg, gif, zip</p>
<button class="btn btn-green" style="width:100%">Upload to students</button></form></div></div>
<div class=box><div class=box-body><h3>New written (non-MCQ) assignment</h3>
<form method=post><input type=hidden name=action value=written>
<input name=title placeholder="Assignment title" required>
<textarea name=description placeholder="Instructions"></textarea>
<select name=form><option value=0 selected>All forms</option><option value=1>Form 1</option><option value=2>Form 2</option><option value=3>Form 3</option><option value=4>Form 4</option></select>
<textarea name=questions rows=5 placeholder="One question per line. Optional marks after a bar:&#10;Explain photosynthesis | 10&#10;Describe the human heart | 8" required></textarea>
<button class="btn btn-blue" style="width:100%">Create written assignment</button></form></div></div>
</div>
<div class=box><div class=box-body><h3>My assignments</h3><table><tr><th>Title</th><th>Form</th><th>Questions</th><th>Submitted</th><th>Actions</th></tr>
{% for a in asg %}<tr><td>{{a.title}}</td><td>{{a.form}}</td><td>{{a.nq}} ({{a.nopen}} written)</td><td>{{a.ns}}</td>
<td><a class="btn btn-blue" href="/teacher/assignment/{{a.id}}/edit">Edit</a> <a class="btn btn-green" href="/teacher/submissions/{{a.id}}">Mark</a></td></tr>
{% else %}<tr><td colspan=5>None yet</td></tr>{% endfor %}</table></div></div>
<div class=box><div class=box-body><h3>My uploads ({{files|length}})</h3><table><tr><th>Title</th><th>Type</th><th>Form</th><th>Likes</th><th>Shares</th><th>Actions</th></tr>
{% for f in files %}<tr><td colspan=6><form method=post style="display:flex;gap:6px;align-items:center;flex-wrap:wrap"><input type=hidden name=id value="{{f.id}}">
<input name=title value="{{f.title}}" style="width:230px;margin:0"><span>{{f.kind}}</span>
<select name=form style="width:100px;margin:0">{% for n in [0,1,2,3,4] %}<option value={{n}} {{'selected' if f.form==n}}>{{'All' if n==0 else 'Form '~n}}</option>{% endfor %}</select>
<span><i class="fa fa-heart" style="color:#e74c3c"></i> {{f.likes}}</span><span><i class="fa fa-share-nodes"></i> {{f.shares}}</span>
<button name=action value=rename class="btn btn-blue">Save</button>
<button name=action value=delete_file class="btn btn-danger" onclick="return confirm('Delete this file?')">Delete</button></form></td></tr>
{% else %}<tr><td colspan=6>No uploads yet</td></tr>{% endfor %}</table></div></div>''', files=files, asg=asg)

    # ----------------------------------------------- EDIT WRITTEN ASSIGNMENTS
    @app.route("/teacher/assignment/<int:aid>/edit", methods=["GET", "POST"])
    @need("teacher")
    def edit_assignment_meta(aid):
        a = own_assignment(aid)
        if request.method == "POST":
            act = request.form.get("action")
            if act == "meta":
                q("UPDATE assignments SET title=?, description=?, form=? WHERE id=?",
                  (request.form["title"], request.form.get("description", ""), toint(request.form.get("form"), 0), aid))
            elif act == "q":
                q("UPDATE questions SET text=?, marks=?, answer=CASE WHEN qtype='open' THEN ? ELSE answer END WHERE id=? AND assignment_id=?",
                  (request.form["text"], toint(request.form.get("marks"), 5), request.form.get("guide", ""),
                   toint(request.form.get("id")), aid))
            elif act == "add_open":
                q("INSERT INTO questions(assignment_id,qtype,text,answer,marks) VALUES(?,?,?,?,?)",
                  (aid, "open", request.form["text"], request.form.get("guide", ""), toint(request.form.get("marks"), 5)))
            elif act == "del":
                q("DELETE FROM questions WHERE id=? AND assignment_id=?", (toint(request.form.get("id")), aid))
            flash("Saved")
            return redirect(f"/teacher/assignment/{aid}/edit")
        qs = q("SELECT * FROM questions WHERE assignment_id=? ORDER BY id", (aid,))
        return page('''
<h2>Edit assignment</h2><a href="/teacher/content" class="btn" style="background:#7f8c8d">&larr; Back</a> <a href="/teacher/submissions/{{a.id}}" class="btn btn-green">Mark submissions</a>
<div class=box><div class=box-body><form method=post><input type=hidden name=action value=meta>
<input name=title value="{{a.title}}" required><textarea name=description>{{a.description}}</textarea>
<select name=form>{% for n in [0,1,2,3,4] %}<option value={{n}} {{'selected' if a.form==n}}>{{'All forms' if n==0 else 'Form '~n}}</option>{% endfor %}</select>
<button class="btn btn-green">Save details</button></form></div></div>
<div class=box><div class=box-body><h3>Questions ({{qs|length}})</h3>
{% for x in qs %}<form method=post style="border:1px solid #eee;padding:10px;margin:8px 0;border-radius:8px"><input type=hidden name=id value="{{x.id}}">
<b>Q{{loop.index}} [{{x.qtype.upper()}}]</b><textarea name=text required>{{x.text}}</textarea>
Marks <input name=marks type=number value="{{x.marks}}" style="width:90px">
{% if x.qtype=='open' %}<textarea name=guide placeholder="Marking guide (only teachers see this)">{{x.answer or ''}}</textarea>{% else %}<p style="font-size:11px;color:#64748b">MCQ options are edited on the <a href="/teacher/assignment/{{a.id}}">MCQ editor</a>.</p>{% endif %}
<button name=action value=q class="btn btn-blue">Save</button> <button name=action value=del class="btn btn-danger" onclick="return confirm('Delete question?')">Delete</button></form>
{% endfor %}</div></div>
<div class=box><div class=box-body><h3>Add written question</h3><form method=post><input type=hidden name=action value=add_open>
<textarea name=text placeholder="Question" required></textarea><input name=marks type=number value=5>
<textarea name=guide placeholder="Marking guide (optional)"></textarea><button class="btn btn-green">Add question</button></form></div></div>''', a=a, qs=qs)

    # ------------------------------------------------------------- MARKING
    @app.route("/teacher/submissions/<int:aid>")
    @need("teacher")
    def submissions_list(aid):
        a = own_assignment(aid)
        rows = q("""SELECT sub.id, st.name, st.adm_no, sub.score, sub.total, sub.ts,
                    (SELECT COUNT(*) FROM open_marks WHERE submission_id=sub.id) marked
                    FROM submissions sub JOIN students st ON st.id=sub.student_id
                    WHERE sub.assignment_id=? ORDER BY st.name""", (aid,))
        rows = [dict(r, when=datetime.fromtimestamp(r["ts"]).strftime("%d %b %H:%M")) for r in rows]
        return page('''
<h2>Submissions: {{a.title}}</h2><a href="/teacher/content" class="btn" style="background:#7f8c8d">&larr; Back</a>
<div class=box><div class=box-body><table><tr><th>Student</th><th>Adm</th><th>Score</th><th>Submitted</th><th>Written marked?</th><th></th></tr>
{% for r in rows %}<tr><td>{{r.name}}</td><td>{{r.adm_no}}</td><td><b>{{r.score}}/{{r.total}}</b></td><td>{{r.when}}</td><td>{{'Yes' if r.marked else 'Not yet'}}</td>
<td><a class="btn btn-green" href="/teacher/mark/{{r.id}}">Mark</a></td></tr>{% else %}<tr><td colspan=6>No submissions yet</td></tr>{% endfor %}</table></div></div>''', a=a, rows=rows)

    @app.route("/teacher/mark/<int:sid>", methods=["GET", "POST"])
    @need("teacher")
    def mark_submission(sid):
        sub = q("SELECT sub.*, st.name sname FROM submissions sub JOIN students st ON st.id=sub.student_id WHERE sub.id=?", (sid,), True)
        if not sub:
            abort(404)
        a = own_assignment(sub["assignment_id"])
        qs = q("SELECT * FROM questions WHERE assignment_id=? ORDER BY id", (a["id"],))
        answers = json.loads(sub["answers"] or "{}")
        if request.method == "POST":
            for x in qs:
                if x["qtype"] == "open":
                    m = max(0, min(toint(request.form.get(f"m{x['id']}")), x["marks"] or 0))
                    q("INSERT OR REPLACE INTO open_marks(submission_id,question_id,marks) VALUES(?,?,?)", (sid, x["id"], m))
            mcq = sum((x["marks"] or 1) for x in qs
                      if x["qtype"] == "mcq" and answers.get(str(x["id"]), "").upper() == (x["answer"] or "").upper())
            opn = q("SELECT COALESCE(SUM(marks),0) v FROM open_marks WHERE submission_id=?", (sid,), True)["v"]
            q("UPDATE submissions SET score=? WHERE id=?", (mcq + opn, sid))
            flash(f"Marked. Score is now {mcq + opn}/{sub['total']}")
            return redirect(f"/teacher/submissions/{a['id']}")
        given = {r["question_id"]: r["marks"] for r in q("SELECT * FROM open_marks WHERE submission_id=?", (sid,))}
        return page('''
<h2>Marking {{sub.sname}} &mdash; {{a.title}}</h2><a href="/teacher/submissions/{{a.id}}" class="btn" style="background:#7f8c8d">&larr; Back</a>
<form method=post>{% for x in qs %}<div class=box><div class=box-body>
<b>Q{{loop.index}} [{{x.qtype.upper()}} {{x.marks}} marks]</b> {{x.text}}
<p style="background:#f8fafc;padding:8px;border-radius:6px;margin:8px 0"><b>Answer:</b> {{answers.get(x.id|string) or '(blank)'}}</p>
{% if x.qtype=='open' %}{% if x.answer %}<p style="font-size:11px;color:#64748b">Marking guide: {{x.answer}}</p>{% endif %}
Marks (0&ndash;{{x.marks}}) <input type=number name="m{{x.id}}" min=0 max="{{x.marks}}" value="{{given.get(x.id, 0)}}" style="width:100px">
{% else %}<p>Correct answer: <b>{{x.answer}}</b> &mdash; {{'Correct' if (answers.get(x.id|string) or '').upper()==(x.answer or '').upper() else 'Wrong'}}</p>{% endif %}
</div></div>{% endfor %}<button class="btn btn-green" style="padding:12px 20px">Save marks</button></form>''', sub=sub, a=a, qs=qs, answers=answers, given=given)

    # ------------------------------------------------------------ ADMIN UPLOADS
    @app.route("/admin/content", methods=["GET", "POST"])
    def admin_content():
        if session.get("role") != "admin":
            flash("Please login as Admin - admin / admin123")
            return redirect("/login/admin")
        if request.method == "POST":
            act = request.form.get("action")
            if act == "upload":
                f = request.files.get("file")
                ext = os.path.splitext(f.filename)[1].lower() if f and f.filename else ""
                if not ext:
                    flash("Choose a file first")
                elif ext not in ALLOWED:
                    flash("File type not allowed: " + ext)
                else:
                    fn = f"{int(time.time())}_{secure_filename(f.filename) or 'file' + ext}"
                    f.save(os.path.join(UPLOADS, fn))
                    q("INSERT INTO files(teacher_id,subject_id,department_id,form,kind,title,filename,ts) VALUES(0,?,0,?,?,?,?,?)",
                      (toint(request.form.get("subject_id"), 1), toint(request.form.get("form")), kind_of(ext),
                       request.form.get("title", "").strip() or f.filename, fn, int(time.time())))
                    flash("Uploaded! Students can now preview and download it from their Library.")
            elif act == "delete_file":
                row = q("SELECT * FROM files WHERE id=?", (toint(request.form.get("id")),), True)
                if row:
                    try:
                        os.remove(os.path.join(UPLOADS, row["filename"]))
                    except OSError:
                        pass
                    q("DELETE FROM file_likes WHERE file_id=?", (row["id"],))
                    q("DELETE FROM files WHERE id=?", (row["id"],))
                    flash("Deleted")
            return redirect("/admin/content")
        files = q("""SELECT f.*, CASE WHEN f.teacher_id=0 THEN 'Admin' ELSE t.name END tname, subj.name sub,
                     (SELECT COUNT(*) FROM file_likes WHERE file_id=f.id) likes
                     FROM files f LEFT JOIN teachers t ON t.id=f.teacher_id LEFT JOIN subjects subj ON subj.id=f.subject_id
                     ORDER BY f.id DESC LIMIT 100""")
        subjects = q("SELECT * FROM subjects ORDER BY name")
        return page('''
<div class="hero"><div><h1><i class="fa fa-cloud-arrow-up"></i> Admin Uploads</h1><p>Upload videos, audio and documents for students.</p></div><a href="/admin" class=btn>&larr; Admin home</a></div>
<div class=box><div class=box-body><form method=post enctype=multipart/form-data><input type=hidden name=action value=upload>
<input name=title placeholder="Title" required>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><select name=subject_id>{% for s in subjects %}<option value={{s.id}}>{{s.name}}</option>{% endfor %}</select>
<select name=form><option value=0>All forms</option>{% for n in [1,2,3,4] %}<option value={{n}}>Form {{n}}</option>{% endfor %}</select></div>
<input type=file name=file required>
<p style="font-size:11px;color:#64748b">Best for video: .mp4 (plays in every browser). Max 500 MB.</p>
<button class="btn btn-green" style="width:100%">Upload for students</button></form></div></div>
<div class=box><div class=box-body><h3>All uploads ({{files|length}})</h3><table><tr><th>Title</th><th>Type</th><th>Subject</th><th>By</th><th>Form</th><th>Likes</th><th></th></tr>
{% for f in files %}<tr><td>{{f.title}}</td><td>{{f.kind}}</td><td>{{f.sub or '-'}}</td><td>{{f.tname or 'Teacher'}}</td><td>{{'All' if f.form==0 else f.form}}</td><td>{{f.likes}}</td>
<td><a class="btn btn-blue" href="/file/{{f.filename}}?dl=1">Download</a> <form method=post style="display:inline"><input type=hidden name=id value="{{f.id}}"><button name=action value=delete_file class="btn btn-danger" onclick="return confirm('Delete this file?')">Delete</button></form></td></tr>
{% else %}<tr><td colspan=7>Nothing uploaded yet</td></tr>{% endfor %}</table></div></div>''', files=files, subjects=subjects)

    # ------------------------------------------------- LIBRARY / LIKE / SHARE
    @app.route("/library")
    def library():
        role = session.get("role")
        if role not in ("student", "teacher", "admin", "parent"):
            return redirect("/")
        kind = request.args.get("kind", "")
        search = request.args.get("search", "").strip()
        sid = session["uid"] if role == "student" else -1
        sform = 0
        if role in ("student", "parent"):
            srow = q("SELECT form FROM students WHERE id=?", (session["uid"],), True)
            sform = formnum(srow["form"]) if srow else 0
        sql = """SELECT f.*, CASE WHEN f.teacher_id=0 THEN 'Admin' ELSE t.name END tname, subj.name sub,
                 (SELECT COUNT(*) FROM file_likes WHERE file_id=f.id) likes,
                 (SELECT COUNT(*) FROM file_likes WHERE file_id=f.id AND student_id=?) liked
                 FROM files f LEFT JOIN teachers t ON t.id=f.teacher_id LEFT JOIN subjects subj ON subj.id=f.subject_id WHERE 1=1"""
        args = [sid]
        if search:
            sql += " AND f.title LIKE ?"
            args.append(f"%{search}%")
        rows, counts = [], {}
        for r in q(sql + " ORDER BY f.id DESC LIMIT 300", args):
            if role in ("student", "parent") and not visible_to(r["form"], sform):
                continue
            d = dict(r)
            d["kind"] = d.get("kind") or "file"
            d["filename"] = d.get("filename") or ""
            d["title"] = d.get("title") or d["filename"] or "Untitled"
            d["missing"] = not (d["filename"] and os.path.exists(os.path.join(UPLOADS, d["filename"])))
            d["share"] = request.url_root + f"share/{r['id']}"
            d["links"] = share_links(d["title"], d["share"])
            d["pdf"] = d["filename"].lower().endswith((".pdf", ".txt"))
            counts[d["kind"]] = counts.get(d["kind"], 0) + 1
            if kind and d["kind"] != kind:
                continue
            rows.append(d)
        types = [("", "All", "fa-border-all"), ("video", "Videos", "fa-circle-play"), ("audio", "Audio", "fa-music"),
                 ("document", "Documents", "fa-file-lines"), ("image", "Images", "fa-image"), ("file", "Other", "fa-file-zipper")]
        return page('''
<div class="hero h-lib"><div><h1><i class="fa fa-photo-film"></i> Learning Library</h1><p>Watch, listen, download, like and share lessons from your teachers.</p>
{% if sform %}<span class=chip><i class="fa fa-layer-group"></i> Showing resources for Form {{sform}} + all forms</span>{% endif %}</div>
<form method=get class=toolbar><input name=search placeholder="Search by title..." value="{{search}}">{% if kind %}<input type=hidden name=kind value="{{kind}}">{% endif %}<button class=btn><i class="fa fa-magnifying-glass"></i> Search</button></form></div>
<div class="chips" style="margin-top:16px">{% for k,label,icon in types %}{% set n = total if k=='' else counts.get(k,0) %}{% if k=='' or n %}<a class="{{'on' if kind==k}}" href="/library?kind={{k}}{{'&search='~search if search}}"><i class="fa {{icon}}"></i> {{label}} <small>({{n}})</small></a>{% endif %}{% endfor %}</div>
{% if files %}<div class=grid>{% for f in files %}<div class="card lib">
{% if f.missing %}<div class=tile style="color:#e74c3c"><i class="fa fa-triangle-exclamation"></i></div>
{% elif f.kind=='video' %}<video controls preload=metadata src="/file/{{f.filename}}#t=0.5">Your browser cannot play this video - use Download.</video>
{% elif f.kind=='image' %}<img class=pv src="/file/{{f.filename}}" alt="{{f.title}}">
{% elif f.kind=='audio' %}<div class=tile><i class="fa fa-music"></i></div><audio controls preload=none src="/file/{{f.filename}}" style="width:100%;display:block"></audio>
{% else %}<div class=tile><i class="fa {{icons.get(f.kind,'fa-file')}}"></i></div>{% endif %}
<div class=pad><h4>{{f.title}}</h4>
<div class=meta><span class="badge info">{{f.kind}}</span> {{f.sub or 'General'}} &middot; {{f.tname or 'Teacher'}} &middot; {{f.ts|fdate}}</div>
{% if f.missing %}<p style="color:#b91c1c;font-size:12px;margin-bottom:8px">File is missing on the server - ask the uploader to upload it again.</p>{% endif %}
<div class=row>
{% if not f.missing %}<a class="btn btn-green" href="/file/{{f.filename}}?dl=1"><i class="fa fa-download"></i> Download</a>{% if f.pdf or f.kind=='document' %}<a class="btn btn-orange" href="/file/{{f.filename}}" target=_blank><i class="fa fa-eye"></i> Preview</a>{% endif %}{% endif %}
<button id="like-{{f.id}}" class=btn onclick="likeFile({{f.id}})" style="background:{{'#e74c3c' if f.liked else '#95a5a6'}}" {{'' if can_like else 'disabled title="Only students can like"'}}><i class="fa fa-heart"></i> <span id="lc-{{f.id}}">{{f.likes}}</span></button>
<details class=share><summary class=btn style="background:#8e44ad"><i class="fa fa-share-nodes"></i> Share</summary><div class=sharebox>
{% for label,href,icon,color in f.links %}<a class=btn style="background:{{color}}" href="{{href}}" target=_blank rel=noopener onclick="logShare({{f.id}},'{{label|lower}}')"><i class="{{icon}}"></i> {{label}}</a>{% endfor %}
<button type=button class=btn style="background:#34495e" data-id="{{f.id}}" data-title="{{f.title}}" data-url="{{f.share}}" onclick="copyLink(this)"><i class="fa fa-link"></i> Copy link</button>
<button type=button class=btn style="background:#667eea" data-id="{{f.id}}" data-title="{{f.title}}" data-url="{{f.share}}" onclick="nativeShare(this)"><i class="fa fa-mobile-screen"></i> Share on phone</button></div></details>
</div></div></div>{% endfor %}</div>
{% else %}<div class=empty><i class="fa fa-film"></i>{% if search or kind %}Nothing matches your search.{% else %}Nothing has been uploaded for you yet.<br>When a teacher uploads a video or document it will appear here.{% endif %}</div>{% endif %}
<script>
function likeFile(id){fetch('/like/'+id,{method:'POST'}).then(function(r){return r.json()}).then(function(d){if(d.error){alert(d.error);return}document.getElementById('lc-'+id).textContent=d.likes;document.getElementById('like-'+id).style.background=d.liked?'#e74c3c':'#95a5a6'})}
function logShare(id,ch){fetch('/share_log/'+id+'?channel='+ch,{method:'POST'})}
function copyLink(b){var u=b.dataset.url;var done=function(){alert('Link copied')};if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(u).then(done)}else{var t=document.createElement('textarea');t.value=u;document.body.appendChild(t);t.select();try{document.execCommand('copy')}catch(e){}document.body.removeChild(t);done()}logShare(b.dataset.id,'copy')}
function nativeShare(b){if(navigator.share){navigator.share({title:b.dataset.title,url:b.dataset.url});logShare(b.dataset.id,'native')}else{copyLink(b)}}
</script>''', files=rows, kind=kind, search=search, can_like=(role == "student"), counts=counts,
                    total=sum(counts.values()), types=types, sform=sform, icons=FILE_ICONS)

    @app.route("/like/<int:fid>", methods=["POST"])
    def like(fid):
        if session.get("role") != "student":
            return jsonify(error="Only students can like files"), 403
        if not q("SELECT 1 FROM files WHERE id=?", (fid,), True):
            return jsonify(error="File not found"), 404
        sid = session["uid"]
        if q("SELECT 1 FROM file_likes WHERE file_id=? AND student_id=?", (fid, sid), True):
            q("DELETE FROM file_likes WHERE file_id=? AND student_id=?", (fid, sid))
            liked = False
        else:
            q("INSERT OR IGNORE INTO file_likes(file_id,student_id,ts) VALUES(?,?,?)", (fid, sid, int(time.time())))
            liked = True
        n = q("SELECT COUNT(*) c FROM file_likes WHERE file_id=?", (fid,), True)["c"]
        return jsonify(liked=liked, likes=n)

    @app.route("/share_log/<int:fid>", methods=["POST"])
    def share_log(fid):
        if not session.get("role"):
            return jsonify(error="login"), 403
        sid = session["uid"] if session.get("role") == "student" else 0
        q("INSERT INTO file_shares(file_id,student_id,channel,ts) VALUES(?,?,?,?)",
          (fid, sid, request.args.get("channel", "")[:20], int(time.time())))
        return jsonify(ok=True)

    @app.route("/share/<int:fid>")
    def share_page(fid):
        # Public landing page: shows only the title, never the file itself.
        f = q("""SELECT f.title, f.kind, t.name tname, subj.name sub FROM files f
                 LEFT JOIN teachers t ON t.id=f.teacher_id LEFT JOIN subjects subj ON subj.id=f.subject_id WHERE f.id=?""", (fid,), True)
        if not f:
            abort(404)
        return page('''
<div style="min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#667eea,#764ba2);padding:20px">
<div class=box style="max-width:460px;width:100%"><div class=box-body style="text-align:center">
<h2>{{f.title}}</h2><p style="color:#64748b">{{f.kind.title()}} &middot; {{f.sub or 'General'}} &middot; {{f.tname or 'Teacher'}}</p>
<p style="margin:14px 0">Shared from MSU Portal. Log in to watch or download.</p>
<a href="/library" class="btn btn-green" style="padding:12px 20px;font-size:13px">Log in to view</a></div></div></div>''', f=f)


register(app, q, db, page, need, DB, UPLOADS)

init()


# ===================== EXPANDED SCHOOL SERVICES (ADDITIVE UPGRADE) =====================
# These tables are additive: existing student.db data is preserved.
EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS student_profiles(student_id INTEGER PRIMARY KEY, clubs TEXT DEFAULT '', leadership_role TEXT DEFAULT '', discipline_note TEXT DEFAULT '', guidance_note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS guidance_appointments(id INTEGER PRIMARY KEY, student_id INTEGER, requested_date TEXT, reason TEXT, status TEXT DEFAULT 'Pending', created_at INTEGER);
CREATE TABLE IF NOT EXISTS school_messages(id INTEGER PRIMARY KEY, audience TEXT, department_id INTEGER DEFAULT 0, sender TEXT, title TEXT, body TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS teacher_profiles(teacher_id INTEGER PRIMARY KEY, photo TEXT DEFAULT '', responsibility TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS department_meetings(id INTEGER PRIMARY KEY, title TEXT, departments TEXT, meeting_date TEXT, meeting_link TEXT, created_by TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS school_accounts(id INTEGER PRIMARY KEY, school_name TEXT UNIQUE, school_code TEXT UNIQUE, auth_hash TEXT, status TEXT DEFAULT 'grace', grace_until TEXT DEFAULT '', subscription_until TEXT DEFAULT '', created_at INTEGER);
CREATE TABLE IF NOT EXISTS fee_methods(id INTEGER PRIMARY KEY, method_name TEXT, paybill TEXT, account_no TEXT, instructions TEXT);
CREATE TABLE IF NOT EXISTS student_results(id INTEGER PRIMARY KEY, student_id INTEGER, subject TEXT, assessment TEXT, score REAL, out_of REAL, teacher_id INTEGER DEFAULT 0, term TEXT DEFAULT '', created_at INTEGER);
CREATE TABLE IF NOT EXISTS school_roles(id INTEGER PRIMARY KEY, teacher_id INTEGER, responsibility TEXT, assigned_by TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS school_settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS chat_messages(id INTEGER PRIMARY KEY, sender_role TEXT, sender_id INTEGER, recipient_role TEXT, recipient_id INTEGER, department_id INTEGER DEFAULT 0, room TEXT DEFAULT 'private', body TEXT, created_at INTEGER);
"""
with sqlite3.connect(DB) as _c:
    _c.executescript(EXTRA_SCHEMA)
    _c.execute("INSERT OR IGNORE INTO school_settings(k,v) VALUES('school_name','MSU Portal'),('motto','Knowledge is Power'),('logo',''),('guidance_contact','Guidance and Counselling Department')")
    _c.commit()

def extra_student_id():
    if session.get("role") == "student":
        return session.get("uid", 0)
    if session.get("role") == "parent":
        return session.get("uid", 0)
    return 0

def money(v):
    try:
        return f"{float(v or 0):,.2f}"
    except (TypeError, ValueError):
        return "0.00"

app.jinja_env.filters["money"] = money

@app.context_processor
def portal_branding():
    try:
        return {"portal_school_name": get_setting("school_name", "MSU Portal"),
                "portal_motto": get_setting("motto", "Knowledge is Power"),
                "portal_logo": get_setting("logo", "")}
    except Exception:
        return {"portal_school_name": "MSU Portal", "portal_motto": "", "portal_logo": ""}

@app.route("/student/services", methods=["GET", "POST"])
def student_services():
    if session.get("role") != "student":
        return redirect("/login/student")
    sid = session["uid"]
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "appointment":
            day = request.form.get("requested_date", "").strip()
            reason = request.form.get("reason", "").strip()[:500]
            if day and reason:
                q("INSERT INTO guidance_appointments(student_id,requested_date,reason,created_at) VALUES(?,?,?,?)",
                  (sid, day, reason, int(time.time())))
                flash("Guidance appointment request submitted.")
            else:
                flash("Choose a date and briefly explain the reason.")
        elif action == "message":
            body = request.form.get("body", "").strip()[:1500]
            if body:
                q("INSERT INTO chat_messages(sender_role,sender_id,recipient_role,recipient_id,room,body,created_at) VALUES(?,?,?,?,?,?,?)",
                  ("student", sid, "teacher", 0, "school", body, int(time.time())))
                flash("Message sent to the school staff inbox.")
        return redirect("/student/services")
    s = q("SELECT * FROM students WHERE id=?", (sid,), True)
    profile = q("SELECT * FROM student_profiles WHERE student_id=?", (sid,), True)
    if not profile:
        q("INSERT OR IGNORE INTO student_profiles(student_id) VALUES(?)", (sid,))
        profile = q("SELECT * FROM student_profiles WHERE student_id=?", (sid,), True)
    fees = q("SELECT type, COALESCE(SUM(amount),0) amount FROM fees WHERE student_id=? GROUP BY type", (sid,))
    paid = sum(float(x["amount"] or 0) for x in fees if x["type"] == "fee")
    bursary = sum(float(x["amount"] or 0) for x in fees if x["type"] == "bursary")
    fee_balance = max(0, BILLED_PER_YEAR - paid - bursary)
    remedial = q("SELECT COALESCE(SUM(amount),0) n FROM fees WHERE student_id=? AND type='remedial'", (sid,), True)["n"]
    welfare = q("SELECT COALESCE(SUM(amount),0) n FROM fees WHERE student_id=? AND type='welfare'", (sid,), True)["n"]
    appointments = q("SELECT * FROM guidance_appointments WHERE student_id=? ORDER BY id DESC", (sid,))
    results = q("SELECT * FROM student_results WHERE student_id=? ORDER BY id DESC", (sid,))
    messages = q("SELECT * FROM school_messages WHERE audience IN ('all','students') ORDER BY id DESC LIMIT 10")
    methods = q("SELECT * FROM fee_methods ORDER BY id DESC")
    return page("""
<div class="hero"><div><h1><i class="fa fa-graduation-cap"></i> My School Services</h1><p>Fees, school property, leadership, guidance and academic records.</p><span class=chip>{{s.adm_no}}</span></div></div>
<div class=stats>
<div class=stat><i class="fa fa-money-bill" style="background:#16a34a"></i><div><b>Ksh {{paid|money}}</b><span>Fee payments recorded</span></div></div>
<div class=stat><i class="fa fa-scale-balanced" style="background:#dc2626"></i><div><b>Ksh {{balance|money}}</b><span>Estimated fee balance*</span></div></div>
<div class=stat><i class="fa fa-hand-holding-heart" style="background:#0ea5e9"></i><div><b>Ksh {{bursary|money}}</b><span>Bursary credited</span></div></div>
<div class=stat><i class="fa fa-chair" style="background:#e67e22"></i><div><b>{{s.chair_no or 'Not assigned'}}</b><span>Chair</span></div></div>
<div class=stat><i class="fa fa-lock" style="background:#475569"></i><div><b>{{s.locker_no or 'Not assigned'}}</b><span>Locker</span></div></div>
</div>
<p style="color:#64748b;font-size:12px">*Fee balance uses the annual fee figure configured in this prototype. The bursar should configure the actual fee structure before school use.</p>
<div class=two>
<div class=box><div class=box-body><h3><i class="fa fa-users"></i> Clubs, societies and leadership</h3>
<p><b>Clubs / societies:</b> {{profile.clubs or 'Ask the administrator to update your record.'}}</p>
<p style="margin-top:8px"><b>Leadership role:</b> {{profile.leadership_role or 'Not recorded'}}</p>
<p style="margin-top:8px"><b>Discipline record:</b> {{profile.discipline_note or 'No note recorded in this portal.'}}</p>
<p style="margin-top:8px"><b>Books:</b> {{s.books or 'Not recorded'}}</p></div></div>
<div class=box><div class=box-body><h3><i class="fa fa-calendar-check"></i> Book guidance appointment</h3>
<form method=post><input type=hidden name=action value=appointment><label>Preferred date</label><input type=date name=requested_date required><label>Reason (keep it brief)</label><textarea name=reason maxlength=500 required placeholder="What would you like support with?"></textarea><button class="btn btn-green">Request appointment</button></form>
{% if appointments %}<hr style="margin:12px 0">{% for a in appointments %}<p style="padding:6px 0">{{a.requested_date}} — {{a.status}}: {{a.reason}}</p>{% endfor %}{% endif %}</div></div>
</div>
<div class=box><div class=box-body><h3><i class="fa fa-chart-line"></i> Marked written assessments / results</h3><div class=tbl><table><tr><th>Subject</th><th>Assessment</th><th>Score</th><th>Term</th><th>Date</th></tr>
{% for r in results %}<tr><td>{{r.subject}}</td><td>{{r.assessment}}</td><td>{{r.score}} / {{r.out_of}}</td><td>{{r.term or '-'}}</td><td>{{r.created_at|fdate}}</td></tr>{% else %}<tr><td colspan=5>No marked written results have been published yet.</td></tr>{% endfor %}</table></div></div></div>
<div class=box><div class=box-body><h3><i class="fa fa-bullhorn"></i> School announcements</h3>{% for m in messages %}<div class=drow><i class="fa fa-bell ic"></i><div><b>{{m.title}}</b><p>{{m.body}}</p><small>{{m.sender}} · {{m.created_at|fdate}}</small></div></div>{% else %}<p>No announcements yet.</p>{% endfor %}</div></div>
<div class=box><div class=box-body><h3><i class="fa fa-building-columns"></i> Fee payment instructions</h3>{% for m in methods %}<div class=drow><i class="fa fa-money-bill-transfer ic"></i><div><b>{{m.method_name}}</b><p>Paybill: {{m.paybill or '-'}} · Account: {{m.account_no or '-'}}</p><p>{{m.instructions}}</p></div></div>{% else %}<p>Ask the bursar to publish the school's approved bank/M-Pesa instructions.</p>{% endfor %}</div></div>
<div class=box><div class=box-body><h3><i class="fa fa-envelope"></i> Contact school staff</h3><form method=post><input type=hidden name=action value=message><textarea name=body required maxlength=1500 placeholder="Write your message to school staff"></textarea><button class="btn btn-blue">Send message</button></form></div></div>
""", s=s, profile=profile, paid=paid, balance=fee_balance, bursary=bursary, remedial=remedial, welfare=welfare, appointments=appointments, results=results, messages=messages, methods=methods)

@app.route("/school-logo")
def school_logo():
    filename=get_setting("logo", "")
    if not filename:
        abort(404)
    safe_name=secure_filename(filename)
    if safe_name != filename or not os.path.isfile(os.path.join(UPLOADS,safe_name)):
        abort(404)
    return send_from_directory(UPLOADS,safe_name,conditional=True)

@app.route("/admin/services", methods=["GET", "POST"])
def admin_services():
    if session.get("role") not in ("admin",):
        return redirect("/login/admin")
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "profile":
            adm = request.form.get("adm_no", "").strip()
            s = q("SELECT id FROM students WHERE adm_no=?", (adm,), True)
            if s:
                q("""INSERT INTO student_profiles(student_id,clubs,leadership_role,discipline_note) VALUES(?,?,?,?)
                     ON CONFLICT(student_id) DO UPDATE SET clubs=excluded.clubs,leadership_role=excluded.leadership_role,discipline_note=excluded.discipline_note""",
                  (s["id"], request.form.get("clubs","")[:300], request.form.get("leadership_role","")[:200], request.form.get("discipline_note","")[:1000]))
                flash("Student clubs, leadership and discipline record updated.")
            else: flash("Student admission number was not found.")
        elif action == "announcement":
            title=request.form.get("title","").strip()[:150]; body=request.form.get("body","").strip()[:3000]
            if title and body:
                q("INSERT INTO school_messages(audience,sender,title,body,created_at) VALUES('all',?,?,?,?)",
                  (session.get("name","Admin"),title,body,int(time.time())))
                flash("Announcement posted.")
        elif action == "fee_method":
            q("INSERT INTO fee_methods(method_name,paybill,account_no,instructions) VALUES(?,?,?,?)",
              (request.form.get("method_name","")[:100],request.form.get("paybill","")[:80],request.form.get("account_no","")[:100],request.form.get("instructions","")[:500]))
            flash("Payment instructions published to student/parent portal.")
        elif action == "branding":
            school_name=request.form.get("school_name","").strip()[:150]
            motto=request.form.get("motto","").strip()[:150]
            if not school_name:
                flash("School name cannot be empty.")
                return redirect("/admin/services")
            for key,value in (("school_name",school_name),("motto",motto)):
                q("INSERT INTO school_settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key,value))
                q("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key,value))
            logo_file=request.files.get("school_logo")
            if logo_file and logo_file.filename:
                ext=os.path.splitext(secure_filename(logo_file.filename))[1].lower()
                if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                    flash("Logo must be PNG, JPG, JPEG, WEBP or GIF.")
                    return redirect("/admin/services")
                # Save under a fixed server-generated name; never trust the uploaded filename.
                filename="school_logo"+ext
                logo_file.save(os.path.join(UPLOADS,filename))
                for table in ("school_settings","settings"):
                    q(f"INSERT INTO {table}(k,v) VALUES('logo',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (filename,))
            flash("School name, motto and any uploaded logo have been saved.")
        return redirect("/admin/services")
    students=q("SELECT name,adm_no FROM students ORDER BY name")
    announcements=q("SELECT * FROM school_messages ORDER BY id DESC LIMIT 20")
    methods=q("SELECT * FROM fee_methods ORDER BY id DESC")
    return page("""
<div class=hero><div><h1><i class="fa fa-sliders"></i> School Services Administration</h1><p>Manage learner records, announcements, payment instructions and branding.</p></div></div>
<div class=two>
<div class=box><div class=box-body><h3>Update student profile</h3><form method=post><input type=hidden name=action value=profile>
<label>Admission number</label><input name=adm_no list=admlist required><datalist id=admlist>{% for s in students %}<option value="{{s.adm_no}}">{{s.name}}</option>{% endfor %}</datalist>
<label>Clubs and societies</label><input name=clubs placeholder="e.g. Science Club, Drama Club">
<label>Leadership role</label><input name=leadership_role placeholder="e.g. Class prefect">
<label>Discipline record / note</label><textarea name=discipline_note placeholder="Use factual, respectful, authorised records"></textarea>
<button class="btn btn-green">Save learner profile</button></form></div></div>
<div class=box><div class=box-body><h3>Post school announcement</h3><form method=post><input type=hidden name=action value=announcement><input name=title required placeholder="Announcement title"><textarea name=body required placeholder="Message for students and parents"></textarea><button class="btn btn-blue">Publish announcement</button></form>
<hr style="margin:14px 0"><h3>School identity</h3><form method=post><input type=hidden name=action value=branding><input name=school_name value="{{portal_school_name}}" required placeholder="School name"><input name=motto value="{{portal_motto}}" placeholder="School motto"><button class="btn btn-green">Save identity</button></form></div></div>
</div>
<div class=two>
<div class=box><div class=box-body><h3>Publish fee payment instructions</h3><form method=post><input type=hidden name=action value=fee_method><input name=method_name required placeholder="e.g. Bank deposit or M-Pesa"><input name=paybill placeholder="Paybill / till number"><input name=account_no placeholder="Account number / admission format"><textarea name=instructions placeholder="Payment steps and receipt instructions"></textarea><button class="btn btn-green">Publish payment method</button></form></div></div>
<div class=box><div class=box-body><h3>Current announcements</h3>{% for a in announcements %}<div class=drow><div><b>{{a.title}}</b><p>{{a.body}}</p></div></div>{% else %}<p>No announcements yet.</p>{% endfor %}</div></div>
</div>
""", students=students, announcements=announcements, methods=methods)

@app.route("/teacher/collaboration", methods=["GET", "POST"])
def teacher_collaboration():
    if session.get("role") not in ("teacher", "admin"):
        return redirect("/login/teacher")
    tid = session.get("uid", 0) if session.get("role") == "teacher" else 0
    teacher = q("SELECT * FROM teachers WHERE id=?", (tid,), True) if tid else None
    dept_id = teacher["department_id"] if teacher else 0
    if request.method == "POST":
        action=request.form.get("action")
        if action == "department_message":
            body=request.form.get("body","").strip()[:2000]
            if body:
                q("INSERT INTO dept_messages(department_id,sender,role,body,ts) VALUES(?,?,?,?,?)",
                  (dept_id,session.get("name","Admin"),session.get("role","teacher"),body,int(time.time())))
                flash("Department message saved.")
        elif action == "meeting":
            title=request.form.get("title","").strip()[:150]
            depts=",".join(request.form.getlist("departments"))[:500]
            date=request.form.get("meeting_date","").strip()
            link=request.form.get("meeting_link","").strip()[:500]
            if title and depts and date:
                q("INSERT INTO department_meetings(title,departments,meeting_date,meeting_link,created_by,created_at) VALUES(?,?,?,?,?,?)",
                  (title,depts,date,link,session.get("name","Admin"),int(time.time())))
                flash("Interdepartment meeting created. Add a valid video-conference link if needed.")
        elif action == "private_message":
            recipient=toint(request.form.get("recipient"))
            body=request.form.get("body","").strip()[:2000]
            if recipient and body:
                q("INSERT INTO dm(from_key,to_key,body,ts) VALUES(?,?,?,?)",
                  (str(tid),str(recipient),body,int(time.time())))
                flash("Private message saved.")
        return redirect("/teacher/collaboration")
    depts=q("SELECT * FROM departments ORDER BY name")
    dept_msgs=q("SELECT * FROM dept_messages WHERE department_id=? OR department_id=0 ORDER BY id DESC LIMIT 30",(dept_id,))
    meetings=q("SELECT * FROM department_meetings ORDER BY id DESC LIMIT 30")
    teachers=q("SELECT id,name,department_id FROM teachers ORDER BY name")
    return page("""
<div class=hero h-teacher><div><h1><i class="fa fa-people-group"></i> Teacher Collaboration</h1><p>Department discussions, private notes and cross-department meetings.</p></div></div>
<div class=two>
<div class=box><div class=box-body><h3>Department group message</h3><form method=post><input type=hidden name=action value=department_message><textarea name=body required maxlength=2000 placeholder="Message colleagues in your department"></textarea><button class="btn btn-blue">Send department message</button></form>
<hr style="margin:12px 0">{% for m in dept_msgs %}<div class=drow><div><b>{{m.sender}}</b><p>{{m.body}}</p><small>{{m.ts|fdate}}</small></div></div>{% else %}<p>No messages yet.</p>{% endfor %}</div></div>
<div class=box><div class=box-body><h3>Arrange an interdepartment meeting</h3><form method=post><input type=hidden name=action value=meeting><input name=title required placeholder="Meeting title"><label>Departments (select multiple)</label><select name=departments multiple size=5 required>{% for d in depts %}<option value="{{d.name}}">{{d.name}}</option>{% endfor %}</select><label>Date / time</label><input name=meeting_date type=datetime-local required><input name=meeting_link placeholder="Video meeting link (optional)"><button class="btn btn-green">Create meeting</button></form>
<hr style="margin:12px 0"><h3>Upcoming / recent meetings</h3>{% for m in meetings %}<div class=drow><div><b>{{m.title}}</b><p>{{m.departments}} · {{m.meeting_date}}</p>{% if m.meeting_link %}<a href="{{m.meeting_link}}" target=_blank rel=noopener>Open meeting link</a>{% endif %}</div></div>{% else %}<p>No meetings yet.</p>{% endfor %}</div></div>
</div>
<div class=box><div class=box-body><h3>Private message a teacher</h3><form method=post><input type=hidden name=action value=private_message><select name=recipient required><option value="">Choose teacher</option>{% for t in teachers %}{% if t.id != tid %}<option value="{{t.id}}">{{t.name}}</option>{% endif %}{% endfor %}</select><textarea name=body required placeholder="Private message"></textarea><button class="btn btn-blue">Send private message</button></form></div></div>
""", depts=depts, dept_msgs=dept_msgs, meetings=meetings, teachers=teachers, tid=tid)

@app.route("/super-admin/schools", methods=["GET", "POST"])
def super_admin_schools():
    # A separately configured super-admin password is required; never use the school admin login here.
    if session.get("role") != "super_admin":
        return redirect("/super-admin/login")
    if request.method == "POST":
        action=request.form.get("action")
        if action == "create":
            name=request.form.get("school_name","").strip()[:150]
            code=request.form.get("school_code","").strip().upper()[:40]
            raw=request.form.get("auth_code","").strip()
            grace=request.form.get("grace_until","").strip()
            if name and code and len(raw) >= 10:
                from werkzeug.security import generate_password_hash
                try:
                    q("INSERT INTO school_accounts(school_name,school_code,auth_hash,status,grace_until,created_at) VALUES(?,?,?,'grace',?,?)",
                      (name,code,generate_password_hash(raw),grace,int(time.time())))
                    flash("School account created. Share the activation code securely with the authorised school administrator.")
                except Exception:
                    flash("Could not create school: school name or code may already exist.")
            else:
                flash("Enter a school name, unique code and an activation code of at least 10 characters.")
        elif action == "status":
            code=request.form.get("school_code","").strip().upper()
            status=request.form.get("status","suspended")
            if status not in ("active","grace","suspended"): status="suspended"
            q("UPDATE school_accounts SET status=? WHERE school_code=?",(status,code))
            flash("School status updated.")
        return redirect("/super-admin/schools")
    schools=q("SELECT id,school_name,school_code,status,grace_until,subscription_until,created_at FROM school_accounts ORDER BY id DESC")
    return page("""
<div class=hero><div><h1><i class="fa fa-building"></i> Super Admin — School Accounts</h1><p>Provision school tenants and manage grace / subscription status.</p></div></div>
<div class=box><div class=box-body><h3>Register a school</h3><form method=post><input type=hidden name=action value=create><input name=school_name required placeholder="School name"><input name=school_code required placeholder="Unique school code"><input name=auth_code type=password minlength=10 required placeholder="Activation code (stored as a hash)"><label>Grace period end date</label><input name=grace_until type=date><button class="btn btn-green">Create school account</button></form></div></div>
<div class=box><div class=box-body><h3>School accounts</h3><table><tr><th>School</th><th>Code</th><th>Status</th><th>Grace until</th><th>Change status</th></tr>{% for s in schools %}<tr><td>{{s.school_name}}</td><td>{{s.school_code}}</td><td>{{s.status}}</td><td>{{s.grace_until or '-'}}</td><td><form method=post><input type=hidden name=action value=status><input type=hidden name=school_code value="{{s.school_code}}"><select name=status><option value=active>Active</option><option value=grace>Grace</option><option value=suspended>Suspended</option></select><button class="btn btn-blue">Update</button></form></td></tr>{% else %}<tr><td colspan=5>No school accounts registered.</td></tr>{% endfor %}</table></div></div>
""", schools=schools)

@app.route("/super-admin/login", methods=["GET", "POST"])
def super_admin_login():
    if request.method == "POST":
        # Configure SUPER_ADMIN_PASSWORD_HASH in environment; no hard-coded master credential.
        expected = os.environ.get("SUPER_ADMIN_PASSWORD_HASH", "")
        from werkzeug.security import check_password_hash
        password = request.form.get("password", "")
        if expected and check_password_hash(expected, password):
            session.clear()
            session["role"] = "super_admin"
            session["uid"] = 0
            session["name"] = "Super Admin"
            return redirect("/super-admin/schools")
        flash("Super-admin login is not configured or the password is incorrect.")
    return page("""<div style="min-height:80vh;display:grid;place-items:center"><div class=box style="max-width:420px;width:100%"><div class=box-body><h2>Super Admin Login</h2><p>Set SUPER_ADMIN_PASSWORD_HASH in your environment before using this page.</p><form method=post><label>Password</label><input name=password type=password required><button class="btn btn-green">Sign in</button></form></div></div></div>""")

# Link the new modules from existing menus, without removing the existing pages.
PAGE = PAGE.replace("('/student','fa-house','Dashboard'),('/library'", "('/student','fa-house','Dashboard'),('/student/services','fa-circle-user','My Services'),('/library'")
PAGE = PAGE.replace("('/teacher','fa-chalkboard-teacher','Teacher Home'),('/teacher/content'", "('/teacher','fa-chalkboard-teacher','Teacher Home'),('/teacher/collaboration','fa-people-group','Collaboration'),('/teacher/content'")
PAGE = PAGE.replace("('/admin','fa-shield-halved','Admin Home'),('/admin/content'", "('/admin','fa-shield-halved','Admin Home'),('/admin/services','fa-sliders','School Services'),('/admin/content'")

if __name__=="__main__":
    print("="*50)
    print("MSU Portal running on http://localhost:5000")
    print("Admin login: username @admin, password @admin2030, authentication code 37302720")
    print("Change the default admin credentials/code before deploying this portal publicly.")
    print("Student: ODIWUOR, Francis Okello / ED/00530/018 | Teacher: T001")
    print("Parent: 0792239596 / ED/00530/018")
    print("="*50)
    app.run(host="0.0.0.0",port=5000,debug=False)
