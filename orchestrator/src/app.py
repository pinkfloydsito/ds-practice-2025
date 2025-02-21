import sys
import os

# This set of lines are needed to import the gRPC stubs.
# The path of the stubs is relative to the current file, or absolute inside the container.
# Change these lines only if strictly needed.
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
fraud_detection_grpc_path = os.path.abspath(
    os.path.join(FILE, "../../../utils/pb/fraud_detection")
)
sys.path.insert(0, fraud_detection_grpc_path)
import fraud_detection_pb2 as fraud_detection
import fraud_detection_pb2_grpc as fraud_detection_grpc

import grpc


def greet(name="you"):
    # Establish a connection with the fraud-detection gRPC service.
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        # Create a stub object.
        stub = fraud_detection_grpc.HelloServiceStub(channel)
        # Call the service through the stub object.
        response = stub.SayHello(fraud_detection.HelloRequest(name=name))
    return response.greeting


# Import Flask.
# Flask is a web framework for Python.
# It allows you to build a web application quickly.
# For more information, see https://flask.palletsprojects.com/en/latest/
from flask import Flask, request
from flask_cors import CORS
import json


def create_app():
    app = Flask(__name__)

    # Import and register blueprints/controllers
    from controllers.bookstore_controller import bookstore_bp

    app.register_blueprint(bookstore_bp)

    # Register error handlers
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
    username = request.args.get("name") or "other"
    response = greet(name=username)
    # Return the response.
    return response


# @app.route("/checkout", methods=["POST"])
# def checkout():
#     """
#     Responds with a JSON object containing the order ID, status, and suggested books.
#     """
#     # Get request object data to json
#     request_data = json.loads(request.data)
#     # Print request object data
#     print("Request Data:", request_data.get("items"))
#
#     # Dummy response following the provided YAML specification for the bookstore
#     order_status_response = {
#         "orderId": "12345",
#         "status": "Order Approved",
#         "suggestedBooks": [
#             {"bookId": "123", "title": "The Best Book", "author": "Author 1"},
#             {"bookId": "456", "title": "The Second Best Book", "author": "Author 2"},
#         ],
#     }
#
#     return order_status_response


if __name__ == "__main__":
    # Run the app in debug mode to enable hot reloading.
    # This is useful for development.
    # The default port is 5000.
    app.run(host="0.0.0.0")
