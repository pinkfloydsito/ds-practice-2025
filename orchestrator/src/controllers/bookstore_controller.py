import os
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


microservices = ["suggestions", "transaction_verification","fraud_detection"]

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


def verify_transaction(grpc_factory, credit_card: str, expiry_date: str):
    try:
        stub = grpc_factory.get_stub(
            "transaction_verification",
            transaction_verification_grpc.TransactionVerificationServiceStub,
            secure=False,
        )

        request = transaction_verification.TransactionRequest(
            creditCardNumber=credit_card,
            expiryDate=expiry_date,
        )

        response = stub.VerifyTransaction(request, timeout=grpc_factory.default_timeout)

        response_dict = MessageToDict(response)

        return response_dict

    except grpc.RpcError as e:
        print(e)
        print(f"gRPC error: {e.code()}: {e.details()}")
        raise

def check_fraud(grpc_factory, user_name: str, user_email: str):
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
            user_name=user_name,
            user_email=user_email,
        )

        # Make the gRPC call with a timeout
        response = stub.CheckFraud(request, timeout=grpc_factory.default_timeout)

        # Convert to a dictionary for convenience
        response_dict = MessageToDict(response)
        return response_dict  # e.g. { "isFraudulent": True/False, "reason": "..." }

    except grpc.RpcError as e:
        print(e)
        print(f"gRPC error: {e.code()}: {e.details()}")
        raise

bookstore_bp = Blueprint("bookstore", __name__)


@bookstore_bp.route("/checkout", methods=["POST"])
def checkout():
    grpc_factory = current_app.grpc_factory
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

        verification_result = None
        suggestions_result = None
        error = None

        def verify_transaction_worker():
            nonlocal verification_result, error
            try:
                print(f"Starting verification for transaction: {credit_card_number}")
                verification_result = verify_transaction(
                    grpc_factory, credit_card_number, expiration_date
                )
                print(f"Verification completed with result: {verification_result}")
            except Exception as e:
                error = f"Verification error: {str(e)}"
                print(error)

        def suggestions_worker():
            nonlocal suggestions_result, error
            try:
                print("Starting suggestions retrieval")
                suggestions_result = get_suggestions(grpc_factory, books_tokens)
                print(
                    f"Retrieved {len(suggestions_result) if suggestions_result else 0} suggestions"
                )
            except Exception as e:
                error = f"Suggestions error: {str(e)}"
                print(error)

        with ThreadPoolExecutor(max_workers=2) as executor:
            verify_transaction_job = executor.submit(verify_transaction_worker)
            suggestions_job = executor.submit(suggestions_worker)

            for future in as_completed([verify_transaction_job, suggestions_job]):
                pass
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
            "orderId": str(uuid.uuid4()),
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
