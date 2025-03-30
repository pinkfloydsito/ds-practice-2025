import os
import sys
import uuid
import requests
import grpc
import threading
from flask import Blueprint, request, jsonify, current_app
from marshmallow import ValidationError
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from google.protobuf.json_format import MessageToDict
from sqlalchemy.orm import sessionmaker

# Insert paths for microservices
microservices = ["suggestions", "transaction_verification", "fraud_detection"]

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
for microservice in microservices:
    grpc_path = os.path.abspath(os.path.join(FILE, f"../../../../utils/pb/{microservice}"))
    sys.path.insert(0, grpc_path)

# Insert path for your models
models_path = os.path.abspath(os.path.join(FILE, "../../../../utils/models"))
sys.path.insert(0, models_path)

# Import proto stubs for suggestions
import suggestions_pb2 as suggestions
import suggestions_pb2_grpc as suggestions_grpc

# Import proto stubs for transaction verification
import transaction_verification_pb2 as transaction_verification
import transaction_verification_pb2_grpc as transaction_verification_grpc

# Import proto stubs for fraud detection
import fraud_detection_pb2 as fraud_pb2
import fraud_detection_pb2_grpc as fraud_pb2_grpc

# Import your own code
from book import Book, engine
from schema import (
    CheckoutRequestSchema,
    OrderStatusResponseSchema,
)

bookstore_bp = Blueprint("bookstore", __name__)

# -----------------------------------------------------------------------------
#  NEW: Initialize calls for each microservice
# -----------------------------------------------------------------------------
def initialize_transaction_order(grpc_factory, order_id: str, credit_card_number: str, expiry_date: str):
    """
    Calls TransactionVerificationService.InitializeOrder to store CC info before final verify.
    """
    try:
        stub = grpc_factory.get_stub(
            "transaction_verification",
            transaction_verification_grpc.TransactionVerificationServiceStub,
            secure=False,
        )
        request = transaction_verification.TransactionInitRequest(
            order_id=order_id,
            creditCardNumber=credit_card_number,
            expiryDate=expiry_date
        )
        response = stub.InitializeOrder(request)
        print(f"[Orchestrator] initialize_transaction_order => success={response.success}")
        return response.success
    except grpc.RpcError as e:
        print(f"gRPC error in initialize_transaction_order: {e.code()}: {e.details()}")
        return False

def initialize_fraud_order(grpc_factory, order_id: str, amount: float, ip_address: str,
                           email: str, billing_country: str, billing_city: str,
                           payment_method: str):
    """
    Calls FraudDetectionService.InitializeOrder to store order data before final CheckFraud.
    """
    try:
        stub = grpc_factory.get_stub(
            "fraud_detection",
            fraud_pb2_grpc.FraudDetectionServiceStub,
            secure=False
        )
        request = fraud_pb2.FraudInitRequest(
            order_id=order_id,
            amount=amount,
            ip_address=ip_address,
            email=email,
            billing_country=billing_country,
            billing_city=billing_city,
            payment_method=payment_method
        )
        response = stub.InitializeOrder(request)
        print(f"[Orchestrator] initialize_fraud_order => success={response.success}")
        return response.success
    except grpc.RpcError as e:
        print(f"gRPC error in initialize_fraud_order: {e.code()}: {e.details()}")
        return False

def initialize_suggestions_order(grpc_factory, order_id: str, book_tokens: List[str], user_id: str):
    """
    Calls BookSuggestion.InitializeOrder to store tokens / user before final GetSuggestions.
    """
    try:
        stub = grpc_factory.get_stub(
            "suggestions",
            suggestions_grpc.BookSuggestionStub,
            secure=False,
        )
        request = suggestions.SuggestionInitRequest(
            order_id=order_id,
            book_tokens=book_tokens,
            user_id=user_id
        )
        response = stub.InitializeOrder(request)
        print(f"[Orchestrator] initialize_suggestions_order => success={response.success}")
        return response.success
    except grpc.RpcError as e:
        print(f"gRPC error in initialize_suggestions_order: {e.code()}: {e.details()}")
        return False

# -----------------------------------------------------------------------------
#  Existing final calls (VerifyTransaction, GetSuggestions, CheckFraud)
# -----------------------------------------------------------------------------
def verify_transaction(grpc_factory, credit_card: str, expiry_date: str, order_id: str):
    try:
        stub = grpc_factory.get_stub(
            "transaction_verification",
            transaction_verification_grpc.TransactionVerificationServiceStub,
            secure=False,
        )
        request = transaction_verification.TransactionRequest(
            order_id=order_id,
            creditCardNumber=credit_card,
            expiryDate=expiry_date,
        )
        response = stub.VerifyTransaction(request)
        return MessageToDict(response)
    except grpc.RpcError as e:
        print(e)
        print(f"gRPC error (verify_transaction): {e.code()}: {e.details()}")
        raise

def get_suggestions(grpc_factory, book_tokens: List[str], order_id: str):
    try:
        stub = grpc_factory.get_stub(
            "suggestions",
            suggestions_grpc.BookSuggestionStub,
            secure=False
        )
        request = suggestions.RecommendationRequest(
            user_id="1",
            limit=3,
            book_tokens=book_tokens,
            order_id=order_id
        )
        response = stub.GetSuggestions(request)
        response_dict = MessageToDict(response)
        raw_recommendations = response_dict.get("recommendations", [])
        formatted = []
        for rec in raw_recommendations:
            book_info = rec.get("book", {})
            formatted.append({
                "productId": book_info.get("id", ""),
                "title": book_info.get("description", ""),
                "author": book_info.get("author", ""),
            })
        return formatted
    except grpc.RpcError as e:
        print(f"gRPC error (get_suggestions): {e.code()}: {e.details()}")
        raise

def check_fraud(grpc_factory, order_id: str, amount: float, ip_address: str,
                email: str, billing_country: str, billing_city: str,
                payment_method: str):
    """
    Calls FraudDetectionService.CheckFraud
    """
    try:
        stub = grpc_factory.get_stub(
            "fraud_detection",
            fraud_pb2_grpc.FraudDetectionServiceStub,
            secure=False
        )
        request = fraud_pb2.FraudRequest(
            amount=amount,
            ip_address=ip_address,
            email=email,
            billing_country=billing_country,
            billing_city=billing_city,
            payment_method=payment_method,
            order_id=order_id
        )
        response = stub.CheckFraud(request)
        return MessageToDict(
            response,
            preserving_proto_field_name=True,
            always_print_fields_with_no_presence=True
        )
    except grpc.RpcError as e:
        print(f"gRPC error (check_fraud): {e.code()}: {e.details()}")
        raise

# -----------------------------------------------------------------------------
#  The main checkout route
# -----------------------------------------------------------------------------
@bookstore_bp.route("/checkout", methods=["POST"])
def checkout():
    order_id = str(uuid.uuid4())
    grpc_factory = current_app.grpc_factory

    try:
        # 1) Validate the request
        schema = CheckoutRequestSchema()
        data = schema.load(request.json)

        if not data["termsAndConditionsAccepted"]:
            return jsonify({
                "error": {
                    "code": "TERMS_NOT_ACCEPTED",
                    "message": "Terms and conditions must be accepted"
                }
            }), 400

        # Gather the main fields
        books = data.get("items", [])
        book_tokens = [b["name"] for b in books]
        user_id = data.get("user", {}).get("name", "guest")

        credit_card_number = data.get("creditCard", {}).get("number")
        expiration_date = data.get("creditCard", {}).get("expirationDate")
        payment_method = "Credit Card"

        amount = sum(b.get("price", 10) for b in books)
        ip_address = request.remote_addr or ""
        email = data.get("user", {}).get("contact", "")
        billing_country = data["billingAddress"]["country"]
        billing_city = data["billingAddress"]["city"]

        # 2) Initialize each microservice BEFORE final concurrency
        tx_init_ok = initialize_transaction_order(
            grpc_factory,
            order_id,
            credit_card_number,
            expiration_date
        )
        fraud_init_ok = initialize_fraud_order(
            grpc_factory,
            order_id,
            amount,
            ip_address,
            email,
            billing_country,
            billing_city,
            payment_method
        )
        sugg_init_ok = initialize_suggestions_order(
            grpc_factory,
            order_id,
            book_tokens,
            user_id
        )

        # If any initialization fails, reject immediately
        if not (tx_init_ok and fraud_init_ok and sugg_init_ok):
            return jsonify({
                "error": {
                    "code": "ORDER_REJECTED",
                    "message": "Initialization failed for one or more services"
                }
            }), 400

        # 3) Prepare concurrency for final calls
        verification_result = None
        suggestions_result = None
        fraud_detection_result = None
        errors = []

        def verify_transaction_worker():
            nonlocal verification_result, errors
            try:
                print(f"[Orchestrator] Starting final VerifyTransaction for card: {credit_card_number}")
                verification_result = verify_transaction(
                    grpc_factory, credit_card_number, expiration_date, order_id
                )
                print(f"[Orchestrator] Verification final result: {verification_result}")
            except Exception as e:
                errors.append(f"Transaction verification error: {str(e)}")

        def suggestions_worker():
            nonlocal suggestions_result, errors
            try:
                print("[Orchestrator] Starting final suggestions retrieval")
                suggestions_result = get_suggestions(
                    grpc_factory, book_tokens, order_id
                )
                count = len(suggestions_result) if suggestions_result else 0
                print(f"[Orchestrator] Retrieved {count} suggestions")
            except Exception as e:
                errors.append(f"Suggestions error: {str(e)}")

        def fraud_detection_worker():
            nonlocal fraud_detection_result, errors
            try:
                print("[Orchestrator] Starting final fraud_detection analysis")
                fraud_detection_result = check_fraud(
                    grpc_factory,
                    order_id,
                    amount,
                    ip_address,
                    email,
                    billing_country,
                    billing_city,
                    payment_method
                )
                print(f"[Orchestrator] Fraud detection final result: {fraud_detection_result}")
            except Exception as e:
                errors.append(f"Fraud detection error: {str(e)}")

        # 4) Execute concurrency
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures_list = []
            futures_list.append(executor.submit(verify_transaction_worker))
            futures_list.append(executor.submit(suggestions_worker))
            futures_list.append(executor.submit(fraud_detection_worker))

            for future in as_completed(futures_list):
                pass

        # If any error was appended
        if errors:
            # We can reject or handle partial errors
            return jsonify({
                "error": {
                    "code": "ORDER_REJECTED",
                    "message": " / ".join(errors)
                }
            }), 400

        # 5) Evaluate Fraud
        if fraud_detection_result is None:
            return jsonify({"error": {"code": "ORDER_REJECTED","message": "Fraud detection not completed"}}), 400

        if fraud_detection_result.get("action", "APPROVE") == "REJECT":
            reasons_list = fraud_detection_result.get("reasons", ["Fraudulent transaction"])
            joined_reasons = ", ".join(reasons_list)
            return jsonify({
                "error": {
                    "code": "ORDER_REJECTED",
                    "message": joined_reasons
                }
            }), 400

        # 6) Evaluate Transaction
        if not (verification_result and verification_result.get("isValid", False)):
            return jsonify({
                "error": {
                    "code": "ORDER_REJECTED",
                    "message": verification_result.get("reason", "Error verifying transaction")
                }
            }), 400

        # 7) If all pass => Approved
        response = {
            "orderId": order_id,
            "status": "Order Approved",
            "suggestedBooks": suggestions_result
        }
        return jsonify(OrderStatusResponseSchema().dump(response))

    except ValidationError as err:
        return jsonify({
            "error": {
                "code": "ORDER_REJECTED",
                "message": ", ".join(
                    f"{field}: {msg}"
                    for field, messages in err.messages.items()
                    for msg in messages
                )
            }
        }), 400

    except Exception as e:
        print(e)
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An internal error occurred"
            }
        }), 500
