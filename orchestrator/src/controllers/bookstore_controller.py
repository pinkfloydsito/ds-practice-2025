from flask import Blueprint, request, jsonify
from marshmallow import ValidationError
from schema import *
import uuid
import requests


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

        if not data["termsAndConditionsAccepted"]:
            return jsonify(
                {
                    "error": {
                        "code": "TERMS_NOT_ACCEPTED",
                        "message": "Terms and conditions must be accepted",
                    }
                }
            ), 400

        # payment_successful = process_payment(data['user'])
        
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
                "suggestedBooks": suggested_books_db[:2]  # Return 2 suggested books
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
            "sender": {
                "name": "Bookstore Inc.",
                "accountNumber": "111122223333"
            },
            "recipient": {
                "name": user['name'],
                "accountNumber": "444455556666" 
            },
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
            "deviceLanguage": "en-US"
        }

        response = requests.post("http://localhost:8081/transfer", json=transfer_payload)

        if response.status_code == 200:
            transfer_data = response.json()
            return transfer_data["status"] == "Transfer Approved"
        else:
            print(f"Transfer API failed with status code: {response.status_code}")
            return False

    except Exception as e:
        print(f"Error processing payment: {e}")
        return False
