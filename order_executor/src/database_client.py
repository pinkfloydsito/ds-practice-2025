import os
import sys
import grpc
import threading
import random
from typing import List, Dict, Any, Optional, Tuple

# Add protocol buffer path
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
PROTO_DIR = os.path.abspath(os.path.join(FILE, "../../../utils/pb/db_node"))
sys.path.insert(0, PROTO_DIR)

try:
    import db_node_pb2
    import db_node_pb2_grpc
except ImportError as e:
    print(f"Failed to import database protobuf modules: {e}")
    print(f"Make sure protobuf definitions are at: {PROTO_DIR}")
    sys.exit(1)


class DatabaseClient:
    """Client for interacting with the distributed database system."""

    def __init__(self, nodes: List[str], timeout: int = 5):
        """
        Initialize the database client.

        Args:
            nodes: List of database node addresses
            timeout: Timeout for gRPC calls in seconds
        """
        self.nodes = nodes
        self.timeout = timeout

        # Track primary node
        self._primary_node = None
        self._primary_lock = threading.RLock()

        # Discover primary node
        self._discover_primary()

    def _discover_primary(self) -> None:
        """Discover the primary database node."""
        # Try all nodes
        for node in self.nodes:
            try:
                with grpc.insecure_channel(node) as channel:
                    stub = db_node_pb2_grpc.DatabaseStub(channel)
                    response = stub.GetStatus(
                        db_node_pb2.StatusRequest(), timeout=self.timeout
                    )

                    if response.role.lower() == "primary":
                        with self._primary_lock:
                            self._primary_node = node
                        print(f"Found primary database node: {node}")
                        return
            except grpc.RpcError:
                continue

        print("No primary database node found")

    def _get_primary_node(self) -> Optional[str]:
        """
        Get the primary database node, discovering it if necessary.

        Returns:
            Primary node address or None if not found
        """
        with self._primary_lock:
            if self._primary_node:
                return self._primary_node

        # Try to discover primary
        self._discover_primary()

        with self._primary_lock:
            return self._primary_node

    def read(self, key: str) -> Tuple[bool, Any, int, Optional[str]]:
        """
        Read a value from the database.

        Args:
            key: Key to read

        Returns:
            Tuple of (success, value, version, error_message)
        """
        # Try all nodes in random order (for load balancing)
        nodes = list(self.nodes)
        random.shuffle(nodes)

        for node in nodes:
            try:
                with grpc.insecure_channel(node) as channel:
                    stub = db_node_pb2_grpc.DatabaseStub(channel)
                    response = stub.Read(
                        db_node_pb2.ReadRequest(key=key), timeout=self.timeout
                    )

                    if response.success:
                        return True, response.value, response.version, None
            except grpc.RpcError:
                continue

        return False, None, 0, f"Key '{key}' not found in any database node"

    def write(
        self, key: str, value: Any, value_type: str = "STRING"
    ) -> Tuple[bool, int, Optional[str]]:
        """
        Write a value to the database.

        Args:
            key: Key to write
            value: Value to write (will be converted to string)
            value_type: Type of value (STRING, INT, FLOAT, JSON)

        Returns:
            Tuple of (success, version, error_message)
        """
        # Convert value to string
        if not isinstance(value, str):
            value = str(value)

        # Determine value type
        type_mapping = {
            "STRING": db_node_pb2.WriteRequest.ValueType.STRING,
            "INT": db_node_pb2.WriteRequest.ValueType.INT,
            "FLOAT": db_node_pb2.WriteRequest.ValueType.FLOAT,
            "JSON": db_node_pb2.WriteRequest.ValueType.JSON,
        }

        value_type_enum = type_mapping.get(
            value_type.upper(), db_node_pb2.WriteRequest.ValueType.STRING
        )

        # Get primary node
        primary_node = self._get_primary_node()
        if not primary_node:
            return False, 0, "No primary database node available"

        # Send write request
        try:
            with grpc.insecure_channel(primary_node) as channel:
                stub = db_node_pb2_grpc.DatabaseStub(channel)
                response = stub.Write(
                    db_node_pb2.WriteRequest(
                        key=key, value=value, type=value_type_enum
                    ),
                    timeout=self.timeout,
                )

                if response.success:
                    return True, response.version, None
                else:
                    # Check if we need to redirect
                    if response.primary_id:
                        # Update primary node and retry
                        with self._primary_lock:
                            self._primary_node = None

                        # Recursive call will discover new primary
                        return self.write(key, value, value_type)
                    else:
                        return False, 0, response.message
        except grpc.RpcError as e:
            # Reset primary node on error
            with self._primary_lock:
                if self._primary_node == primary_node:
                    self._primary_node = None

            return False, 0, f"Database error: {e.code()}: {e.details()}"

    def decrement_stock(
        self, key: str, amount: int = 1
    ) -> Tuple[bool, float, int, Optional[str]]:
        """
        Atomically decrement a value in the database.

        Args:
            key: Key to decrement
            amount: Amount to decrement

        Returns:
            Tuple of (success, new_value, version, error_message)
        """
        # Get primary node
        primary_node = self._get_primary_node()
        if not primary_node:
            return False, 0, 0, "No primary database node available"

        # Send decrement request
        try:
            with grpc.insecure_channel(primary_node) as channel:
                stub = db_node_pb2_grpc.DatabaseStub(channel)
                response = stub.DecrementStock(
                    db_node_pb2.DecrementRequest(key=key, amount=amount),
                    timeout=self.timeout,
                )

                if response.success:
                    return True, response.new_value, response.version, None
                else:
                    # Check if we need to redirect
                    if response.primary_id:
                        # Update primary node and retry
                        with self._primary_lock:
                            self._primary_node = None

                        # Recursive call will discover new primary
                        return self.decrement_stock(key, amount)
                    else:
                        return False, response.current_value, 0, response.message
        except grpc.RpcError as e:
            # Reset primary node on error
            with self._primary_lock:
                if self._primary_node == primary_node:
                    self._primary_node = None

            return False, 0, 0, f"Database error: {e.code()}: {e.details()}"

    def get_all_nodes_status(self) -> List[Dict[str, Any]]:
        """
        Get status of all database nodes.

        Returns:
            List of node status dictionaries
        """
        statuses = []

        for node in self.nodes:
            try:
                with grpc.insecure_channel(node) as channel:
                    stub = db_node_pb2_grpc.DatabaseStub(channel)
                    response = stub.GetStatus(
                        db_node_pb2.StatusRequest(), timeout=self.timeout
                    )

                    statuses.append(
                        {
                            "node_id": response.node_id,
                            "address": node,
                            "role": response.role,
                            "primary_id": response.primary_id,
                            "record_count": response.record_count,
                            "term": response.term,
                        }
                    )
            except grpc.RpcError:
                statuses.append(
                    {
                        "node_id": "unknown",
                        "address": node,
                        "role": "unavailable",
                        "primary_id": "unknown",
                        "record_count": 0,
                        "term": 0,
                    }
                )

        return statuses

    def initialize_books(self, books: Dict[str, int]) -> bool:
        """
        Initialize book stock in the database.

        Args:
            books: Dictionary mapping book names to initial stock

        Returns:
            True if all writes succeeded, False otherwise
        """
        all_success = True

        for book_name, stock in books.items():
            stock_key = f"stock:{book_name}"
            success, _, error = self.write(stock_key, stock, "INT")

            if not success:
                print(f"Failed to initialize stock for {book_name}: {error}")
                all_success = False

        return all_success
