import json
import os
import sys
import time
import uuid
import grpc
import traceback
import threading
from typing import Dict, List, Any, Optional, Tuple

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

    def _generate_transaction_id(self) -> str:
        """Generate a unique transaction ID."""
        return str(uuid.uuid4())

    def execute_order(
        self, order_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Execute an order using the Two-Phase Commit protocol.

        Args:
            order_data: Order data containing items to process

        Returns:
            Tuple of (success, error_message, result)
        """
        # Create transaction ID
        transaction_id = self._generate_transaction_id()
        print(f"Starting transaction {transaction_id} for order execution")

        # Initialize transaction record
        order_id = order_data.get("order_id", "unknown")

        with self._transaction_lock:
            self.transactions[transaction_id] = {
                "id": transaction_id,
                "status": "STARTED",
                "order_id": order_id,
                "order_data": order_data,
                "start_time": time.time(),
                "participants": ["database", "payment"],
                "phase1_results": {},
                "phase2_results": {},
            }
            success, error = self._create_order_in_db(
                transaction_id, order_data, "PROCESSING"
            )

            if not success:
                self._global_abort(transaction_id, error)
                return (
                    False,
                    error,
                    {"transaction_id": transaction_id, "status": "FAILED"},
                )

        try:
            # Phase 1: Prepare
            phase1_success, phase1_error, prepare_data = self._phase1_prepare(
                transaction_id
            )
            if not phase1_success:
                self._global_abort(
                    transaction_id, phase1_error or "Prepare phase failed"
                )
                return (
                    False,
                    phase1_error,
                    {"transaction_id": transaction_id, "status": "ABORTED"},
                )

            # Phase 2: Commit
            phase2_success, phase2_error, result = self._phase2_commit(
                transaction_id, prepare_data
            )
            if not phase2_success:
                self._global_abort(
                    transaction_id, phase2_error or "Commit phase failed"
                )
                return (
                    False,
                    phase2_error,
                    {"transaction_id": transaction_id, "status": "ABORTED"},
                )

            # Update transaction status
            with self._transaction_lock:
                if transaction_id in self.transactions:
                    self.transactions[transaction_id]["status"] = "COMMITTED"
                    self.transactions[transaction_id]["end_time"] = time.time()

            return True, None, result

        except Exception as e:
            error_msg = f"Transaction {transaction_id} failed with error: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            self._global_abort(transaction_id, error_msg)
            return (
                False,
                error_msg,
                {"transaction_id": transaction_id, "status": "ABORTED"},
            )

    def _phase1_prepare(
        self, transaction_id: str
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Phase 1 of 2PC: Ask all participants if they can commit.

        Args:
            transaction_id: Transaction ID

        Returns:
            Tuple of (success, error_message, prepare_data)
        """
        # Update transaction status
        with self._transaction_lock:
            if transaction_id not in self.transactions:
                return False, "Transaction not found", {}

            self.transactions[transaction_id]["status"] = "PREPARING"
            order_data = self.transactions[transaction_id]["order_data"]

        print(f"Phase 1 (Prepare) for transaction {transaction_id}")

        # Prepare data for phase 2
        prepare_data = {}

        # 1. Ask database if it can commit (check stock)
        db_can_commit, db_error, db_prepare_data = self._prepare_database(
            transaction_id, order_data
        )
        if not db_can_commit:
            return False, f"Database prepare failed: {db_error}", {}

        prepare_data["database"] = db_prepare_data

        # 2. Ask payment service if it can commit
        payment_can_commit, payment_error, payment_prepare_data = self._prepare_payment(
            transaction_id, order_data
        )
        if not payment_can_commit:
            return False, f"Payment prepare failed: {payment_error}", {}

        prepare_data["payment"] = payment_prepare_data

        # All participants can commit
        return True, None, prepare_data

    def _prepare_database(
        self, transaction_id: str, order_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Ask database if it can commit (check stock).

        Args:
            transaction_id: Transaction ID
            order_data: Order data

        Returns:
            Tuple of (can_commit, error_message, prepare_data)
        """
        # Get items from order
        items = order_data.get("book_tokens", [])
        if not items:
            return False, "No items in order", {}

        # check stock for each item
        stock_checks = {}
        primary_node = self._get_primary_db_node()

        if not primary_node:
            return False, "No primary database node available", {}

        try:
            with grpc.insecure_channel(primary_node) as channel:
                stub = db_node_pb2_grpc.DatabaseStub(channel)
                response = stub.ReadAll(
                    db_node_pb2.ReadAllRequest(), timeout=self.timeout
                )
                if response.success:
                    print(f"DEBUG: Found {response.total_returned} items in database")
                    for item in response.items:
                        print(
                            f"  Key: {item.key}, Value: {item.value}, Version: {item.version}, Type: {item.type}"
                        )
                else:
                    print(f"DEBUG: Failed to read all items: {response.message}")

                for item in items:
                    # TODO change the model and fix this
                    book_name = item
                    quantity = 1

                    if not book_name:
                        return False, "Item missing name", {}

                    # Check stock
                    stock_key = f"stock:{book_name}"

                    response = stub.Read(
                        db_node_pb2.ReadRequest(key=stock_key), timeout=self.timeout
                    )

                    if not response.success:
                        return (
                            False,
                            f"Failed to check stock for {book_name}: Item not found",
                            {},
                        )

                    # Parse stock value
                    try:
                        current_stock = int(float(response.value))
                    except ValueError:
                        return (
                            False,
                            f"Invalid stock value for {book_name}: {response.value}",
                            {},
                        )

                    # Check if enough stock
                    if current_stock < quantity:
                        return (
                            False,
                            f"Insufficient stock for {book_name}: {current_stock} available, {quantity} requested",
                            {},
                        )

                    # Record stock check
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

                    self.transactions[transaction_id]["phase1_results"]["database"] = {
                        "can_commit": True,
                        "stock_checks": stock_checks,
                    }

            # All stock checks passed
            return True, None, {"stock_checks": stock_checks}

        except grpc.RpcError as e:
            error_msg = f"Database error during prepare: {e.code()}: {e.details()}"
            print(error_msg)
            return False, error_msg, {}

    def _prepare_payment(
        self, transaction_id: str, order_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Ask payment service if it can process payment.

        Args:
            transaction_id: Transaction ID
            order_data: Order data

        Returns:
            Tuple of (can_commit, error_message, prepare_data)
        """
        # Extract payment information
        amount = order_data.get("amount", 0)
        if amount <= 0:
            # Calculate amount from items if not provided
            items = order_data.get("items", [])
            amount = sum(
                item.get("price", 10) * item.get("amount", 1) for item in items
            )

        payment_method = order_data.get("payment_method", "Credit Card")
        customer_id = order_data.get("customer_id", "guest")

        # Prepare metadata
        metadata = {
            "order_id": order_data.get("order_id", transaction_id),
            "timestamp": str(int(time.time())),
        }

        try:
            with grpc.insecure_channel(self.payment_service) as channel:
                stub = payment_pb2_grpc.PaymentServiceStub(channel)

                # Create prepare request
                prepare_request = payment_pb2.PrepareRequest(
                    transaction_id=transaction_id,
                    amount=amount,
                    payment_method=payment_method,
                    customer_id=customer_id,
                    metadata=metadata,
                )

                # Send prepare request
                response = stub.Prepare(prepare_request, timeout=self.timeout)

                # Check result
                if not response.can_commit:
                    return False, response.error_message, {}

                # Record prepare result
                payment_id = response.payment_id

                with self._transaction_lock:
                    if transaction_id in self.transactions:
                        if "phase1_results" not in self.transactions[transaction_id]:
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
            print(error_msg)
            return False, error_msg, {}

    def _phase2_commit(
        self, transaction_id: str, prepare_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Phase 2 of 2PC: Tell all participants to commit.
        Args:
            transaction_id: Transaction ID
            prepare_data: Data from prepare phase
        Returns:
            Tuple of (success, error_message, result)
        """
        # Update transaction status
        with self._transaction_lock:
            if transaction_id not in self.transactions:
                return False, "Transaction not found", {}
            self.transactions[transaction_id]["status"] = "COMMITTING"
            order_data = self.transactions[transaction_id]["order_data"]

        print(f"Phase 2 (Commit) for transaction {transaction_id}")

        # Initialize result structure
        result = {
            "transaction_id": transaction_id,
            "order_id": order_data.get("order_id", "unknown"),
            "status": "PROCESSING",
            "items": order_data.get("items", []),
            "commit_results": {},
        }

        # 1. Commit payment first
        payment_commit_success, payment_error, payment_result = self._commit_payment(
            transaction_id, prepare_data.get("payment", {})
        )

        if not payment_commit_success:
            # Payment failed - no need for compensation, just report failure
            return False, f"Payment commit failed: {payment_error}", {}

        result["commit_results"]["payment"] = payment_result

        # 2. Commit database changes (decrement stock) after successful payment
        db_commit_success, db_error, db_result = self._commit_database(
            transaction_id, prepare_data.get("database", {})
        )

        if not db_commit_success:
            # Database commit failed - need to compensate payment
            print(f"Compensating payment")
            payment_compensation_success = True  # TODO check for the failing escenarios

            if payment_compensation_success:
                return (
                    False,
                    f"Database commit failed, payment refunded: {db_error}",
                    {},
                )
            else:
                return (
                    False,
                    f"CRITICAL: Database commit failed and payment refund failed: {db_error}",
                    {},
                )

        result["commit_results"]["database"] = db_result

        # Both commits succeeded
        if db_commit_success and payment_commit_success:
            # Update order status to COMPLETED
            order_id = order_data.get("order_id", transaction_id)
            self._update_order_status(order_id, "COMPLETED", payment_result)

        result["status"] = "COMPLETED"
        return True, None, result

    def _compensate_database_commit(
        self, transaction_id: str, db_commit_result: Dict[str, Any]
    ) -> bool:
        """Compensate for database changes by restoring stock."""
        try:
            primary_node = self._get_primary_db_node()
            if not primary_node:
                return False

            with grpc.insecure_channel(primary_node) as channel:
                stub = db_node_pb2_grpc.DatabaseStub(channel)

                # Now this will work because we're returning updated_stock
                updated_stock = db_commit_result.get("updated_stock", {})

                for book_name, stock_info in updated_stock.items():
                    stock_key = stock_info["key"]
                    quantity_decremented = stock_info["amount"]

                    # Restore stock by incrementing back
                    response = stub.IncrementStock(
                        db_node_pb2.IncrementRequest(
                            key=stock_key, amount=quantity_decremented
                        ),
                        timeout=self.timeout,
                    )

                    print("debug: ", response)

                    if not response.success:
                        print(f"Failed to restore stock for {book_name}")
                        return False

                # Update order status to FAILED
                with self._transaction_lock:
                    order_data = self.transactions[transaction_id]["order_data"]
                    order_id = order_data.get("order_id", transaction_id)

                self._update_order_status(
                    order_id, "FAILED", {"reason": "Payment failed"}
                )

                return True

        except Exception as e:
            print(f"Error during compensation: {str(e)}")
            return False

    def _update_order_status(
        self, order_id: str, status: str, info: Dict[str, Any] = None
    ):
        """Update order status in database."""
        primary_node = self._get_primary_db_node()

        try:
            with grpc.insecure_channel(primary_node) as channel:
                stub = db_node_pb2_grpc.DatabaseStub(channel)

                # Read current order data
                order_key = f"order:{order_id}"
                read_response = stub.Read(
                    db_node_pb2.ReadRequest(key=order_key), timeout=self.timeout
                )

                print("debug", read_response)

                if read_response.success:
                    order_data = json.loads(read_response.value)

                    # Update status
                    order_data["status"] = status
                    order_data["updated_at"] = time.time()

                    if info.get("payment_id") is not None:
                        order_data["payment"] = {
                            "payment_id": info.get("payment_id"),
                            "confirmation_code": info.get("confirmation_code"),
                            "processed_at": info.get("timestamp"),
                        }
                    elif info.get("reason") is not None:
                        order_data["reason"] = info.get("reason")

                    # Write back
                    write_response = stub.Write(
                        db_node_pb2.WriteRequest(
                            key=order_key,
                            value=json.dumps(order_data),
                            type=db_node_pb2.WriteRequest.ValueType.JSON,
                        ),
                        timeout=self.timeout,
                    )

                    return write_response.success
        except grpc.RpcError:
            return False

    def _commit_database(
        self, transaction_id: str, prepare_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Commit database changes (decrement stock).

        Args:
            transaction_id: Transaction ID
            prepare_data: Data from prepare phase for database

        Returns:
            Tuple of (success, error_message, commit_result)
        """
        # Get stock checks from prepare phase
        stock_checks = prepare_data.get("stock_checks", {})
        if not stock_checks:
            return False, "No stock checks in prepare data", {}

        # Get primary database node
        primary_node = self._get_primary_db_node()
        if not primary_node:
            return False, "No primary database node available", {}

        # Commit results
        commit_results = {"updated_stock": {}}

        try:
            with grpc.insecure_channel(primary_node) as channel:
                stub = db_node_pb2_grpc.DatabaseStub(channel)

                for book_name, check_data in stock_checks.items():
                    # Get stock information
                    stock_key = check_data["key"]
                    quantity = check_data["amount"]

                    print(
                        f"decrementing stock for {stock_key} {book_name} by {quantity}"
                    )

                    # Decrement stock
                    response = stub.DecrementStock(
                        db_node_pb2.DecrementRequest(key=stock_key, amount=quantity),
                        timeout=self.timeout,
                    )

                    if not response.success:
                        # Handle failure - in a real system, we would need to
                        # restore any other stock decrements we already made
                        return (
                            False,
                            f"Failed to decrement stock for {book_name}: {response.message}",
                            {},
                        )

                    # Record what we changed for potential rollback
                    commit_results["updated_stock"][book_name] = {
                        "new_stock": response.new_value,
                        "old_stock": check_data["current_stock"],  # From prepare phase
                        "amount": quantity,
                        "version": response.version,
                        "key": stock_key,
                    }

            with self._transaction_lock:
                order_data = self.transactions[transaction_id]["order_data"]
                order_id = order_data.get("order_id", transaction_id)

            with grpc.insecure_channel(primary_node) as channel:
                stub = db_node_pb2_grpc.DatabaseStub(channel)

                # for book_name, check_data in stock_checks.items():
                #     # Get stock information
                #     stock_key = check_data["key"]
                #     quantity = check_data["amount"]
                #
                #     # Decrement stock
                #     response = stub.DecrementStock(
                #         db_node_pb2.DecrementRequest(key=stock_key, amount=quantity),
                #         timeout=self.timeout,
                #     )
                #
                #     if not response.success:
                #         # Handle failure - in a real system, we would need to
                #         # restore any other stock decrements we already made
                #         return (
                #             False,
                #             f"Failed to decrement stock for {book_name}: {response.message}",
                #             {},
                #         )
                #
                #     # Record commit result
                #     commit_results[book_name] = {
                #         "new_stock": response.new_value,
                #         "amount": quantity,
                #         "version": response.version,
                #     }

                # store order status
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
                    return False, f"Failed to store order status", {}

                commit_results["order_status"] = {
                    "order_id": order_id,
                    "status": "PROCESSING",
                    "version": response.version,
                }

                return True, None, commit_results

        except grpc.RpcError as e:
            error_msg = f"Database error during commit: {e.code()}: {e.details()}"
            print(error_msg)
            traceback.print_exc()

            return False, error_msg, {}

    def _commit_payment(
        self, transaction_id: str, prepare_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Commit payment.

        Args:
            transaction_id: Transaction ID
            prepare_data: Data from prepare phase for payment

        Returns:
            Tuple of (success, error_message, commit_result)
        """
        # Get payment ID from prepare phase
        payment_id = prepare_data.get("payment_id")
        if not payment_id:
            return False, "No payment ID in prepare data", {}

        try:
            with grpc.insecure_channel(self.payment_service) as channel:
                stub = payment_pb2_grpc.PaymentServiceStub(channel)

                # Create commit request
                commit_request = payment_pb2.CommitRequest(
                    transaction_id=transaction_id, payment_id=payment_id
                )

                # Send commit request
                response = stub.Commit(commit_request, timeout=self.timeout)

                # Check result
                if not response.success:
                    return False, response.error_message, {}

                # Extract payment result
                payment_result = {
                    "payment_id": response.payment_result.payment_id,
                    "amount": response.payment_result.amount,
                    "payment_method": response.payment_result.payment_method,
                    "status": response.payment_result.status,
                    "confirmation_code": response.payment_result.confirmation_code,
                    "timestamp": response.payment_result.timestamp,
                }

                # Record commit result
                with self._transaction_lock:
                    if transaction_id in self.transactions:
                        if "phase2_results" not in self.transactions[transaction_id]:
                            self.transactions[transaction_id]["phase2_results"] = {}

                        self.transactions[transaction_id]["phase2_results"][
                            "payment"
                        ] = {"success": True, "payment_result": payment_result}

                return True, None, payment_result

        except grpc.RpcError as e:
            error_msg = (
                f"Payment service error during commit: {e.code()}: {e.details()}"
            )
            print(error_msg)
            return False, error_msg, {}

    def _create_order_in_db(
        self, transaction_id: str, order_data: Dict[str, Any], status: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Create the order in the database with the given status.
        """
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

    def _global_abort(self, transaction_id: str, reason: str) -> None:
        """
        Abort the transaction globally.

        Args:
            transaction_id: Transaction ID
            reason: Reason for aborting
        """
        # Update transaction status
        with self._transaction_lock:
            if transaction_id not in self.transactions:
                return

            self.transactions[transaction_id]["status"] = "ABORTING"
            self.transactions[transaction_id]["abort_reason"] = reason

            # Check if we need to abort database (if we got to phase 2)
            need_database_abort = False
            if "phase2_results" in self.transactions[transaction_id]:
                if "database" in self.transactions[transaction_id]["phase2_results"]:
                    need_database_abort = True

            # Check if we need to abort payment
            need_payment_abort = False
            payment_id = None
            if "phase1_results" in self.transactions[transaction_id]:
                if "payment" in self.transactions[transaction_id]["phase1_results"]:
                    payment_info = self.transactions[transaction_id]["phase1_results"][
                        "payment"
                    ]
                    if payment_info.get("can_commit"):
                        need_payment_abort = True
                        payment_id = payment_info.get("payment_id")

        print(f"Aborting transaction {transaction_id}: {reason}")

        with self._transaction_lock:
            order_data = self.transactions[transaction_id]["order_data"]
            order_id = order_data.get("order_id", transaction_id)

        # ensure this doesn't fail D:
        self._update_order_status(order_id, "FAILED", {"reason": reason})

        # Abort payment if needed
        if need_payment_abort and payment_id:
            try:
                with grpc.insecure_channel(self.payment_service) as channel:
                    stub = payment_pb2_grpc.PaymentServiceStub(channel)

                    # Create abort request
                    abort_request = payment_pb2.AbortRequest(
                        transaction_id=transaction_id,
                        payment_id=payment_id,
                        reason=reason,
                    )

                    # Send abort request
                    stub.Abort(abort_request, timeout=self.timeout)

            except grpc.RpcError as e:
                print(f"Error aborting payment: {e.code()}: {e.details()}")

        # In a real system, we would implement compensating transactions for the database
        # if we had already committed changes there

        # Update transaction status
        with self._transaction_lock:
            if transaction_id in self.transactions:
                self.transactions[transaction_id]["status"] = "ABORTED"
                self.transactions[transaction_id]["end_time"] = time.time()

    def get_transaction_status(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status of a transaction.

        Args:
            transaction_id: Transaction ID

        Returns:
            Transaction status info or None if not found
        """
        with self._transaction_lock:
            if transaction_id in self.transactions:
                # Return a copy to avoid modification
                return dict(self.transactions[transaction_id])
            return None
