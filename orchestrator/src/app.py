import logging

from flask import Flask, request, current_app
from flask_cors import CORS

from error_handlers import register_error_handlers
from grpc_client_factory import GrpcClientFactory

from utils.logging import configure_logging


def create_app(config_object="config.default"):
    app = Flask(__name__)

    configure_logging(app)

    configure_cors(app)

    app.config.from_object(config_object)

    register_blueprints(app)

    register_grpc(app)

    register_error_handlers(app)

    return app


def register_grpc(app):
    app.grpc_factory = GrpcClientFactory()


def register_blueprints(app):
    blueprints = [
        ("controllers.bookstore_controller", "bookstore_bp"),
        ("controllers.fintech_controller", "fintech_bp"),
        ("controllers.health_controller", "api_bp"),
    ]

    for module_path, bp_name in blueprints:
        module = __import__(module_path, fromlist=[bp_name])
        blueprint = getattr(module, bp_name)
        app.register_blueprint(blueprint)


def configure_cors(app):
    """Configure CORS."""
    origins = app.config.get("CORS_ORIGINS", "*")
    CORS(app, resources={r"/*": {"origins": origins}})
    logging.info(f"CORS configured with origins: {origins}")


app = create_app()


if __name__ == "__main__":
    # Run the app in debug mode to enable hot reloading.
    # This is useful for development.
    # The default port is 5000.
    app.run(host="0.0.0.0")
