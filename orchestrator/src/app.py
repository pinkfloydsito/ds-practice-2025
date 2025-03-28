import sys
import os

import grpc
import logging

from flask import Flask, request, current_app
from flask_cors import CORS

from grpc_client_factory import GrpcClientFactory


# This set of lines are needed to import the gRPC stubs.
# The path of the stubs is relative to the current file, or absolute inside the container.
# Change these lines only if strictly needed.

microservices = ["fraud_detection"]

for microservice in microservices:
    FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
    grpc_path = os.path.abspath(os.path.join(FILE, f"../../../utils/pb/{microservice}"))
    sys.path.insert(0, grpc_path)

import fraud_detection_pb2 as fraud_detection
import fraud_detection_pb2_grpc as fraud_detection_grpc

vector_clock_path = os.path.abspath(os.path.join(FILE, f"../../../utils/vector_clock"))
sys.path.insert(0, vector_clock_path)

from vector_clock import OrderEventTracker


def greet(grpc_factory, name="you"):
    try:
        # Get the appropriate stub
        stub = grpc_factory.get_stub(
            "fraud_detection", fraud_detection_grpc.HelloServiceStub, secure=False
        )

        # Make the call with timeout
        response = stub.SayHello(
            fraud_detection.HelloRequest(name=name),
            timeout=grpc_factory.default_timeout,
        )
        return response.greeting
    except grpc.RpcError as e:
        logging.error(f"gRPC error: {e.code()}: {e.details()}")
        raise


def create_app():
    app = Flask(__name__)
    app.grpc_factory = GrpcClientFactory()
    app.event_tracker = OrderEventTracker()

    # ✅ List of blueprints
    blueprints = [
        ("controllers.bookstore_controller", "bookstore_bp"),
        ("controllers.fintech_controller", "fintech_bp"),
    ]

    # Dynamically import and register blueprints
    for module_path, bp_name in blueprints:
        module = __import__(module_path, fromlist=[bp_name])
        blueprint = getattr(module, bp_name)
        app.register_blueprint(blueprint)

    # ✅ Register error handlers
    from error_handlers import register_error_handlers

    register_error_handlers(app)

    return app


app = create_app()
# Enable CORS for the app.
CORS(app, resources={r"/*": {"origins": "*"}})


# Define a GET endpoint.
@app.route("/", methods=["GET"])
def index():
    """
    Responds with 'Hello, [name]' when a GET request is made to '/' endpoint.
    """
    # Test the fraud-detection gRPC service.
    grpc_factory = current_app.grpc_factory
    username = request.args.get("name") or "other"
    response = greet(grpc_factory, name=username)

    return response


if __name__ == "__main__":
    # Run the app in debug mode to enable hot reloading.
    # This is useful for development.
    # The default port is 5000.
    app.run(host="0.0.0.0")
