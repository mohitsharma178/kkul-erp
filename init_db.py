from backend import create_app
from backend.extensions import db

# Database ke saare models register karein.
from backend.models import (
    User,
    BagType,
    StockMovement,
    InwardBill,
    InwardItem,
    Plant,
    Supervisor,
    BagIssue,
    DailyIssueLimit,
    BagRequest,
)


def initialize_database():
    app = create_app()

    with app.app_context():
        try:
            db.create_all()

            print("\nDatabase tables successfully created.")
            print("KKUL ERP database initialization complete.")
            print("\nRegistered models:")

            models = [
                User,
                BagType,
                StockMovement,
                InwardBill,
                InwardItem,
                Plant,
                Supervisor,
                BagIssue,
                DailyIssueLimit,
                BagRequest,
            ]

            for model in models:
                print(f"- {model.__name__}: {model.__tablename__}")

        except Exception as error:
            db.session.rollback()
            print("\nDatabase initialization failed.")
            print("Error:", error)
            raise


if __name__ == "__main__":
    initialize_database()
