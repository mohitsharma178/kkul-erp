
import csv

from io import StringIO
from datetime import date, datetime, timedelta, timezone
from flask import Blueprint, render_template, request, Response
from flask_login import login_required
from sqlalchemy import func

from backend.extensions import db
from backend.models import (
    BagIssue,
    BagType,
    InwardBill,
    InwardItem,
    Plant,
    StockMovement,
    Supervisor,
    User,
)
from backend.permissions import permission_required


reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


# --------------------------------------------------
# COMMON FILTERS
# --------------------------------------------------

def apply_report_filters(
    query, start_date, end_date, plant_id=None, supervisor_id=None
):
    query = query.filter(
        BagIssue.issue_date >= start_date,
        BagIssue.issue_date <= end_date,
    )

    if plant_id:
        query = query.filter(BagIssue.plant_id == plant_id)

    if supervisor_id:
        query = query.filter(BagIssue.supervisor_id == supervisor_id)

    return query


def parse_report_filters():
    today = date.today()
    period = request.args.get("period", "monthly")

    if period == "daily":
        default_start = today
    elif period == "weekly":
        default_start = today - timedelta(days=today.weekday())
    else:
        period = "monthly"
        default_start = today.replace(day=1)

    start_text = request.args.get("start_date", default_start.isoformat())
    end_text = request.args.get("end_date", today.isoformat())

    try:
        start_date = date.fromisoformat(start_text)
        end_date = date.fromisoformat(end_text)

        if start_date > end_date:
            raise ValueError("Start date cannot be after end date")

        if (end_date - start_date).days > 3660:
            raise ValueError("Date range is too large")

    except ValueError:
        start_date = default_start
        end_date = today

    plant_id = request.args.get("plant_id", type=int)
    supervisor_id = request.args.get("supervisor_id", type=int)

    if plant_id and not db.session.get(Plant, plant_id):
        plant_id = None

    if supervisor_id and not db.session.get(Supervisor, supervisor_id):
        supervisor_id = None

    return start_date, end_date, plant_id, supervisor_id


# --------------------------------------------------
# REPORT DATA
# --------------------------------------------------

def get_report_data(start_date, end_date, plant_id=None, supervisor_id=None):
    # Plant issue details
    issue_query = (
        BagIssue.query
        .filter(
            BagIssue.issue_date >= start_date,
            BagIssue.issue_date <= end_date,
        )
    )

    if plant_id:
        issue_query = issue_query.filter(BagIssue.plant_id == plant_id)

    if supervisor_id:
        issue_query = issue_query.filter(
            BagIssue.supervisor_id == supervisor_id
        )

    issues = (
        issue_query
        .order_by(BagIssue.issue_date.desc(), BagIssue.created_at.desc())
        .all()
    )

    total_bags = sum(issue.quantity or 0 for issue in issues)
    total_transactions = len(issues)

    plant_summary = (
        db.session.query(
            Plant.name,
            func.sum(BagIssue.quantity).label("total_quantity"),
        )
        .join(BagIssue, BagIssue.plant_id == Plant.id)
        .filter(
            BagIssue.issue_date >= start_date,
            BagIssue.issue_date <= end_date,
        )
    )

    supervisor_summary = (
        db.session.query(
            Supervisor.name,
            Plant.name.label("plant_name"),
            func.sum(BagIssue.quantity).label("total_quantity"),
        )
        .join(BagIssue, BagIssue.supervisor_id == Supervisor.id)
        .join(Plant, Supervisor.plant_id == Plant.id)
        .filter(
            BagIssue.issue_date >= start_date,
            BagIssue.issue_date <= end_date,
        )
    )

    shift_summary = (
        db.session.query(
            BagIssue.shift,
            func.sum(BagIssue.quantity).label("total_quantity"),
            func.count(BagIssue.id).label("total_transactions"),
        )
        .filter(
            BagIssue.issue_date >= start_date,
            BagIssue.issue_date <= end_date,
        )
    )

    incharge_summary = (
        db.session.query(
            User.full_name.label("incharge_name"),
            func.sum(BagIssue.quantity).label("total_quantity"),
            func.count(BagIssue.id).label("total_transactions"),
        )
        .join(BagIssue, BagIssue.user_id == User.id)
        .filter(
            BagIssue.issue_date >= start_date,
            BagIssue.issue_date <= end_date,
        )
    )

    # Keep plant/supervisor filters consistent across issue summaries.
    if plant_id:
        plant_summary = plant_summary.filter(BagIssue.plant_id == plant_id)
        supervisor_summary = supervisor_summary.filter(
            BagIssue.plant_id == plant_id
        )
        shift_summary = shift_summary.filter(BagIssue.plant_id == plant_id)
        incharge_summary = incharge_summary.filter(
            BagIssue.plant_id == plant_id
        )

    if supervisor_id:
        plant_summary = plant_summary.filter(
            BagIssue.supervisor_id == supervisor_id
        )
        supervisor_summary = supervisor_summary.filter(
            BagIssue.supervisor_id == supervisor_id
        )
        shift_summary = shift_summary.filter(
            BagIssue.supervisor_id == supervisor_id
        )
        incharge_summary = incharge_summary.filter(
            BagIssue.supervisor_id == supervisor_id
        )

    plant_summary = (
        plant_summary.group_by(Plant.name)
        .order_by(func.sum(BagIssue.quantity).desc())
        .all()
    )

    supervisor_summary = (
        supervisor_summary
        .group_by(Supervisor.name, Plant.name)
        .order_by(func.sum(BagIssue.quantity).desc())
        .all()
    )

    shift_summary = (
        shift_summary.group_by(BagIssue.shift)
        .order_by(BagIssue.shift)
        .all()
    )

    incharge_summary = (
        incharge_summary.group_by(User.full_name)
        .order_by(func.sum(BagIssue.quantity).desc())
        .all()
    )

    # Supplier inward details: one row per bag type on each bill.
    inward_items = (
        db.session.query(InwardBill, InwardItem, BagType)
        .join(InwardItem, InwardItem.inward_bill_id == InwardBill.id)
        .join(BagType, InwardItem.bag_type_id == BagType.id)
        .filter(
            InwardBill.inward_date >= start_date,
            InwardBill.inward_date <= end_date,
        )
        .order_by(
            InwardBill.inward_date.desc(),
            InwardBill.id.desc(),
            InwardItem.id,
        )
        .all()
    )

    # Current stock is a current snapshot, not historical stock for the
    # selected report period.
    stock_items = (
        BagType.query
        .order_by(BagType.name.asc(), BagType.size_kg.asc())
        .all()
    )

    # Stock movement history filtered by its creation date.
    movement_items = (
        db.session.query(StockMovement, BagType, User)
        .join(BagType, StockMovement.bag_type_id == BagType.id)
        .outerjoin(User, StockMovement.user_id == User.id)
        .filter(
            func.date(StockMovement.created_at) >= start_date,
            func.date(StockMovement.created_at) <= end_date,
        )
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .all()
    )

    return {
        "issues": issues,
        "total_bags": int(total_bags or 0),
        "total_transactions": int(total_transactions or 0),
        "plant_summary": plant_summary,
        "supervisor_summary": supervisor_summary,
        "shift_summary": shift_summary,
        "incharge_summary": incharge_summary,
        "inward_items": inward_items,
        "stock_items": stock_items,
        "movement_items": movement_items,
    }


def get_last_24_hour_brand_summary():
    """
    Rolling 24-hour issue totals, grouped by bag brand/size
    and then by plant. created_at is stored as UTC.
    """
    now_utc = datetime.now(timezone.utc)

    # MySQL DateTime columns commonly return/store naive UTC values.
    cutoff_utc = (now_utc - timedelta(hours=24)).replace(tzinfo=None)
    now_utc_naive = now_utc.replace(tzinfo=None)

    rows = (
        db.session.query(
            BagType.id.label("bag_type_id"),
            BagType.name.label("brand_name"),
            BagType.size_kg.label("size_kg"),
            Plant.id.label("plant_id"),
            Plant.name.label("plant_name"),
            func.sum(BagIssue.quantity).label("total_quantity"),
        )
        .join(BagIssue, BagIssue.bag_type_id == BagType.id)
        .join(Plant, BagIssue.plant_id == Plant.id)
        .filter(
            BagIssue.created_at >= cutoff_utc,
            BagIssue.created_at <= now_utc_naive,
        )
        .group_by(
            BagType.id,
            BagType.name,
            BagType.size_kg,
            Plant.id,
            Plant.name,
        )
        .order_by(
            BagType.name.asc(),
            BagType.size_kg.asc(),
            Plant.name.asc(),
        )
        .all()
    )

    summary = {}
    grand_total = 0

    for row in rows:
        key = (row.bag_type_id, row.brand_name, row.size_kg)

        if key not in summary:
            summary[key] = {
                "brand_name": row.brand_name,
                "size_kg": row.size_kg,
                "plant_totals": [],
                "grand_total": 0,
            }

        quantity = int(row.total_quantity or 0)

        summary[key]["plant_totals"].append({
            "plant_name": row.plant_name,
            "quantity": quantity,
        })
        summary[key]["grand_total"] += quantity
        grand_total += quantity

    return list(summary.values()), grand_total
# --------------------------------------------------
# SUPERVISOR-WISE BRAND / SIZE ANALYSIS
# --------------------------------------------------

def get_supervisor_brand_summary(
    start_date,
    end_date,
    plant_id=None,
    supervisor_id=None,
):
    query = (
        db.session.query(
            Supervisor.id.label("supervisor_id"),
            Supervisor.name.label("supervisor_name"),
            Plant.name.label("plant_name"),
            BagType.id.label("bag_type_id"),
            BagType.name.label("brand_name"),
            BagType.size_kg.label("size_kg"),
            func.sum(BagIssue.quantity).label("total_issued"),
            func.count(BagIssue.id).label("transactions"),
        )
        .join(BagIssue, BagIssue.supervisor_id == Supervisor.id)
        .join(Plant, BagIssue.plant_id == Plant.id)
        .join(BagType, BagIssue.bag_type_id == BagType.id)
        .filter(
            BagIssue.issue_date >= start_date,
            BagIssue.issue_date <= end_date,
        )
    )

    if plant_id:
        query = query.filter(BagIssue.plant_id == plant_id)

    if supervisor_id:
        query = query.filter(
            BagIssue.supervisor_id == supervisor_id
        )

    return (
        query
        .group_by(
            Supervisor.id,
            Supervisor.name,
            Plant.name,
            BagType.id,
            BagType.name,
            BagType.size_kg,
        )
        .order_by(
            Supervisor.name.asc(),
            Plant.name.asc(),
            BagType.name.asc(),
            BagType.size_kg.asc(),
        )
        .all()
    )
# --------------------------------------------------
# CSV HELPERS
# --------------------------------------------------

def safe_csv_value(value):
    """Reduce spreadsheet formula-injection risk in exported text."""
    if value is None:
        return ""

    value = str(value)

    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value

    return value


def make_csv_response(headers, rows, filename):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)

    for row in rows:
        writer.writerow([safe_csv_value(value) for value in row])

    return Response(
        "\ufeff" + output.getvalue(),
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


def report_filename(prefix, start_date, end_date):
    return f"KKUL_{prefix}_{start_date.isoformat()}_{end_date.isoformat()}.csv"


# --------------------------------------------------
# MAIN REPORT PAGE
# --------------------------------------------------

@reports_bp.route("/", methods=["GET"])
@login_required
@permission_required("reports")
def index():
    start_date, end_date, plant_id, supervisor_id = parse_report_filters()

    data = get_report_data(
        start_date, end_date, plant_id, supervisor_id
    )
    supervisor_brand_summary = get_supervisor_brand_summary(
    start_date,
    end_date,
    plant_id,
    supervisor_id,
)
    brand_issue_summary, last_24_hours_total = (
    get_last_24_hour_brand_summary()
)
    # Chart data for Plant-wise and Shift-wise analytics
    chart_plant_labels = [
        row.name for row in data["plant_summary"]
    ]
    chart_plant_values = [
        int(row.total_quantity or 0)
        for row in data["plant_summary"]
    ]

    chart_shift_labels = [
        row.shift or "Unknown"
        for row in data["shift_summary"]
    ]
    chart_shift_values = [
        int(row.total_quantity or 0)
        for row in data["shift_summary"]
    ]
    plants = Plant.query.order_by(Plant.name.asc()).all()
    supervisors = Supervisor.query.order_by(Supervisor.name.asc()).all()

    return render_template(
        "reports.html",
        supervisor_brand_summary=supervisor_brand_summary,
        start_date=start_date,
        end_date=end_date,
        selected_plant_id=plant_id,
        selected_supervisor_id=supervisor_id,
        plants=plants,
        supervisors=supervisors,
                chart_plant_labels=chart_plant_labels,
        chart_plant_values=chart_plant_values,
        chart_shift_labels=chart_shift_labels,
        chart_shift_values=chart_shift_values,
        **data,
        brand_issue_summary=brand_issue_summary,
last_24_hours_total=last_24_hours_total,
    )


# --------------------------------------------------
# PLANT ISSUE CSV
# Existing URL preserved: /reports/export.csv
# --------------------------------------------------

@reports_bp.route("/supervisor-brand-export.csv")
@login_required
@permission_required("reports")
def supervisor_brand_export():
    start_date, end_date, plant_id, supervisor_id = parse_report_filters()

    rows = get_supervisor_brand_summary(
        start_date,
        end_date,
        plant_id,
        supervisor_id,
    )

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Supervisor",
        "Plant",
        "Bag Brand",
        "Bag Size (kg)",
        "Total Issued",
        "Transactions",
    ])

    for item in rows:
        writer.writerow([
            item.supervisor_name,
            item.plant_name,
            item.brand_name,
            item.size_kg,
            item.total_issued or 0,
            item.transactions or 0,
        ])

    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                "attachment; filename=supervisor_brand_analysis.csv"
        },
    )

@reports_bp.route("/export.csv", methods=["GET"])
@login_required
@permission_required("reports")
def export_csv():
    start_date, end_date, plant_id, supervisor_id = parse_report_filters()
    data = get_report_data(start_date, end_date, plant_id, supervisor_id)

    rows = []

    for issue in data["issues"]:
        rows.append([
            issue.reference_no,
            issue.issue_date.isoformat() if issue.issue_date else "",
            issue.plant.name if issue.plant else "",
            issue.supervisor.name if issue.supervisor else "",
            issue.bag_type.name if issue.bag_type else "",
            issue.bag_type.size_kg if issue.bag_type else "",
            issue.quantity,
            issue.shift or "Unknown (old record)",
            issue.user.full_name if issue.user else "",
        ])

    return make_csv_response(
        [
            "Reference No.", "Issue Date", "Plant", "Supervisor",
            "Bag Type", "Bag Size (kg)", "Quantity", "Shift",
            "Godown In-charge",
        ],
        rows,
        report_filename("Plant_Issue_Report", start_date, end_date),
    )


# --------------------------------------------------
# SUPPLIER INWARD CSV
# --------------------------------------------------

@reports_bp.route("/inward-export.csv", methods=["GET"])
@login_required
@permission_required("reports")
def inward_export_csv():
    start_date, end_date, _, _ = parse_report_filters()
    data = get_report_data(start_date, end_date)

    rows = []

    for bill, item, bag in data["inward_items"]:
        rows.append([
            bill.reference_no,
            bill.inward_date.isoformat() if bill.inward_date else "",
            bill.supplier_name,
            bill.bill_number,
            bill.vehicle_number,
            bag.name,
            bag.size_kg,
            item.quantity,
            "Yes" if bill.bill_photo else "No",
            bill.user.full_name if bill.user else "",
        ])

    return make_csv_response(
        [
            "Inward Reference", "Inward Date", "Supplier", "Bill Number",
            "Vehicle Number", "Bag Type", "Bag Size (kg)", "Quantity",
            "Bill Photo Available", "Entered By",
        ],
        rows,
        report_filename("Supplier_Inward_Report", start_date, end_date),
    )


# --------------------------------------------------
# CURRENT STOCK CSV
# --------------------------------------------------

@reports_bp.route("/stock-export.csv", methods=["GET"])
@login_required
@permission_required("reports")
def stock_export_csv():
    data = get_report_data(date.today(), date.today())

    rows = [
        [
            bag.name,
            bag.size_kg,
            bag.current_stock,
            "Active" if bag.is_active else "Inactive",
        ]
        for bag in data["stock_items"]
    ]

    return make_csv_response(
        ["Bag Type", "Bag Size (kg)", "Current Stock", "Status"],
        rows,
        "KKUL_Current_Stock_Report.csv",
    )


# --------------------------------------------------
# STOCK MOVEMENT HISTORY CSV
# --------------------------------------------------

@reports_bp.route("/movement-export.csv", methods=["GET"])
@login_required
@permission_required("reports")
def movement_export_csv():
    start_date, end_date, _, _ = parse_report_filters()
    data = get_report_data(start_date, end_date)

    rows = []

    for movement, bag, user in data["movement_items"]:
        rows.append([
            movement.created_at.isoformat() if movement.created_at else "",
            movement.movement_type,
            bag.name,
            bag.size_kg,
            movement.previous_qty,
            movement.new_qty,
            movement.change_qty,
            movement.reason,
            user.full_name if user else "",
        ])

    return make_csv_response(
        [
            "Timestamp", "Movement Type", "Bag Type", "Bag Size (kg)",
            "Previous Stock", "New Stock", "Change Quantity",
            "Reason", "User",
        ],
        rows,
        report_filename("Stock_Movement_History", start_date, end_date),
    )
