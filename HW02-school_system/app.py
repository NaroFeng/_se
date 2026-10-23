"""NKU portal — Flask entrypoint."""
import os

from flask import Flask

from config import Config, TestConfig
from models import init_db, register_db
from routes import (
    admin_bp,
    announcement_bp,
    auth_bp,
    menu_bp,
    page_bp,
    partial_bp,
)


def create_app(config_class: type = Config) -> Flask:
    app = Flask(
        __name__,
        instance_relative_config=False,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config_class)
    register_db(app)

    app.register_blueprint(page_bp)
    app.register_blueprint(partial_bp)
    app.register_blueprint(menu_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(announcement_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        init_db(app)

    return app


app = create_app()


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    port = int(os.environ.get("FLASK_RUN_PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=debug)