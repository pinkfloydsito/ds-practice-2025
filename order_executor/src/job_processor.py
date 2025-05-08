import os
import json
from typing import Dict, Any, Optional, Tuple

from two_phase_commit import TwoPhaseCommitCoordinator


class OrderProcessor:
    """Processes orders by orchestrating distributed transactions."""

    def __init__(self):
        """Initialize the order processor."""
        # Get database nodes from environment
        db_nodes_env = os.getenv(
            "DB_NODES", "db-node1:50052,db-node2:50052,db-node3:50052"
        )
        db_nodes = db_nodes_env.split(",")

        # Get payment service from environment
        payment_service = os.getenv("PAYMENT_SERVICE", "payment-service:50053")

        # Initialize 2PC coordinator
        self.coordinator = TwoPhaseCommitCoordinator(db_nodes, payment_service)

        print(
            f"Order processor initialized with DB nodes: {db_nodes}, payment service: {payment_service}"
        )

    def process_job(
        self, job_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Process a job from the queue.

        Args:
            job_data: Job data including order information

        Returns:
            Tuple of (success, error_message, result)
        """
        job_id = job_data.get("job_id", "unknown")
        print(f"Processing job {job_id}")

        try:
            # Extract order information
            order_payload = job_data.get("payload", {})
            if isinstance(order_payload, str):
                try:
                    order_payload = json.loads(order_payload)
                except json.JSONDecodeError:
                    error_msg = "Invalid order payload: not a valid JSON"
                    print(f"{error_msg} for job {job_id}")
                    return False, error_msg, {"status": "FAILED"}

            # Validate order
            if not self._validate_order(order_payload):
                error_msg = "Invalid order: missing required fields"
                print(f"{error_msg} for job {job_id}")
                return False, error_msg, {"status": "FAILED"}

            # Ensure order has an ID
            if "order_id" not in order_payload:
                order_payload["order_id"] = job_id

            # Execute the order using 2PC
            success, error, result = self.coordinator.execute_order(order_payload)

            if not success:
                print(f"Order execution failed: {error}")
                return False, error, {"status": "FAILED", "reason": error}

            print(f"Order {job_id} processed successfully")
            return True, None, result

        except Exception as e:
            error_msg = f"Error processing job {job_id}: {str(e)}"
            print(error_msg)
            return False, error_msg, {"status": "ERROR"}

    def _validate_order(self, order: Dict[str, Any]) -> bool:
        """
        Validate an order to ensure it has the required fields.

        Args:
            order: Order data

        Returns:
            True if order is valid, False otherwise
        """
        # Check for required fields
        items_key = "book_tokens" if "book_tokens" in order else "items"
        if items_key not in order or not order[items_key]:
            return False

        # Validate items
        # for item in order[items_key]:
        #     if "name" not in item or not item["name"]:
        #         return False
        #     if (
        #         "amount" not in item
        #         or not isinstance(item["amount"], int)
        #         or item["amount"] <= 0
        #     ):
        #         return False

        return True
