import sys
import os
import datetime
from datetime import datetime as dt

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
models_path = os.path.abspath(os.path.join(FILE, "../../../utils/models"))
vector_clock_path = os.path.abspath(os.path.join(FILE, "../../../utils/vector_clock"))
grpc_path = os.path.abspath(
    os.path.join(FILE, "../../../utils/pb/transaction_verification")
)
sys.path.insert(0, grpc_path)
sys.path.insert(0, models_path)
sys.path.insert(0, vector_clock_path)


import grpc
from concurrent import futures
import re  # for regex checks, if you like

# Import the generated classes
import transaction_verification_pb2
import transaction_verification_pb2_grpc

from vector_clock import OrderEventTracker


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
        self.service_name = "transaction_verification"
        self.order_event_tracker = OrderEventTracker()

    def VerifyBooks(self, request, context):
        """
        Verify that the order items list is not empty
        """
        order_id = request.orderId
        books = request.books
        received_clock = dict(request.vectorClock)

        # Process the event and update vector clock
        updated_clock = self.order_event_tracker.record_event(
            order_id=order_id,
            service=self.service_name,
            event_name="verify_items",
            received_clock=received_clock,
        )

        # Log the current vector clock
        print(
            f"Service {self.service_name}, Order {order_id}, Event 'verify_items', Clock: {updated_clock}"
        )

        # Check if items list is empty
        is_valid = len(books) > 0
        reason = "" if is_valid else "Order must contain at least one item"

        # Create and return response with updated vector clock
        return transaction_verification_pb2.BooksResponse(
            isValid=is_valid, vectorClock=updated_clock
        )

    def VerifyTransaction(self, request, context):
        """
        Very simple checks:
        1. Credit card number length
        2. Expiry date format and validity
        """
        credit_card_number = request.creditCardNumber
        expiry_date = request.expiryDate  # "MM/YY" or "MM/YYYY"
        order_id = request.orderId  # "MM/YY" or "MM/YYYY"
        received_clock = dict(request.vectorClock)

        is_valid = True
        reason = "OK"

        # 1. Check credit card length
        if not (13 <= len(credit_card_number) <= 19):
            is_valid = False
            reason = f"Invalid credit card length: {len(credit_card_number)}"

        if is_valid:
            if not check_luhn_algorithm(credit_card_number):
                is_valid = False
                reason = "Invalid credit card number (Luhn algorithm check failed)"

        # 2. Check expiry date
        if is_valid:
            # A simple approach: parse "MM/YY"
            # More robust approach: parse date with datetime library
            pattern = r"^(0[1-9]|1[0-2])/(20)?\d{2}$"  # e.g. 08/2025 or 08/25
            if not re.match(pattern, expiry_date):
                is_valid = False
                reason = f"Invalid expiry date format: {expiry_date}"
            else:
                try:
                    # Parse the date string
                    if len(expiry_date) == 5:  # MM/YY
                        month, year_short = expiry_date.split("/")
                        year = int("20" + year_short)
                    else:  # MM/YYYY
                        month, year = expiry_date.split("/")
                        year = int(year)

                    month = int(month)

                    # Credit cards expire at the end of the month
                    # Create a date for the first day of the next month and subtract one day
                    if month == 12:
                        next_month = 1
                        next_year = year + 1
                    else:
                        next_month = month + 1
                        next_year = year

                    expiry_date_obj = dt(next_year, next_month, 1) - datetime.timedelta(
                        days=1
                    )

                    # Check if the card is not expired (last day of the expiry month)
                    current_date = dt.now()
                    valid_date = expiry_date_obj >= current_date

                    if not valid_date:
                        reason = "Card has expired"
                        is_valid = False
                except ValueError:
                    is_valid = False
                    reason = "Invalid date values"

                pass

        # Process the event and update vector clock
        updated_clock = self.order_event_tracker.record_event(
            order_id=order_id,
            service=self.service_name,
            event_name="verify_credit_card",
            received_clock=received_clock,
        )
        print(f"Transaction Verification result: {is_valid}, reason: {reason}")
        return transaction_verification_pb2.TransactionResponse(
            isValid=is_valid, reason=reason, vectorClock=updated_clock
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    transaction_verification_pb2_grpc.add_TransactionVerificationServiceServicer_to_server(
        TransactionVerificationServiceServicer(), server
    )
    server.add_insecure_port("[::]:50052")
    server.start()
    print("Transaction Verification service listening on port 50052.")

    # Keep thread alive
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
