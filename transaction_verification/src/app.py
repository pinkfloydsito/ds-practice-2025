import sys
import os

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
models_path = os.path.abspath(os.path.join(FILE, "../../../utils/models"))
grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/transaction_verification"))
sys.path.insert(0, grpc_path)
sys.path.insert(0, models_path)



import grpc
from concurrent import futures
import time
import re  # for regex checks, if you like

# Import the generated classes
import transaction_verification_pb2
import transaction_verification_pb2_grpc


class TransactionVerificationServiceServicer(transaction_verification_pb2_grpc.TransactionVerificationServiceServicer):
    def VerifyTransaction(self, request, context):
        """
        Very simple checks:
        1. Credit card number length
        2. Expiry date format and validity
        """
        credit_card_number = request.creditCardNumber
        expiry_date = request.expiryDate  # "MM/YY" or "MM/YYYY"

        is_valid = True
        reason = "OK"

        # 1. Check credit card length
        if not (13 <= len(credit_card_number) <= 19):
            is_valid = False
            reason = f"Invalid credit card length: {len(credit_card_number)}"

        # 2. Check expiry date
        if is_valid:
            # A simple approach: parse "MM/YY"
            # More robust approach: parse date with datetime library
            pattern = r'^(0[1-9]|1[0-2])/(20)?\d{2}$'  # e.g. 08/2025 or 08/25
            if not re.match(pattern, expiry_date):
                is_valid = False
                reason = f"Invalid expiry date format: {expiry_date}"
            else:

                pass

        return transaction_verification_pb2.TransactionResponse(isValid=is_valid, reason=reason)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    transaction_verification_pb2_grpc.add_TransactionVerificationServiceServicer_to_server(
        TransactionVerificationServiceServicer(), server
    )
    server.add_insecure_port('[::]:50052')
    server.start()
    print("Transaction Verification service listening on port 50052.")
    try:
        while True:
            time.sleep(86400)  # Keep alive
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == '__main__':
    serve()
