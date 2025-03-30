import sys
import os
import datetime
from datetime import datetime as dt

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
models_path = os.path.abspath(os.path.join(FILE, "../../../utils/models"))
grpc_path = os.path.abspath(
    os.path.join(FILE, "../../../utils/pb/transaction_verification")
)
sys.path.insert(0, grpc_path)
sys.path.insert(0, models_path)

import grpc
from concurrent import futures
import re  # for regex checks, if you like

import transaction_verification_pb2
import transaction_verification_pb2_grpc


def check_luhn_algorithm(card_no):
    n_digits = len(card_no)
    n_sum = 0
    is_second = False

    for i in range(n_digits - 1, -1, -1):
        d = int(card_no[i])
        if is_second:
            d = d * 2
        n_sum += d // 10
        n_sum += d % 10
        is_second = not is_second

    return n_sum % 10 == 0


class TransactionVerificationServiceServicer(
    transaction_verification_pb2_grpc.TransactionVerificationServiceServicer
):
    def __init__(self):
        # This dictionary will hold data from InitializeOrder
        # keyed by order_id.
        # e.g. self.orders = {
        #   "BOOK-UUID123": {"creditCardNumber": "1234...", "expiryDate": "MM/YY"}
        # }
        self.orders = {}

    def InitializeOrder(self, request, context):
        """
        Save the order data (credit card info, expiry date, etc.) 
        but don't run actual checks yet.
        """
        order_id = request.order_id
        self.orders[order_id] = {
            "creditCardNumber": request.creditCardNumber,
            "expiryDate": request.expiryDate,
        }

        print(f"[TransactionVerification] Initialized order {order_id} "
              f"with creditCardNumber={request.creditCardNumber}, expiryDate={request.expiryDate}")

        return transaction_verification_pb2.TransactionInitResponse(success=True)

    def VerifyTransaction(self, request, context):
        """
        We retrieve the data that was cached in InitializeOrder if we like, 
        or we can just use request.*. It's up to your design.
        """
        order_id = request.order_id
        is_valid = True
        reason = "OK"

        # If we want to rely on the data from 'InitializeOrder', let's retrieve it:
        # If we never got an InitializeOrder call for this order, fallback to the request fields
        cached = self.orders.get(order_id)
        if cached:
            credit_card_number = cached["creditCardNumber"]
            expiry_date = cached["expiryDate"]
        else:
            # Or just use the request fields if not found
            credit_card_number = request.creditCardNumber
            expiry_date = request.expiryDate

        # 1. Check credit card length
        if not (13 <= len(credit_card_number) <= 19):
            is_valid = False
            reason = f"Invalid credit card length: {len(credit_card_number)}"

        # 1a. Luhn algorithm
        if is_valid:
            if not check_luhn_algorithm(credit_card_number):
                is_valid = False
                reason = "Invalid credit card number (Luhn algorithm check failed)"

        # 2. Check expiry date format & validity
        if is_valid:
            pattern = r"^(0[1-9]|1[0-2])/(20)?\d{2}$"  # e.g. 08/2025 or 08/25
            if not re.match(pattern, expiry_date):
                is_valid = False
                reason = f"Invalid expiry date format: {expiry_date}"
            else:
                try:
                    if len(expiry_date) == 5:  # MM/YY
                        month, year_short = expiry_date.split("/")
                        year = int("20" + year_short)
                    else:  # MM/YYYY
                        month, year = expiry_date.split("/")
                        year = int(year)

                    month = int(month)
                    # Compute last day of that month
                    if month == 12:
                        next_month = 1
                        next_year = year + 1
                    else:
                        next_month = month + 1
                        next_year = year

                    expiry_date_obj = dt(next_year, next_month, 1) - datetime.timedelta(days=1)
                    current_date = dt.now()
                    if expiry_date_obj < current_date:
                        reason = "Card has expired"
                        is_valid = False
                except ValueError:
                    is_valid = False
                    reason = "Invalid date values"

        print(f"[TransactionVerification] VerifyTransaction for order {order_id} => {is_valid}, reason={reason}")
        return transaction_verification_pb2.TransactionResponse(isValid=is_valid, reason=reason)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    transaction_verification_pb2_grpc.add_TransactionVerificationServiceServicer_to_server(
        TransactionVerificationServiceServicer(), server
    )
    server.add_insecure_port("[::]:50052")
    server.start()
    print("Transaction Verification service listening on port 50052.")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
