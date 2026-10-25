
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.exc import SQLAlchemyError

from backend.extensions import db
from backend.models import Plant, BagType, DailyIssueLimit
from backend.permissions import roles_required

daily_limits_bp = Blueprint(
    "daily_limits",
    __name__,
    url_prefix="/daily-limits"
)


@daily_limits_bp.route("/", methods=["GET", "POST"])
@login_required
@roles_required("admin","godown")
def index():
    if request.method == "POST":
        plant_id = request.form.get("plant_id", type=int)
        bag_type_id = request.form.get("bag_type_id", type=int)
        daily_limit = request.form.get("daily_limit", type=int)

        if not plant_id or not bag_type_id:
            flash("Plant aur bag type select karein.", "danger")
            return redirect(url_for("daily_limits.index"))

        if daily_limit is None or daily_limit <= 0:
            flash("Daily limit 1 ya usse zyada honi chahiye.", "danger")
            return redirect(url_for("daily_limits.index"))

        plant = db.session.get(Plant, plant_id)
        bag = db.session.get(BagType, bag_type_id)

        if not plant or not bag:
            flash("Selected plant ya bag type nahi mila.", "danger")
            return redirect(url_for("daily_limits.index"))

        try:
            limit_record = DailyIssueLimit.query.filter_by(
                plant_id=plant_id,
                bag_type_id=bag_type_id
            ).first()

            if limit_record:
                limit_record.daily_limit = daily_limit
                message = "Daily limit successfully update ho gayi."
            else:
                limit_record = DailyIssueLimit(
                    plant_id=plant_id,
                    bag_type_id=bag_type_id,
                    daily_limit=daily_limit
                )
                db.session.add(limit_record)
                message = "Daily limit successfully save ho gayi."

            db.session.commit()
            flash(message, "success")

        except SQLAlchemyError:
            db.session.rollback()
            flash("Limit save nahi hui. Error ke liye terminal check karein.", "danger")

        return redirect(url_for("daily_limits.index"))

    plants = Plant.query.order_by(Plant.name.asc()).all()
    bags = BagType.query.order_by(BagType.name.asc()).all()

    limits = DailyIssueLimit.query.order_by(
        DailyIssueLimit.plant_id.asc(),
        DailyIssueLimit.bag_type_id.asc()
    ).all()

    return render_template(
        "daily_limits.html",
        plants=plants,
        bags=bags,
        limits=limits
    )
