import sys
import os
import grpc

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

    def __init__(self, grpc_factory):
        self.grpc_factory = grpc_factory

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
            request = fraud_pb2.FraudInitRequest(
                order_id=order.order_id,
                amount=order.amount,
                ip_address=user.ip_address,
                email=user.email,
                billing_country=billing.country,
                billing_city=billing.city,
                payment_method=order.payment_method,
            )
            response = stub.InitializeOrder(request)
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
            request = fraud_pb2.FraudRequest(
                order_id=order.order_id,
                amount=order.amount,
                ip_address=user.ip_address,
                email=user.email,
                billing_country=billing.country,
                billing_city=billing.city,
                payment_method=order.payment_method,
            )
            response = stub.CheckFraud(request)
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
