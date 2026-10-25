
import getpass

from backend import create_app
from backend.extensions import db
from backend.models import User

app = create_app()

with app.app_context():
    username = input("Admin username: ").strip()
    full_name = input("Admin full name: ").strip()
    password = getpass.getpass("Admin password (minimum 12 characters): ")
    confirm = getpass.getpass("Confirm password: ")

    if not username or not full_name:
        raise SystemExit("Username aur full name required hain.")

    if len(password) < 12:
        raise SystemExit("Password kam se kam 12 characters ka hona chahiye.")

    if password != confirm:
        raise SystemExit("Passwords match nahi karte.")

    if User.query.filter_by(username=username).first():
        raise SystemExit("Ye username pehle se exist karta hai.")

    admin = User(
        username=username,
        full_name=full_name,
        role="admin",
    )
    admin.set_password(password)

    db.session.add(admin)
    db.session.commit()

    print("Admin account successfully created.")
