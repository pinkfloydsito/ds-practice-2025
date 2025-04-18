import sys
import os
import grpc

from typing import Dict

from utils.grpc_config import GrpcConfig
from google.protobuf.json_format import MessageToDict

config = GrpcConfig()
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
config.init_paths(FILE)
config.setup_paths()

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")

models_path = os.path.abspath(os.path.join(FILE, "../../../../../../utils/models"))
sys.path.insert(0, models_path)

import fraud_detection_pb2 as fraud_pb2
import fraud_detection_pb2_grpc as fraud_pb2_grpc

from bookstore_models import ServiceResult, OrderInfo, UserInfo, BillingInfo


class FraudService:
    """Client for the fraud detection service."""

    def __init__(self, grpc_factory, order_event_tracker):
        self.grpc_factory = grpc_factory
        self.order_event_tracker = order_event_tracker

    def initialize_order(
        self, order: OrderInfo, user: UserInfo, billing: BillingInfo
    ) -> bool:
        """Initialize a fraud detection order."""
        try:
            stub = self.grpc_factory.get_stub(
                "fraud_detection",
                fraud_pb2_grpc.FraudDetectionServiceStub,
                secure=False,
            )

            current_clock = self.order_event_tracker.get_clock(
                order.order_id, "orchestrator"
            )

            request = fraud_pb2.FraudInitRequest(
                order_id=order.order_id,
                amount=order.amount,
                ip_address=user.ip_address,
                email=user.email,
                billing_country=billing.country,
                billing_city=billing.city,
                payment_method=order.payment_method,
                vectorClock=current_clock,
            )
            response = stub.InitializeOrder(request)
            self._record_vector_clock(order.order_id, response.vectorClock)

            print(
                f"[Orchestrator] initialize_fraud_order => success={response.success}"
            )
            return response.success
        except grpc.RpcError as e:
            print(f"gRPC error in initialize_fraud_order: {e.code()}: {e.details()}")
            return False

    def check_fraud(
        self, order: OrderInfo, user: UserInfo, billing: BillingInfo
    ) -> ServiceResult:
        """Check for fraud."""
        result = ServiceResult()
        try:
            stub = self.grpc_factory.get_stub(
                "fraud_detection",
                fraud_pb2_grpc.FraudDetectionServiceStub,
                secure=False,
            )

            current_clock = self.order_event_tracker.get_clock(
                order.order_id, "orchestrator"
            )

            request = fraud_pb2.FraudRequest(
                order_id=order.order_id,
                amount=order.amount,
                ip_address=user.ip_address,
                email=user.email,
                billing_country=billing.country,
                billing_city=billing.city,
                payment_method=order.payment_method,
                vectorClock=current_clock,
            )
            response = stub.CheckFraud(request)

            self._record_vector_clock(order.order_id, response.vectorClock)

            result.data = MessageToDict(
                response,
                preserving_proto_field_name=True,
                always_print_fields_with_no_presence=True,
            )

            action = result.data.get("action", "APPROVE")
            result.success = action == "APPROVE"

            if not result.success:
                reasons_list = result.data.get("reasons", ["Fraudulent transaction"])
                result.error = ", ".join(reasons_list)

            return result
        except grpc.RpcError as e:
            print(f"gRPC error (check_fraud): {e.code()}: {e.details()}")
            result.error = f"Fraud service error: {e.details()}"
            return result

    def _record_vector_clock(self, order_id, clock):
        self.order_event_tracker.record_event(
            order_id=order_id,
            service="orchestrator",
            event_name="transaction_verified",
            received_clock=dict(clock),
        )

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
                "fraud_detection",
                fraud_pb2_grpc.FraudDetectionServiceStub,
                secure=False,
            )

            # Call the ClearOrder method on the gRPC service
            response = stub.ClearOrder(
                fraud_pb2.ClearOrderRequest(
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
