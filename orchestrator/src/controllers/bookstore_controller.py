from flask import Blueprint, request, jsonify
from marshmallow import ValidationError
from schema import *
import uuid

# XXX: Change this: Mock database for demonstration
suggested_books_db = [
    {"bookId": "book1", "title": "The Great Gatsby", "author": "F. Scott Fitzgerald"},
    {"bookId": "book2", "title": "1984", "author": "George Orwell"},
    {"bookId": "book3", "title": "To Kill a Mockingbird", "author": "Harper Lee"},
]

bookstore_bp = Blueprint("bookstore", __name__)


@bookstore_bp.route("/checkout", methods=["POST"])
def checkout():
    try:
        # Validate request data
        schema = CheckoutRequestSchema()
        data = schema.load(request.json)

        # Validate terms and conditions
        if not data["termsAndConditionsAccepted"]:
            return jsonify(
                {
                    "error": {
                        "code": "TERMS_NOT_ACCEPTED",
                        "message": "Terms and conditions must be accepted",
                    }
                }
            ), 400

        # Process payment
        # payment_successful = process_payment(data['creditCard'])

        # if payment_successful:
        #     # Generate order response
        #     response = {
        #         "orderId": str(uuid.uuid4()),
        #         "status": "Order Approved",
        #         "suggestedBooks": suggested_books_db[:2]  # Return 2 suggested books
        #     }
        #     return jsonify(OrderStatusResponseSchema().dump(response))
        # else:
        #     # Payment failed
        #     response = {
        #         "orderId": str(uuid.uuid4()),
        #         "status": "Order Rejected",
        #         "suggestedBooks": []
        #     }
        #     return jsonify(OrderStatusResponseSchema().dump(response))

        response = {
            "orderId": str(uuid.uuid4()),
            "status": "Order Approved",
            "suggestedBooks": suggested_books_db[:2],  # Return 2 suggested books
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
