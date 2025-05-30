import json
import os
import sys
import time
import uuid
import grpc
import traceback
import threading
from typing import Dict, List, Any, Optional, Tuple

from opentelemetry import trace, metrics
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

#
# Setup OpenTelemetry
resource = Resource.create(attributes={"service.name": "order-executor-2pc"})
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://observability:4318/v1/traces"))
)

reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint="http://observability:4318/v1/metrics")
)
metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
meter = metrics.get_meter(__name__)

# Order processing metrics
orders_started_2pc = meter.create_counter(
    "order_executor_orders_started_total",
    description="Total orders started in 2PC",
    unit="1",
)

orders_completed_2pc = meter.create_counter(
    "order_executor_orders_completed_total",
    description="Total orders completed successfully in 2PC",
    unit="1",
)

orders_failed_2pc = meter.create_counter(
    "order_executor_orders_failed_total",
    description="Total orders that failed in 2PC",
    unit="1",
)

order_2pc_duration = meter.create_histogram(
    "order_executor_processing_duration_seconds",
    description="Time taken to process orders in 2PC",
    unit="s",
)

payment_operations = meter.create_histogram(
    "order_executor_payment_duration_seconds",
    description="Payment operation durations",
    unit="s",
)

stock_operations = meter.create_histogram(
    "order_executor_stock_duration_seconds",
    description="Stock operation durations",
    unit="s",
)


FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
DB_PROTO_DIR = os.path.abspath(os.path.join(FILE, "../../../utils/pb/db_node"))
PAYMENT_PROTO_DIR = os.path.abspath(
    os.path.join(FILE, "../../../utils/pb/payment_service")
)
sys.path.insert(0, DB_PROTO_DIR)
sys.path.insert(0, PAYMENT_PROTO_DIR)

try:
    import db_node_pb2
    import db_node_pb2_grpc
    import payment_service_pb2 as payment_pb2
    import payment_service_pb2_grpc as payment_pb2_grpc
except ImportError as e:
    print(f"Failed to import protobuf modules: {e}")
    print(
        f"Make sure protobuf definitions are at: {DB_PROTO_DIR} and {PAYMENT_PROTO_DIR}"
    )
    sys.exit(1)


class TwoPhaseCommitCoordinator:
    """
    Coordinator for distributed transactions using Two-Phase Commit (2PC).
    """

    def __init__(self, db_nodes: List[str], payment_service: str):
        """
        Initialize the 2PC coordinator.

        Args:
            db_nodes: List of database node addresses
            payment_service: Payment service address
        """
        self.db_nodes = db_nodes
        self.payment_service = payment_service

        # Track transactions
        self.transactions = {}
        self._transaction_lock = threading.RLock()

        # Timeouts and retries
        self.timeout = 5
        self.max_retries = 3

        # Track primary database node
        self._primary_node = None
        self._primary_lock = threading.RLock()

    def _get_primary_db_node(self) -> Optional[str]:
        """
        Get the primary database node.

        Returns:
            Primary node address or None if not found
        """
        # Return cached primary if available
        with self._primary_lock:
            if self._primary_node:
                return self._primary_node

        # Try to find primary by querying nodes
        for node in self.db_nodes:
            try:
                with grpc.insecure_channel(node) as channel:
                    stub = db_node_pb2_grpc.DatabaseStub(channel)
                    response = stub.GetStatus(
                        db_node_pb2.StatusRequest(), timeout=self.timeout
                    )

                    if response.role.lower() == "primary":
                        with self._primary_lock:
                            self._primary_node = node
                        return node
            except grpc.RpcError:
                continue

        return None

    def execute_order(
        self, order_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Execute an order using 2PC with comprehensive order tracking."""

        transaction_id = self._generate_transaction_id()
        order_id = order_data.get("order_id", "unknown")

        with tracer.start_as_current_span("2pc.execute_order") as main_span:
            # Set comprehensive order tracking attributes
            main_span.set_attribute("order.id", order_id)
            main_span.set_attribute("transaction.id", transaction_id)
            main_span.set_attribute(
                "order.customer", order_data.get("user", {}).get("name", "unknown")
            )
            main_span.set_attribute("order.amount", order_data.get("amount", 0))
            main_span.set_attribute(
                "order.items_count", len(order_data.get("book_tokens", []))
            )

            # Add individual book items as span attributes
            for i, item in enumerate(order_data.get("book_tokens", [])):
                main_span.set_attribute(f"order.item.{i}.name", item)

            start_time = time.time()
            orders_started_2pc.add(1, {"customer_type": "regular"})

            print(f"[2PC] Starting transaction {transaction_id} for order {order_id}")

            # Initialize transaction record
            with self._transaction_lock:
                self.transactions[transaction_id] = {
                    "id": transaction_id,
                    "status": "STARTED",
                    "order_id": order_id,
                    "order_data": order_data,
                    "start_time": start_time,
                    "participants": ["database", "payment"],
                    "phase1_results": {},
                    "phase2_results": {},
                }

                # Create initial order record
                with tracer.start_as_current_span(
                    "2pc.create_order_record"
                ) as create_span:
                    create_span.set_attribute("order.id", order_id)
                    create_span.set_attribute("order.initial_status", "PROCESSING")

                    success, error = self._create_order_in_db(
                        transaction_id, order_data, "PROCESSING"
                    )
                    create_span.set_attribute("order.creation_success", success)

                    if not success:
                        create_span.set_status(Status(StatusCode.ERROR, error))
                        main_span.set_status(
                            Status(StatusCode.ERROR, f"Order creation failed: {error}")
                        )
                        self._global_abort(transaction_id, error)
                        orders_failed_2pc.add(1, {"reason": "order_creation_failed"})
                        return (
                            False,
                            error,
                            {"transaction_id": transaction_id, "status": "FAILED"},
                        )

            try:
                # Phase 1: Prepare with comprehensive tracking
                with tracer.start_as_current_span("2pc.phase1_prepare") as phase1_span:
                    phase1_span.set_attribute("transaction.id", transaction_id)
                    phase1_span.set_attribute("order.id", order_id)
                    phase1_span.set_attribute("phase", "1_prepare")

                    phase1_start = time.time()
                    phase1_success, phase1_error, prepare_data = self._phase1_prepare(
                        transaction_id
                    )
                    phase1_duration = time.time() - phase1_start

                    phase1_span.set_attribute(
                        "phase1.duration_seconds", phase1_duration
                    )
                    phase1_span.set_attribute("phase1.success", phase1_success)

                    if not phase1_success:
                        phase1_span.set_status(Status(StatusCode.ERROR, phase1_error))
                        main_span.set_status(
                            Status(StatusCode.ERROR, f"Phase 1 failed: {phase1_error}")
                        )
                        self._global_abort(
                            transaction_id, phase1_error or "Prepare phase failed"
                        )
                        orders_failed_2pc.add(1, {"reason": "phase1_failed"})
                        return (
                            False,
                            phase1_error,
                            {"transaction_id": transaction_id, "status": "ABORTED"},
                        )

                # Phase 2: Commit with comprehensive tracking
                with tracer.start_as_current_span("2pc.phase2_commit") as phase2_span:
                    phase2_span.set_attribute("transaction.id", transaction_id)
                    phase2_span.set_attribute("order.id", order_id)
                    phase2_span.set_attribute("phase", "2_commit")

                    phase2_start = time.time()
                    phase2_success, phase2_error, result = self._phase2_commit(
                        transaction_id, prepare_data
                    )
                    phase2_duration = time.time() - phase2_start

                    phase2_span.set_attribute(
                        "phase2.duration_seconds", phase2_duration
                    )
                    phase2_span.set_attribute("phase2.success", phase2_success)

                    if not phase2_success:
                        phase2_span.set_status(Status(StatusCode.ERROR, phase2_error))
                        main_span.set_status(
                            Status(StatusCode.ERROR, f"Phase 2 failed: {phase2_error}")
                        )
                        self._global_abort(
                            transaction_id, phase2_error or "Commit phase failed"
                        )
                        orders_failed_2pc.add(1, {"reason": "phase2_failed"})
                        return (
                            False,
                            phase2_error,
                            {"transaction_id": transaction_id, "status": "ABORTED"},
                        )

                # Success - update transaction status
                with self._transaction_lock:
                    if transaction_id in self.transactions:
                        self.transactions[transaction_id]["status"] = "COMMITTED"
                        self.transactions[transaction_id]["end_time"] = time.time()

                # Record comprehensive success metrics and span attributes
                total_duration = time.time() - start_time
                order_2pc_duration.record(total_duration, {"status": "completed"})
                orders_completed_2pc.add(1, {"customer_type": "regular"})

                main_span.set_attribute("order.final_status", "COMPLETED")
                main_span.set_attribute("order.total_duration_seconds", total_duration)
                main_span.set_attribute("transaction.status", "COMMITTED")

                # Add result details to span
                if isinstance(result, dict):
                    main_span.set_attribute(
                        "result.transaction_id", result.get("transaction_id", "unknown")
                    )
                    main_span.set_attribute(
                        "result.status", result.get("status", "unknown")
                    )

                    # Add payment and database commit details
                    if "commit_results" in result:
                        commit_results = result["commit_results"]
                        if "payment" in commit_results:
                            payment_info = commit_results["payment"]
                            main_span.set_attribute(
                                "result.payment_id",
                                payment_info.get("payment_id", "unknown"),
                            )
                            main_span.set_attribute(
                                "result.payment_amount", payment_info.get("amount", 0)
                            )
                            main_span.set_attribute(
                                "result.confirmation_code",
                                payment_info.get("confirmation_code", "unknown"),
                            )

                        if (
                            "database" in commit_results
                            and "updated_stock" in commit_results["database"]
                        ):
                            stock_updates = len(
                                commit_results["database"]["updated_stock"]
                            )
                            main_span.set_attribute(
                                "result.stock_updates_count", stock_updates
                            )

                main_span.set_status(Status(StatusCode.OK))
                print(
                    f"[2PC] Order {order_id} completed successfully in {total_duration:.2f}s"
                )
                return True, None, result

            except Exception as e:
                error_msg = f"Transaction {transaction_id} failed with error: {str(e)}"
                print(error_msg)
                traceback.print_exc()

                main_span.record_exception(e)
                main_span.set_status(Status(StatusCode.ERROR, error_msg))

                total_duration = time.time() - start_time
                order_2pc_duration.record(total_duration, {"status": "failed"})
                orders_failed_2pc.add(1, {"reason": "exception"})

                self._global_abort(transaction_id, error_msg)
                return (
                    False,
                    error_msg,
                    {"transaction_id": transaction_id, "status": "ABORTED"},
                )

    def _phase1_prepare(
        self, transaction_id: str
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Phase 1 preparation with detailed tracking."""

        with self._transaction_lock:
            if transaction_id not in self.transactions:
                return False, "Transaction not found", {}
            self.transactions[transaction_id]["status"] = "PREPARING"
            order_data = self.transactions[transaction_id]["order_data"]

        print(f"[2PC] Phase 1 (Prepare) for transaction {transaction_id}")
        prepare_data = {}

        # Database preparation with detailed tracking
        with tracer.start_as_current_span("2pc.prepare_database") as db_span:
            db_span.set_attribute("transaction.id", transaction_id)
            db_span.set_attribute("operation", "stock_validation")

            db_start = time.time()
            db_can_commit, db_error, db_prepare_data = self._prepare_database(
                transaction_id, order_data
            )
            db_duration = time.time() - db_start

            stock_operations.record(
                db_duration, {"operation": "prepare", "success": str(db_can_commit)}
            )
            db_span.set_attribute("database.duration_seconds", db_duration)
            db_span.set_attribute("database.can_commit", db_can_commit)

            if not db_can_commit:
                db_span.set_status(Status(StatusCode.ERROR, db_error))
                return False, f"Database prepare failed: {db_error}", {}

            if db_prepare_data and "stock_checks" in db_prepare_data:
                db_span.set_attribute(
                    "database.books_validated", len(db_prepare_data["stock_checks"])
                )

            prepare_data["database"] = db_prepare_data

        # Payment preparation with detailed tracking
        with tracer.start_as_current_span("2pc.prepare_payment") as payment_span:
            payment_span.set_attribute("transaction.id", transaction_id)
            payment_span.set_attribute("operation", "payment_authorization")

            payment_start = time.time()
            payment_can_commit, payment_error, payment_prepare_data = (
                self._prepare_payment(transaction_id, order_data)
            )
            payment_duration = time.time() - payment_start

            payment_operations.record(
                payment_duration,
                {"operation": "prepare", "success": str(payment_can_commit)},
            )
            payment_span.set_attribute("payment.duration_seconds", payment_duration)
            payment_span.set_attribute("payment.can_commit", payment_can_commit)

            if not payment_can_commit:
                payment_span.set_status(Status(StatusCode.ERROR, payment_error))
                return False, f"Payment prepare failed: {payment_error}", {}

            if payment_prepare_data:
                payment_span.set_attribute(
                    "payment.payment_id",
                    payment_prepare_data.get("payment_id", "unknown"),
                )
                payment_span.set_attribute(
                    "payment.amount", payment_prepare_data.get("amount", 0)
                )

            prepare_data["payment"] = payment_prepare_data

        return True, None, prepare_data

    def _phase2_commit(
        self, transaction_id: str, prepare_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Phase 2 commit with detailed tracking."""

        with self._transaction_lock:
            if transaction_id not in self.transactions:
                return False, "Transaction not found", {}
            self.transactions[transaction_id]["status"] = "COMMITTING"
            order_data = self.transactions[transaction_id]["order_data"]

        print(f"[2PC] Phase 2 (Commit) for transaction {transaction_id}")

        result = {
            "transaction_id": transaction_id,
            "order_id": order_data.get("order_id", "unknown"),
            "status": "PROCESSING",
            "items": order_data.get("book_tokens", []),
            "commit_results": {},
        }

        # Commit payment first with tracking
        with tracer.start_as_current_span("2pc.commit_payment") as payment_span:
            payment_span.set_attribute("transaction.id", transaction_id)
            payment_span.set_attribute("operation", "payment_processing")

            payment_start = time.time()
            payment_commit_success, payment_error, payment_result = (
                self._commit_payment(transaction_id, prepare_data.get("payment", {}))
            )
            payment_duration = time.time() - payment_start

            payment_operations.record(
                payment_duration,
                {"operation": "commit", "success": str(payment_commit_success)},
            )
            payment_span.set_attribute("payment.duration_seconds", payment_duration)
            payment_span.set_attribute("payment.success", payment_commit_success)

            if not payment_commit_success:
                payment_span.set_status(Status(StatusCode.ERROR, payment_error))
                return False, f"Payment commit failed: {payment_error}", {}

            if payment_result:
                payment_span.set_attribute(
                    "payment.confirmation_code",
                    payment_result.get("confirmation_code", "unknown"),
                )
                payment_span.set_attribute(
                    "payment.amount_processed", payment_result.get("amount", 0)
                )

            result["commit_results"]["payment"] = payment_result

        # Commit database changes with tracking
        with tracer.start_as_current_span("2pc.commit_database") as db_span:
            db_span.set_attribute("transaction.id", transaction_id)
            db_span.set_attribute("operation", "stock_update")

            db_start = time.time()
            db_commit_success, db_error, db_result = self._commit_database(
                transaction_id, prepare_data.get("database", {})
            )
            db_duration = time.time() - db_start

            stock_operations.record(
                db_duration, {"operation": "commit", "success": str(db_commit_success)}
            )
            db_span.set_attribute("database.duration_seconds", db_duration)
            db_span.set_attribute("database.success", db_commit_success)

            if not db_commit_success:
                db_span.set_status(Status(StatusCode.ERROR, db_error))
                # Database commit failed - would need compensation in production
                print(f"[2PC] Database commit failed - compensation needed")
                return False, f"Database commit failed: {db_error}", {}

            if db_result and "updated_stock" in db_result:
                db_span.set_attribute(
                    "database.stock_updates", len(db_result["updated_stock"])
                )

            result["commit_results"]["database"] = db_result

        # Both commits succeeded - finalize order
        if db_commit_success and payment_commit_success:
            with tracer.start_as_current_span("2pc.finalize_order") as finalize_span:
                finalize_span.set_attribute("transaction.id", transaction_id)
                finalize_span.set_attribute("operation", "order_completion")

                order_id = order_data.get("order_id", transaction_id)
                self._update_order_status(order_id, "COMPLETED", payment_result)

                finalize_span.set_attribute("order.final_status", "COMPLETED")

        result["status"] = "COMPLETED"
        return True, None, result

    def _prepare_database(
        self, transaction_id: str, order_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Database preparation with detailed stock validation tracking."""

        items = order_data.get("book_tokens", [])
        if not items:
            return False, "No items in order", {}

        stock_checks = {}
        primary_node = self._get_primary_db_node()

        if not primary_node:
            return False, "No primary database node available", {}

        with tracer.start_as_current_span("2pc.validate_stock") as span:
            span.set_attribute("database.primary_node", primary_node)
            span.set_attribute("items.count", len(items))

            try:
                with grpc.insecure_channel(primary_node) as channel:
                    stub = db_node_pb2_grpc.DatabaseStub(channel)

                    for i, item in enumerate(items):
                        book_name = item
                        quantity = 1  # TODO: get from order data

                        with tracer.start_as_current_span(
                            f"2pc.check_stock.{book_name}"
                        ) as item_span:
                            item_span.set_attribute("book.name", book_name)
                            item_span.set_attribute("book.quantity_requested", quantity)

                            stock_key = f"stock:{book_name}"
                            response = stub.Read(
                                db_node_pb2.ReadRequest(key=stock_key),
                                timeout=self.timeout,
                            )

                            if not response.success:
                                item_span.set_status(
                                    Status(StatusCode.ERROR, "Stock not found")
                                )
                                return (
                                    False,
                                    f"Failed to check stock for {book_name}: Item not found",
                                    {},
                                )

                            try:
                                current_stock = int(float(response.value))
                            except ValueError:
                                item_span.set_status(
                                    Status(StatusCode.ERROR, "Invalid stock value")
                                )
                                return (
                                    False,
                                    f"Invalid stock value for {book_name}: {response.value}",
                                    {},
                                )

                            item_span.set_attribute("book.current_stock", current_stock)
                            item_span.set_attribute(
                                "book.stock_sufficient", current_stock >= quantity
                            )

                            if current_stock < quantity:
                                item_span.set_status(
                                    Status(StatusCode.ERROR, "Insufficient stock")
                                )
                                return (
                                    False,
                                    f"Insufficient stock for {book_name}: {current_stock} available, {quantity} requested",
                                    {},
                                )

                            stock_checks[book_name] = {
                                "current_stock": current_stock,
                                "amount": quantity,
                                "key": stock_key,
                                "version": response.version,
                            }

                # Record prepare result
                with self._transaction_lock:
                    if transaction_id in self.transactions:
                        if "phase1_results" not in self.transactions[transaction_id]:
                            self.transactions[transaction_id]["phase1_results"] = {}
                        self.transactions[transaction_id]["phase1_results"][
                            "database"
                        ] = {
                            "can_commit": True,
                            "stock_checks": stock_checks,
                        }

                span.set_attribute("validation.success", True)
                span.set_attribute("books_validated.count", len(stock_checks))
                return True, None, {"stock_checks": stock_checks}

            except grpc.RpcError as e:
                error_msg = f"Database error during prepare: {e.code()}: {e.details()}"
                span.set_status(Status(StatusCode.ERROR, error_msg))
                return False, error_msg, {}

    def _prepare_payment(
        self, transaction_id: str, order_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Payment preparation with detailed tracking."""

        amount = order_data.get("amount", 0)
        if amount <= 0:
            items = order_data.get("items", [])
            amount = sum(
                item.get("price", 10) * item.get("amount", 1) for item in items
            )

        payment_method = order_data.get("payment_method", "Credit Card")
        customer_id = order_data.get("customer_id", "guest")
        order_id = order_data.get("order_id", transaction_id)

        with tracer.start_as_current_span("2pc.authorize_payment") as span:
            span.set_attribute("payment.amount", amount)
            span.set_attribute("payment.method", payment_method)
            span.set_attribute("payment.customer_id", customer_id)
            span.set_attribute("payment.order_id", order_id)

            metadata = {
                "order_id": order_id,
                "timestamp": str(int(time.time())),
            }

            try:
                with grpc.insecure_channel(self.payment_service) as channel:
                    stub = payment_pb2_grpc.PaymentServiceStub(channel)

                    prepare_request = payment_pb2.PrepareRequest(
                        transaction_id=transaction_id,
                        order_id=order_id,
                        amount=amount,
                        payment_method=payment_method,
                        customer_id=customer_id,
                        metadata=metadata,
                    )

                    response = stub.Prepare(prepare_request, timeout=self.timeout)

                    if not response.can_commit:
                        span.set_status(
                            Status(StatusCode.ERROR, response.error_message)
                        )
                        return False, response.error_message, {}

                    payment_id = response.payment_id
                    span.set_attribute("payment.payment_id", payment_id)
                    span.set_attribute("payment.authorized", True)

                    # Record prepare result
                    with self._transaction_lock:
                        if transaction_id in self.transactions:
                            if (
                                "phase1_results"
                                not in self.transactions[transaction_id]
                            ):
                                self.transactions[transaction_id]["phase1_results"] = {}
                            self.transactions[transaction_id]["phase1_results"][
                                "payment"
                            ] = {
                                "can_commit": True,
                                "payment_id": payment_id,
                                "amount": amount,
                            }

                    return True, None, {"payment_id": payment_id, "amount": amount}

            except grpc.RpcError as e:
                error_msg = (
                    f"Payment service error during prepare: {e.code()}: {e.details()}"
                )
                span.set_status(Status(StatusCode.ERROR, error_msg))
                return False, error_msg, {}

    def _commit_database(
        self, transaction_id: str, prepare_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Database commit with detailed stock operation tracking."""

        stock_checks = prepare_data.get("stock_checks", {})
        if not stock_checks:
            return False, "No stock checks in prepare data", {}

        primary_node = self._get_primary_db_node()
        if not primary_node:
            return False, "No primary database node available", {}

        commit_results = {"updated_stock": {}}

        with tracer.start_as_current_span("2pc.update_stock") as span:
            span.set_attribute("books_to_update.count", len(stock_checks))

            try:
                with grpc.insecure_channel(primary_node) as channel:
                    stub = db_node_pb2_grpc.DatabaseStub(channel)

                    for book_name, check_data in stock_checks.items():
                        with tracer.start_as_current_span(
                            f"2pc.decrement_stock.{book_name}"
                        ) as item_span:
                            stock_key = check_data["key"]
                            quantity = check_data["amount"]

                            item_span.set_attribute("book.name", book_name)
                            item_span.set_attribute(
                                "book.quantity_to_decrement", quantity
                            )

                            response = stub.DecrementStock(
                                db_node_pb2.DecrementRequest(
                                    key=stock_key, amount=quantity
                                ),
                                timeout=self.timeout,
                            )

                            if not response.success:
                                item_span.set_status(
                                    Status(StatusCode.ERROR, response.message)
                                )
                                return (
                                    False,
                                    f"Failed to decrement stock for {book_name}: {response.message}",
                                    {},
                                )

                            item_span.set_attribute(
                                "book.new_stock", response.new_value
                            )
                            commit_results["updated_stock"][book_name] = {
                                "new_stock": response.new_value,
                                "old_stock": check_data["current_stock"],
                                "amount": quantity,
                                "version": response.version,
                                "key": stock_key,
                            }

                    # Update order status
                    with self._transaction_lock:
                        order_data = self.transactions[transaction_id]["order_data"]
                        order_id = order_data.get("order_id", transaction_id)

                    order_key = f"order:{order_id}"
                    order_value = {
                        "order_id": order_id,
                        "status": "PROCESSING",
                        "items": order_data.get("book_tokens", []),
                        "amount": order_data.get("amount", 0),
                        "customer": order_data.get("user", {}).get("name", "unknown"),
                        "timestamp": time.time(),
                        "transaction_id": transaction_id,
                    }

                    response = stub.Write(
                        db_node_pb2.WriteRequest(
                            key=order_key,
                            value=json.dumps(order_value),
                            type=db_node_pb2.WriteRequest.ValueType.JSON,
                        ),
                        timeout=self.timeout,
                    )

                    if not response.success:
                        span.set_status(
                            Status(StatusCode.ERROR, "Failed to store order")
                        )
                        return False, "Failed to store order status", {}

                    commit_results["order_status"] = {
                        "order_id": order_id,
                        "status": "PROCESSING",
                        "version": response.version,
                    }

                    span.set_attribute("database.commit_success", True)
                    return True, None, commit_results

            except grpc.RpcError as e:
                error_msg = f"Database error during commit: {e.code()}: {e.details()}"
                span.set_status(Status(StatusCode.ERROR, error_msg))
                return False, error_msg, {}

    def _commit_payment(
        self, transaction_id: str, prepare_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Payment commit with detailed tracking."""

        payment_id = prepare_data.get("payment_id")
        if not payment_id:
            return False, "No payment ID in prepare data", {}

        with tracer.start_as_current_span("2pc.process_payment") as span:
            span.set_attribute("payment.payment_id", payment_id)

            try:
                with grpc.insecure_channel(self.payment_service) as channel:
                    stub = payment_pb2_grpc.PaymentServiceStub(channel)

                    commit_request = payment_pb2.CommitRequest(
                        transaction_id=transaction_id, payment_id=payment_id
                    )

                    response = stub.Commit(commit_request, timeout=self.timeout)

                    if not response.success:
                        span.set_status(
                            Status(StatusCode.ERROR, response.error_message)
                        )
                        return False, response.error_message, {}

                    payment_result = {
                        "payment_id": response.payment_result.payment_id,
                        "amount": response.payment_result.amount,
                        "payment_method": response.payment_result.payment_method,
                        "status": response.payment_result.status,
                        "confirmation_code": response.payment_result.confirmation_code,
                        "timestamp": response.payment_result.timestamp,
                    }

                    span.set_attribute(
                        "payment.amount_processed", payment_result["amount"]
                    )
                    span.set_attribute(
                        "payment.confirmation_code", payment_result["confirmation_code"]
                    )
                    span.set_attribute("payment.processed_successfully", True)

                    # Record commit result
                    with self._transaction_lock:
                        if transaction_id in self.transactions:
                            if (
                                "phase2_results"
                                not in self.transactions[transaction_id]
                            ):
                                self.transactions[transaction_id]["phase2_results"] = {}
                            self.transactions[transaction_id]["phase2_results"][
                                "payment"
                            ] = {"success": True, "payment_result": payment_result}

                    return True, None, payment_result

            except grpc.RpcError as e:
                error_msg = (
                    f"Payment service error during commit: {e.code()}: {e.details()}"
                )
                span.set_status(Status(StatusCode.ERROR, error_msg))
                return False, error_msg, {}

    def _global_abort(self, transaction_id: str, reason: str) -> None:
        """Abort transaction with comprehensive tracking."""

        with tracer.start_as_current_span("2pc.global_abort") as span:
            span.set_attribute("transaction.id", transaction_id)
            span.set_attribute("abort.reason", reason)

            with self._transaction_lock:
                if transaction_id not in self.transactions:
                    span.set_attribute("transaction.found", False)
                    return

                self.transactions[transaction_id]["status"] = "ABORTING"
                self.transactions[transaction_id]["abort_reason"] = reason
                order_data = self.transactions[transaction_id]["order_data"]
                order_id = order_data.get("order_id", transaction_id)

                # Check if payment needs to be aborted
                need_payment_abort = False
                payment_id = None
                if "phase1_results" in self.transactions[transaction_id]:
                    if "payment" in self.transactions[transaction_id]["phase1_results"]:
                        payment_info = self.transactions[transaction_id][
                            "phase1_results"
                        ]["payment"]
                        if payment_info.get("can_commit"):
                            need_payment_abort = True
                            payment_id = payment_info.get("payment_id")

            span.set_attribute("order.id", order_id)
            span.set_attribute("payment.needs_abort", need_payment_abort)

            print(f"[2PC] Aborting transaction {transaction_id}: {reason}")

            # Update order status to FAILED
            self._update_order_status(order_id, "FAILED", {"reason": reason})

            # Abort payment if needed
            if need_payment_abort and payment_id:
                with tracer.start_as_current_span("2pc.abort_payment") as payment_span:
                    payment_span.set_attribute("payment.payment_id", payment_id)

                    try:
                        with grpc.insecure_channel(self.payment_service) as channel:
                            stub = payment_pb2_grpc.PaymentServiceStub(channel)
                            abort_request = payment_pb2.AbortRequest(
                                transaction_id=transaction_id,
                                payment_id=payment_id,
                                reason=reason,
                            )
                            stub.Abort(abort_request, timeout=self.timeout)
                            payment_span.set_attribute("payment.abort_success", True)
                    except grpc.RpcError as e:
                        error_msg = f"Error aborting payment: {e.code()}: {e.details()}"
                        payment_span.set_status(Status(StatusCode.ERROR, error_msg))
                        print(error_msg)

            # Finalize transaction status
            with self._transaction_lock:
                if transaction_id in self.transactions:
                    self.transactions[transaction_id]["status"] = "ABORTED"
                    self.transactions[transaction_id]["end_time"] = time.time()

    def _create_order_in_db(
        self, transaction_id: str, order_data: Dict[str, Any], status: str
    ) -> Tuple[bool, Optional[str]]:
        """Create order record in database with tracking."""
        order_id = order_data.get("order_id", transaction_id)
        order_key = f"order:{order_id}"

        order_value = {
            "order_id": order_id,
            "status": status,
            "items": order_data.get("book_tokens", []),
            "amount": order_data.get("amount", 0),
            "customer": order_data.get("user", {}).get("name", "unknown"),
            "timestamp": time.time(),
            "transaction_id": transaction_id,
        }

        primary_node = self._get_primary_db_node()
        if not primary_node:
            return False, "No primary database node available"

        try:
            with grpc.insecure_channel(primary_node) as channel:
                stub = db_node_pb2_grpc.DatabaseStub(channel)
                response = stub.Write(
                    db_node_pb2.WriteRequest(
                        key=order_key,
                        value=json.dumps(order_value),
                        type=db_node_pb2.WriteRequest.ValueType.JSON,
                    ),
                    timeout=self.timeout,
                )
                return (
                    response.success,
                    response.message if not response.success else None,
                )
        except grpc.RpcError as e:
            return False, f"Database error: {e.details()}"

    def _update_order_status(
        self, order_id: str, status: str, info: Dict[str, Any] = None
    ):
        """Update order status with tracking."""
        primary_node = self._get_primary_db_node()

        with tracer.start_as_current_span("2pc.update_order_status") as span:
            span.set_attribute("order.id", order_id)
            span.set_attribute("order.new_status", status)

            try:
                with grpc.insecure_channel(primary_node) as channel:
                    stub = db_node_pb2_grpc.DatabaseStub(channel)

                    order_key = f"order:{order_id}"
                    read_response = stub.Read(
                        db_node_pb2.ReadRequest(key=order_key), timeout=self.timeout
                    )

                    if read_response.success:
                        order_data = json.loads(read_response.value)
                        order_data["status"] = status
                        order_data["updated_at"] = time.time()

                        if info and info.get("payment_id"):
                            order_data["payment"] = {
                                "payment_id": info.get("payment_id"),
                                "confirmation_code": info.get("confirmation_code"),
                                "processed_at": info.get("timestamp"),
                            }
                            span.set_attribute(
                                "payment.confirmation_code",
                                info.get("confirmation_code"),
                            )
                        elif info and info.get("reason"):
                            order_data["reason"] = info.get("reason")
                            span.set_attribute(
                                "order.failure_reason", info.get("reason")
                            )

                        write_response = stub.Write(
                            db_node_pb2.WriteRequest(
                                key=order_key,
                                value=json.dumps(order_data),
                                type=db_node_pb2.WriteRequest.ValueType.JSON,
                            ),
                            timeout=self.timeout,
                        )

                        span.set_attribute(
                            "database.update_success", write_response.success
                        )
                        return write_response.success
                    else:
                        span.set_status(Status(StatusCode.ERROR, "Order not found"))
                        return False
            except grpc.RpcError as e:
                error_msg = f"Database error: {e.details()}"
                span.set_status(Status(StatusCode.ERROR, error_msg))
                return False

    def _get_primary_db_node(self) -> Optional[str]:
        """Get the primary database node."""
        with self._primary_lock:
            if self._primary_node:
                return self._primary_node

        for node in self.db_nodes:
            try:
                with grpc.insecure_channel(node) as channel:
                    stub = db_node_pb2_grpc.DatabaseStub(channel)
                    response = stub.GetStatus(
                        db_node_pb2.StatusRequest(), timeout=self.timeout
                    )
                    if response.role.lower() == "primary":
                        with self._primary_lock:
                            self._primary_node = node
                        return node
            except grpc.RpcError:
                continue
        return None

    def _generate_transaction_id(self) -> str:
        """Generate a unique transaction ID."""
        return str(uuid.uuid4())

    def get_transaction_status(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a transaction."""
        with self._transaction_lock:
            if transaction_id in self.transactions:
                return dict(self.transactions[transaction_id])
            return None
