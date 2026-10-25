
import os
import uuid
from pathlib import Path
from datetime import date

from werkzeug.utils import secure_filename
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    abort,
)
from flask_login import login_required, current_user
from sqlalchemy.exc import SQLAlchemyError

from backend.extensions import db
from backend.permissions import roles_required
from backend.models import BagType, StockMovement, InwardBill, InwardItem


inward_bp = Blueprint("inward", __name__, url_prefix="/inward")

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}
MAX_QUANTITY = 2_147_483_647


def allowed_file(filename):
    return (
        bool(filename)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def remove_uploaded_file(path):
    """Best-effort cleanup if the database transaction fails."""
    try:
        if path is not None and path.is_file():
            path.unlink()
    except OSError:
        current_app.logger.exception(
            "Failed to clean up uploaded inward file"
        )


@inward_bp.route("/", methods=["GET", "POST"])
@login_required
@roles_required("admin", "godown")
def index():
    bags = (
        BagType.query
        .filter_by(is_active=True)
        .order_by(BagType.name, BagType.size_kg)
        .all()
    )

    if request.method == "POST":
        supplier_name = request.form.get("supplier_name", "").strip()
        bill_number = request.form.get("bill_number", "").strip()
        vehicle_number = request.form.get("vehicle_number", "").strip()
        inward_date_text = request.form.get("inward_date", "").strip()
        photo = request.files.get("bill_photo")

        if not all((
            supplier_name,
            bill_number,
            vehicle_number,
            inward_date_text,
        )):
            flash(
                "Supplier, bill number, vehicle aur date zaroori hain.",
                "danger",
            )
            return redirect(url_for("inward.index"))

        if (
            len(supplier_name) > 150
            or len(bill_number) > 100
            or len(vehicle_number) > 30
        ):
            flash(
                "Supplier, bill number ya vehicle number ki length limit se zyada hai.",
                "danger",
            )
            return redirect(url_for("inward.index"))

        try:
            inward_date = date.fromisoformat(inward_date_text)
        except ValueError:
            flash("Valid inward date select karein.", "danger")
            return redirect(url_for("inward.index"))

        if not photo or not photo.filename:
            flash(
                "Bill ki photo ya PDF upload karna mandatory hai.",
                "danger",
            )
            return redirect(url_for("inward.index"))

        if not allowed_file(photo.filename):
            flash(
                "Sirf JPG, JPEG, PNG, WEBP ya PDF file upload karein.",
                "danger",
            )
            return redirect(url_for("inward.index"))

        safe_original_name = secure_filename(photo.filename)

        if (
            not safe_original_name
            or "." not in safe_original_name
            or not allowed_file(safe_original_name)
        ):
            flash("Valid file name aur extension wali file upload karein.", "danger")
            return redirect(url_for("inward.index"))

        extension = safe_original_name.rsplit(".", 1)[1].lower()

        bag_ids = request.form.getlist("bag_id")
        quantities = request.form.getlist("quantity")

        if not bag_ids or len(bag_ids) != len(quantities):
            flash("Kam se kam ek bag item add karein.", "danger")
            return redirect(url_for("inward.index"))

        parsed_items = []
        seen_bag_ids = set()

        try:
            for raw_id, raw_qty in zip(bag_ids, quantities):
                raw_id = raw_id.strip()
                raw_qty = raw_qty.strip()

                # Blank dynamic form rows are ignored.
                if not raw_id and not raw_qty:
                    continue

                if not raw_id or not raw_qty:
                    raise ValueError(
                        "Har selected bag ke liye bag type aur quantity dono dein."
                    )

                if not raw_id.isascii() or not raw_id.isdecimal():
                    raise ValueError("Invalid bag type select kiya gaya hai.")

                if not raw_qty.isascii() or not raw_qty.isdecimal():
                    raise ValueError(
                        "Quantity zero ya usse zyada poori sankhya honi chahiye."
                    )

                bag_id = int(raw_id)
                qty = int(raw_qty)

                if bag_id <= 0:
                    raise ValueError("Invalid bag type select kiya gaya hai.")

                if qty > MAX_QUANTITY:
                    raise ValueError("Quantity allowed limit se zyada hai.")

                # Preserve the existing behaviour: zero rows are skipped.
                if qty == 0:
                    continue

                if bag_id in seen_bag_ids:
                    raise ValueError(
                        "Ek bag type ko sirf ek baar add karein."
                    )

                seen_bag_ids.add(bag_id)
                parsed_items.append((bag_id, qty))

        except (ValueError, TypeError) as error:
            flash(
                str(error) or "Valid bag quantity enter karein.",
                "danger",
            )
            return redirect(url_for("inward.index"))

        if not parsed_items:
            flash(
                "Kam se kam ek bag ki quantity zero se zyada honi chahiye.",
                "danger",
            )
            return redirect(url_for("inward.index"))

        selected_ids = sorted(bag_id for bag_id, _ in parsed_items)

        upload_dir = (
            Path(current_app.root_path).parent
            / "uploads"
            / "inward"
        )

        try:
            upload_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            current_app.logger.exception("Unable to create inward upload directory")
            flash("Upload folder ready nahi hai. Administrator se contact karein.", "danger")
            return redirect(url_for("inward.index"))

        stored_name = f"{uuid.uuid4().hex}.{extension}"
        photo_path = upload_dir / stored_name

        reference_no = (
            f"KKUL/INW/{date.today().strftime('%Y%m%d')}/"
            f"{uuid.uuid4().hex[:8].upper()}"
        )

        try:
            # Lock selected bag rows in a consistent order.
            # This helps coordinate concurrent stock changes on transactional DBs.
            selected_bags = (
                BagType.query
                .filter(BagType.id.in_(selected_ids))
                .order_by(BagType.id)
                .with_for_update()
                .all()
            )

            bags_by_id = {bag.id: bag for bag in selected_bags}

            if len(bags_by_id) != len(selected_ids):
                db.session.rollback()
                flash(
                    "Selected bag type nahi mila. Inward save nahi hua.",
                    "danger",
                )
                return redirect(url_for("inward.index"))

            if any(not bag.is_active for bag in selected_bags):
                db.session.rollback()
                flash(
                    "Selected bag type inactive hai. Inward save nahi hua.",
                    "danger",
                )
                return redirect(url_for("inward.index"))

            # Check stock arithmetic before writing records.
            quantities_by_id = dict(parsed_items)

            for bag_id, qty in parsed_items:
                if bags_by_id[bag_id].current_stock + qty > MAX_QUANTITY:
                    raise ValueError(
                        "Inward ke baad stock database ki supported limit se zyada ho jayega."
                    )

            # Save the file; remove it if the database transaction fails.
            photo.save(str(photo_path))

            bill = InwardBill(
                reference_no=reference_no,
                supplier_name=supplier_name,
                bill_number=bill_number,
                vehicle_number=vehicle_number,
                inward_date=inward_date,
                bill_photo=f"inward/{stored_name}",
                user_id=current_user.id,
            )

            db.session.add(bill)
            db.session.flush()

            for bag_id, qty in parsed_items:
                bag = bags_by_id[bag_id]
                old_qty = bag.current_stock
                new_qty = old_qty + qty

                db.session.add(
                    InwardItem(
                        inward_bill_id=bill.id,
                        bag_type_id=bag.id,
                        quantity=qty,
                    )
                )

                db.session.add(
                    StockMovement(
                        bag_type_id=bag.id,
                        movement_type="supplier_inward",
                        previous_qty=old_qty,
                        new_qty=new_qty,
                        change_qty=qty,
                        reason=(
                            f"Supplier inward {reference_no}; "
                            f"bill {bill_number}"
                        ),
                        user_id=current_user.id,
                    )
                )

                bag.current_stock = new_qty

            db.session.commit()

        except ValueError as error:
            db.session.rollback()
            remove_uploaded_file(photo_path)
            flash(str(error), "danger")
            return redirect(url_for("inward.index"))

        except (SQLAlchemyError, OSError):
            db.session.rollback()
            remove_uploaded_file(photo_path)
            current_app.logger.exception("Supplier inward failed")
            flash(
                "Inward save nahi hua. Error log check karein.",
                "danger",
            )
            return redirect(url_for("inward.index"))

        flash(
            f"Inward save ho gaya. Reference: {reference_no}",
            "success",
        )
        return redirect(url_for("inward.index"))

    recent_bills = (
        InwardBill.query
        .order_by(InwardBill.created_at.desc())
        .limit(20)
        .all()
    )

    return render_template(
        "inward.html",
        bags=bags,
        recent_bills=recent_bills,
    )
