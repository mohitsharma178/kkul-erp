from pathlib import Path
from flask import Flask

from backend.config import Config
from backend.extensions import db, login_manager, csrf

def create_app():
    project_root = Path(__file__).resolve().parent.parent

    app = Flask(
        __name__,
        template_folder=str(project_root / "frontend" / "templates"),
        static_folder=str(project_root / "frontend" / "static"),
        static_url_path="/static"
    )

    app.config.from_object(Config)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY missing hai. Root .env file check karein."
        )

    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError(
            "DATABASE_URL missing hai. Root .env file check karein."
        )

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Blueprints ko app create hone ke baad register karna hai.
    from backend.auth import auth_bp
    from backend.dashboard import dashboard_bp
    from backend.inventory import inventory_bp
    from backend.inward import inward_bp
    from backend.plants import plants_bp
    from backend.supervisors import supervisors_bp
    from backend.issues import issues_bp
    from backend.daily_limits import daily_limits_bp
    from backend.reports import reports_bp
    from backend.users import users_bp
    from backend.requests import requests_bp
    from backend.stock_ledger import stock_ledger_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(inward_bp)
    app.register_blueprint(plants_bp)
    app.register_blueprint(supervisors_bp)
    app.register_blueprint(issues_bp)
    app.register_blueprint(daily_limits_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(stock_ledger_bp)

    return app