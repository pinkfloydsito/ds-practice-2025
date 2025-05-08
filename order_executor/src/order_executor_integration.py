import json
from typing import Dict, Any

from job_processor import OrderProcessor


class OrderExecutorService:
    """
    Service that handles order execution when called by the Raft cluster.
    """

    _instance = None

    @classmethod
    def get_instance(cls):
        """Get the singleton instance of OrderExecutorService."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        """Initialize the order executor service."""
        self.order_processor = OrderProcessor()
        print("Order executor service initialized")

    def execute_order(self, job_id: str, payload: str) -> Dict[str, Any]:
        """
        Execute an order from the Raft cluster.

        Args:
            job_id: Job ID
            payload: JSON payload containing order data

        Returns:
            Result dictionary
        """
        print(f"Executing order {job_id}")

        try:
            # Parse payload
            try:
                if isinstance(payload, str):
                    order_data = json.loads(payload)
                else:
                    order_data = payload
            except json.JSONDecodeError:
                print(f"Invalid order payload for job {job_id}")
                return {
                    "success": False,
                    "error": "Invalid order payload: not a valid JSON",
                    "job_id": job_id,
                }

            # Prepare job data
            job_data = {"job_id": job_id, "payload": order_data}

            # Process the job
            success, error, result = self.order_processor.process_job(job_data)

            if not success:
                print(f"Job {job_id} execution failed: {error}")
                return {"success": False, "error": error, "job_id": job_id}

            print(f"Job {job_id} executed successfully")
            return {"success": True, "result": result, "job_id": job_id}

        except Exception as e:
            print(f"Error executing order {job_id}: {str(e)}")
            return {
                "success": False,
                "error": f"Error executing order: {str(e)}",
                "job_id": job_id,
            }
