import sys
import os
import grpc

from utils.grpc_config import GrpcConfig
from google.protobuf.json_format import MessageToDict
from typing import Dict

config = GrpcConfig()
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
config.init_paths(FILE)
config.setup_paths()

models_path = os.path.abspath(os.path.join(FILE, "../../../../../../utils/models"))
sys.path.insert(0, models_path)

import transaction_verification_pb2 as transaction_verification
import transaction_verification_pb2_grpc as transaction_verification_grpc

from bookstore_models import CreditCardInfo, BillingInfo, ServiceResult


class TransactionService:
    """Client for the transaction verification service."""

    def __init__(self, grpc_factory, order_event_tracker):
        self.grpc_factory = grpc_factory
        self.event_tracker = order_event_tracker

    def initialize_order(
        self, order_id: str, credit_card: CreditCardInfo, billing: BillingInfo
    ) -> bool:
        """Initialize a transaction order."""
        try:
            stub = self.grpc_factory.get_stub(
                "transaction_verification",
                transaction_verification_grpc.TransactionVerificationServiceStub,
                secure=False,
            )

            current_clock = self.event_tracker.get_clock(
                order_id,
                "orchestrator",
            )
            request = transaction_verification.TransactionInitRequest(
                order_id=order_id,
                creditCardNumber=credit_card.number,
                expiryDate=credit_card.expiry_date,
                billingCity=billing.city,
                billingCountry=billing.country,
                vectorClock=current_clock,
            )
            response = stub.InitializeOrder(request)

            self.event_tracker.record_event(
                order_id=order_id,
                service="orchestrator",
                event_name="transaction_service.InitializeOrder",
                received_clock=response.vectorClock,
            )

            print(
                f"[Orchestrator] initialize_transaction_order => success={response.success}"
            )

            return response.success
        except grpc.RpcError as e:
            print(
                f"gRPC error in initialize_transaction_order: {e.code()}: {e.details()}"
            )
            return False

    def verify_transaction(
        self, order_id: str, credit_card: CreditCardInfo, billing: BillingInfo
    ) -> ServiceResult:
        """Verify a transaction."""
        result = ServiceResult()
        try:
            stub = self.grpc_factory.get_stub(
                "transaction_verification",
                transaction_verification_grpc.TransactionVerificationServiceStub,
                secure=False,
            )

            current_clock = self.event_tracker.get_clock(
                order_id,
                "orchestrator",
            )

            request = transaction_verification.TransactionRequest(
                order_id=order_id,
                creditCardNumber=credit_card.number,
                expiryDate=credit_card.expiry_date,
                billingCity=billing.city,
                billingCountry=billing.country,
                vectorClock=current_clock,
            )

            response = stub.VerifyTransaction(request)

            self.event_tracker.record_event(
                order_id=order_id,
                service="orchestrator",
                event_name="transaction_service.InitializeOrder",
                received_clock=response.vectorClock,
            )

            result.data = MessageToDict(response)
            result.success = result.data.get("isValid", False)
            if not result.success:
                result.error = result.data.get("reason", "Unknown transaction error")
            return result
        except grpc.RpcError as e:
            print(f"gRPC error (verify_transaction): {e.code()}: {e.details()}")
            result.error = f"Transaction service error: {e.details()}"
            return result

    def clear_order_data(
        self, order_id: str, final_vector_clock: Dict[str, int]
    ) -> bool:
        """
        Clear the order data if the local vector clock is <= final_vector_clock.

        Args:
            order_id: The order ID to clear
            final_vector_clock: The final vector clock from the orchestrator

        Returns:
            bool: True if cleared successfully, False otherwise
        """
        try:
            stub = self.grpc_factory.get_stub(
                "transaction_verification",
                transaction_verification_grpc.TransactionVerificationServiceStub,
                secure=False,
            )

            # Call the ClearOrder method on the gRPC service
            response = stub.ClearOrder(
                transaction_verification.ClearOrderRequest(
                    order_id=order_id, vectorClock=final_vector_clock
                )
            )

            # Verify the response
            if not response or not response.success:
                error_msg = response.error if response else "Unknown error"
                print(f"Failed to clear order data: {error_msg}")
                return False

            print(f"Successfully cleared order data for order {order_id}")
            return True

        except Exception as e:
            print(f"[Orchestrator] Error clearing order data: {str(e)}")
            return False
