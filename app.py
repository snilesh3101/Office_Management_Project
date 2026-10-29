"""
Office Manager - a small office management app
------------------------------------------------
Home       : KPI summary + 6 graphs
Employees  : employee salary table, add / remove employees
Attendance : mark daily attendance, monthly summary per employee
Payroll    : monthly net pay = salary - deduction for absent / half days
Expenses   : office expense table, add / remove expenses, category filter

Run:   pip install flask matplotlib
       python app.py
Open:  http://127.0.0.1:5000
Data is stored in office.db (SQLite) next to this file and is created
automatically with sample data on first run.
"""
import io
import os
import random
import sqlite3
from datetime import date, timedelta

import matplotlib

matplotlib.use("Agg")  # draw charts without a display window
import matplotlib.pyplot as plt
from flask import (Flask, Response, abort, g, redirect, render_template,
                   request, url_for)
from jinja2 import DictLoader

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "office.db")
CATEGORIES = ["Rent", "Utilities", "Internet", "Supplies", "Travel",
              "Maintenance", "Software", "Other"]
DEPARTMENTS = ["Engineering", "Sales", "HR", "Finance", "Operations"]

# Chart colours (same palette as the page)
INK, TEAL, AMBER = "#1f2933", "#0f766e", "#c2410c"
PALETTE = ["#0f766e", "#c2410c", "#4f6d7a", "#b08900", "#7a5c8e",
           "#2f855a", "#9a3412", "#64748b"]

app = Flask(__name__)


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS employees(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, department TEXT NOT NULL, role TEXT NOT NULL,
            monthly_salary REAL NOT NULL, join_date TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS expenses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, category TEXT NOT NULL,
            description TEXT NOT NULL, amount REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL, date TEXT NOT NULL, status TEXT NOT NULL,
            UNIQUE(employee_id, date));
    """)
    if db.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 0:
        today = date.today()
        staff = [
            ("Aarav Mehta", "Engineering", "Senior Developer", 95000, 900),
            ("Diya Nair", "Engineering", "Developer", 68000, 600),
            ("Rohan Kulkarni", "Engineering", "QA Engineer", 52000, 420),
            ("Sneha Iyer", "Sales", "Sales Manager", 78000, 1100),
            ("Vikram Shah", "Sales", "Sales Executive", 45000, 300),
            ("Priya Deshmukh", "HR", "HR Manager", 72000, 1300),
            ("Karan Malhotra", "Finance", "Accountant", 58000, 800),
            ("Isha Patil", "Finance", "Finance Analyst", 54000, 200),
            ("Manoj Pawar", "Operations", "Office Admin", 36000, 1500),
            ("Neha Joshi", "Operations", "Front Desk", 30000, 150),
        ]
        db.executemany(
            "INSERT INTO employees(name,department,role,monthly_salary,join_date)"
            " VALUES(?,?,?,?,?)",
            [(n, d, r, s, (today - timedelta(days=ago)).isoformat())
             for n, d, r, s, ago in staff])

        random.seed(7)
        base = {"Rent": (85000, 0), "Utilities": (14000, 3000),
                "Internet": (6500, 0), "Supplies": (9000, 4000),
                "Travel": (12000, 9000), "Maintenance": (7000, 5000),
                "Software": (18000, 2500), "Other": (4000, 2500)}
        rows = []
        for back in range(5, -1, -1):          # last 6 months
            y, m = today.year, today.month - back
            while m <= 0:
                y, m = y - 1, m + 12
            for cat, (fixed, var) in base.items():
                amt = fixed + random.randint(-var, var) if var else fixed
                day = min(28, random.randint(1, 27))
                rows.append((date(y, m, day).isoformat(), cat,
                             f"{cat} - {date(y, m, 1):%b %Y}", amt))
        db.executemany(
            "INSERT INTO expenses(date,category,description,amount) VALUES(?,?,?,?)",
            rows)
    if db.execute("SELECT COUNT(*) FROM attendance").fetchone()[0] == 0:
        random.seed(11)
        today = date.today()
        ids = [r[0] for r in db.execute("SELECT id FROM employees")]
        rows = []
        for back in range(0, 75):
            d = today - timedelta(days=back)
            if d.weekday() >= 5:
                continue
            for emp_id in ids:
                st = random.choices(["Present", "Half Day", "Leave", "Absent"],
                                    weights=[89, 4, 4, 3])[0]
                rows.append((emp_id, d.isoformat(), st))
        db.executemany("INSERT INTO attendance(employee_id,date,status) VALUES(?,?,?)", rows)
    db.commit()
    db.close()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def inr(value):
    """Format a number with Indian digit grouping, e.g. 1234567 -> ₹12,34,567"""
    s = f"{int(round(value or 0))}"
    head, tail = s[:-3], s[-3:]
    if head:
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return "₹" + s


app.jinja_env.filters["inr"] = inr


def last_months(n=6):
    """Return the last n months as (year, month) tuples, oldest first."""
    today = date.today()
    out = []
    for back in range(n - 1, -1, -1):
        y, m = today.year, today.month - back
        while m <= 0:
            y, m = y - 1, m + 12
        out.append((y, m))
    return out


def month_end(y, m):
    return date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)


def monthly_series():
    """Payroll and office expenses for each of the last 6 months."""
    db = get_db()
    emps = db.execute("SELECT monthly_salary, join_date FROM employees").fetchall()
    labels, payroll, expenses = [], [], []
    for y, m in last_months():
        end = month_end(y, m).isoformat()
        labels.append(date(y, m, 1).strftime("%b"))
        payroll.append(sum(e["monthly_salary"] for e in emps if e["join_date"] <= end))
        key = f"{y}-{m:02d}"
        expenses.append(db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE substr(date,1,7)=?",
            (key,)).fetchone()[0])
    return labels, payroll, expenses


# --------------------------------------------------------------------------
# Charts (drawn with matplotlib, served as PNG)
# --------------------------------------------------------------------------
def style_axes(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#b8c0c8")
    ax.tick_params(colors=INK, labelsize=9)
    ax.set_facecolor("white")


def lakh(x, _pos=None):
    return f"{x / 100000:.1f}L" if x else "0"


def chart_monthly(ax):
    labels, payroll, expenses = monthly_series()
    ax.bar(labels, payroll, color=TEAL, label="Payroll", width=0.6)
    ax.bar(labels, expenses, bottom=payroll, color=AMBER,
           label="Office expenses", width=0.6)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lakh))
    ax.legend(frameon=False, fontsize=9, loc="upper left", ncol=2)
    ax.set_ylim(0, max(p + e for p, e in zip(payroll, expenses)) * 1.18)
    ax.set_title("Monthly spend (₹ lakh)", loc="left", fontsize=11, color=INK)


def chart_categories(ax):
    rows = get_db().execute(
        "SELECT category, SUM(amount) t FROM expenses GROUP BY category "
        "ORDER BY t DESC").fetchall()
    vals = [r["t"] for r in rows]
    wedges, _ = ax.pie(vals, colors=PALETTE[:len(vals)], startangle=90,
                       counterclock=False, wedgeprops=dict(width=0.38, edgecolor="white"))
    total = sum(vals)
    ax.legend(wedges, [f"{r['category']}  {r['t'] / total:.0%}" for r in rows],
              loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=9)
    ax.set_title("Where office money goes (6 months)", loc="left", fontsize=11, color=INK)


def chart_departments(ax):
    rows = get_db().execute(
        "SELECT department, SUM(monthly_salary) t FROM employees GROUP BY department "
        "ORDER BY t").fetchall()
    ax.barh([r["department"] for r in rows], [r["t"] for r in rows], color=TEAL, height=0.58)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lakh))
    for i, r in enumerate(rows):
        ax.text(r["t"] + 3000, i, inr(r["t"]), va="center", fontsize=9, color=INK)
    ax.set_xlim(0, max(r["t"] for r in rows) * 1.28)
    ax.set_title("Monthly payroll by department", loc="left", fontsize=11, color=INK)


def chart_trend(ax):
    labels, _, expenses = monthly_series()
    ax.plot(labels, expenses, color=AMBER, marker="o", linewidth=2.2)
    ax.fill_between(labels, expenses, color=AMBER, alpha=0.1)
    for x, y in zip(labels, expenses):
        ax.annotate(f"{y / 1000:.0f}k", (x, y), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=8.5, color=INK)
    ax.set_ylim(min(expenses) * 0.85, max(expenses) * 1.1)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
    ax.set_title("Office expense trend (₹)", loc="left", fontsize=11, color=INK)


CHARTS = {"monthly": chart_monthly, "categories": chart_categories,
          "departments": chart_departments, "trend": chart_trend}


@app.route("/chart/<name>.png")
def chart(name):
    if name not in CHARTS:
        abort(404)
    fig, ax = plt.subplots(figsize=(6.2, 3.3), dpi=110)
    fig.patch.set_facecolor("white")
    style_axes(ax)
    CHARTS[name](ax)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return Response(buf.getvalue(), mimetype="image/png")


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@app.route("/")
def home():
    db = get_db()
    n_emp, payroll = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(monthly_salary),0) FROM employees").fetchone()
    key = date.today().strftime("%Y-%m")
    this_month = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE substr(date,1,7)=?",
        (key,)).fetchone()[0]
    present_today = db.execute(
        "SELECT COUNT(*) FROM attendance WHERE date=? AND status IN ('Present','Half Day')",
        (date.today().isoformat(),)).fetchone()[0]
    top_cat = db.execute(
        "SELECT category FROM expenses GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1"
    ).fetchone()
    return render_template("home.html", tab="home", n_emp=n_emp, payroll=payroll,
                           this_month=this_month, total=payroll + this_month, present_today=present_today,
                           top_cat=top_cat["category"] if top_cat else "-",
                           month_name=date.today().strftime("%B"))


@app.route("/salaries")
def salaries():
    db = get_db()
    dept = request.args.get("dept", "")
    sql, args = "SELECT * FROM employees", []
    if dept:
        sql, args = sql + " WHERE department=?", [dept]
    emps = db.execute(sql + " ORDER BY monthly_salary DESC", args).fetchall()
    total = sum(e["monthly_salary"] for e in emps)
    avg = total / len(emps) if emps else 0
    return render_template("salaries.html", tab="salaries", emps=emps, total=total,
                           avg=avg, dept=dept, departments=DEPARTMENTS,
                           today=date.today().isoformat())


@app.post("/salaries/add")
def add_employee():
    f = request.form
    try:
        salary = float(f["monthly_salary"])
        if not f["name"].strip() or salary <= 0:
            raise ValueError
    except (KeyError, ValueError):
        abort(400, "Enter a name and a salary greater than zero.")
    get_db().execute(
        "INSERT INTO employees(name,department,role,monthly_salary,join_date) VALUES(?,?,?,?,?)",
        (f["name"].strip(), f["department"], f["role"].strip() or "Staff",
         salary, f["join_date"] or date.today().isoformat()))
    get_db().commit()
    return redirect(url_for("salaries"))


@app.post("/salaries/delete/<int:emp_id>")
def delete_employee(emp_id):
    get_db().execute("DELETE FROM employees WHERE id=?", (emp_id,))
    get_db().execute("DELETE FROM attendance WHERE employee_id=?", (emp_id,))
    get_db().commit()
    return redirect(url_for("salaries"))


@app.route("/expenses")
def expenses():
    db = get_db()
    cat = request.args.get("category", "")
    sql, args = "SELECT * FROM expenses", []
    if cat:
        sql, args = sql + " WHERE category=?", [cat]
    rows = db.execute(sql + " ORDER BY date DESC, id DESC", args).fetchall()
    total = sum(r["amount"] for r in rows)
    return render_template("expenses.html", tab="expenses", rows=rows, total=total,
                           cat=cat, categories=CATEGORIES, today=date.today().isoformat())


@app.post("/expenses/add")
def add_expense():
    f = request.form
    try:
        amount = float(f["amount"])
        if not f["description"].strip() or amount <= 0:
            raise ValueError
    except (KeyError, ValueError):
        abort(400, "Enter a description and an amount greater than zero.")
    get_db().execute(
        "INSERT INTO expenses(date,category,description,amount) VALUES(?,?,?,?)",
        (f["date"] or date.today().isoformat(), f["category"],
         f["description"].strip(), amount))
    get_db().commit()
    return redirect(url_for("expenses"))


@app.post("/expenses/delete/<int:exp_id>")
def delete_expense(exp_id):
    get_db().execute("DELETE FROM expenses WHERE id=?", (exp_id,))
    get_db().commit()
    return redirect(url_for("expenses"))


# --------------------------------------------------------------------------
# Attendance & payroll
# --------------------------------------------------------------------------
STATUSES = ["Present", "Half Day", "Leave", "Absent"]
STATUS_COLORS = {"Present": TEAL, "Half Day": "#b08900", "Leave": "#4f6d7a", "Absent": AMBER}


def parse_month(text):
    """'2026-10' -> (2026, 10); falls back to the current month."""
    try:
        y, m = text.split("-")
        y, m = int(y), int(m)
        date(y, m, 1)
        return y, m
    except (ValueError, AttributeError):
        t = date.today()
        return t.year, t.month


def working_days(y, m):
    """Monday-Friday days in the month."""
    d, n = date(y, m, 1), 0
    while d.month == m:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n


def month_summary(y, m):
    """Attendance counts and attendance % for every employee in a month."""
    db = get_db()
    key = f"{y}-{m:02d}"
    out = []
    for e in db.execute("SELECT * FROM employees ORDER BY name"):
        counts = {s: 0 for s in STATUSES}
        for r in db.execute(
                "SELECT status, COUNT(*) c FROM attendance "
                "WHERE employee_id=? AND substr(date,1,7)=? GROUP BY status", (e["id"], key)):
            counts[r["status"]] = r["c"]
        marked = sum(counts.values())
        pct = (counts["Present"] + 0.5 * counts["Half Day"]) / marked * 100 if marked else 0
        out.append(dict(emp=e, counts=counts, marked=marked, pct=pct))
    return out


@app.route("/attendance")
def attendance():
    day = request.args.get("date") or date.today().isoformat()
    try:
        d = date.fromisoformat(day)
    except ValueError:
        d = date.today()
    db = get_db()
    existing = {r["employee_id"]: r["status"] for r in
                db.execute("SELECT employee_id, status FROM attendance WHERE date=?",
                           (d.isoformat(),))}
    emps = db.execute("SELECT * FROM employees ORDER BY name").fetchall()
    summary = month_summary(d.year, d.month)
    return render_template("attendance.html", tab="attendance", day=d.isoformat(),
                           weekend=d.weekday() >= 5, emps=emps, existing=existing,
                           statuses=STATUSES, summary=summary,
                           month_label=d.strftime("%B %Y"), saved=request.args.get("saved"))


@app.post("/attendance/save")
def save_attendance():
    day = request.form.get("date", date.today().isoformat())
    db = get_db()
    for e in db.execute("SELECT id FROM employees"):
        status = request.form.get(f"status_{e['id']}")
        if status in STATUSES:
            db.execute("INSERT INTO attendance(employee_id,date,status) VALUES(?,?,?) "
                       "ON CONFLICT(employee_id,date) DO UPDATE SET status=excluded.status",
                       (e["id"], day, status))
    db.commit()
    return redirect(url_for("attendance", date=day, saved=1))


@app.route("/payroll")
def payroll():
    y, m = parse_month(request.args.get("month", ""))
    wd = working_days(y, m)
    rows, tot_base, tot_ded = [], 0, 0
    for item in month_summary(y, m):
        e, c = item["emp"], item["counts"]
        lost = c["Absent"] + 0.5 * c["Half Day"]
        per_day = e["monthly_salary"] / wd
        ded = per_day * lost
        rows.append(dict(emp=e, counts=c, lost=lost, per_day=per_day,
                         deduction=ded, net=e["monthly_salary"] - ded))
        tot_base += e["monthly_salary"]
        tot_ded += ded
    return render_template("payroll.html", tab="payroll", rows=rows, wd=wd,
                           month=f"{y}-{m:02d}", month_label=date(y, m, 1).strftime("%B %Y"),
                           tot_base=tot_base, tot_ded=tot_ded, tot_net=tot_base - tot_ded)


def chart_attendance_daily(ax):
    db = get_db()
    days = []
    d = date.today()
    while len(days) < 14:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    labels = [x.strftime("%d %b") for x in days]
    bottom = [0] * len(days)
    for st in STATUSES:
        vals = [db.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status=?",
                           (x.isoformat(), st)).fetchone()[0] for x in days]
        ax.bar(labels, vals, bottom=bottom, color=STATUS_COLORS[st], label=st, width=0.7)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.tick_params(axis="x", rotation=60, labelsize=8)
    ax.legend(frameon=False, fontsize=8, ncol=4, loc="upper center",
              bbox_to_anchor=(0.5, 1.0))
    ax.set_ylim(0, max(max(bottom), 1) * 1.3)
    ax.set_title("Daily attendance (last 14 working days)", loc="left", fontsize=11, color=INK)


def chart_attendance_pct(ax):
    t = date.today()
    data = sorted(month_summary(t.year, t.month), key=lambda r: r["pct"])
    names = [r["emp"]["name"].split()[0] for r in data]
    pcts = [r["pct"] for r in data]
    colors = [TEAL if p >= 90 else AMBER for p in pcts]
    ax.barh(names, pcts, color=colors, height=0.6)
    for i, p in enumerate(pcts):
        ax.text(p + 1, i, f"{p:.0f}%", va="center", fontsize=8.5, color=INK)
    ax.set_xlim(0, 118)
    ax.tick_params(axis="y", labelsize=8.5)
    ax.set_title(f"Attendance % - {t.strftime('%B')}", loc="left", fontsize=11, color=INK)


CHARTS.update({"att_daily": chart_attendance_daily, "att_pct": chart_attendance_pct})


# --------------------------------------------------------------------------
# Templates (kept in this file so the project is a single script)
# --------------------------------------------------------------------------
BASE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Office Management</title>
<style>
  :root { --ink:#1f2933; --muted:#667085; --paper:#f3f4f1; --card:#fff;
          --line:#dde1e5; --teal:#0f766e; --amber:#c2410c; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--paper); color:var(--ink);
         font:15px/1.5 "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
  header { background:var(--ink); color:#fff; padding:18px 32px 0; }
  header h1 { margin:0 0 14px; font-size:20px; font-weight:600; letter-spacing:.2px; }
  nav a { display:inline-block; padding:10px 22px; color:#c9d1d9; text-decoration:none;
          border-radius:6px 6px 0 0; margin-right:4px; }
  nav a.active { background:var(--paper); color:var(--ink); font-weight:600; }
  main { padding:26px 32px 48px; max-width:1180px; margin:0 auto; }
  h2 { font-size:18px; margin:0 0 4px; }
  .sub { color:var(--muted); margin:0 0 18px; }
  .kpis { margin:0 -8px 10px; font-size:0; }
  .kpi { display:inline-block; width:25%; padding:0 8px; vertical-align:top; font-size:15px; }
  .kpi div { background:var(--card); border:1px solid var(--line); border-radius:6px;
             padding:14px 16px; border-top:3px solid var(--teal); }
  .kpi.warm div { border-top-color:var(--amber); }
  .kpi small { color:var(--muted); display:block; }
  .kpi b { font-size:24px; font-weight:600; }
  .grid { margin:0 -8px; font-size:0; }
  .cell { display:inline-block; width:50%; padding:8px; vertical-align:top; font-size:15px; }
  .cell div { background:var(--card); border:1px solid var(--line); border-radius:6px; padding:10px; }
  .cell img { width:100%; display:block; }
  table { width:100%; border-collapse:collapse; background:var(--card);
          border:1px solid var(--line); }
  th, td { padding:10px 14px; text-align:left; border-bottom:1px solid var(--line); }
  th { background:#eceee9; font-weight:600; font-size:14px; }
  td.num, th.num { text-align:right; }
  tfoot td { font-weight:600; background:#f8f9f6; }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:6px;
           padding:16px; margin-bottom:18px; }
  .panel label { display:inline-block; margin:0 10px 8px 0; font-size:13px; color:var(--muted); }
  .panel label span { display:block; }
  input, select { padding:8px 10px; border:1px solid #b8c0c8; border-radius:5px;
                  font:inherit; background:#fff; }
  button { padding:9px 18px; border:0; border-radius:5px; background:var(--teal);
           color:#fff; font:inherit; font-weight:600; cursor:pointer; }
  button.link { background:none; color:var(--amber); padding:2px 6px; font-weight:500; }
  .filter { margin-bottom:14px; }
  .filter a { margin-right:6px; padding:4px 12px; border:1px solid var(--line); background:#fff;
              border-radius:14px; color:var(--ink); text-decoration:none; font-size:13px;
              display:inline-block; margin-bottom:6px; }
  .filter a.on { background:var(--ink); color:#fff; border-color:var(--ink); }
  .tag { display:inline-block; padding:1px 9px; border-radius:10px; font-size:12px; color:#fff; }
  .Present { background:#0f766e; } .HalfDay { background:#b08900; }
  .Leave { background:#4f6d7a; } .Absent { background:#c2410c; }
  .note { color:var(--muted); font-size:13px; margin:10px 0 0; }
  .ok { background:#e6f4f1; border:1px solid #b5ded7; padding:8px 14px; border-radius:6px; margin-bottom:14px; }
  .empty { padding:22px; text-align:center; color:var(--muted); }
</style></head>
<body>
<header>
  <h1>Shiv Sena Office</h1>
  <nav>
    <a href="{{ url_for('home') }}" class="{{ 'active' if tab=='home' }}">Home</a>
    <a href="{{ url_for('salaries') }}" class="{{ 'active' if tab=='salaries' }}">Employees &amp; salaries</a>
    <a href="{{ url_for('attendance') }}" class="{{ 'active' if tab=='attendance' }}">Attendance</a>
    <a href="{{ url_for('payroll') }}" class="{{ 'active' if tab=='payroll' }}">Payroll</a>
    <a href="{{ url_for('expenses') }}" class="{{ 'active' if tab=='expenses' }}">Office expenses</a>
  </nav>
</header>
<main>{% block body %}{% endblock %}</main>
</body></html>"""

HOME = """{% extends 'base.html' %}{% block body %}
<h2>Overview</h2>
<p class="sub">Payroll and office spending at a glance.</p>
<div class="kpis">
  <div class="kpi"><div><small>Employees</small><b>{{ n_emp }}</b></div></div>
  <div class="kpi"><div><small>Monthly payroll</small><b>{{ payroll|inr }}</b></div></div>
  <div class="kpi warm"><div><small>{{ month_name }} office expenses</small><b>{{ this_month|inr }}</b></div></div>
  <div class="kpi"><div><small>Present today</small><b>{{ present_today }} of {{ n_emp }}</b></div></div>
</div>
<div class="grid">
  <div class="cell"><div><img src="{{ url_for('chart', name='monthly') }}" alt="Monthly payroll and expenses"></div></div>
  <div class="cell"><div><img src="{{ url_for('chart', name='categories') }}" alt="Expenses by category"></div></div>
  <div class="cell"><div><img src="{{ url_for('chart', name='departments') }}" alt="Payroll by department"></div></div>
  <div class="cell"><div><img src="{{ url_for('chart', name='trend') }}" alt="Expense trend"></div></div>
  <div class="cell"><div><img src="{{ url_for('chart', name='att_daily') }}" alt="Daily attendance"></div></div>
  <div class="cell"><div><img src="{{ url_for('chart', name='att_pct') }}" alt="Attendance percent"></div></div>
</div>
{% endblock %}"""

SALARIES = """{% extends 'base.html' %}{% block body %}
<h2>Employees &amp; salaries</h2>
<p class="sub">{{ emps|length }} employees · total {{ total|inr }} a month · average {{ avg|inr }}</p>

<form class="panel" method="post" action="{{ url_for('add_employee') }}">
  <label><span>Name</span><input name="name" required></label>
  <label><span>Department</span>
    <select name="department">{% for d in departments %}<option>{{ d }}</option>{% endfor %}</select></label>
  <label><span>Role</span><input name="role"></label>
  <label><span>Monthly salary (₹)</span><input name="monthly_salary" type="number" min="1" required></label>
  <label><span>Join date</span><input name="join_date" type="date" value="{{ today }}"></label>
  <button type="submit">Add employee</button>
</form>

<div class="filter">
  <a href="{{ url_for('salaries') }}" class="{{ 'on' if not dept }}">All departments</a>
  {% for d in departments %}<a href="{{ url_for('salaries', dept=d) }}" class="{{ 'on' if dept==d }}">{{ d }}</a>{% endfor %}
</div>

<table>
  <thead><tr><th>Name</th><th>Department</th><th>Role</th><th>Joined</th>
    <th class="num">Monthly</th><th class="num">Yearly</th><th></th></tr></thead>
  <tbody>
  {% for e in emps %}
    <tr><td>{{ e.name }}</td><td>{{ e.department }}</td><td>{{ e.role }}</td><td>{{ e.join_date }}</td>
      <td class="num">{{ e.monthly_salary|inr }}</td><td class="num">{{ (e.monthly_salary*12)|inr }}</td>
      <td class="num"><form method="post" action="{{ url_for('delete_employee', emp_id=e.id) }}"
          onsubmit="return confirm('Remove {{ e.name|e }}?')"><button class="link">Remove</button></form></td></tr>
  {% else %}
    <tr><td colspan="7" class="empty">No employees here yet. Add one using the form above.</td></tr>
  {% endfor %}
  </tbody>
  {% if emps %}<tfoot><tr><td colspan="4">Total</td><td class="num">{{ total|inr }}</td>
    <td class="num">{{ (total*12)|inr }}</td><td></td></tr></tfoot>{% endif %}
</table>
{% endblock %}"""

EXPENSES = """{% extends 'base.html' %}{% block body %}
<h2>Office expenses</h2>
<p class="sub">{{ rows|length }} entries{% if cat %} in {{ cat }}{% endif %} · total {{ total|inr }}</p>

<form class="panel" method="post" action="{{ url_for('add_expense') }}">
  <label><span>Date</span><input name="date" type="date" value="{{ today }}"></label>
  <label><span>Category</span>
    <select name="category">{% for c in categories %}<option>{{ c }}</option>{% endfor %}</select></label>
  <label><span>Description</span><input name="description" required></label>
  <label><span>Amount (₹)</span><input name="amount" type="number" min="1" required></label>
  <button type="submit">Add expense</button>
</form>

<div class="filter">
  <a href="{{ url_for('expenses') }}" class="{{ 'on' if not cat }}">All categories</a>
  {% for c in categories %}<a href="{{ url_for('expenses', category=c) }}" class="{{ 'on' if cat==c }}">{{ c }}</a>{% endfor %}
</div>

<table>
  <thead><tr><th>Date</th><th>Category</th><th>Description</th><th class="num">Amount</th><th></th></tr></thead>
  <tbody>
  {% for r in rows %}
    <tr><td>{{ r.date }}</td><td>{{ r.category }}</td><td>{{ r.description }}</td>
      <td class="num">{{ r.amount|inr }}</td>
      <td class="num"><form method="post" action="{{ url_for('delete_expense', exp_id=r.id) }}"
          onsubmit="return confirm('Delete this expense?')"><button class="link">Delete</button></form></td></tr>
  {% else %}
    <tr><td colspan="5" class="empty">No expenses recorded. Add one using the form above.</td></tr>
  {% endfor %}
  </tbody>
  {% if rows %}<tfoot><tr><td colspan="3">Total</td><td class="num">{{ total|inr }}</td><td></td></tr></tfoot>{% endif %}
</table>
{% endblock %}"""


ATTENDANCE = """{% extends 'base.html' %}{% block body %}
<h2>Attendance</h2>
<p class="sub">Pick a date, set each person's status, then save.</p>
{% if saved %}<div class="ok">Attendance saved for {{ day }}.</div>{% endif %}
<form class="panel" method="get" action="{{ url_for('attendance') }}">
  <label><span>Date</span><input type="date" name="date" value="{{ day }}"></label>
  <button type="submit">Open date</button>
</form>
{% if weekend %}<p class="note">{{ day }} is a weekend. You can still record attendance if the office was open.</p>{% endif %}
<form method="post" action="{{ url_for('save_attendance') }}">
  <input type="hidden" name="date" value="{{ day }}">
  <table>
    <thead><tr><th>Employee</th><th>Department</th><th>Status on {{ day }}</th></tr></thead>
    <tbody>
    {% for e in emps %}
      <tr><td>{{ e.name }}</td><td>{{ e.department }}</td>
        <td><select name="status_{{ e.id }}">
          {% for s in statuses %}<option {{ 'selected' if existing.get(e.id, 'Present')==s }}>{{ s }}</option>{% endfor %}
        </select>{% if e.id not in existing %} <span class="note">not saved yet</span>{% endif %}</td></tr>
    {% else %}
      <tr><td colspan="3" class="empty">Add employees first.</td></tr>
    {% endfor %}
    </tbody>
  </table>
  {% if emps %}<p><button type="submit">Save attendance</button></p>{% endif %}
</form>

<h2 style="margin-top:28px">Monthly summary - {{ month_label }}</h2>
<p class="sub">Attendance % = (present days + half days / 2) / days recorded.</p>
<table>
  <thead><tr><th>Employee</th><th class="num">Present</th><th class="num">Half day</th>
    <th class="num">Leave</th><th class="num">Absent</th><th class="num">Days recorded</th><th class="num">Attendance</th></tr></thead>
  <tbody>
  {% for r in summary %}
    <tr><td>{{ r.emp.name }}</td><td class="num">{{ r.counts['Present'] }}</td><td class="num">{{ r.counts['Half Day'] }}</td>
      <td class="num">{{ r.counts['Leave'] }}</td><td class="num">{{ r.counts['Absent'] }}</td>
      <td class="num">{{ r.marked }}</td><td class="num">{{ '%.0f'|format(r.pct) }}%</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}"""

PAYROLL = """{% extends 'base.html' %}{% block body %}
<h2>Payroll</h2>
<p class="sub">{{ month_label }} · {{ wd }} working days (Mon-Fri) · net pay {{ tot_net|inr }}</p>
<form class="panel" method="get" action="{{ url_for('payroll') }}">
  <label><span>Month</span><input type="month" name="month" value="{{ month }}"></label>
  <button type="submit">Show month</button>
  <p class="note">Each absent day deducts one day's pay (monthly salary / working days). A half day deducts half. Leave is paid.</p>
</form>
<table>
  <thead><tr><th>Employee</th><th>Department</th><th class="num">Base salary</th><th class="num">Absent</th>
    <th class="num">Half days</th><th class="num">Deduction</th><th class="num">Net pay</th></tr></thead>
  <tbody>
  {% for r in rows %}
    <tr><td>{{ r.emp.name }}</td><td>{{ r.emp.department }}</td><td class="num">{{ r.emp.monthly_salary|inr }}</td>
      <td class="num">{{ r.counts['Absent'] }}</td><td class="num">{{ r.counts['Half Day'] }}</td>
      <td class="num">{{ r.deduction|inr }}</td><td class="num"><b>{{ r.net|inr }}</b></td></tr>
  {% else %}
    <tr><td colspan="7" class="empty">No employees yet.</td></tr>
  {% endfor %}
  </tbody>
  {% if rows %}<tfoot><tr><td colspan="2">Total</td><td class="num">{{ tot_base|inr }}</td><td></td><td></td>
    <td class="num">{{ tot_ded|inr }}</td><td class="num">{{ tot_net|inr }}</td></tr></tfoot>{% endif %}
</table>
{% endblock %}"""

app.jinja_loader = DictLoader({"base.html": BASE, "home.html": HOME,
                               "salaries.html": SALARIES, "expenses.html": EXPENSES,
                               "attendance.html": ATTENDANCE, "payroll.html": PAYROLL})

if __name__ == "__main__":
    init_db()
    print("Office Manager running at http://127.0.0.1:5000  (Ctrl+C to stop)")
    app.run(debug=False)
