
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.extensions import db
from backend.models import Plant
from backend.permissions import roles_required

plants_bp = Blueprint("plants", __name__, url_prefix="/plants")


@plants_bp.route("/", methods=["GET", "POST"])
@login_required
@roles_required("admin","godown")
def index():
    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if not name:
            flash("Plant ka naam bharna zaroori hai.", "danger")
            return redirect(url_for("plants.index"))

        plant = Plant(name=name)
        db.session.add(plant)

        try:
            db.session.commit()
            flash("Plant successfully add ho gaya.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("Is naam ka plant pehle se maujood hai.", "danger")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Plant save nahi hua. Terminal error check karein.", "danger")

        return redirect(url_for("plants.index"))

    plants = Plant.query.order_by(Plant.name.asc()).all()
    return render_template("plants.html", plants=plants)


@plants_bp.route("/<int:plant_id>/toggle", methods=["POST"])
@login_required
@roles_required("admin","godown")
def toggle(plant_id):
    plant = db.get_or_404(Plant, plant_id)
    plant.is_active = not plant.is_active

    try:
        db.session.commit()
        status = "active" if plant.is_active else "inactive"
        flash(f"Plant ab {status} hai.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        flash("Plant status update nahi hua.", "danger")

    return redirect(url_for("plants.index"))
