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


microservices = ["suggestions"]

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
        recommendations = get_suggestions(grpc_factory, books_tokens)

        response = {
            "orderId": str(uuid.uuid4()),
            "status": "Order Approved",
            "suggestedBooks": recommendations,
        }
        return jsonify(OrderStatusResponseSchema().dump(response))

    except ValidationError as err:
        return jsonify(
            {"error": {"code": "VALIDATION_ERROR", "message": str(err.messages)}}
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
