import os
import traceback
import sys
from flask import Blueprint, request, jsonify, current_app
from marshmallow import ValidationError
from schema import *
import uuid
import grpc
import requests
from google.protobuf.json_format import MessageToDict
from typing import List
from sqlalchemy.orm import sessionmaker

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


microservices = ["suggestions", "transaction_verification", "fraud_detection"]

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
for microservice in microservices:
    grpc_path = os.path.abspath(
        os.path.join(FILE, f"../../../../utils/pb/{microservice}")
    )
    sys.path.insert(0, grpc_path)

models_path = os.path.abspath(os.path.join(FILE, "../../../../utils/models"))
sys.path.insert(0, models_path)

from book import Book, engine
import suggestions_pb2 as suggestions
import suggestions_pb2_grpc as suggestions_grpc

import transaction_verification_pb2 as transaction_verification
import transaction_verification_pb2_grpc as transaction_verification_grpc

import fraud_detection_pb2 as fraud_pb2
import fraud_detection_pb2_grpc as fraud_pb2_grpc


def get_suggestions(grpc_factory, book_tokens: List[str]):
    try:
        stub = grpc_factory.get_stub(
            "suggestions", suggestions_grpc.BookSuggestionStub, secure=False
        )

        request = suggestions.RecommendationRequest(
            user_id="1",
            limit=3,
            book_tokens=book_tokens,
        )

        response = stub.GetSuggestions(request, timeout=grpc_factory.default_timeout)

        response_dict = MessageToDict(response)

        raw_recommendations = response_dict.get("recommendations", [])
        formatted_recommendations = []

        for rec in raw_recommendations:
            book_info = rec.get("book", {})
            formatted_recommendations.append(
                {
                    "productId": book_info.get("id", ""),
                    "title": book_info.get("description", ""),
                    "author": book_info.get("author", ""),
                }
            )

        return formatted_recommendations
    except grpc.RpcError as e:
        print(e)
        print(f"gRPC error: {e.code()}: {e.details()}")
        raise


def verify_transaction(
    grpc_factory, credit_card: str, expiry_date: str, vector_clock, order_id
):
    try:
        stub = grpc_factory.get_stub(
            "transaction_verification",
            transaction_verification_grpc.TransactionVerificationServiceStub,
            secure=False,
        )

        request = transaction_verification.TransactionRequest(
            creditCardNumber=credit_card,
            expiryDate=expiry_date,
            vectorClock=vector_clock,
            orderId=order_id,
        )

        response = stub.VerifyTransaction(request, timeout=grpc_factory.default_timeout)

        response_dict = MessageToDict(response)

        return response_dict

    except grpc.RpcError as e:
        print(e)
        print(f"gRPC error: {e.code()}: {e.details()}")
        raise


def verify_items(grpc_factory, books: list[str], vector_clock, order_id):
    try:
        stub = grpc_factory.get_stub(
            "transaction_verification",
            transaction_verification_grpc.TransactionVerificationServiceStub,
            secure=False,
        )

        request = transaction_verification.BooksRequest(
            books=books,
            vectorClock=vector_clock,
            orderId=order_id,
        )

        response = stub.VerifyBooks(request, timeout=grpc_factory.default_timeout)

        response_dict = MessageToDict(response)

        return response_dict

    except grpc.RpcError as e:
        print(e)
        print(f"gRPC error: {e.code()}: {e.details()}")
        raise


def check_fraud(
    grpc_factory,
    amount: float,
    ip_address: str,
    email: str,
    billing_country: str,
    billing_city: str,
    payment_method: str,
):
    """
    Calls the FraudDetectionService.CheckFraud RPC,
    passing a user name and user email.
    """
    try:
        # Acquire a stub for the 'fraud_detection' microservice.
        stub = grpc_factory.get_stub(
            "fraud_detection",
            fraud_pb2_grpc.FraudDetectionServiceStub,
            secure=False,
        )

        # Build the request object (fields depend on your .proto definition)
        request = fraud_pb2.FraudRequest(
            amount=amount,
            ip_address=ip_address,
            email=email,
            billing_country=billing_country,
            billing_city=billing_city,
            payment_method=payment_method,
        )

        # Make the gRPC call with a timeout
        response = stub.CheckFraud(request, timeout=grpc_factory.default_timeout)

        # Convert to a dictionary for convenience
        response_dict = MessageToDict(
            response,
            preserving_proto_field_name=True,
            always_print_fields_with_no_presence=True,
        )
        return response_dict  # e.g. { "is_fraudulent": True/False, "reason": "..." }

    except grpc.RpcError as e:
        print(e)
        print(f"gRPC error: {e.code()}: {e.details()}")
        raise


bookstore_bp = Blueprint("bookstore", __name__)


@bookstore_bp.route("/checkout", methods=["POST"])
def checkout():
    grpc_factory = current_app.grpc_factory
    event_tracker = current_app.event_tracker

    print("Received checkout request")
    try:
        # Validate request data
        schema = CheckoutRequestSchema()
        data = schema.load(request.json)

        if not data["termsAndConditionsAccepted"]:
            return jsonify(
                {
                    "error": {
                        "code": "TERMS_NOT_ACCEPTED",
                        "message": "Terms and conditions must be accepted",
                    }
                }
            ), 400

        books = data.get("items", [])

        books_tokens = [book["name"] for book in books]

        credit_card_number = data.get("creditCard", {}).get("number")
        expiration_date = data.get("creditCard", {}).get("expirationDate")

        payment_method = "Credit Card"

        amount = sum(book.get("price", 10) for book in books)
        ip_address = request.remote_addr or ""
        # ip_address = "5.45.198.12"
        email = data.get("user", {}).get("contact", "")
        billing_country = data["billingAddress"]["country"]
        billing_city = data["billingAddress"]["city"]

        verification_result = None
        verification_items_result = None
        suggestions_result = None
        fraud_detection_result = None
        order_id = str(uuid.uuid4())

        print(f"Processing order: {order_id}")

        event_tracker.initialize_order(order_id)

        # initial clock
        initial_clock = event_tracker.record_event(
            order_id=order_id, service="orchestrator", event_name="checkout_started"
        )

        print(f"vector clock: {initial_clock}")

        errors = []
        final_vector_clock = None

        # Event execution flag to control flow instead of using locks and mutex
        event_completed = {
            "verify_items": threading.Event(),
            # "verify_user_data": threading.Event(),
            "verify_transaction": threading.Event(),
            # "check_fraud": threading.Event(),
            # "check_payment_fraud": threading.Event(),
            # "generate_suggestions": threading.Event(),
        }

        def verify_items_worker():
            nonlocal verification_items_result, errors
            try:
                print(f"Starting verification of books for order: {order_id}")

                current_clock = event_tracker.get_clock(order_id, "orchestrator")

                verification_items_result = verify_items(
                    grpc_factory,
                    books_tokens,
                    vector_clock=current_clock,
                    order_id=order_id,
                )

                event_tracker.record_event(
                    order_id=order_id,
                    service="orchestrator",
                    event_name="items_verified",
                    received_clock=dict(verification_items_result.vectorClock),
                )

                print(
                    f"Verification of books completed with result: {verification_items_result}"
                )

            except Exception as e:
                error = f"Verification error: {str(e)}"
                errors.append(error)
                print(error)
            finally:
                event_completed["verify_items"].set()

        def verify_transaction_worker():
            nonlocal verification_result, errors

            # wait for the verification of the items
            event_completed["verify_items"].wait()

            try:
                print(f"Starting verification for transaction: {credit_card_number}")

                current_clock = event_tracker.get_clock(order_id, "orchestrator")

                verification_result = verify_transaction(
                    grpc_factory,
                    credit_card_number,
                    expiration_date,
                    vector_clock=current_clock,
                    order_id=order_id,
                )
                print(f"Verification completed with result: {verification_result}")
            except Exception as e:
                error = f"Verification error: {str(e)}"
                errors.append(error)
                print(error)
            finally:
                event_completed["verify_transaction"].set()

        def suggestions_worker():
            nonlocal suggestions_result, errors
            try:
                print("Starting suggestions retrieval")
                suggestions_result = get_suggestions(grpc_factory, books_tokens)
                print(
                    f"Retrieved {len(suggestions_result) if suggestions_result else 0} suggestions"
                )
            except Exception as e:
                error = f"Suggestions error: {str(e)}"
                errors.append(error)

                print(error)

        def fraud_detection_worker():
            nonlocal fraud_detection_result, errors
            try:
                print("Starting fraud_detection analysis")
                fraud_detection_result = check_fraud(
                    grpc_factory,
                    amount=amount,
                    ip_address=ip_address,
                    email=email,
                    billing_country=billing_country,
                    billing_city=billing_city,
                    payment_method=payment_method,
                )
                print(
                    f"Fraud detection completed with result: {fraud_detection_result}"
                )
            except Exception as e:
                error = f"Fraud detection error: {str(e)}"
                errors.append(error)

                print(error)

        with ThreadPoolExecutor(max_workers=4) as executor:
            verify_items_job = executor.submit(verify_items_worker)
            verify_transaction_job = executor.submit(verify_transaction_worker)
            suggestions_job = executor.submit(suggestions_worker)
            fraud_detection_job = executor.submit(fraud_detection_worker)

            for future in as_completed(
                [
                    verify_items_job,
                    verify_transaction_job,
                    suggestions_job,
                    fraud_detection_job,
                ]
            ):
                if final_vector_clock:
                    broadcast_clear_order(grpc_factory, order_id, final_vector_clock)

        if (
            fraud_detection_result
            and not fraud_detection_result.get("action", "REJECT") == "APPROVE"
        ):
            details = fraud_detection_result.get("details", {})
            for key, value in details.items():
                if key in ["ip_country", "ip_country_mismatch"]:
                    errors.append(f"Fraud detection: {key} - {value}")
            print(f"Fraud detection result: {fraud_detection_result}")
            return jsonify(
                {
                    "error": {
                        "code": "ORDER_REJECTED",
                        "message": ", ".join(
                            fraud_detection_result.get(
                                "reasons", ["Fraudulent transaction"]
                            )
                        ),
                    }
                }
            ), 400

        if not (verification_result and verification_result.get("isValid", False)):
            return jsonify(
                {
                    "error": {
                        "code": "ORDER_REJECTED",
                        "message": verification_result.get(
                            "reason", "Error verifying transaction"
                        ),
                    }
                }
            ), 400

        response = {
            "orderId": order_id,
            "status": "Order Approved",
            "suggestedBooks": suggestions_result,
        }

        return jsonify(OrderStatusResponseSchema().dump(response))

    except ValidationError as err:
        # If your frontend expects an 'error' key with a 'message':
        return jsonify(
            {
                "error": {
                    "code": "ORDER_REJECTED",
                    "message": ", ".join(
                        f"{field}: {msg}"
                        for field, messages in err.messages.items()
                        for msg in messages
                    ),
                }
            }
        ), 400

    except Exception as e:
        print(e)
        # trace
        traceback.print_exc()
        return jsonify(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal error occurred",
                }
            }
        ), 500


def process_payment(user):
    """Handles the payment by calling the /transfer API."""
    try:
        transfer_payload = {
            "sender": {"name": "Bookstore Inc.", "accountNumber": "111122223333"},
            "recipient": {"name": user["name"], "accountNumber": "444455556666"},
            "amount": 10000,
            "currency": "USD",
            "paymentMethod": "Credit Card",
            "transferNote": "Book purchase",
            "notificationPreferences": ["Email"],
            "device": {"type": "Desktop", "model": "PC", "os": "Windows 11"},
            "browser": {"name": "Chrome", "version": "118.0"},
            "appVersion": "1.0.0",
            "screenResolution": "1920x1080",
            "referrer": "Bookstore Website",
            "deviceLanguage": "en-US",
        }

        response = requests.post(
            "http://localhost:8081/transfer", json=transfer_payload
        )

        if response.status_code == 200:
            transfer_data = response.json()
            return transfer_data["status"] == "Transfer Approved"
        else:
            print(f"Transfer API failed with status code: {response.status_code}")
            return False

    except Exception as e:
        print(f"Error processing payment: {e}")
        return False


@bookstore_bp.route("/books", methods=["GET"])
def list_books():
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 10, type=int)

        genre = request.args.get("genre")
        author = request.args.get("author")

        query = session.query(Book).with_entities(
            Book.id,
            Book.title,
            Book.author,
            Book.genre,
            Book.subgenre,
            Book.height,
            Book.publisher,
        )

        # Apply filters if provided
        if genre:
            query = query.filter(Book.genres.contains([genre]))
        if author:
            query = query.filter(Book.author.ilike(f"%{author}%"))

        # Get total count for pagination
        total = query.count()

        # Apply pagination
        books = query.offset((page - 1) * limit).limit(limit).all()

        # Convert to dictionary for JSON response
        books_data = [book._asdict() for book in books]

        response = {
            "books": books_data,
            "pagination": {
                "total": total,
                "page": page,
                "limit": limit,
                "pages": (total + limit - 1) // limit,
            },
        }

        return jsonify(response)
    except Exception as e:
        print(e)
        traceback.print_exc()
        return jsonify(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal error occurred",
                }
            }
        ), 500
    finally:
        session.close()


# Helper function to broadcast clear order command
def broadcast_clear_order(grpc_factory, order_id, final_vector_clock):
    """
    Broadcast to all services to clear the order data
    """
    services = ["suggestions", "transaction_verification", "fraud_detection"]

    for service_name in services:
        try:
            # Each service would need a ClearOrder gRPC method
            service_module = globals().get(f"{service_name}_grpc")
            stub_class = getattr(
                service_module, f"{service_name.capitalize()}ServiceStub", None
            )

            if not stub_class:
                print(f"Stub class not found for {service_name}")
                continue

            stub = grpc_factory.get_stub(service_name, stub_class, secure=False)

            # Create appropriate request message
            module = globals().get(service_name)
            request_class = getattr(module, "ClearOrderRequest", None)

            if not request_class:
                print(f"Request class not found for {service_name}")
                continue

            request = request_class(orderId=order_id, vectorClock=final_vector_clock)

            # Call the service
            stub.ClearOrder(request, timeout=grpc_factory.default_timeout)

        except Exception as e:
            print(f"Error clearing order from {service_name}: {e}")
