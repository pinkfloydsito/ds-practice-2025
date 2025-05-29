import logging
import sys
import os
import datetime
from datetime import datetime as dt

# OTEL Imports
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

# OTEL setup
resource = Resource(attributes={SERVICE_NAME: "transaction_verification"})
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://observability:4318/v1/traces"))
)

metrics.set_meter_provider(MeterProvider(resource=resource))
metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint="http://observability:4318/v1/metrics"))
from opentelemetry.sdk.metrics import MeterProvider
metrics.set_meter_provider(MeterProvider(metric_readers=[metric_reader]))
meter = metrics.get_meter(__name__)

# Example metrics
verification_counter = meter.create_counter(
    "transaction_verification_validations_total",
    description="Total number of validation attempts",
)

validation_duration = meter.create_histogram(
    "transaction_verification_duration_ms",
    description="Duration of transaction validation steps in milliseconds",
)

# Path setup
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
models_path = os.path.abspath(os.path.join(FILE, "../../../utils/models"))
vector_clock_path = os.path.abspath(os.path.join(FILE, "../../../utils/vector_clock"))
grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/transaction_verification"))
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
    pattern = r"^(0[1-9]|1[0-2])/(20)?\d{2}$"
    if not re.match(pattern, expiry_date):
        return False, f"Invalid expiry date format: {expiry_date}"

    try:
        if len(expiry_date) == 5:
            month, year_short = expiry_date.split("/")
            year = int("20" + year_short)
        else:
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
    if not city or not country:
        return False, "Billing address is incomplete"
    return True, "OK"

class TransactionVerificationServiceServicer(tv_pb2_grpc.TransactionVerificationServiceServicer):
    def __init__(self):
        self.orders = {}
        self.service_name = "transaction_verification"
        self.order_event_tracker = OrderEventTracker()

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

        updated_clock = self.order_event_tracker.record_event(
            order_id, self.service_name, "InitializeOrder", received_clock
        )
        return tv_pb2.TransactionInitResponse(success=True, vectorClock=updated_clock)

    def CheckCard(self, request, context):
        order_id = request.order_id
        is_valid = True
        reason = "OK"
        received_clock = dict(request.vectorClock)
        start = datetime.datetime.now()

        with tracer.start_as_current_span("CheckCard"):
            cached = self.orders.get(order_id)
            credit_card_number = cached["creditCardNumber"] if cached else request.creditCardNumber
            expiry_date = cached["expiryDate"] if cached else request.expiryDate

            if not (13 <= len(credit_card_number) <= 19):
                is_valid = False
                reason = f"Invalid credit card length: {len(credit_card_number)}"
            elif not check_luhn_algorithm(credit_card_number):
                is_valid = False
                reason = "Invalid credit card number (Luhn check failed)"
            else:
                expiry_ok, expiry_reason = check_expiry_date(expiry_date)
                if not expiry_ok:
                    is_valid = False
                    reason = expiry_reason

        duration = (datetime.datetime.now() - start).total_seconds() * 1000
        validation_duration.record(duration)
        verification_counter.add(1)

        updated_clock = self.order_event_tracker.record_event(
            order_id, self.service_name, "CheckCard", received_clock
        )
        return tv_pb2.TransactionResponse(isValid=is_valid, reason=reason, vectorClock=updated_clock)

    def CheckBilling(self, request, context):
        order_id = request.order_id
        is_valid = True
        reason = "OK"
        received_clock = dict(request.vectorClock)
        start = datetime.datetime.now()

        with tracer.start_as_current_span("CheckBilling"):
            cached = self.orders.get(order_id)
            billing_city = cached["billingCity"] if cached else request.billingCity
            billing_country = cached["billingCountry"] if cached else request.billingCountry

            billing_ok, addr_reason = check_billing_city_country(billing_city, billing_country)
            if not billing_ok:
                is_valid = False
                reason = addr_reason

        duration = (datetime.datetime.now() - start).total_seconds() * 1000
        validation_duration.record(duration)
        verification_counter.add(1)

        updated_clock = self.order_event_tracker.record_event(
            order_id, self.service_name, "CheckBilling", received_clock
        )
        return tv_pb2.TransactionResponse(isValid=is_valid, reason=reason, vectorClock=updated_clock)

    def VerifyTransaction(self, request, context):
        order_id = request.order_id
        is_valid = True
        reason = "OK"
        received_clock = dict(request.vectorClock)
        start = datetime.datetime.now()

        with tracer.start_as_current_span("VerifyTransaction"):
            cached = self.orders.get(order_id)
            credit_card_number = cached["creditCardNumber"] if cached else request.creditCardNumber
            expiry_date = cached["expiryDate"] if cached else request.expiryDate
            billing_city = cached["billingCity"] if cached else request.billingCity
            billing_country = cached["billingCountry"] if cached else request.billingCountry

            if not (13 <= len(credit_card_number) <= 19):
                is_valid = False
                reason = f"Invalid credit card length: {len(credit_card_number)}"
            elif not check_luhn_algorithm(credit_card_number):
                is_valid = False
                reason = "Invalid credit card number (Luhn)"
            else:
                matched, reason_tmp = check_expiry_date(expiry_date)
                if not matched:
                    is_valid = False
                    reason = reason_tmp
                else:
                    billing_ok, reason_tmp = check_billing_city_country(billing_city, billing_country)
                    if not billing_ok:
                        is_valid = False
                        reason = reason_tmp

        duration = (datetime.datetime.now() - start).total_seconds() * 1000
        validation_duration.record(duration)
        verification_counter.add(1)

        updated_clock = self.order_event_tracker.record_event(
            order_id, self.service_name, "VerifyTransaction", received_clock
        )
        return tv_pb2.TransactionResponse(isValid=is_valid, reason=reason, vectorClock=updated_clock)

    def ClearOrder(self, request, context):
        order_id = request.order_id
        received_clock = dict(request.vectorClock)

        try:
            if order_id in self.orders:
                del self.orders[order_id]

            updated_clock = self.order_event_tracker.record_event(
                order_id, self.service_name, "ClearOrder", received_clock
            )
            return tv_pb2.ClearOrderResponse(success=True, vectorClock=updated_clock)
        except Exception as e:
            local_clock = self.order_event_tracker.get_clock(order_id, self.service_name)
            return tv_pb2.ClearOrderResponse(success=False, error=str(e), vectorClock=local_clock)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=5))
    tv_pb2_grpc.add_TransactionVerificationServiceServicer_to_server(
        TransactionVerificationServiceServicer(), server
    )
    server.add_insecure_port("[::]:50052")
    print("[TransactionVerification] SERVICE listening on port 50052.")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
