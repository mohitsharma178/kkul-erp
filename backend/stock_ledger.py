from datetime import date, datetime, time, timedelta

from flask import Blueprint, render_template, request, abort
from flask_login import login_required
from sqlalchemy import func

from backend.extensions import db
from backend.models import (
    BagType,
    StockMovement,
    User,
    InwardBill,
    InwardItem,
    BagIssue,
    Plant,
    Supervisor,
)
from backend.permissions import permission_required


stock_ledger_bp = Blueprint(
    "stock_ledger",
    __name__,
    url_prefix="/stock-ledger",
)


def parse_date(value, default):
    """Parse a date safely."""
    try:
        return date.fromisoformat(value) if value else default
    except (TypeError, ValueError):
        return default


def get_date_range():
    """Read and validate the requested date range."""
    today = date.today()

    start_date = parse_date(
        request.args.get("start_date", ""),
        today.replace(day=1),
    )
    end_date = parse_date(
        request.args.get("end_date", ""),
        today,
    )

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    if (end_date - start_date).days > 3660:
        start_date = end_date - timedelta(days=3660)

    return start_date, end_date


def get_current_stock_total():
    total = (
        db.session.query(
            func.coalesce(func.sum(BagType.current_stock), 0)
        )
        .filter(BagType.is_active.is_(True))
        .scalar()
    )
    return int(total or 0)


@stock_ledger_bp.route("/", methods=["GET"])
@login_required
@permission_required("reports")
def index():
    """Main page: list all active bag brands and sizes."""
    bags = (
        BagType.query
        .filter_by(is_active=True)
        .order_by(BagType.name.asc(), BagType.size_kg.asc())
        .all()
    )

    current_stock_total = get_current_stock_total()

    return render_template(
        "stock_ledger.html",
        bags=bags,
        current_stock_total=current_stock_total,
    )


@stock_ledger_bp.route("/<int:bag_id>", methods=["GET"])
@login_required
@permission_required("reports")
def personal_ledger(bag_id):
    """Show the date-wise ledger for one bag type."""
    bag = (
        BagType.query
        .filter_by(id=bag_id, is_active=True)
        .first()
    )

    if not bag:
        abort(404)

    start_date, end_date = get_date_range()

    start_datetime = datetime.combine(start_date, time.min)
    end_datetime = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
    )

    # All stock movements for this bag, ordered by recorded time.
    movements = (
        StockMovement.query
        .filter_by(bag_type_id=bag.id)
        .order_by(
            StockMovement.created_at.asc(),
            StockMovement.id.asc(),
        )
        .all()
    )

    # Load inward records for this bag.
    inward_records = (
        db.session.query(InwardItem, InwardBill)
        .join(
            InwardBill,
            InwardItem.inward_bill_id == InwardBill.id,
        )
        .filter(InwardItem.bag_type_id == bag.id)
        .all()
    )

    inward_by_reference = {
        bill.reference_no: (item, bill)
        for item, bill in inward_records
    }

    # Load issue records for this bag.
    issue_records = (
        db.session.query(BagIssue, Plant, Supervisor, User)
        .join(Plant, BagIssue.plant_id == Plant.id)
        .join(
            Supervisor,
            BagIssue.supervisor_id == Supervisor.id,
        )
        .outerjoin(User, BagIssue.user_id == User.id)
        .filter(BagIssue.bag_type_id == bag.id)
        .all()
    )

    issue_by_reference = {
        issue.reference_no: (issue, plant, supervisor, user)
        for issue, plant, supervisor, user in issue_records
    }

    ledger_rows = []
    opening_balance = None
    closing_balance = None
    total_inward = 0
    total_issued = 0
    unmatched_records = 0

    # Map the movement rows to their detailed business records.
    # The reference is stored in StockMovement.reason.
    for movement in movements:
        reason = movement.reason or ""

        row_date = (
            movement.created_at.date()
            if movement.created_at
            else date.today()
        )

        row = {
            "date": row_date,
            "created_at": movement.created_at,
            "movement_type": movement.movement_type,
            "reference_no": "",
            "supplier_name": "",
            "bill_number": "",
            "vehicle_number": "",
            "bill_photo": None,
            "plant_name": "",
            "supervisor_name": "",
            "shift": "",
            "parchi_photo": None,
            "reason": reason,
            "previous_qty": int(movement.previous_qty),
            "inward_qty": 0,
            "issue_qty": 0,
            "change_qty": int(movement.change_qty or 0),
            "new_qty": int(movement.new_qty),
            "user_name": (
                movement.user.full_name
                if movement.user
                else "Unknown"
            ),
            "details_matched": False,
        }

        if movement.movement_type == "supplier_inward":
            # Current inward.py stores:
            # "Supplier inward <reference>; bill <bill_number>"
            reference = ""
            marker = "Supplier inward "

            if marker in reason:
                reference = reason.split(marker, 1)[1]
                reference = reference.split(";", 1)[0].strip()

            matched = inward_by_reference.get(reference)

            if matched:
                item, bill = matched

                row["date"] = bill.inward_date
                row["reference_no"] = bill.reference_no
                row["supplier_name"] = bill.supplier_name
                row["bill_number"] = bill.bill_number
                row["vehicle_number"] = bill.vehicle_number
                row["bill_photo"] = bill.bill_photo
                row["inward_qty"] = int(item.quantity)
                row["details_matched"] = True
            else:
                row["inward_qty"] = max(row["change_qty"], 0)
                unmatched_records += 1

        elif movement.movement_type == "plant_issue":
            # Current issues.py stores:
            # "Plant issue <reference_no>"
            reference = ""

            marker = "Plant issue "
            if marker in reason:
                reference = reason.split(marker, 1)[1].strip()

            matched = issue_by_reference.get(reference)

            if matched:
                issue, plant, supervisor, user = matched

                row["date"] = issue.issue_date
                row["reference_no"] = issue.reference_no
                row["plant_name"] = plant.name
                row["supervisor_name"] = supervisor.name
                row["shift"] = issue.shift or "Unknown"
                row["parchi_photo"] = issue.parchi_photo
                row["issue_qty"] = int(issue.quantity)
                row["user_name"] = (
                    user.full_name if user else "Unknown"
                )
                row["details_matched"] = True
            else:
                row["issue_qty"] = abs(min(row["change_qty"], 0))
                unmatched_records += 1

        else:
            # Other movement types are not expected in this ledger.
            continue

        # Include only rows whose business date falls in the period.
        if not (start_date <= row["date"] <= end_date):
            continue

        ledger_rows.append(row)

    # Sort using business date first, then timestamp and reference.
    ledger_rows.sort(
        key=lambda row: (
            row["date"],
            row["created_at"] or datetime.min,
            row["reference_no"],
        )
    )

    # Historical opening balance:
    # use the recorded new_qty from the latest movement before
    # the selected period, based on its business date where mapped.
    prior_rows = [
        row for row in movements
        if row.created_at and row.created_at < start_datetime
    ]

    # We cannot reliably reconstruct business-date opening balance
    # for every legacy record from created_at alone. Use the recorded
    # previous_qty of the first displayed movement as a safe fallback.
    if ledger_rows:
        first_row = ledger_rows[0]
        opening_balance = first_row["previous_qty"]
    else:
        latest_prior = (
            StockMovement.query
            .filter(
                StockMovement.bag_type_id == bag.id,
                StockMovement.created_at < start_datetime,
            )
            .order_by(
                StockMovement.created_at.desc(),
                StockMovement.id.desc(),
            )
            .first()
        )

        if latest_prior:
            opening_balance = int(latest_prior.new_qty)
        else:
            opening_balance = 0

    running_balance = opening_balance

    for row in ledger_rows:
        row["running_balance"] = running_balance + (
            row["inward_qty"] - row["issue_qty"]
        )

        running_balance = row["running_balance"]

        total_inward += row["inward_qty"]
        total_issued += row["issue_qty"]

    closing_balance = running_balance

    return render_template(
        "stock_ledger_personal.html",
        bag=bag,
        start_date=start_date,
        end_date=end_date,
        ledger_rows=ledger_rows,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        total_inward=total_inward,
        total_issued=total_issued,
        current_stock=int(bag.current_stock),
        unmatched_records=unmatched_records,
    )