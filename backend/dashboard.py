
from datetime import date, timedelta

from flask import Blueprint, redirect, url_for, render_template
from flask_login import login_required, current_user
from sqlalchemy import func

from backend.extensions import db
from backend.models import (
    BagType,
    InwardBill,
    InwardItem,
    BagIssue,
    StockMovement,
)
from backend.permissions import has_permission


dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    url_prefix="/dashboard",
)

# Dashboard low-stock threshold.
# Har active bag type ke liye 2,000 bags se kam = Low Stock.
LOW_STOCK_THRESHOLD = 2000


@dashboard_bp.route("/")
@login_required
def index():
    # Dashboard permission check
    if not has_permission("dashboard"):
        if has_permission("reports"):
            return redirect(url_for("reports.index"))

        return "Aapko is page ka access nahi hai.", 403

    today = date.today()
    # --------------------------------------------------
    # 1A. Last 7 days analytics for dashboard charts
    # --------------------------------------------------

    chart_dates = [
        today - timedelta(days=offset)
        for offset in range(6, -1, -1)
    ]

    chart_labels = [
        day.strftime("%d %b")
        for day in chart_dates
    ]

    inward_by_day = {day: 0 for day in chart_dates}
    issues_by_day = {day: 0 for day in chart_dates}

    start_date = chart_dates[0]

    # Daily inward totals: actual database records only.
    if has_permission("inward"):
        inward_rows = (
            db.session.query(
                InwardBill.inward_date,
                func.coalesce(func.sum(InwardItem.quantity), 0),
            )
            .join(
                InwardItem,
                InwardItem.inward_bill_id == InwardBill.id,
            )
            .filter(
                InwardBill.inward_date >= start_date,
                InwardBill.inward_date <= today,
            )
            .group_by(InwardBill.inward_date)
            .all()
        )

        for day, quantity in inward_rows:
            inward_by_day[day] = int(quantity or 0)

    # Daily issue totals: actual database records only.
    if has_permission("issues"):
        issue_rows = (
            db.session.query(
                BagIssue.issue_date,
                func.coalesce(func.sum(BagIssue.quantity), 0),
            )
            .filter(
                BagIssue.issue_date >= start_date,
                BagIssue.issue_date <= today,
            )
            .group_by(BagIssue.issue_date)
            .all()
        )

        for day, quantity in issue_rows:
            issues_by_day[day] = int(quantity or 0)

    chart_inward_data = [
        inward_by_day[day] for day in chart_dates
    ]

    chart_issues_data = [
        issues_by_day[day] for day in chart_dates
    ]

    # --------------------------------------------------
    # 1. Dashboard summary metrics
    # --------------------------------------------------

    total_stock = (
        db.session.query(
            func.coalesce(func.sum(BagType.current_stock), 0)
        )
        .filter(BagType.is_active.is_(True))
        .scalar()
    )

    total_bag_types = (
        BagType.query
        .filter_by(is_active=True)
        .count()
    )

    today_inward = (
        db.session.query(
            func.coalesce(func.sum(InwardItem.quantity), 0)
        )
        .join(
            InwardBill,
            InwardItem.inward_bill_id == InwardBill.id,
        )
        .filter(InwardBill.inward_date == today)
        .scalar()
    )

    today_issues = (
        db.session.query(
            func.coalesce(func.sum(BagIssue.quantity), 0)
        )
        .filter(BagIssue.issue_date == today)
        .scalar()
    )

    # --------------------------------------------------
    # 2. Stock alerts - inventory permission required
    # --------------------------------------------------

    stock_alerts = []
    out_of_stock_count = 0
    low_stock_count = 0

    if has_permission("inventory"):
        active_bags = (
            BagType.query
            .filter(BagType.is_active.is_(True))
            .order_by(BagType.current_stock.asc(), BagType.name.asc())
            .all()
        )

        for bag in active_bags:
            stock = int(bag.current_stock or 0)

            if stock <= 0:
                out_of_stock_count += 1
                stock_alerts.append({
                    "bag_name": bag.name,
                    "size_kg": bag.size_kg,
                    "current_stock": stock,
                    "status": "out",
                    "status_label": "Out of Stock",
                })

            elif stock < LOW_STOCK_THRESHOLD:
                low_stock_count += 1
                stock_alerts.append({
                    "bag_name": bag.name,
                    "size_kg": bag.size_kg,
                    "current_stock": stock,
                    "status": "low",
                    "status_label": "Low Stock",
                })

        # Out of stock first, then lowest quantity.
        stock_alerts.sort(
            key=lambda item: (
                0 if item["status"] == "out" else 1,
                item["current_stock"],
                item["bag_name"],
            )
        )

    # --------------------------------------------------
    # 3. Recent transactions
    #    Only show modules the user can access.
    # --------------------------------------------------

    recent_transactions = []

    if has_permission("inward"):
        bills = (
            InwardBill.query
            .order_by(
                InwardBill.created_at.desc(),
                InwardBill.id.desc(),
            )
            .limit(8)
            .all()
        )

        for bill in bills:
            quantity = sum(
                int(item.quantity or 0)
                for item in bill.items
            )

            recent_transactions.append({
                "transaction_type": "Inward",
                "reference_no": bill.reference_no,
                "description": bill.supplier_name,
                "date": bill.inward_date,
                "quantity": quantity,
                "created_at": bill.created_at,
            })

    if has_permission("issues"):
        issues = (
            BagIssue.query
            .order_by(
                BagIssue.created_at.desc(),
                BagIssue.id.desc(),
            )
            .limit(8)
            .all()
        )

        for issue in issues:
            recent_transactions.append({
                "transaction_type": "Issue",
                "reference_no": issue.reference_no,
                "description": (
                    issue.plant.name if issue.plant else "Plant"
                ),
                "date": issue.issue_date,
                "quantity": int(issue.quantity or 0),
                "shift": issue.shift or "Not recorded",
                "created_at": issue.created_at,
            })

    if has_permission("inventory"):
        movements = (
            StockMovement.query
            .order_by(
                StockMovement.created_at.desc(),
                StockMovement.id.desc(),
            )
            .limit(8)
            .all()
        )

        for movement in movements:
            bag_name = (
                movement.bag_type.name
                if movement.bag_type
                else "Bag type"
            )

            recent_transactions.append({
                "transaction_type": "Stock Movement",
                "reference_no": f"Movement #{movement.id}",
                "description": f"{bag_name} — {movement.reason}",
                "date": movement.created_at.date(),
                "quantity": int(movement.change_qty or 0),
                "created_at": movement.created_at,
            })

    # Merge records from available modules and show newest first.
    # Use ISO strings to avoid naive/aware datetime comparison errors.
    recent_transactions.sort(
        key=lambda item: (
            item["created_at"].isoformat()
            if item["created_at"]
            else ""
        ),
        reverse=True,
    )

    recent_transactions = recent_transactions[:10]

    return render_template(
        "dashboard.html",
        user=current_user,
        total_stock=int(total_stock or 0),
        total_bag_types=total_bag_types,
        today_inward=int(today_inward or 0),
        today_issues=int(today_issues or 0),
        today=today,
                chart_labels=chart_labels,
        chart_inward_data=chart_inward_data,
        chart_issues_data=chart_issues_data,
        low_stock_threshold=LOW_STOCK_THRESHOLD,
        stock_alerts=stock_alerts,
        out_of_stock_count=out_of_stock_count,
        low_stock_count=low_stock_count,
        recent_transactions=recent_transactions,
        can_view_inventory=has_permission("inventory"),
        can_view_inward=has_permission("inward"),
        can_view_issues=has_permission("issues"),
        can_view_reports=has_permission("reports"),
        can_manage_plants=has_permission("plants"),
        can_manage_supervisors=has_permission("supervisors"),
        can_manage_limits=has_permission("daily_limits"),
        can_manage_users=has_permission("users"),
    )
