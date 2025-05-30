import os
import sys
import time
import uuid
import random
import threading
import grpc
from concurrent import futures
from typing import Dict, Any, Optional

# protobuff imports
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
PROTO_DIR = os.path.abspath(os.path.join(FILE, "../../../utils/pb/payment_service"))
sys.path.insert(0, PROTO_DIR)

try:
    import payment_service_pb2 as payment_pb2
    import payment_service_pb2_grpc as payment_pb2_grpc
except ImportError as e:
    print(f"Failed to import payment protobuf modules: {e}")
    sys.exit(1)

# --- OpenTelemetry setup ---
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

OTEL_EXPORTER_ENDPOINT = "http://otel-collector:4318"
resource = Resource.create(attributes={"service.name": "payment"})

# Tracing setup
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)
span_processor = BatchSpanProcessor(
    OTLPSpanExporter(endpoint=f"{OTEL_EXPORTER_ENDPOINT}/v1/traces")
)
trace.get_tracer_provider().add_span_processor(span_processor)

# Metrics setup
metrics.set_meter_provider(
    MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{OTEL_EXPORTER_ENDPOINT}/v1/metrics")
            )
        ],
    )
)
meter = metrics.get_meter(__name__)
payment_counter = meter.create_counter(
    name="payment_transactions_total",
    unit="1",
    description="Number of payment transactions processed",
)

DEFAULT_PORT = 50053


class PaymentService(payment_pb2_grpc.PaymentServiceServicer):
    def __init__(self):
        self.transactions = {}
        self._transaction_lock = threading.RLock()

    def Prepare(self, request, context):
        with tracer.start_as_current_span("payment.prepare"):
            transaction_id = request.transaction_id
            amount = request.amount
            payment_method = request.payment_method
            customer_id = request.customer_id

            print(
                f"[Payment] Preparing payment for transaction {transaction_id}: ${amount}"
            )

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

            # Simulate payment validation (95% success rate for demo)
            can_commit = random.random() < 0.95

            with self._transaction_lock:
                if can_commit:
                    self.transactions[transaction_id]["status"] = "PREPARED"
                    print(
                        f"[Payment] Transaction {transaction_id} prepared successfully"
                    )
                else:
                    self.transactions[transaction_id]["status"] = "FAILED"
                    self.transactions[transaction_id]["error"] = (
                        "Payment validation failed"
                    )
                    print(f"[Payment] Transaction {transaction_id} preparation failed")

            if can_commit:
                return payment_pb2.PrepareResponse(
                    can_commit=True, payment_id=payment_id
                )
            else:
                return payment_pb2.PrepareResponse(
                    can_commit=False, error_message="Payment validation failed"
                )

    def Commit(self, request, context):
        """FIXED: Remove duplicate logic and race condition"""
        with tracer.start_as_current_span("payment.commit"):
            transaction_id = request.transaction_id
            payment_id = request.payment_id

            print(f"[Payment] Committing transaction {transaction_id}")

            # Check if transaction exists and validate state
            with self._transaction_lock:
                if transaction_id not in self.transactions:
                    print(f"[Payment] Transaction {transaction_id} not found")
                    return payment_pb2.CommitResponse(
                        success=False, error_message="Transaction not found"
                    )

                transaction = self.transactions[transaction_id]

                # Verify payment ID matches
                if transaction["payment_id"] != payment_id:
                    print(
                        f"[Payment] Invalid payment ID for transaction {transaction_id}"
                    )
                    return payment_pb2.CommitResponse(
                        success=False, error_message="Invalid payment ID"
                    )

                # Check if transaction is in PREPARED state
                if transaction["status"] != "PREPARED":
                    error_msg = (
                        f"Transaction not in PREPARED state: {transaction['status']}"
                    )
                    print(f"[Payment] {error_msg} for transaction {transaction_id}")
                    return payment_pb2.CommitResponse(
                        success=False, error_message=error_msg
                    )

                # Update status to COMMITTING to prevent double processing
                transaction["status"] = "COMMITTING"
                print(
                    f"[Payment] Transaction {transaction_id} status set to COMMITTING"
                )

            # Simulate payment processing (98% success rate for demo)
            success = random.random() < 0.98
            payment_counter.add(1, {"status": "committed" if success else "failed"})

            # Update final transaction status
            with self._transaction_lock:
                if transaction_id in self.transactions:
                    if success:
                        self.transactions[transaction_id]["status"] = "COMMITTED"
                        self.transactions[transaction_id]["confirmation_code"] = (
                            f"PAY-{uuid.uuid4().hex[:8].upper()}"
                        )
                        self.transactions[transaction_id]["commit_time"] = time.time()
                        print(
                            f"[Payment] Transaction {transaction_id} committed successfully"
                        )
                    else:
                        self.transactions[transaction_id]["status"] = "FAILED"
                        self.transactions[transaction_id]["error"] = (
                            "Payment processing failed"
                        )
                        print(f"[Payment] Transaction {transaction_id} commit failed")

            if success:
                # Return successful payment result
                with self._transaction_lock:
                    transaction = self.transactions[transaction_id]
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
        with tracer.start_as_current_span("payment.abort"):
            transaction_id = request.transaction_id
            reason = request.reason

            print(f"[Payment] Aborting transaction {transaction_id}: {reason}")

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
        with tracer.start_as_current_span("payment.status"):
            transaction_id = request.transaction_id

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
