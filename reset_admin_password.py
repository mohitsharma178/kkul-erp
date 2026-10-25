
from getpass import getpass

from backend import create_app
from backend.extensions import db
from backend.models import User

app = create_app()

with app.app_context():
    username = input("Admin username [mohitsharma]: ").strip()
    if not username:
        username = "mohitsharma"

    user = User.query.filter_by(username=username).first()

    if user is None:
        print("Is username ka account nahi mila.")
    else:
        password = getpass("Naya password (minimum 12 characters): ")
        confirm = getpass("Naya password dobara enter karein: ")

        if len(password) < 12:
            print("Password kam se kam 12 characters ka hona chahiye.")
        elif password != confirm:
            print("Dono passwords match nahi karte.")
        else:
            user.set_password(password)
            db.session.commit()
            print("Password successfully reset ho gaya.")
