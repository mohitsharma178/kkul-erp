
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
)
from flask_login import login_required, current_user
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from backend.extensions import db
from backend.models import BagType, StockMovement
from backend.permissions import roles_required


inventory_bp = Blueprint(
    "inventory",
    __name__,
    url_prefix="/inventory"
)


@inventory_bp.route("/", methods=["GET"])
@login_required
@roles_required("admin", "godown")
def index():
    bags = (
        BagType.query
        .filter_by(is_active=True)
        .order_by(BagType.name, BagType.size_kg)
        .all()
    )

    movements = (
        StockMovement.query
        .order_by(StockMovement.created_at.desc())
        .limit(20)
        .all()
    )

    return render_template(
        "inventory.html",
        bags=bags,
        movements=movements
    )


@inventory_bp.route("/add", methods=["POST"])
@login_required
@roles_required("admin", "godown")
def add_bag():
    name = request.form.get("name", "").strip()
    size_text = request.form.get("size_kg", "").strip()

    if not name or not size_text:
        flash("Bag ka naam aur weight zaroori hai.", "danger")
        return redirect(url_for("inventory.index"))

    if len(name) > 150:
        flash("Bag ka naam maximum 150 characters ka ho sakta hai.", "danger")
        return redirect(url_for("inventory.index"))

    try:
        size_kg = Decimal(size_text)

        if (
            not size_kg.is_finite()
            or size_kg <= 0
            or size_kg > Decimal("9999.99")
            or size_kg.as_tuple().exponent < -2
        ):
            raise InvalidOperation

    except (InvalidOperation, ValueError):
        flash("Valid bag weight enter karein (maximum 2 decimal places).", "danger")
        return redirect(url_for("inventory.index"))

    try:
        existing = BagType.query.filter_by(
            name=name,
            size_kg=size_kg
        ).first()

        if existing:
            flash(
                "Ye bag name aur weight pehle se maujood hai.",
                "warning"
            )
            return redirect(url_for("inventory.index"))

        bag = BagType(
            name=name,
            size_kg=size_kg,
            current_stock=0
        )

        db.session.add(bag)
        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        flash(
            "Ye bag type pehle se maujood hai ya database constraint fail hua.",
            "warning"
        )
        return redirect(url_for("inventory.index"))

    except SQLAlchemyError:
        db.session.rollback()
        flash(
            "Bag type save nahi ho saka. Database error hua.",
            "danger"
        )
        return redirect(url_for("inventory.index"))

    flash("Bag type successfully add ho gaya.", "success")
    return redirect(url_for("inventory.index"))


@inventory_bp.route("/<int:bag_id>/stock", methods=["POST"])
@login_required
@roles_required("admin", "godown")
def set_stock(bag_id):
    reason = request.form.get("reason", "").strip()
    quantity_text = request.form.get("quantity", "").strip()

    if not quantity_text:
        flash("Stock quantity zaroori hai.", "danger")
        return redirect(url_for("inventory.index"))

    # Integer quantity only; negative values and decimals are rejected.
    try:
        if not quantity_text.isascii() or not quantity_text.isdecimal():
            raise ValueError

        new_qty = int(quantity_text)

        if new_qty < 0:
            raise ValueError

    except (ValueError, TypeError):
        flash(
            "Stock quantity zero ya usse zyada poori sankhya honi chahiye.",
            "danger"
        )
        return redirect(url_for("inventory.index"))

    if not reason:
        flash("Stock change ka reason dena zaroori hai.", "danger")
        return redirect(url_for("inventory.index"))

    if len(reason) > 255:
        flash(
            "Stock change ka reason maximum 255 characters ka ho sakta hai.",
            "danger"
        )
        return redirect(url_for("inventory.index"))

    try:
        # Lock this bag row until the transaction completes.
        bag = (
            BagType.query
            .filter_by(id=bag_id)
            .with_for_update()
            .first()
        )

        if bag is None:
            db.session.rollback()
            abort(404)

        if not bag.is_active:
            db.session.rollback()
            flash("Inactive bag type ka stock update nahi kar sakte.", "warning")
            return redirect(url_for("inventory.index"))

        previous_qty = bag.current_stock

        if new_qty == previous_qty:
            db.session.rollback()
            flash("Quantity mein koi change nahi hua.", "info")
            return redirect(url_for("inventory.index"))

        movement = StockMovement(
            bag_type_id=bag.id,
            movement_type="stock_adjustment",
            previous_qty=previous_qty,
            new_qty=new_qty,
            change_qty=new_qty - previous_qty,
            reason=reason,
            user_id=current_user.id
        )

        bag.current_stock = new_qty
        db.session.add(movement)

        # Stock and history are committed together.
        db.session.commit()

    except SQLAlchemyError:
        db.session.rollback()
        flash(
            "Stock update save nahi ho saka. Koi change commit nahi hua; dobara check karein.",
            "danger"
        )
        return redirect(url_for("inventory.index"))

    flash("Stock update ho gaya aur history save ho gayi.", "success")
    return redirect(url_for("inventory.index"))
