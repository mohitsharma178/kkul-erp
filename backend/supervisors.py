
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.extensions import db
from backend.models import Plant, Supervisor
from backend.permissions import roles_required

supervisors_bp = Blueprint(
    "supervisors",
    __name__,
    url_prefix="/supervisors"
)


@supervisors_bp.route("/", methods=["GET", "POST"])
@login_required
@roles_required("admin","godown")
def index():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        employee_code = request.form.get("employee_code", "").strip() or None
        phone = request.form.get("phone", "").strip() or None
        plant_id_text = request.form.get("plant_id", "").strip()

        if not name or not plant_id_text:
            flash("Supervisor ka naam aur plant select karna zaroori hai.", "danger")
            return redirect(url_for("supervisors.index"))

        try:
            plant_id = int(plant_id_text)
        except ValueError:
            flash("Invalid plant select kiya gaya hai.", "danger")
            return redirect(url_for("supervisors.index"))

        plant = db.session.get(Plant, plant_id)

        if plant is None or not plant.is_active:
            flash("Active plant select karein.", "danger")
            return redirect(url_for("supervisors.index"))

        supervisor = Supervisor(
            name=name,
            employee_code=employee_code,
            phone=phone,
            plant_id=plant.id
        )
        db.session.add(supervisor)

        try:
            db.session.commit()
            flash("Supervisor successfully add ho gaya.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("Ye employee code pehle se use ho raha hai.", "danger")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Supervisor save nahi hua. Terminal error check karein.", "danger")

        return redirect(url_for("supervisors.index"))

    plants = (
        Plant.query
        .filter_by(is_active=True)
        .order_by(Plant.name.asc())
        .all()
    )
    supervisors = (
        Supervisor.query
        .order_by(Supervisor.name.asc())
        .all()
    )

    return render_template(
        "supervisors.html",
        plants=plants,
        supervisors=supervisors
    )


@supervisors_bp.route("/<int:supervisor_id>/toggle", methods=["POST"])
@login_required
@roles_required("admin","godown")
def toggle(supervisor_id):
    supervisor = db.get_or_404(Supervisor, supervisor_id)
    supervisor.is_active = not supervisor.is_active

    try:
        db.session.commit()
        status = "active" if supervisor.is_active else "inactive"
        flash(f"Supervisor ab {status} hai.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        flash("Supervisor status update nahi hua.", "danger")

    return redirect(url_for("supervisors.index"))
