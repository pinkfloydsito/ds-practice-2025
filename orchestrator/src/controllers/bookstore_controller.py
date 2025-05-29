import os
import traceback
import sys
import uuid
import threading
from flask import Blueprint, request, jsonify, current_app
from marshmallow import ValidationError
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from google.protobuf.json_format import MessageToDict
from sqlalchemy.orm import sessionmaker

from services.raft_service import RaftService
from schema import (
    CheckoutRequestSchema,
    OrderStatusResponseSchema,
)

from services.order_orchestrator_service import OrderOrchestratorService

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")

# models path
models_path = os.path.abspath(os.path.join(FILE, "../../../../utils/models"))
sys.path.insert(0, models_path)

# import book model
from book import Book, engine
from bookstore_models import (
    UserInfo,
    CreditCardInfo,
    BillingInfo,
    OrderInfo,
)

bookstore_bp = Blueprint("bookstore", __name__)


# -----------------------------------------------------------------------------
#  checkout route
# -----------------------------------------------------------------------------
@bookstore_bp.route("/checkout", methods=["POST"])
def checkout():
    """Handle book checkout process."""
    order_id = str(uuid.uuid4())
    grpc_factory = current_app.grpc_factory
    order_event_tracker = current_app.order_event_tracker

    try:
        # 1) Validate the request
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

        # 2) Extract all required information
        books = data.get("items", [])
        book_tokens = [b["name"] for b in books]
        amount = sum(b.get("price", 10) for b in books)

        # Create dataclass instances
        user = UserInfo(
            user_id=data.get("user", {}).get("name", "guest"),
            email=data.get("user", {}).get("contact", ""),
            ip_address=request.remote_addr or "",
        )

        credit_card = CreditCardInfo(
            number=data.get("creditCard", {}).get("number"),
            expiry_date=data.get("creditCard", {}).get("expirationDate"),
        )

        billing = BillingInfo(
            city=data["billingAddress"]["city"],
            country=data["billingAddress"]["country"],
        )

        order = OrderInfo(order_id=order_id, book_tokens=book_tokens, amount=amount)

        # 3) Create orchestrator and process order
        orchestrator = OrderOrchestratorService(grpc_factory, order_event_tracker)

        # Initialize services [grpc calls]
        if not orchestrator.initialize_services(order, user, credit_card, billing):
            return jsonify(
                {
                    "error": {
                        "code": "ORDER_REJECTED",
                        "message": "Initialization failed for one or more services",
                    }
                }
            ), 400

        # Process order
        success, result = orchestrator.process_order(order, user, credit_card, billing)
        if not success:
            return jsonify(result), 400

        # success response
        return jsonify(OrderStatusResponseSchema().dump(result))

    except ValidationError as err:
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
        print(f"Unexpected error: {e}")
        return jsonify(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal error occurred",
                }
            }
        ), 500


@bookstore_bp.route("/v2/checkout", methods=["POST"])
def checkout_v2():
    """Enhanced checkout v2 with validation and service initialization before Raft submission."""
    order_id = str(uuid.uuid4())
    grpc_factory = current_app.grpc_factory
    order_event_tracker = current_app.order_event_tracker

    try:
        # 1. Validate request schema
        checkout_data = _validate_checkout_request(request.json)

        # 2. Extract and create domain objects
        order_info = _create_order_info(order_id, checkout_data)
        user_info = _create_user_info(checkout_data, request.remote_addr)
        credit_card_info = _create_credit_card_info(checkout_data)
        billing_info = _create_billing_info(checkout_data)

        # 3. Initialize orchestrator and services
        orchestrator = OrderOrchestratorService(grpc_factory, order_event_tracker)

        if not orchestrator.initialize_services(
            order_info, user_info, credit_card_info, billing_info
        ):
            print("[Orchestrator] Service initialization failed")
            return _create_error_response(
                "ORDER_REJECTED", "Service initialization failed"
            ), 400

        # Process sync order operations
        success, result = orchestrator.process_order(
            order_info, user_info, credit_card_info, billing_info
        )

        if not success:
            print(f"[Orchestrator] Order processing failed: {result}")
            return _create_error_response(
                "ORDER_REJECTED", result.get("message", "Order processing failed")
            ), 400

        store_order_result(order_id, result)

        # 4. Submit to Raft cluster
        raft_service = RaftService(grpc_factory)
        print(order_info)
        raft_result = raft_service.submit_job(order_id, order_info)

        if not raft_result.success:
            print(f"[Orchestrator] Raft submission failed: {raft_result.error}")
            return _create_error_response(
                "ORDER_REJECTED", "Raft submission failed"
            ), 400

        # 5. Return pending response for polling
        response_data = {
            "orderId": order_id,
            "status": "PENDING",
        }

        return jsonify(OrderStatusResponseSchema().dump(response_data))

    except ValidationError as err:
        print(f"[Orchestrator] Validation error: {err.messages}")
        return _create_validation_error_response(err), 400
    except Exception as e:
        print(f"Unexpected error: {e}")
        traceback.print_exc()
        return _create_error_response(
            "INTERNAL_ERROR", "An internal error occurred"
        ), 500


def store_order_result(order_id: str, result: dict):
    """Store the complete order result in Flask app context."""

    with current_app.order_results_lock:
        print(f"[Orchestrator] Stored result for order {order_id}")
        current_app.order_results[order_id] = result


def clear_stored_order_result(order_id: str):
    """Clear stored order result from Flask app context."""
    if order_id in current_app.order_results:
        del current_app.order_results[order_id]
        print(f"[Orchestrator] Cleared stored result for order {order_id}")


def _validate_checkout_request(request_json):
    """Validate the incoming checkout request."""
    schema = CheckoutRequestSchema()
    data = schema.load(request_json)

    if not data["termsAndConditionsAccepted"]:
        raise ValidationError(
            {"termsAndConditionsAccepted": ["Terms and conditions must be accepted"]}
        )

    return data


def _create_order_info(order_id: str, checkout_data: dict) -> OrderInfo:
    """Create OrderInfo from checkout data."""
    books = checkout_data.get("items", [])
    book_tokens = [book["name"] for book in books]
    amount = sum(book.get("price", 10) for book in books)

    return OrderInfo(order_id=order_id, book_tokens=book_tokens, amount=amount)


def _create_user_info(checkout_data: dict, remote_addr: str) -> UserInfo:
    """Create UserInfo from checkout data."""
    user_data = checkout_data.get("user", {})
    return UserInfo(
        user_id=user_data.get("name", "guest"),
        email=user_data.get("contact", ""),
        ip_address=remote_addr or "",
    )


def _create_credit_card_info(checkout_data: dict) -> CreditCardInfo:
    """Create CreditCardInfo from checkout data."""
    card_data = checkout_data.get("creditCard", {})
    return CreditCardInfo(
        number=card_data.get("number"), expiry_date=card_data.get("expirationDate")
    )


def _create_billing_info(checkout_data: dict) -> BillingInfo:
    """Create BillingInfo from checkout data."""
    billing_data = checkout_data["billingAddress"]
    return BillingInfo(city=billing_data["city"], country=billing_data["country"])


def _create_error_response(error_code: str, message: str) -> dict:
    """Create standardized error response."""
    return {"error": {"code": error_code, "message": message}}


def _create_validation_error_response(validation_error: ValidationError) -> dict:
    """Create validation error response from marshmallow ValidationError."""
    return {
        "error": {
            "code": "ORDER_REJECTED",
            "message": ", ".join(
                f"{field}: {msg}"
                for field, messages in validation_error.messages.items()
                for msg in messages
            ),
        }
    }


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


def items_from_data(order_id, data) -> OrderInfo:
    books = data.get("items", [])
    book_tokens = [b["name"] for b in books]
    amount = sum(b.get("price", 10) for b in books)

    order = OrderInfo(order_id=order_id, book_tokens=book_tokens, amount=amount)

    return order
