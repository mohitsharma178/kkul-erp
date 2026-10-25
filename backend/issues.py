
import uuid
from datetime import date
from pathlib import Path

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
)
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename

from backend.extensions import db
from backend.models import (
    Plant,
    Supervisor,
    BagType,
    BagIssue,
    DailyIssueLimit,
    StockMovement,
    BagRequest,
)
from backend.permissions import roles_required


issues_bp = Blueprint("issues", __name__, url_prefix="/issues")

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_SHIFTS = {"Shift 1", "Shift 2"}


def allowed_file(filename):
    return (
        bool(filename)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def positive_int(value):
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def make_issue_reference():
    return (
        f"KKUL/ISS/{date.today():%Y%m%d}/"
        f"{uuid.uuid4().hex[:10].upper()}"
    )


def today_issued_quantity(plant_id, bag_type_id):
    result = (
        db.session.query(func.coalesce(func.sum(BagIssue.quantity), 0))
        .filter(
            BagIssue.plant_id == plant_id,
            BagIssue.bag_type_id == bag_type_id,
            BagIssue.issue_date == date.today(),
        )
        .scalar()
    )
    return result or 0


@issues_bp.route("/", methods=["GET", "POST"])
@login_required
@roles_required(
    "admin",
    "godown",
    "godown_incharge",
    "godown_supervisor",
)
def index():

    # =====================================================
    # POST: ISSUE BAGS
    # =====================================================
    if request.method == "POST":

        # Debug information: check what the browser sends.
        mode = (request.form.get("issue_mode") or "").strip()
        shift = (request.form.get("shift") or "").strip()

        current_app.logger.warning(
            "DEBUG ISSUE MODE: %r", mode
        )
        current_app.logger.warning(
            "DEBUG FORM DATA: %s", dict(request.form)
        )

        # Accept only the two supported form modes.
        if mode not in {"manual", "request"}:
            flash(
                "Issue mode receive nahi hua. "
                "issues.html mein dono forms ka issue_mode check karein.",
                "danger",
            )
            return redirect(url_for("issues.index"))

        if shift not in ALLOWED_SHIFTS:
            flash(
                "Kripya Shift 1 ya Shift 2 select karein.",
                "danger",
            )
            return redirect(url_for("issues.index"))

        # Parchi photo is optional.
        photo = request.files.get("parchi_photo")
        original_filename = None

        if photo and photo.filename:
            if not allowed_file(photo.filename):
                flash(
                    "Photo JPG, JPEG, PNG ya WEBP format mein honi chahiye.",
                    "danger",
                )
                return redirect(url_for("issues.index"))

            original_filename = secure_filename(photo.filename)

            if not original_filename:
                flash("Photo filename valid nahi hai.", "danger")
                return redirect(url_for("issues.index"))

        saved_photo_path = None

        try:
            bag_request = None

            # -------------------------------------------------
            # MODE 1: PENDING REQUEST
            # -------------------------------------------------
            if mode == "request":

                request_id = positive_int(
                    request.form.get("request_id")
                )

                if not request_id:
                    flash(
                        "Pending Supervisor Request select karein.",
                        "danger",
                    )
                    return redirect(url_for("issues.index"))

                bag_request = (
                    BagRequest.query
                    .filter_by(id=request_id)
                    .with_for_update()
                    .first()
                )

                if not bag_request:
                    flash("Selected request nahi mili.", "danger")
                    return redirect(url_for("issues.index"))

                if bag_request.status != "Pending":
                    flash(
                        "Yeh request pehle hi process ho chuki hai.",
                        "warning",
                    )
                    return redirect(url_for("issues.index"))

                plant_id = bag_request.plant_id
                supervisor_id = bag_request.supervisor_id
                bag_type_id = bag_request.bag_type_id
                quantity = positive_int(
                    bag_request.requested_quantity
                )

                if not quantity:
                    flash(
                        "Request ki quantity invalid hai.",
                        "danger",
                    )
                    return redirect(url_for("issues.index"))

            # -------------------------------------------------
            # MODE 2: MANUAL ISSUE
            # -------------------------------------------------
            else:
                plant_id = positive_int(
                    request.form.get("plant_id")
                )
                supervisor_id = positive_int(
                    request.form.get("supervisor_id")
                )
                bag_type_id = positive_int(
                    request.form.get("bag_type_id")
                )
                quantity = positive_int(
                    request.form.get("quantity")
                )

                if not all(
                    [plant_id, supervisor_id, bag_type_id, quantity]
                ):
                    flash(
                        "Manual Issue ke liye Plant, Supervisor, "
                        "Bag Type aur valid Quantity select karein.",
                        "danger",
                    )
                    return redirect(url_for("issues.index"))

            # -------------------------------------------------
            # Validate plant
            # -------------------------------------------------
            plant = (
                Plant.query
                .filter_by(id=plant_id, is_active=True)
                .first()
            )

            if not plant:
                flash(
                    "Selected plant inactive hai ya available nahi hai.",
                    "danger",
                )
                return redirect(url_for("issues.index"))

            # -------------------------------------------------
            # Validate supervisor belongs to selected plant
            # -------------------------------------------------
            supervisor = (
                Supervisor.query
                .filter_by(
                    id=supervisor_id,
                    plant_id=plant_id,
                    is_active=True,
                )
                .first()
            )

            if not supervisor:
                flash(
                    "Selected supervisor selected plant se linked "
                    "nahi hai ya inactive hai.",
                    "danger",
                )
                return redirect(url_for("issues.index"))

            # -------------------------------------------------
            # Lock and validate bag type
            # -------------------------------------------------
            bag_type = (
                BagType.query
                .filter_by(id=bag_type_id, is_active=True)
                .with_for_update()
                .first()
            )

            if not bag_type:
                flash(
                    "Selected bag type inactive hai ya available nahi hai.",
                    "danger",
                )
                return redirect(url_for("issues.index"))

            # -------------------------------------------------
            # Check daily limit
            # -------------------------------------------------
            limit_record = (
                DailyIssueLimit.query
                .filter_by(
                    plant_id=plant_id,
                    bag_type_id=bag_type_id,
                )
                .first()
            )

            if limit_record:
                already_issued = today_issued_quantity(
                    plant_id,
                    bag_type_id,
                )

                remaining = limit_record.daily_limit - already_issued

                if quantity > remaining:
                    flash(
                        f"Daily limit exceed! Limit: "
                        f"{limit_record.daily_limit}, aaj pehle issue: "
                        f"{already_issued}, abhi quantity: {quantity}, "
                        f"remaining limit: {max(remaining, 0)}.",
                        "danger",
                    )
                    return redirect(url_for("issues.index"))

            # -------------------------------------------------
            # Check stock: no partial issue
            # -------------------------------------------------
            previous_qty = bag_type.current_stock

            if previous_qty < quantity:
                flash(
                    f"Stock insufficient! Available: {previous_qty}, "
                    f"Required: {quantity}. Issue save nahi hua.",
                    "danger",
                )
                return redirect(url_for("issues.index"))

            new_qty = previous_qty - quantity

            # -------------------------------------------------
            # Save optional photo
            # -------------------------------------------------
            relative_photo_path = None

            if original_filename:
                upload_folder = (
                    Path(current_app.root_path).parent
                    / "uploads"
                    / "issues"
                )
                upload_folder.mkdir(parents=True, exist_ok=True)

                unique_filename = (
                    f"{uuid.uuid4().hex}_{original_filename}"
                )
                saved_photo_path = upload_folder / unique_filename

                photo.save(str(saved_photo_path))

                relative_photo_path = (
                    f"issues/{unique_filename}"
                )

            # -------------------------------------------------
            # Create issue
            # -------------------------------------------------
            reference_no = make_issue_reference()

            issue = BagIssue(
                request_id=bag_request.id if bag_request else None,
                reference_no=reference_no,
                plant_id=plant_id,
                supervisor_id=supervisor_id,
                bag_type_id=bag_type_id,
                quantity=quantity,
                issue_date=date.today(),
                shift=shift,
                parchi_photo=relative_photo_path,
                user_id=current_user.id,
            )
            db.session.add(issue)

            # -------------------------------------------------
            # Create stock ledger movement
            # -------------------------------------------------
            movement = StockMovement(
                bag_type_id=bag_type_id,
                movement_type="plant_issue",
                previous_qty=previous_qty,
                new_qty=new_qty,
                change_qty=-quantity,
                reason=(
                    f"Plant issue {reference_no} - "
                    f"{plant.name} - {supervisor.name}"
                ),
                user_id=current_user.id,
            )
            db.session.add(movement)

            # Update stock.
            bag_type.current_stock = new_qty

            # Only request-based issues complete a request.
            if bag_request:
                bag_request.status = "Completed"

            # Save everything together.
            db.session.commit()

            current_app.logger.info(
                "Issue saved: ref=%s mode=%s quantity=%s",
                reference_no,
                mode,
                quantity,
            )

            if mode == "manual":
                flash(
                    f"Manual issue successful! Reference: {reference_no}. "
                    f"Issued: {quantity}. Remaining stock: {new_qty}.",
                    "success",
                )
            else:
                flash(
                    f"Request issue successful! Reference: {reference_no}. "
                    f"Issued: {quantity}. Remaining stock: {new_qty}.",
                    "success",
                )

            return redirect(url_for("issues.index"))

        except (SQLAlchemyError, OSError):
            db.session.rollback()

            if saved_photo_path and saved_photo_path.exists():
                try:
                    saved_photo_path.unlink()
                except OSError:
                    current_app.logger.exception(
                        "Failed to remove photo after issue error."
                    )

            current_app.logger.exception(
                "Error saving bag issue."
            )

            flash(
                "Issue save nahi ho paya. Terminal ka error check karein.",
                "danger",
            )
            return redirect(url_for("issues.index"))

        except Exception:
            db.session.rollback()

            if saved_photo_path and saved_photo_path.exists():
                try:
                    saved_photo_path.unlink()
                except OSError:
                    current_app.logger.exception(
                        "Failed to remove photo after unexpected error."
                    )

            current_app.logger.exception(
                "Unexpected bag issue error."
            )

            flash(
                "Unexpected error aaya. VS Code Terminal check karein.",
                "danger",
            )
            return redirect(url_for("issues.index"))

    # =====================================================
    # GET: LOAD PAGE
    # =====================================================
    plants = (
        Plant.query
        .filter_by(is_active=True)
        .order_by(Plant.name.asc())
        .all()
    )

    supervisors = (
        Supervisor.query
        .filter_by(is_active=True)
        .order_by(Supervisor.name.asc())
        .all()
    )

    bag_types = (
        BagType.query
        .filter_by(is_active=True)
        .order_by(BagType.size_kg.asc(), BagType.name.asc())
        .all()
    )

    pending_requests = (
        BagRequest.query
        .filter_by(status="Pending")
        .order_by(
            BagRequest.request_date.asc(),
            BagRequest.id.asc(),
        )
        .all()
    )

    recent_issues = (
        BagIssue.query
        .order_by(
            BagIssue.created_at.desc(),
            BagIssue.id.desc(),
        )
        .limit(50)
        .all()
    )

    return render_template(
        "issues.html",
        plants=plants,
        supervisors=supervisors,
        bag_types=bag_types,
        pending_requests=pending_requests,
        recent_issues=recent_issues,
    )
