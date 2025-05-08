import traceback
import os
import sys
import grpc
from typing import Dict, Any, Optional, Tuple, List

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
PROTO_DIR = os.path.abspath(os.path.join(FILE, "../../../../utils/pb/db_node"))
sys.path.insert(0, PROTO_DIR)

try:
    import db_node_pb2
    import db_node_pb2_grpc
except ImportError as e:
    print(f"Failed to import database protobuf modules: {e}")
    sys.exit(1)


class DatabaseService:
    """Service for reading directly from the distributed database."""

    def __init__(self, db_nodes: List[str], timeout: int = 5):
        """
        Initialize the database service.

        Args:
            db_nodes: List of database node addresses
            timeout: Timeout for gRPC calls
        """
        self.db_nodes = db_nodes
        self.timeout = timeout
        self._current_node_index = 0

    def read_book_stock(
        self, book_name: str
    ) -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Read stock for a specific book using round-robin load balancing.

        Args:
            book_name: Name of the book

        Returns:
            Tuple of (success, stock, error_message)
        """
        stock_key = f"stock:{book_name}"

        # Try reading from nodes using round-robin
        for attempt in range(len(self.db_nodes)):
            # Get next node in round-robin fashion
            node_index = (self._current_node_index + attempt) % len(self.db_nodes)
            node = self.db_nodes[node_index]

            try:
                with grpc.insecure_channel(node) as channel:
                    stub = db_node_pb2_grpc.DatabaseStub(channel)
                    response = stub.Read(
                        db_node_pb2.ReadRequest(key=stock_key), timeout=self.timeout
                    )

                    if response.success:
                        # Update round-robin counter for next request
                        self._current_node_index = (node_index + 1) % len(self.db_nodes)

                        # Parse stock value
                        try:
                            stock = int(float(response.value))
                            return True, stock, None
                        except ValueError as e:
                            traceback.print_exc()
                            print(f"Error parsing stock value: {e}")
                            return False, None, f"Invalid stock value: {response.value}"
            except grpc.RpcError as e:
                print(f"Error reading from node {node}: {e}")
                continue

        return (
            False,
            None,
            f"Could not read stock for {book_name} from any database node",
        )

    def get_all_books_stock(self, book_names: List[str]) -> Dict[str, Any]:
        """
        Get stock for multiple books.

        Args:
            book_names: List of book names to check

        Returns:
            Dictionary with stock information for each book
        """
        result = {}

        for book_name in book_names:
            success, stock, error = self.read_book_stock(book_name)

            if success:
                result[book_name] = {"stock": stock, "available": stock > 0}
            else:
                result[book_name] = {"stock": 0, "available": False, "error": error}

        return result

    def get_database_status(self) -> List[Dict[str, Any]]:
        """
        Get status of all database nodes.

        Returns:
            List of node status dictionaries
        """
        statuses = []

        for node in self.db_nodes:
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
                            "status": "online",
                        }
                    )
            except grpc.RpcError:
                statuses.append(
                    {
                        "address": node,
                        "status": "offline",
                        "error": "Node not responding",
                    }
                )

        return statuses
