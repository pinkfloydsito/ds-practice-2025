import logging
import sys
import os
import grpc
import time
import re
from concurrent import futures

# Insert the stubs path so we can import the generated modules
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/fraud_detection"))
sys.path.insert(0, grpc_path)

import fraud_detection_pb2 as fd_pb2
import fraud_detection_pb2_grpc as fd_pb2_grpc

logging.basicConfig(level=logging.INFO)

class FraudDetectionService(fd_pb2_grpc.FraudDetectionServiceServicer):
    """
    Checks:
    1. If user_name is in a known blocklist (5 names).
    2. If user_email ends with .ru suffix.
    """
    BLOCKED_NAMES = {"alex", "john", "maria", "anna", "ivan"}  

    def CheckFraud(self, request, context):
        user_name = request.user_name.strip().lower()
        user_email = request.user_email.strip().lower()

        is_fraudulent = False
        reason = ""

        # Check if name is in the blocklist
        if user_name in self.BLOCKED_NAMES:
            is_fraudulent = True
            reason = f"Name '{request.user_name}' is on the fraud list."

        # Check if email ends with .ru
        if not is_fraudulent:  # Only check if not already flagged
            if user_email.endswith(".ru"):
                is_fraudulent = True
                reason = f"Email '{request.user_email}' ends with .ru"

        logging.info(
            f"[FraudDetection] user_name={request.user_name}, user_email={request.user_email}, "
            f"is_fraudulent={is_fraudulent}, reason={reason}"
        )

        return fd_pb2.FraudResponse(is_fraudulent=is_fraudulent, reason=reason)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    fd_pb2_grpc.add_FraudDetectionServiceServicer_to_server(FraudDetectionService(), server)
    port = "50051"
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logging.info(f"Fraud Detection service listening on port {port}")
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == "__main__":
    serve()
