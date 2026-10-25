
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from backend.extensions import db
from backend.models import User
from backend.permissions import roles_required

users_bp = Blueprint("users", __name__, url_prefix="/users")

ALLOWED_ROLES = {
    "admin",
    "godown_incharge",
    "godown_supervisor",
    "godown",
    "shift",
    "viewer",
}


def admin_required():
    return current_user.is_authenticated and current_user.role == "admin"

@users_bp.route("/", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def index():

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "").strip()

        if not username or not full_name or not password or not role:
            flash("Saare fields bharna zaroori hai.", "danger")
            return redirect(url_for("users.index"))

        if len(password) < 12:
            flash("Password kam se kam 12 characters ka hona chahiye.", "danger")
            return redirect(url_for("users.index"))

        if role not in ALLOWED_ROLES:
            flash("Invalid role select kiya gaya hai.", "danger")
            return redirect(url_for("users.index"))

        if User.query.filter_by(username=username).first():
            flash("Ye username pehle se exist karta hai.", "danger")
            return redirect(url_for("users.index"))

        user = User(
            username=username,
            full_name=full_name,
            role=role,
            is_active_user=True,
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("Naya user successfully create ho gaya.", "success")
        return redirect(url_for("users.index"))

    users = User.query.order_by(User.id.desc()).all()
    return render_template("users.html", users=users, roles=sorted(ALLOWED_ROLES))
