"""
DentalBot v2 — management_portal.py
Flask-based internal management portal for clinic staff.

Runs on port 5000 (separate from main.py which runs on 8000).
Protected by session-based login.

Sections:
    /dashboard         → Overview: counts, today's appointments, recent complaints
    /appointments      → View, filter, update, cancel appointments
    /patients          → View patient records, search by name/contact
    /complaints        → View complaints, update status (pending/reviewed/resolved)
    /orders            → View patient orders, update status (placed/ready/delivered)
    /business-logs     → View all supplier/agent/business call logs
    /login             → Staff login
    /logout            → Logout
"""

import os
from flask import (
    Flask, render_template_string, request,
    redirect, url_for, session, flash, jsonify
)
from dotenv import load_dotenv
from datetime import date, datetime
from functools import wraps

from db.db_connection import get_db_connection, db_cursor
from utils.text_utils import title_case
from utils.phone_utils import normalize_phone, format_phone_for_speech

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("PORTAL_SECRET_KEY", "dentalbot-portal-secret-2026")

# ─────────────────────────────────────────────────────────────────────────────
# STAFF CREDENTIALS (loaded from .env — never hardcoded in prod)
# ─────────────────────────────────────────────────────────────────────────────

PORTAL_USERNAME = os.getenv("PORTAL_USERNAME", "admin")
PORTAL_PASSWORD = os.getenv("PORTAL_PASSWORD", "clinic2026")


# ─────────────────────────────────────────────────────────────────────────────
# AUTH GUARD
# ─────────────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
# BASE TEMPLATE
# ─────────────────────────────────────────────────────────────────────────────

BASE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} — DentalBot Portal</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
               Roboto, sans-serif; background: #f0f4f8; color: #1a202c; }

        /* NAV */
        .nav {
            background: #1a365d; color: white;
            display: flex; align-items: center;
            justify-content: space-between;
            padding: 0 2rem; height: 56px;
        }
        .nav-brand { font-weight: 700; font-size: 1.1rem; letter-spacing: 0.5px; }
        .nav-links { display: flex; gap: 1.5rem; list-style: none; }
        .nav-links a {
            color: #bee3f8; text-decoration: none;
            font-size: 0.875rem; padding: 4px 8px;
            border-radius: 4px; transition: background 0.2s;
        }
        .nav-links a:hover, .nav-links a.active { background: #2b6cb0; color: white; }
        .nav-right { font-size: 0.8rem; color: #bee3f8; }
        .logout-btn {
            background: #c53030; color: white; border: none;
            padding: 6px 14px; border-radius: 4px; cursor: pointer;
            font-size: 0.8rem; margin-left: 1rem;
        }
        .logout-btn:hover { background: #9b2c2c; }

        /* LAYOUT */
        .container { max-width: 1300px; margin: 0 auto; padding: 2rem; }
        h1 { font-size: 1.5rem; color: #2d3748; margin-bottom: 1.5rem;
             padding-bottom: 0.5rem; border-bottom: 2px solid #e2e8f0; }
        h2 { font-size: 1.1rem; color: #4a5568; margin-bottom: 1rem; }

        /* CARDS */
        .card {
            background: white; border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            padding: 1.5rem; margin-bottom: 1.5rem;
        }

        /* STAT CARDS */
        .stats-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem; margin-bottom: 1.5rem;
        }
        .stat-card {
            background: white; border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            padding: 1.2rem 1.5rem; border-left: 4px solid #3182ce;
        }
        .stat-card.green  { border-left-color: #38a169; }
        .stat-card.orange { border-left-color: #dd6b20; }
        .stat-card.red    { border-left-color: #e53e3e; }
        .stat-card.purple { border-left-color: #805ad5; }
        .stat-number { font-size: 2rem; font-weight: 700; color: #2d3748; }
        .stat-label  { font-size: 0.8rem; color: #718096; margin-top: 4px; }

        /* TABLE */
        .table-wrap { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
        th {
            background: #edf2f7; color: #4a5568;
            padding: 10px 14px; text-align: left;
            font-weight: 600; font-size: 0.8rem;
            text-transform: uppercase; letter-spacing: 0.5px;
            border-bottom: 2px solid #e2e8f0;
        }
        td { padding: 10px 14px; border-bottom: 1px solid #f7fafc; }
        tr:hover td { background: #f7fafc; }
        tr:last-child td { border-bottom: none; }

        /* BADGES */
        .badge {
            display: inline-block; padding: 2px 10px;
            border-radius: 12px; font-size: 0.75rem; font-weight: 600;
        }
        .badge-blue    { background: #ebf8ff; color: #2b6cb0; }
        .badge-green   { background: #f0fff4; color: #276749; }
        .badge-orange  { background: #fffaf0; color: #c05621; }
        .badge-red     { background: #fff5f5; color: #c53030; }
        .badge-purple  { background: #faf5ff; color: #6b46c1; }
        .badge-gray    { background: #f7fafc; color: #4a5568; }

        /* FORMS */
        .search-bar { display: flex; gap: 0.75rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
        input[type="text"], input[type="password"], select {
            padding: 8px 12px; border: 1px solid #e2e8f0;
            border-radius: 6px; font-size: 0.875rem;
            outline: none; transition: border 0.2s;
        }
        input[type="text"]:focus, select:focus { border-color: #3182ce; }
        .btn {
            padding: 8px 16px; border: none; border-radius: 6px;
            cursor: pointer; font-size: 0.875rem; font-weight: 500;
            transition: background 0.2s;
        }
        .btn-blue   { background: #3182ce; color: white; }
        .btn-blue:hover   { background: #2b6cb0; }
        .btn-green  { background: #38a169; color: white; }
        .btn-green:hover  { background: #276749; }
        .btn-orange { background: #dd6b20; color: white; }
        .btn-orange:hover { background: #c05621; }
        .btn-red    { background: #e53e3e; color: white; }
        .btn-red:hover    { background: #c53030; }
        .btn-gray   { background: #e2e8f0; color: #4a5568; }
        .btn-gray:hover   { background: #cbd5e0; }
        .btn-sm { padding: 4px 10px; font-size: 0.78rem; }

        /* ALERTS */
        .alert {
            padding: 12px 16px; border-radius: 6px;
            margin-bottom: 1rem; font-size: 0.875rem;
        }
        .alert-success { background: #f0fff4; color: #276749;
                         border: 1px solid #c6f6d5; }
        .alert-error   { background: #fff5f5; color: #c53030;
                         border: 1px solid #fed7d7; }

        /* LOGIN */
        .login-wrap {
            min-height: 100vh; display: flex;
            align-items: center; justify-content: center;
            background: #1a365d;
        }
        .login-card {
            background: white; border-radius: 12px;
            padding: 3rem 2.5rem; width: 360px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        .login-card h1 {
            font-size: 1.4rem; text-align: center;
            margin-bottom: 0.25rem; border: none;
        }
        .login-card p { text-align: center; color: #718096;
                        font-size: 0.875rem; margin-bottom: 2rem; }
        .form-group { margin-bottom: 1rem; }
        .form-group label { display: block; font-size: 0.8rem;
                            font-weight: 600; color: #4a5568;
                            margin-bottom: 4px; }
        .form-group input { width: 100%; }
        .no-data { text-align: center; color: #a0aec0;
                   padding: 3rem; font-size: 0.9rem; }
    </style>
</head>
<body>

{% if show_nav %}
<nav class="nav">
    <div class="nav-brand">🦷 Primary Dental — Management Portal</div>
    <ul class="nav-links">
        <li><a href="/dashboard"      {% if active=='dashboard'      %}class="active"{% endif %}>Dashboard</a></li>
        <li><a href="/appointments"   {% if active=='appointments'   %}class="active"{% endif %}>Appointments</a></li>
        <li><a href="/patients"       {% if active=='patients'       %}class="active"{% endif %}>Patients</a></li>
        <li><a href="/complaints"     {% if active=='complaints'     %}class="active"{% endif %}>Complaints</a></li>
        <li><a href="/orders"         {% if active=='orders'         %}class="active"{% endif %}>Orders</a></li>
        <li><a href="/business-logs"  {% if active=='business-logs'  %}class="active"{% endif %}>Business Logs</a></li>
    </ul>
    <div class="nav-right">
        Staff: {{ session.username }}
        <form action="/logout" method="post" style="display:inline">
            <button class="logout-btn" type="submit">Logout</button>
        </form>
    </div>
</nav>
{% endif %}

<div class="container">
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% for category, message in messages %}
            <div class="alert alert-{{ category }}">{{ message }}</div>
        {% endfor %}
    {% endwith %}
    {{ content }}
</div>

</body>
</html>
"""


def render_page(title, content, active="", show_nav=True):
    return render_template_string(
        BASE_HTML,
        title=title,
        content=content,
        active=active,
        show_nav=show_nav
    )


# ─────────────────────────────────────────────────────────────────────────────
# LOGIN / LOGOUT
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if username == PORTAL_USERNAME and password == PORTAL_PASSWORD:
            session["logged_in"] = True
            session["username"]  = username
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.", "error")

    content = """
    <div class="login-wrap">
        <div class="login-card">
            <h1>🦷 DentalBot Portal</h1>
            <p>Primary Dental Clinic — Staff Login</p>
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endwith %}
            <form method="post">
                <div class="form-group">
                    <label>Username</label>
                    <input type="text" name="username"
                           placeholder="Enter username" autocomplete="off" required>
                </div>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" name="password"
                           placeholder="Enter password" required>
                </div>
                <button type="submit" class="btn btn-blue"
                        style="width:100%;padding:10px;margin-top:0.5rem;font-size:1rem">
                    Login
                </button>
            </form>
        </div>
    </div>
    """
    return render_template_string(BASE_HTML, title="Login",
                                  content=content, active="", show_nav=False)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    return redirect(url_for("dashboard"))


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    conn   = get_db_connection()
    cursor = conn.cursor()
    today  = date.today().strftime("%Y-%m-%d")

    # Stats
    cursor.execute("SELECT COUNT(*) FROM patients")
    total_patients = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM appointments WHERE status != 'cancelled'"
    )
    total_appointments = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM appointments WHERE preferred_date = %s "
        "AND status != 'cancelled'", (today,)
    )
    todays_appointments = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM complaints WHERE status = 'pending'"
    )
    pending_complaints = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM patient_orders WHERE order_status = 'ready'"
    )
    ready_orders = cursor.fetchone()[0]

    # Today's appointments detail
    cursor.execute("""
        SELECT
            p.first_name, p.last_name, p.contact_number,
            a.preferred_treatment, a.preferred_time, a.preferred_dentist, a.status
        FROM appointments a
        JOIN patients p ON a.patient_id = p.patient_id
        WHERE a.preferred_date = %s AND a.status != 'cancelled'
        ORDER BY a.preferred_time ASC
    """, (today,))
    todays_appts = cursor.fetchall()

    # Recent complaints (last 5 pending)
    cursor.execute("""
        SELECT
            patient_name, contact_number, complaint_category,
            complaint_text, created_at
        FROM complaints
        WHERE status = 'pending'
        ORDER BY created_at DESC
        LIMIT 5
    """)
    recent_complaints = cursor.fetchall()

    # Ready orders
    cursor.execute("""
        SELECT
            po.product_name, p.first_name, p.last_name,
            p.contact_number, po.updated_at
        FROM patient_orders po
        JOIN patients p ON po.patient_id = p.patient_id
        WHERE po.order_status = 'ready'
        ORDER BY po.updated_at DESC
        LIMIT 5
    """)
    ready_order_list = cursor.fetchall()

    cursor.close()
    conn.close()

    # Build today's appointments table
    if todays_appts:
        rows = ""
        for r in todays_appts:
            status_class = "badge-green" if r[6] == "confirmed" else "badge-blue"
            rows += f"""
            <tr>
                <td>{title_case(r[0])} {title_case(r[1])}</td>
                <td>{format_phone_for_speech(r[2])}</td>
                <td>{r[3]}</td>
                <td>{r[4]}</td>
                <td>{r[5]}</td>
                <td><span class="badge {status_class}">{r[6]}</span></td>
            </tr>"""
        todays_table = f"""
        <div class="table-wrap">
        <table>
            <tr>
                <th>Patient</th><th>Contact</th><th>Treatment</th>
                <th>Time</th><th>Dentist</th><th>Status</th>
            </tr>
            {rows}
        </table>
        </div>"""
    else:
        todays_table = '<p class="no-data">No appointments today.</p>'

    # Recent complaints section
    if recent_complaints:
        comp_rows = ""
        for r in recent_complaints:
            cat_class = "badge-orange" if r[2] == "treatment" else "badge-blue"
            text_short = r[3][:80] + "..." if len(r[3]) > 80 else r[3]
            comp_rows += f"""
            <tr>
                <td>{r[0]}</td>
                <td>{format_phone_for_speech(r[1])}</td>
                <td><span class="badge {cat_class}">{r[2]}</span></td>
                <td>{text_short}</td>
                <td>{str(r[4])[:16]}</td>
            </tr>"""
        comp_table = f"""
        <div class="table-wrap">
        <table>
            <tr>
                <th>Patient</th><th>Contact</th><th>Type</th>
                <th>Summary</th><th>Received</th>
            </tr>
            {comp_rows}
        </table>
        </div>"""
    else:
        comp_table = '<p class="no-data">No pending complaints.</p>'

    # Ready orders section
    if ready_order_list:
        order_rows = ""
        for r in ready_order_list:
            order_rows += f"""
            <tr>
                <td>{r[0]}</td>
                <td>{title_case(r[1])} {title_case(r[2])}</td>
                <td>{format_phone_for_speech(r[3])}</td>
                <td>{str(r[4])[:16]}</td>
            </tr>"""
        order_table = f"""
        <div class="table-wrap">
        <table>
            <tr>
                <th>Item</th><th>Patient</th><th>Contact</th><th>Ready Since</th>
            </tr>
            {order_rows}
        </table>
        </div>"""
    else:
        order_table = '<p class="no-data">No items ready for collection.</p>'

    content = f"""
    <h1>📊 Dashboard</h1>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-number">{total_patients}</div>
            <div class="stat-label">Total Patients</div>
        </div>
        <div class="stat-card green">
            <div class="stat-number">{todays_appointments}</div>
            <div class="stat-label">Today's Appointments</div>
        </div>
        <div class="stat-card blue">
            <div class="stat-number">{total_appointments}</div>
            <div class="stat-label">All Active Appointments</div>
        </div>
        <div class="stat-card red">
            <div class="stat-number">{pending_complaints}</div>
            <div class="stat-label">Pending Complaints</div>
        </div>
        <div class="stat-card orange">
            <div class="stat-number">{ready_orders}</div>
            <div class="stat-label">Orders Ready for Collection</div>
        </div>
    </div>

    <div class="card">
        <h2>📅 Today's Appointments — {today}</h2>
        {todays_table}
    </div>

    <div class="card">
        <h2>⚠️ Pending Complaints</h2>
        {comp_table}
        <div style="margin-top:0.75rem">
            <a href="/complaints" class="btn btn-orange btn-sm">View All Complaints →</a>
        </div>
    </div>

    <div class="card">
        <h2>📦 Orders Ready for Collection</h2>
        {order_table}
        <div style="margin-top:0.75rem">
            <a href="/orders" class="btn btn-blue btn-sm">View All Orders →</a>
        </div>
    </div>
    """

    return render_page("Dashboard", content, active="dashboard")


# ─────────────────────────────────────────────────────────────────────────────
# APPOINTMENTS
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/appointments", methods=["GET", "POST"])
@login_required
def appointments():
    search    = request.args.get("search", "").strip()
    dentist_f = request.args.get("dentist", "").strip()
    status_f  = request.args.get("status", "").strip()
    date_f    = request.args.get("date", "").strip()

    conn   = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT
            a.appointment_id, p.first_name, p.last_name,
            p.contact_number, a.preferred_treatment,
            a.preferred_date, a.preferred_time,
            a.preferred_dentist, a.status, a.created_at
        FROM appointments a
        JOIN patients p ON a.patient_id = p.patient_id
        WHERE 1=1
    """
    params = []

    if search:
        query  += " AND (LOWER(p.first_name) LIKE LOWER(%s) OR LOWER(p.last_name) LIKE LOWER(%s))"
        params += [f"%{search}%", f"%{search}%"]
    if dentist_f:
        query  += " AND LOWER(a.preferred_dentist) LIKE LOWER(%s)"
        params += [f"%{dentist_f}%"]
    if status_f:
        query  += " AND a.status = %s"
        params += [status_f]
    if date_f:
        query  += " AND a.preferred_date = %s"
        params += [date_f]

    query += " ORDER BY a.preferred_date DESC, a.preferred_time DESC LIMIT 200"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    status_colors = {
        "confirmed": "badge-green",
        "pending":   "badge-blue",
        "cancelled": "badge-red",
        "completed": "badge-gray"
    }

    table_rows = ""
    for r in rows:
        s_class = status_colors.get(r[8], "badge-gray")
        table_rows += f"""
        <tr>
            <td>{title_case(r[1])} {title_case(r[2])}</td>
            <td>{format_phone_for_speech(r[3])}</td>
            <td>{r[4]}</td>
            <td>{r[5]}</td>
            <td>{r[6]}</td>
            <td>{r[7]}</td>
            <td><span class="badge {s_class}">{r[8]}</span></td>
            <td>{str(r[9])[:10]}</td>
            <td>
                <form method="post" action="/appointments/update-status" style="display:inline">
                    <input type="hidden" name="appointment_id" value="{r[0]}">
                    <select name="new_status" style="font-size:0.78rem;padding:3px 6px">
                        <option value="">Change...</option>
                        <option value="confirmed">confirmed</option>
                        <option value="completed">completed</option>
                        <option value="cancelled">cancelled</option>
                        <option value="pending">pending</option>
                    </select>
                    <button type="submit" class="btn btn-blue btn-sm">Save</button>
                </form>
            </td>
        </tr>"""

    if not table_rows:
        table_rows = '<tr><td colspan="9" class="no-data">No appointments found.</td></tr>'

    content = f"""
    <h1>📅 Appointments</h1>

    <div class="card">
        <form method="get" class="search-bar">
            <input type="text"  name="search"  placeholder="Search patient name..."
                   value="{search}" style="width:220px">
            <input type="text"  name="date"    placeholder="Date (YYYY-MM-DD)"
                   value="{date_f}" style="width:170px">
            <select name="dentist">
                <option value="">All Dentists</option>
                <option value="Carter"   {"selected" if "Carter"   in dentist_f else ""}>Dr. Emily Carter</option>
                <option value="Nguyen"   {"selected" if "Nguyen"   in dentist_f else ""}>Dr. James Nguyen</option>
                <option value="Mitchell" {"selected" if "Mitchell" in dentist_f else ""}>Dr. Sarah Mitchell</option>
            </select>
            <select name="status">
                <option value="">All Statuses</option>
                <option value="confirmed" {"selected" if status_f=="confirmed" else ""}>Confirmed</option>
                <option value="pending"   {"selected" if status_f=="pending"   else ""}>Pending</option>
                <option value="completed" {"selected" if status_f=="completed" else ""}>Completed</option>
                <option value="cancelled" {"selected" if status_f=="cancelled" else ""}>Cancelled</option>
            </select>
            <button type="submit" class="btn btn-blue">Search</button>
            <a href="/appointments" class="btn btn-gray">Clear</a>
        </form>

        <div class="table-wrap">
        <table>
            <tr>
                <th>Patient</th><th>Contact</th><th>Treatment</th>
                <th>Date</th><th>Time</th><th>Dentist</th>
                <th>Status</th><th>Booked</th><th>Action</th>
            </tr>
            {table_rows}
        </table>
        </div>
    </div>
    """

    return render_page("Appointments", content, active="appointments")


@app.route("/appointments/update-status", methods=["POST"])
@login_required
def update_appointment_status():
    appointment_id = request.form.get("appointment_id")
    new_status     = request.form.get("new_status", "").strip()

    if not appointment_id or not new_status:
        flash("Missing appointment ID or status.", "error")
        return redirect(url_for("appointments"))

    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE appointments
            SET status = %s
            WHERE appointment_id = %s
        """, (new_status, appointment_id))
        conn.commit()
        cursor.close()
        conn.close()
        flash(f"Appointment status updated to '{new_status}'.", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for("appointments"))


# ─────────────────────────────────────────────────────────────────────────────
# PATIENTS
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/patients")
@login_required
def patients():
    search = request.args.get("search", "").strip()

    conn   = get_db_connection()
    cursor = conn.cursor()

    if search:
        cursor.execute("""
            SELECT
                patient_id, first_name, last_name,
                date_of_birth, contact_number,
                insurance_info, created_at
            FROM patients
            WHERE LOWER(first_name) LIKE LOWER(%s)
               OR LOWER(last_name)  LIKE LOWER(%s)
               OR contact_number    LIKE %s
            ORDER BY created_at DESC
            LIMIT 100
        """, (f"%{search}%", f"%{search}%", f"%{search}%"))
    else:
        cursor.execute("""
            SELECT
                patient_id, first_name, last_name,
                date_of_birth, contact_number,
                insurance_info, created_at
            FROM patients
            ORDER BY created_at DESC
            LIMIT 100
        """)

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    table_rows = ""
    for r in rows:
        ins = r[5] if r[5] else '<span style="color:#a0aec0">None</span>'
        table_rows += f"""
        <tr>
            <td>{title_case(r[1])} {title_case(r[2])}</td>
            <td>{r[3]}</td>
            <td>{format_phone_for_speech(r[4])}</td>
            <td>{ins}</td>
            <td>{str(r[6])[:10]}</td>
            <td>
                <a href="/patients/{r[0]}" class="btn btn-blue btn-sm">View</a>
            </td>
        </tr>"""

    if not table_rows:
        table_rows = '<tr><td colspan="6" class="no-data">No patients found.</td></tr>'

    content = f"""
    <h1>👥 Patients</h1>

    <div class="card">
        <form method="get" class="search-bar">
            <input type="text" name="search"
                   placeholder="Search by name or contact..."
                   value="{search}" style="width:300px">
            <button type="submit" class="btn btn-blue">Search</button>
            <a href="/patients" class="btn btn-gray">Clear</a>
        </form>

        <div class="table-wrap">
        <table>
            <tr>
                <th>Name</th><th>Date of Birth</th><th>Contact</th>
                <th>Insurance</th><th>Registered</th><th>Action</th>
            </tr>
            {table_rows}
        </table>
        </div>
    </div>
    """

    return render_page("Patients", content, active="patients")


@app.route("/patients/<int:patient_id>")
@login_required
def patient_detail(patient_id):
    with db_cursor() as (cursor, conn):

        # Patient info
        cursor.execute("""
            SELECT first_name, last_name, date_of_birth,
                contact_number, insurance_info, created_at
            FROM patients WHERE patient_id = %s
        """, (patient_id,))
        p = cursor.fetchone()

    if not p:
        flash("Patient not found.", "error")
        return redirect(url_for("patients"))

    # Appointments
    cursor.execute("""
        SELECT preferred_treatment, preferred_date, preferred_time,
               preferred_dentist, status, created_at
        FROM appointments
        WHERE patient_id = %s
        ORDER BY preferred_date DESC
    """, (patient_id,))
    appts = cursor.fetchall()

    # Complaints
    cursor.execute("""
        SELECT complaint_category, complaint_text,
               treatment_name, dentist_name, status, created_at
        FROM complaints
        WHERE LOWER(patient_name) LIKE LOWER(%s)
        ORDER BY created_at DESC
    """, (f"%{p[1]}%",))
    comps = cursor.fetchall()

    # Orders
    cursor.execute("""
        SELECT product_name, order_status, notes, placed_at, updated_at
        FROM patient_orders
        WHERE patient_id = %s
        ORDER BY placed_at DESC
    """, (patient_id,))
    orders = cursor.fetchall()


    # Build appointment rows
    appt_rows = ""
    for a in appts:
        s_class = {"confirmed": "badge-green", "cancelled": "badge-red",
                   "completed": "badge-gray"}.get(a[4], "badge-blue")
        appt_rows += f"""
        <tr>
            <td>{a[0]}</td><td>{a[1]}</td><td>{a[2]}</td>
            <td>{a[3]}</td>
            <td><span class="badge {s_class}">{a[4]}</span></td>
            <td>{str(a[5])[:10]}</td>
        </tr>"""

    # Build complaint rows
    comp_rows = ""
    for c in comps:
        cat_class = "badge-orange" if c[0] == "treatment" else "badge-blue"
        st_class  = {"pending":  "badge-red", "reviewed": "badge-orange",
                     "resolved": "badge-green"}.get(c[4], "badge-gray")
        short_text = c[1][:60] + "..." if len(c[1]) > 60 else c[1]
        comp_rows += f"""
        <tr>
            <td><span class="badge {cat_class}">{c[0]}</span></td>
            <td>{short_text}</td>
            <td>{c[2] or "—"}</td><td>{c[3] or "—"}</td>
            <td><span class="badge {st_class}">{c[4]}</span></td>
            <td>{str(c[5])[:10]}</td>
        </tr>"""

    # Build order rows
    order_rows = ""
    for o in orders:
        st_class = {"placed": "badge-blue", "ready": "badge-orange",
                    "delivered": "badge-green"}.get(o[1], "badge-gray")
        order_rows += f"""
        <tr>
            <td>{o[0]}</td>
            <td><span class="badge {st_class}">{o[1]}</span></td>
            <td>{o[2] or "—"}</td>
            <td>{str(o[3])[:10]}</td><td>{str(o[4])[:10]}</td>
        </tr>"""

    ins = p[4] if p[4] else "None"

    content = f"""
    <h1>👤 {title_case(p[0])} {title_case(p[1])}</h1>
    <p style="margin-bottom:1.5rem">
        <a href="/patients" style="color:#3182ce;text-decoration:none">
            ← Back to Patients
        </a>
    </p>

    <div class="card">
        <h2>Patient Details</h2>
        <table style="width:auto;margin-bottom:0">
            <tr><td style="color:#718096;padding:6px 16px 6px 0">Name</td>
                <td style="padding:6px 0"><strong>{title_case(p[0])} {title_case(p[1])}</strong></td></tr>
            <tr><td style="color:#718096;padding:6px 16px 6px 0">Date of Birth</td>
                <td style="padding:6px 0">{p[2]}</td></tr>
            <tr><td style="color:#718096;padding:6px 16px 6px 0">Contact</td>
                <td style="padding:6px 0">{format_phone_for_speech(p[3])}</td></tr>
            <tr><td style="color:#718096;padding:6px 16px 6px 0">Insurance</td>
                <td style="padding:6px 0">{ins}</td></tr>
            <tr><td style="color:#718096;padding:6px 16px 6px 0">Registered</td>
                <td style="padding:6px 0">{str(p[5])[:10]}</td></tr>
        </table>
    </div>

    <div class="card">
        <h2>📅 Appointments ({len(appts)})</h2>
        {'<div class="table-wrap"><table><tr><th>Treatment</th><th>Date</th><th>Time</th><th>Dentist</th><th>Status</th><th>Booked</th></tr>' + appt_rows + '</table></div>'
         if appts else '<p class="no-data">No appointments.</p>'}
    </div>

    <div class="card">
        <h2>⚠️ Complaints ({len(comps)})</h2>
        {'<div class="table-wrap"><table><tr><th>Type</th><th>Description</th><th>Treatment</th><th>Dentist</th><th>Status</th><th>Date</th></tr>' + comp_rows + '</table></div>'
         if comps else '<p class="no-data">No complaints.</p>'}
    </div>

    <div class="card">
        <h2>📦 Orders ({len(orders)})</h2>
        {'<div class="table-wrap"><table><tr><th>Product</th><th>Status</th><th>Notes</th><th>Placed</th><th>Updated</th></tr>' + order_rows + '</table></div>'
         if orders else '<p class="no-data">No orders.</p>'}
    </div>
    """

    return render_page(f"{p[0]} {p[1]}", content, active="patients")


# ─────────────────────────────────────────────────────────────────────────────
# COMPLAINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/complaints", methods=["GET"])
@login_required
def complaints():
    status_f   = request.args.get("status",   "").strip()
    category_f = request.args.get("category", "").strip()
    search     = request.args.get("search",   "").strip()

    conn   = get_db_connection()
    cursor = conn.cursor()

    query  = """
        SELECT complaint_id, complaint_category, patient_name,
               contact_number, complaint_text, treatment_name,
               dentist_name, treatment_date, status, created_at
        FROM complaints WHERE 1=1
    """
    params = []

    if status_f:
        query  += " AND status = %s"
        params += [status_f]
    if category_f:
        query  += " AND complaint_category = %s"
        params += [category_f]
    if search:
        query  += " AND LOWER(patient_name) LIKE LOWER(%s)"
        params += [f"%{search}%"]

    query += " ORDER BY created_at DESC LIMIT 200"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    table_rows = ""
    for r in rows:
        cat_class = "badge-orange" if r[1] == "treatment" else "badge-blue"
        st_class  = {"pending":  "badge-red", "reviewed": "badge-orange",
                     "resolved": "badge-green"}.get(r[8], "badge-gray")
        short_text = r[4][:70] + "..." if len(r[4]) > 70 else r[4]
        table_rows += f"""
        <tr>
            <td>{r[2]}</td>
            <td>{format_phone_for_speech(r[3])}</td>
            <td><span class="badge {cat_class}">{r[1]}</span></td>
            <td>{short_text}</td>
            <td>{r[5] or "—"}</td>
            <td>{r[6] or "—"}</td>
            <td><span class="badge {st_class}">{r[8]}</span></td>
            <td>{str(r[9])[:10]}</td>
            <td>
                <form method="post" action="/complaints/update-status"
                      style="display:inline">
                    <input type="hidden" name="complaint_id" value="{r[0]}">
                    <select name="new_status"
                            style="font-size:0.78rem;padding:3px 6px">
                        <option value="">Change...</option>
                        <option value="pending">pending</option>
                        <option value="reviewed">reviewed</option>
                        <option value="resolved">resolved</option>
                    </select>
                    <button type="submit" class="btn btn-orange btn-sm">
                        Save
                    </button>
                </form>
            </td>
        </tr>"""

    if not table_rows:
        table_rows = '<tr><td colspan="9" class="no-data">No complaints found.</td></tr>'

    content = f"""
    <h1>⚠️ Complaints</h1>

    <div class="card">
        <form method="get" class="search-bar">
            <input type="text" name="search"
                   placeholder="Search patient name..."
                   value="{search}" style="width:220px">
            <select name="status">
                <option value="">All Statuses</option>
                <option value="pending"  {"selected" if status_f=="pending"  else ""}>Pending</option>
                <option value="reviewed" {"selected" if status_f=="reviewed" else ""}>Reviewed</option>
                <option value="resolved" {"selected" if status_f=="resolved" else ""}>Resolved</option>
            </select>
            <select name="category">
                <option value="">All Types</option>
                <option value="general"   {"selected" if category_f=="general"   else ""}>General</option>
                <option value="treatment" {"selected" if category_f=="treatment" else ""}>Treatment</option>
            </select>
            <button type="submit" class="btn btn-blue">Filter</button>
            <a href="/complaints" class="btn btn-gray">Clear</a>
        </form>

        <div class="table-wrap">
        <table>
            <tr>
                <th>Patient</th><th>Contact</th><th>Type</th>
                <th>Description</th><th>Treatment</th><th>Dentist</th>
                <th>Status</th><th>Date</th><th>Action</th>
            </tr>
            {table_rows}
        </table>
        </div>
    </div>
    """

    return render_page("Complaints", content, active="complaints")


@app.route("/complaints/update-status", methods=["POST"])
@login_required
def update_complaint_status():
    complaint_id = request.form.get("complaint_id")
    new_status   = request.form.get("new_status", "").strip()

    if not complaint_id or not new_status:
        flash("Missing complaint ID or status.", "error")
        return redirect(url_for("complaints"))

    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE complaints SET status = %s
            WHERE complaint_id = %s
        """, (new_status, complaint_id))
        conn.commit()
        cursor.close()
        conn.close()
        flash(f"Complaint status updated to '{new_status}'.", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for("complaints"))


# ─────────────────────────────────────────────────────────────────────────────
# ORDERS
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/orders", methods=["GET"])
@login_required
def orders():
    status_f = request.args.get("status", "").strip()
    search   = request.args.get("search", "").strip()

    conn   = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT
            po.order_id, p.first_name, p.last_name,
            p.contact_number, po.product_name,
            po.order_status, po.notes,
            po.placed_at, po.updated_at
        FROM patient_orders po
        JOIN patients p ON po.patient_id = p.patient_id
        WHERE 1=1
    """
    params = []

    if status_f:
        query  += " AND po.order_status = %s"
        params += [status_f]
    if search:
        query  += " AND (LOWER(p.first_name) LIKE LOWER(%s) OR LOWER(p.last_name) LIKE LOWER(%s))"
        params += [f"%{search}%", f"%{search}%"]

    query += " ORDER BY po.updated_at DESC LIMIT 200"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    table_rows = ""
    for r in rows:
        st_class = {"placed": "badge-blue", "ready": "badge-orange",
                    "delivered": "badge-green"}.get(r[5], "badge-gray")
        table_rows += f"""
        <tr>
            <td>{title_case(r[1])} {title_case(r[2])}</td>
            <td>{format_phone_for_speech(r[3])}</td>
            <td>{r[4]}</td>
            <td><span class="badge {st_class}">{r[5]}</span></td>
            <td>{r[6] or "—"}</td>
            <td>{str(r[7])[:10]}</td>
            <td>{str(r[8])[:10]}</td>
            <td>
                <form method="post" action="/orders/update-status"
                      style="display:inline">
                    <input type="hidden" name="order_id" value="{r[0]}">
                    <select name="new_status"
                            style="font-size:0.78rem;padding:3px 6px">
                        <option value="">Change...</option>
                        <option value="placed">placed</option>
                        <option value="ready">ready</option>
                        <option value="delivered">delivered</option>
                    </select>
                    <button type="submit" class="btn btn-blue btn-sm">
                        Save
                    </button>
                </form>
            </td>
        </tr>"""

    if not table_rows:
        table_rows = '<tr><td colspan="8" class="no-data">No orders found.</td></tr>'

    content = f"""
    <h1>📦 Patient Orders</h1>

    <div class="card">
        <form method="get" class="search-bar">
            <input type="text" name="search"
                   placeholder="Search patient name..."
                   value="{search}" style="width:220px">
            <select name="status">
                <option value="">All Statuses</option>
                <option value="placed"    {"selected" if status_f=="placed"    else ""}>Placed</option>
                <option value="ready"     {"selected" if status_f=="ready"     else ""}>Ready</option>
                <option value="delivered" {"selected" if status_f=="delivered" else ""}>Delivered</option>
            </select>
            <button type="submit" class="btn btn-blue">Filter</button>
            <a href="/orders" class="btn btn-gray">Clear</a>
        </form>

        <div class="table-wrap">
        <table>
            <tr>
                <th>Patient</th><th>Contact</th><th>Item</th>
                <th>Status</th><th>Notes</th>
                <th>Placed</th><th>Updated</th><th>Action</th>
            </tr>
            {table_rows}
        </table>
        </div>
    </div>
    """

    return render_page("Orders", content, active="orders")


@app.route("/orders/update-status", methods=["POST"])
@login_required
def update_order_status():
    order_id   = request.form.get("order_id")
    new_status = request.form.get("new_status", "").strip()

    if not order_id or not new_status:
        flash("Missing order ID or status.", "error")
        return redirect(url_for("orders"))

    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE patient_orders
            SET order_status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE order_id = %s
        """, (new_status, order_id))
        conn.commit()
        cursor.close()
        conn.close()
        flash(f"Order status updated to '{new_status}'.", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for("orders"))


# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS LOGS
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/business-logs")
@login_required
def business_logs():
    search   = request.args.get("search",  "").strip()
    purpose_f = request.args.get("purpose", "").strip()

    conn   = get_db_connection()
    cursor = conn.cursor()

    query  = """
        SELECT log_id, caller_name, company_name,
               contact_number, purpose, full_call_notes, created_at
        FROM business_logs WHERE 1=1
    """
    params = []

    if search:
        query  += " AND (LOWER(caller_name) LIKE LOWER(%s) OR LOWER(company_name) LIKE LOWER(%s))"
        params += [f"%{search}%", f"%{search}%"]
    if purpose_f:
        query  += " AND purpose = %s"
        params += [purpose_f]

    query += " ORDER BY created_at DESC LIMIT 200"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    purpose_colors = {
        "order_ready":          "badge-green",
        "invoice_billing":      "badge-orange",
        "promotion_partnership":"badge-purple",
        "general_business":     "badge-blue"
    }

    table_rows = ""
    for r in rows:
        p_class = purpose_colors.get(r[4], "badge-gray")
        notes_short = (r[5] or "")[:80] + "..." if r[5] and len(r[5]) > 80 else (r[5] or "—")
        table_rows += f"""
        <tr>
            <td>{r[1] or "—"}</td>
            <td>{r[2] or "—"}</td>
            <td>{format_phone_for_speech(r[3]) if r[3] else "—"}</td>
            <td><span class="badge {p_class}">{(r[4] or "").replace("_"," ")}</span></td>
            <td>{notes_short}</td>
            <td>{str(r[6])[:16]}</td>
        </tr>"""

    if not table_rows:
        table_rows = '<tr><td colspan="6" class="no-data">No business logs found.</td></tr>'

    content = f"""
    <h1>📋 Business Call Logs</h1>

    <div class="card">
        <form method="get" class="search-bar">
            <input type="text" name="search"
                   placeholder="Search caller or company..."
                   value="{search}" style="width:240px">
            <select name="purpose">
                <option value="">All Types</option>
                <option value="order_ready"           {"selected" if purpose_f=="order_ready"           else ""}>Order Ready</option>
                <option value="invoice_billing"       {"selected" if purpose_f=="invoice_billing"       else ""}>Invoice / Billing</option>
                <option value="promotion_partnership" {"selected" if purpose_f=="promotion_partnership" else ""}>Promotion / Partnership</option>
                <option value="general_business"      {"selected" if purpose_f=="general_business"      else ""}>General</option>
            </select>
            <button type="submit" class="btn btn-blue">Filter</button>
            <a href="/business-logs" class="btn btn-gray">Clear</a>
        </form>

        <div class="table-wrap">
        <table>
            <tr>
                <th>Caller</th><th>Company</th><th>Contact</th>
                <th>Purpose</th><th>Notes</th><th>Date & Time</th>
            </tr>
            {table_rows}
        </table>
        </div>
    </div>
    """

    return render_page("Business Logs", content, active="business-logs")


# ─────────────────────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  DentalBot v2 — Management Portal")
    print("  URL  : http://localhost:5000")
    print(f"  User : {PORTAL_USERNAME}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=8081, debug=True)
