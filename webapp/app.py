import os
from flask import Flask, render_template
from flask_login import LoginManager

from config.settings import FLASK_SECRET_KEY, BASE_DIR
from core.database import get_db
from webapp.auth_web import WebUser
from webapp.api import api_bp
from webapp.views import views_bp


def create_app(test_config=None) -> Flask:
    """Application factory for DigiBook Flask Web Application."""
    app = Flask(
        __name__,
        template_folder=os.path.join(BASE_DIR, "webapp", "templates"),
        static_folder=os.path.join(BASE_DIR, "webapp", "static"),
    )

    app.config["SECRET_KEY"] = FLASK_SECRET_KEY
    app.config["JSON_SORT_KEYS"] = False

    if test_config:
        app.config.update(test_config)

    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.login_view = "views.signin"
    login_manager.login_message_category = "info"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        db = getattr(app, "_test_db", None) or get_db()
        return WebUser.get(user_id, db=db)

    # Register Blueprints
    app.register_blueprint(api_bp)
    app.register_blueprint(views_bp)

    # Error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("base.html", error_title="404 - Not Found", error_message="The requested resource could not be found."), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template("base.html", error_title="500 - Server Error", error_message="An internal server error occurred."), 500

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
