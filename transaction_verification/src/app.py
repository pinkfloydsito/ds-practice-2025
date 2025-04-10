import logging
import sys
import os
import datetime
from datetime import datetime as dt

logger = logging.getLogger(__name__)

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
import re
import datetime

import transaction_verification_pb2 as tv_pb2
import transaction_verification_pb2_grpc as tv_pb2_grpc
from vector_clock import OrderEventTracker

def check_luhn_algorithm(card_no):
    n_digits = len(card_no)
    n_sum = 0
    is_second = False
    for i in range(n_digits - 1, -1, -1):
        d = int(card_no[i])
        if is_second:
            d *= 2
        n_sum += d // 10
        n_sum += d % 10
        is_second = not is_second
    return (n_sum % 10) == 0

def check_expiry_date(expiry_date: str) -> (bool, str):
    """Check expiry format (MM/YY or MM/YYYY) and confirm card is not expired."""
    pattern = r"^(0[1-9]|1[0-2])/(20)?\d{2}$"
    if not re.match(pattern, expiry_date):
        return False, f"Invalid expiry date format: {expiry_date}"

    try:
        if len(expiry_date) == 5:  # MM/YY
            month, year_short = expiry_date.split("/")
            year = int("20" + year_short)
        else:  # MM/YYYY
            month, year = expiry_date.split("/")
            year = int(year)

        month = int(month)
        if month == 12:
            next_month = 1
            next_year = year + 1
        else:
            next_month = month + 1
            next_year = year

        expiry_date_obj = dt(next_year, next_month, 1) - datetime.timedelta(days=1)
        if expiry_date_obj < dt.now():
            return False, "Card has expired"
    except ValueError:
        return False, "Invalid date values"
    return True, "OK"

def check_billing_city_country(city: str, country: str) -> (bool, str):
    """Ensure city and country are non-empty."""
    if not city or not country:
        return False, "Billing address is incomplete"
    return True, "OK"

class TransactionVerificationServiceServicer(tv_pb2_grpc.TransactionVerificationServiceServicer):
    def __init__(self):
        self.orders = {}  # store data from InitializeOrder
        self.service_name = "transaction_verification"
        self.order_event_tracker = OrderEventTracker()

    # -------------------------------------------------
    #  InitializeOrder - existing
    # -------------------------------------------------
    def InitializeOrder(self, request, context):
        order_id = request.order_id
        self.orders[order_id] = {
            "creditCardNumber": request.creditCardNumber,
            "expiryDate": request.expiryDate,
            "billingStreet": request.billingStreet,
            "billingCity": request.billingCity,
            "billingState": request.billingState,
            "billingZip": request.billingZip,
            "billingCountry": request.billingCountry,
        }
        received_clock = dict(request.vectorClock)

        if not self.order_event_tracker.order_exists(order_id):
            self.order_event_tracker.initialize_order(order_id)
            print(f"[TransactionVerification] Created vector clock for {order_id}")

        updated_clock = self.order_event_tracker.record_event(
            order_id=order_id,
            service=self.service_name,
            event_name="InitializeOrder",
            received_clock=received_clock,
        )

        print(
            f"[TransactionVerification] InitializeOrder => stored data for {order_id}, Updated Clock: {updated_clock}"
        )

        return tv_pb2.TransactionInitResponse(success=True, vectorClock=updated_clock)

    # -------------------------------------------------
    #  NEW: CheckCard
    # -------------------------------------------------
    def CheckCard(self, request, context):
        """
        Checks only card length, Luhn, expiry.
        """
        order_id = request.order_id
        is_valid = True
        reason = "OK"

        received_clock = dict(request.vectorClock)

        # If we have data from InitializeOrder, use it
        cached = self.orders.get(order_id)
        if cached:
            credit_card_number = cached["creditCardNumber"]
            expiry_date = cached["expiryDate"]
        else:
            # fallback to request fields
            credit_card_number = request.creditCardNumber
            expiry_date = request.expiryDate

        # 1) length
        if not (13 <= len(credit_card_number) <= 19):
            is_valid = False
            reason = f"Invalid credit card length: {len(credit_card_number)}"

        # 2) Luhn
        if is_valid:
            if not check_luhn_algorithm(credit_card_number):
                is_valid = False
                reason = "Invalid credit card number (Luhn check failed)"

        # 3) Expiry
        if is_valid:
            expiry_ok, expiry_reason = check_expiry_date(expiry_date)
            if not expiry_ok:
                is_valid = False
                reason = expiry_reason

        updated_clock = self.order_event_tracker.record_event(
            order_id=order_id,
            service=self.service_name,
            event_name="CheckCard",
            received_clock=received_clock,
        )

        print(
            f"[TransactionVerification] CheckCard => order {order_id}, isValid={is_valid}, reason={reason}, newClock={updated_clock}"
        )

        return tv_pb2.TransactionResponse(isValid=is_valid, reason=reason, vectorClock=updated_clock)

    # -------------------------------------------------
    #  NEW: CheckBilling
    # -------------------------------------------------
    def CheckBilling(self, request, context):
        """
        Checks only that billing city/country exist (and optionally more fields).
        """
        order_id = request.order_id
        is_valid = True
        reason = "OK"

        received_clock = dict(request.vectorClock)

        cached = self.orders.get(order_id)
        if cached:
            billing_city = cached["billingCity"]
            billing_country = cached["billingCountry"]
        else:
            billing_city = request.billingCity
            billing_country = request.billingCountry

        # confirm these fields are not empty
        billing_ok, addr_reason = check_billing_city_country(billing_city, billing_country)
        if not billing_ok:
            is_valid = False
            reason = addr_reason

        updated_clock = self.order_event_tracker.record_event(
            order_id=order_id,
            service=self.service_name,
            event_name="CheckBilling",
            received_clock=received_clock,
        )

        print(
            f"[TransactionVerification] CheckBilling => order {order_id}, isValid={is_valid}, reason={reason}, newClock={updated_clock}"
        )

        return tv_pb2.TransactionResponse(isValid=is_valid, reason=reason, vectorClock=updated_clock)

    # -------------------------------------------------
    #  Existing "VerifyTransaction" combined approach
    # -------------------------------------------------
    def VerifyTransaction(self, request, context):
        """
        Original single-step approach: checks card + billing in one shot.
        """
        order_id = request.order_id
        is_valid = True
        reason = "OK"

        received_clock = dict(request.vectorClock)

        cached = self.orders.get(order_id)
        if cached:
            credit_card_number = cached["creditCardNumber"]
            expiry_date = cached["expiryDate"]
            billing_city = cached["billingCity"]
            billing_country = cached["billingCountry"]
        else:
            # fallback
            credit_card_number = request.creditCardNumber
            expiry_date = request.expiryDate
            billing_city = request.billingCity
            billing_country = request.billingCountry

        # Card checks
        if not (13 <= len(credit_card_number) <= 19):
            is_valid = False
            reason = f"Invalid credit card length: {len(credit_card_number)}"

        if is_valid and not check_luhn_algorithm(credit_card_number):
            is_valid = False
            reason = "Invalid credit card number (Luhn)"

        if is_valid:
            matched, reason_tmp = check_expiry_date(expiry_date)
            if not matched:
                is_valid = False
                reason = reason_tmp

        # Billing checks
        if is_valid:
            billing_ok, reason_tmp = check_billing_city_country(billing_city, billing_country)
            if not billing_ok:
                is_valid = False
                reason = reason_tmp

        updated_clock = self.order_event_tracker.record_event(
            order_id=order_id,
            service=self.service_name,
            event_name="VerifyTransaction",
            received_clock=received_clock,
        )

        print(
            f"[TransactionVerification] VerifyTransaction => order {order_id}, isValid={is_valid}, reason={reason}, newClock={updated_clock}"
        )

        return tv_pb2.TransactionResponse(
            isValid=is_valid, reason=reason, vectorClock=updated_clock
        )

    # -------------------------------------------------
    #  ClearOrder
    # -------------------------------------------------
    def ClearOrder(self, request, context):
        order_id = request.order_id
        received_clock = dict(request.vectorClock)

        if order_id not in self.orders:
            print(
                f"[TransactionVerification] Order {order_id} not found for clearing - possibly already cleared"
            )
            updated_clock = self.order_event_tracker.record_event(
                order_id=order_id,
                service=self.service_name,
                event_name=self.service_name + ".ClearOrder",
                received_clock=received_clock,
            )
            return tv_pb2.ClearOrderResponse(success=True, vectorClock=updated_clock)

        local_clock = self.order_event_tracker.get_clock(order_id, self.service_name)
        # minimal vector clock checks omitted for brevity
        try:
            del self.orders[order_id]
            updated_clock = self.order_event_tracker.record_event(
                order_id=order_id,
                service=self.service_name,
                event_name=self.service_name + ".ClearOrder",
                received_clock=received_clock,
            )
            print(f"[TransactionVerification] Cleared order {order_id}")
            return tv_pb2.ClearOrderResponse(success=True, vectorClock=updated_clock)
        except Exception as e:
            err = f"Error clearing order data: {str(e)}"
            print(f"[TransactionVerification] {err}")
            return tv_pb2.ClearOrderResponse(success=False, error=err, vectorClock=local_clock)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=5))
    tv_pb2_grpc.add_TransactionVerificationServiceServicer_to_server(
        TransactionVerificationServiceServicer(), server
    )
    server.add_insecure_port("[::]:50052")
    server.start()
    print("[TransactionVerification] SERVICE listening on port 50052.")
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
