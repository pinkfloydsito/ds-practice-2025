import os
import sys
import time
import uuid
import random
import threading
import grpc
from concurrent import futures
from typing import Dict, Any, Optional

# Add protocol buffer path
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
PROTO_DIR = os.path.abspath(os.path.join(FILE, "../../../utils/pb/payment_service"))
sys.path.insert(0, PROTO_DIR)

try:
    import payment_service_pb2 as payment_pb2
    import payment_service_pb2_grpc as payment_pb2_grpc
except ImportError as e:
    print(f"Failed to import payment protobuf modules: {e}")
    print(f"Make sure protobuf definitions are at: {PROTO_DIR}")
    sys.exit(1)

# Default port
DEFAULT_PORT = 50053


class PaymentService(payment_pb2_grpc.PaymentServiceServicer):
    """Implementation of the Payment Service."""

    def __init__(self):
        """Initialize the payment service."""
        # Track transactions
        self.transactions = {}
        self._transaction_lock = threading.RLock()

    def Prepare(self, request, context):
        """
        Prepare phase of 2PC - check if payment can be processed.
        """
        transaction_id = request.transaction_id
        amount = request.amount
        payment_method = request.payment_method
        customer_id = request.customer_id

        print(f"Preparing payment for transaction {transaction_id}: {amount}")

        # Create transaction record
        payment_id = str(uuid.uuid4())
        with self._transaction_lock:
            self.transactions[transaction_id] = {
                "payment_id": payment_id,
                "status": "PREPARING",
                "amount": amount,
                "payment_method": payment_method,
                "customer_id": customer_id,
                "start_time": time.time(),
                "metadata": {k: v for k, v in request.metadata.items()},
            }

        # Simulate payment validation
        if payment_method == "Credit Card":
            # 95% success rate
            can_commit = random.random() < 0.95
        elif payment_method == "Bank Transfer":
            # 90% success rate
            can_commit = random.random() < 0.90
        else:
            # Unknown payment method
            can_commit = False

        # Update transaction status
        with self._transaction_lock:
            if transaction_id in self.transactions:
                if can_commit:
                    self.transactions[transaction_id]["status"] = "PREPARED"
                else:
                    self.transactions[transaction_id]["status"] = "FAILED"
                    self.transactions[transaction_id]["error"] = (
                        "Payment validation failed"
                    )

        if can_commit:
            return payment_pb2.PrepareResponse(can_commit=True, payment_id=payment_id)
        else:
            return payment_pb2.PrepareResponse(
                can_commit=False, error_message="Payment validation failed"
            )

    def Commit(self, request, context):
        """
        Commit phase of 2PC - process the payment.
        """
        transaction_id = request.transaction_id
        payment_id = request.payment_id

        # Check if transaction exists
        with self._transaction_lock:
            if transaction_id not in self.transactions:
                return payment_pb2.CommitResponse(
                    success=False, error_message="Transaction not found"
                )

            transaction = self.transactions[transaction_id]

            # Verify payment ID
            if transaction["payment_id"] != payment_id:
                return payment_pb2.CommitResponse(
                    success=False, error_message="Invalid payment ID"
                )

            # Check if transaction is in PREPARED state
            if transaction["status"] != "PREPARED":
                return payment_pb2.CommitResponse(
                    success=False,
                    error_message=f"Transaction not in PREPARED state: {transaction['status']}",
                )

            # Update status
            transaction["status"] = "COMMITTING"

        print(f"Committing payment for transaction {transaction_id}")

        # Simulate payment processing
        # 98% success rate
        success = random.random() < 0.0001

        # TODO: check this
        # success = True
        # Update transaction status
        with self._transaction_lock:
            if transaction_id in self.transactions:
                if success:
                    self.transactions[transaction_id]["status"] = "COMMITTED"
                    self.transactions[transaction_id]["confirmation_code"] = (
                        f"PAY-{uuid.uuid4().hex[:8].upper()}"
                    )
                    self.transactions[transaction_id]["commit_time"] = time.time()
                else:
                    self.transactions[transaction_id]["status"] = "FAILED"
                    self.transactions[transaction_id]["error"] = (
                        "Payment processing failed"
                    )

        if success:
            # Get transaction details
            with self._transaction_lock:
                transaction = self.transactions[transaction_id]

                # Create payment result
                payment_result = payment_pb2.PaymentResult(
                    payment_id=payment_id,
                    amount=transaction["amount"],
                    payment_method=transaction["payment_method"],
                    status="COMPLETED",
                    confirmation_code=transaction["confirmation_code"],
                    timestamp=int(transaction["commit_time"]),
                )

                return payment_pb2.CommitResponse(
                    success=True, payment_result=payment_result
                )
        else:
            return payment_pb2.CommitResponse(
                success=False, error_message="Payment processing failed"
            )

    def Abort(self, request, context):
        """
        Abort the payment transaction.
        """
        transaction_id = request.transaction_id
        reason = request.reason

        print(f"Aborting payment for transaction {transaction_id}: {reason}")

        # Update transaction status
        with self._transaction_lock:
            if transaction_id in self.transactions:
                self.transactions[transaction_id]["status"] = "ABORTED"
                self.transactions[transaction_id]["abort_reason"] = reason
                self.transactions[transaction_id]["abort_time"] = time.time()

                return payment_pb2.AbortResponse(
                    success=True, message=f"Transaction {transaction_id} aborted"
                )
            else:
                return payment_pb2.AbortResponse(
                    success=False, message=f"Transaction {transaction_id} not found"
                )

    def GetStatus(self, request, context):
        """
        Get the status of a payment transaction.
        """
        transaction_id = request.transaction_id

        # Get transaction status
        with self._transaction_lock:
            if transaction_id in self.transactions:
                transaction = self.transactions[transaction_id]

                response = payment_pb2.StatusResponse(
                    transaction_id=transaction_id,
                    status=transaction["status"],
                    payment_id=transaction["payment_id"],
                    amount=transaction["amount"],
                    payment_method=transaction["payment_method"],
                    last_updated=int(time.time()),
                )

                if "error" in transaction:
                    response.error_message = transaction["error"]

                return response
            else:
                return payment_pb2.StatusResponse(
                    transaction_id=transaction_id,
                    status="NOT_FOUND",
                    last_updated=int(time.time()),
                )


def serve():
    """Start the payment service server."""
    # Get port from environment or use default
    port = int(os.getenv("PAYMENT_PORT", DEFAULT_PORT))
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    payment_pb2_grpc.add_PaymentServiceServicer_to_server(PaymentService(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"Payment service started on port {port}")

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("Payment service shutting down...")
        server.stop(0)


if __name__ == "__main__":
    serve()
