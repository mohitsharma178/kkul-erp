
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from backend.extensions import db, login_manager


def utc_now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="godown_incharge")
    is_active_user = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    @property
    def is_active(self):
        return self.is_active_user

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None

class BagType(db.Model):
    __tablename__ = "bag_types"
    __table_args__ = (
        db.UniqueConstraint(
            "name", "size_kg",
            name="uq_bag_name_size"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    size_kg = db.Column(db.Numeric(6, 2), nullable=False)
    current_stock = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True),
                           default=utc_now, nullable=False)


class StockMovement(db.Model):
    __tablename__ = "stock_movements"

    id = db.Column(db.Integer, primary_key=True)
    bag_type_id = db.Column(
        db.Integer,
        db.ForeignKey("bag_types.id"),
        nullable=False
    )
    movement_type = db.Column(db.String(30), nullable=False)
    previous_qty = db.Column(db.Integer, nullable=False)
    new_qty = db.Column(db.Integer, nullable=False)
    change_qty = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )
    created_at = db.Column(db.DateTime(timezone=True),
                           default=utc_now, nullable=False)

    bag_type = db.relationship("BagType")
    user = db.relationship("User")
class InwardBill(db.Model):
    __tablename__ = "inward_bills"

    id = db.Column(db.Integer, primary_key=True)

    reference_no = db.Column(
        db.String(40), unique=True, nullable=False, index=True
    )
    supplier_name = db.Column(db.String(150), nullable=False)
    bill_number = db.Column(db.String(100), nullable=False)
    vehicle_number = db.Column(db.String(30), nullable=False)
    inward_date = db.Column(db.Date, nullable=False)

    bill_photo = db.Column(db.String(255), nullable=False)

    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime(timezone=True), default=utc_now, nullable=False
    )

    items = db.relationship(
        "InwardItem",
        back_populates="inward_bill",
        cascade="all, delete-orphan"
    )
    user = db.relationship("User")


class InwardItem(db.Model):
    __tablename__ = "inward_items"

    id = db.Column(db.Integer, primary_key=True)

    inward_bill_id = db.Column(
        db.Integer,
        db.ForeignKey("inward_bills.id"),
        nullable=False,
        index=True
    )
    bag_type_id = db.Column(
        db.Integer,
        db.ForeignKey("bag_types.id"),
        nullable=False
    )
    quantity = db.Column(db.Integer, nullable=False)

    inward_bill = db.relationship(
        "InwardBill", back_populates="items"
    )
    bag_type = db.relationship("BagType")
    
class Plant(db.Model):
    __tablename__ = "plants"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    supervisors = db.relationship("Supervisor", back_populates="plant")


class Supervisor(db.Model):
    __tablename__ = "supervisors"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    employee_code = db.Column(db.String(50), unique=True, nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    plant_id = db.Column(db.Integer, db.ForeignKey("plants.id"), nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    plant = db.relationship("Plant", back_populates="supervisors")


class BagIssue(db.Model):
    __tablename__ = "bag_issues"
    request_id = db.Column(
        db.Integer,
        db.ForeignKey("bag_requests.id", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=True,
        index=True
    )

    id = db.Column(db.Integer, primary_key=True)

    reference_no = db.Column(
        db.String(60),
        unique=True,
        nullable=False,
        index=True
    )

    plant_id = db.Column(
        db.Integer,
        db.ForeignKey("plants.id"),
        nullable=False,
        index=True
    )

    supervisor_id = db.Column(
        db.Integer,
        db.ForeignKey("supervisors.id"),
        nullable=False,
        index=True
    )

    bag_type_id = db.Column(
        db.Integer,
        db.ForeignKey("bag_types.id"),
        nullable=False,
        index=True
    )

    # Full quantity issue hoti hai; partial issue allowed nahi hai.
    quantity = db.Column(db.Integer, nullable=False)

    issue_date = db.Column(db.Date, nullable=False, index=True)

    # Purane records ki shift unknown ho sakti hai.
    shift = db.Column(
        db.String(20),
        nullable=True,
        default=None
    )

    parchi_photo = db.Column(db.String(255), nullable=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    plant = db.relationship("Plant")
    supervisor = db.relationship("Supervisor")
    bag_type = db.relationship("BagType")
    user = db.relationship("User")
    bag_request = db.relationship("BagRequest", foreign_keys=[request_id])


class DailyIssueLimit(db.Model):
    __tablename__ = "daily_issue_limits"

    __table_args__ = (
        db.UniqueConstraint(
            "plant_id",
            "bag_type_id",
            name="uq_daily_limit_plant_bag"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    plant_id = db.Column(
        db.Integer,
        db.ForeignKey("plants.id"),
        nullable=False
    )

    bag_type_id = db.Column(
        db.Integer,
        db.ForeignKey("bag_types.id"),
        nullable=False
    )

    daily_limit = db.Column(db.Integer, nullable=False)

    plant = db.relationship("Plant")
    bag_type = db.relationship("BagType")
class BagRequest(db.Model):
    __tablename__ = "bag_requests"

    id = db.Column(db.Integer, primary_key=True)

    reference_no = db.Column(
        db.String(60),
        unique=True,
        nullable=False,
        index=True
    )

    plant_id = db.Column(
        db.Integer,
        db.ForeignKey("plants.id"),
        nullable=False,
        index=True
    )

    supervisor_id = db.Column(
        db.Integer,
        db.ForeignKey("supervisors.id"),
        nullable=False,
        index=True
    )

    bag_type_id = db.Column(
        db.Integer,
        db.ForeignKey("bag_types.id"),
        nullable=False,
        index=True
    )

    requested_quantity = db.Column(
        db.Integer,
        nullable=False
    )

    request_date = db.Column(
        db.Date,
        nullable=False,
        index=True
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="Pending"
    )

    remarks = db.Column(
        db.String(255),
        nullable=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    plant = db.relationship("Plant")
    supervisor = db.relationship("Supervisor")
    bag_type = db.relationship("BagType")
    user = db.relationship("User")