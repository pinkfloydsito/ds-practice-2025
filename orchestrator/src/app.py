import threading
import os
import sys
import logging

from flask import Flask
from flask_cors import CORS

from error_handlers import register_error_handlers
from grpc_client_factory import GrpcClientFactory

from utils.logging import configure_logging

logger = logging.getLogger(__name__)

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")

vector_clock_path = os.path.abspath(os.path.join(FILE, "../../../utils/vector_clock"))

sys.path.insert(0, vector_clock_path)


def create_app(config_object="config.default"):
    app = Flask(__name__)

    configure_logging(app)

    configure_cors(app)

    app.config.from_object(config_object)

    register_blueprints(app)

    register_grpc(app)

    register_vector_clock(app)

    register_database_service(app)

    register_error_handlers(app)

    app.order_results = {}
    app.order_results_lock = threading.Lock()

    return app


def register_grpc(app):
    app.grpc_factory = GrpcClientFactory()


def register_database_service(app):
    """Initialize and register the database service."""
    from services.database_service import DatabaseService

    # Get database nodes from environment
    db_nodes_env = os.getenv("DB_NODES", "db-node1:50052,db-node2:50052,db-node3:50052")
    db_nodes = db_nodes_env.split(",")

    # Initialize database service
    app.database_service = DatabaseService(db_nodes)


def register_vector_clock(app):
    FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
    vector_clock_path = os.path.abspath(
        os.path.join(FILE, f"../../../utils/vector_clock")
    )
    sys.path.insert(0, vector_clock_path)

    from vector_clock import OrderEventTracker

    app.order_event_tracker = OrderEventTracker()


def register_blueprints(app):
    blueprints = [
        ("controllers.bookstore_controller", "bookstore_bp"),
        ("controllers.fintech_controller", "fintech_bp"),
        ("controllers.health_controller", "api_bp"),
        ("controllers.database_controller", "database_bp"),
        ("controllers.order_controller", "order_bp"),
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
