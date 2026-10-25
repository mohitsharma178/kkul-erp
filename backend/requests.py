from datetime import date
from uuid import uuid4

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy.exc import SQLAlchemyError

from backend.extensions import db
from backend.models import BagRequest, Plant, Supervisor, BagType
from backend.permissions import roles_required


requests_bp = Blueprint(
    "bag_requests",
    __name__,
    url_prefix="/requests"
)


@requests_bp.route("/", methods=["GET", "POST"])
@login_required
@roles_required("admin", "godown")
def index():
    plants = Plant.query.filter_by(is_active=True).order_by(Plant.name).all()
    supervisors = (
        Supervisor.query
        .filter_by(is_active=True)
        .order_by(Supervisor.name)
        .all()
    )
    bag_types = (
        BagType.query
        .filter_by(is_active=True)
        .order_by(BagType.name, BagType.size_kg)
        .all()
    )

    if request.method == "POST":
        try:
            plant_id = int(request.form.get("plant_id", ""))
            supervisor_id = int(request.form.get("supervisor_id", ""))
            bag_type_id = int(request.form.get("bag_type_id", ""))
            quantity = int(request.form.get("requested_quantity", ""))
            request_date = date.fromisoformat(
                request.form.get("request_date", "")
            )
            remarks = request.form.get("remarks", "").strip() or None

            if quantity <= 0:
                raise ValueError("Quantity 0 se zyada honi chahiye.")

            plant = db.session.get(Plant, plant_id)
            supervisor = db.session.get(Supervisor, supervisor_id)
            bag_type = db.session.get(BagType, bag_type_id)

            if not plant or not plant.is_active:
                raise ValueError("Valid active plant select karein.")

            if (
                not supervisor
                or not supervisor.is_active
                or supervisor.plant_id != plant.id
            ):
                raise ValueError(
                    "Selected supervisor is plant se belong nahi karta."
                )

            if not bag_type or not bag_type.is_active:
                raise ValueError("Valid active bag brand select karein.")

            bag_request = BagRequest(
                reference_no=(
                    f"KKUL/REQ/{date.today():%Y%m%d}/"
                    f"{uuid4().hex[:10].upper()}"
                ),
                plant_id=plant.id,
                supervisor_id=supervisor.id,
                bag_type_id=bag_type.id,
                requested_quantity=quantity,
                request_date=request_date,
                status="Pending",
                remarks=remarks,
                user_id=current_user.id,
            )

            db.session.add(bag_request)
            db.session.commit()

            flash(
                f"Bag request saved successfully. Reference: "
                f"{bag_request.reference_no}",
                "success",
            )
            return redirect(url_for("bag_requests.index"))

        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(f"Request save nahi hui: {error}", "danger")

        except SQLAlchemyError:
            db.session.rollback()
            flash(
                "Database error: request save nahi hui. "
                "Terminal mein error check karein.",
                "danger",
            )

    recent_requests = (
        BagRequest.query
        .order_by(BagRequest.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template(
    "bag_requests.html",
    plants=plants,
    supervisors=supervisors,
    bag_types=bag_types,
    recent_requests=recent_requests,
    today_date=date.today().isoformat(),
)
   