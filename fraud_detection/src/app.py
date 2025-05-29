import logging
import sys
import os
import grpc
from concurrent import futures
import pandas as pd
import geoip2.database
import joblib

from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

# OpenTelemetry setup
resource = Resource.create(attributes={"service.name": "fraud_detection"})

tracer_provider = TracerProvider(resource=resource)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer(__name__)
span_exporter = OTLPSpanExporter(endpoint="http://observability:4318/v1/traces")
tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))

metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint="http://observability:4318/v1/metrics")
)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter(__name__)

logger = logging.getLogger(__name__)
FRAUD_THRESHOLD = float(os.environ.get("FRAUD_THRESHOLD", "0.7"))

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/fraud_detection"))
vector_clock_path = os.path.abspath(os.path.join(FILE, "../../../utils/vector_clock"))
sys.path.insert(0, grpc_path)
sys.path.insert(0, vector_clock_path)

import fraud_detection_pb2 as fd_pb2
import fraud_detection_pb2_grpc as fd_pb2_grpc
from vector_clock import OrderEventTracker

GEOIP_PATH = os.path.join(os.path.dirname(__file__), "GeoLite2-Country.mmdb")
MODEL_PATH = os.path.join(os.path.dirname(__file__), "fraud_model.pkl")
ENCODERS_PATH = os.path.join(os.path.dirname(__file__), "label_encoders.pkl")

logging.basicConfig(level=logging.INFO)

model = joblib.load(MODEL_PATH)
label_encoders = joblib.load(ENCODERS_PATH)
try:
    geoip_reader = geoip2.database.Reader(GEOIP_PATH)
except:
    geoip_reader = None

def get_country_from_ip(ip_address, reader):
    try:
        response = reader.country(ip_address)
        return response.country.name
    except Exception as e:
        return f"Unknown error {e}"

def predict_fraud(order_data):
    ip_address = order_data["ip_address"]
    ip_country = get_country_from_ip(ip_address, geoip_reader)

    input_data = pd.DataFrame({
        "billing_city": [order_data["billing_city"]],
        "billing_country": [order_data["billing_country"]],
        "amount": [order_data["amount"]],
        "payment_method": [order_data["payment_method"]],
    })

    for col, le in label_encoders.items():
        if col in input_data.columns:
            try:
                input_data[col] = le.transform(input_data[col])
            except ValueError:
                input_data[col] = -1

    fraud_probability = model.predict_proba(input_data)[0][1]
    ip_country_mismatch = ip_country != order_data["billing_country"] and ip_country != "Unknown"

    if ip_country_mismatch:
        fraud_probability = max(fraud_probability, 0.5)

    is_high_risk_country = order_data["billing_country"] in ["Russia", "North Korea", "Syria"]
    is_high_risk_payment = order_data["payment_method"] == "Crypto"

    details = {
        "ip_country": ip_country,
        "ip_country_mismatch": ip_country_mismatch,
        "high_risk_country": is_high_risk_country,
        "high_risk_payment": is_high_risk_payment,
        "model_score": float(fraud_probability),
        "final_score": float(fraud_probability),
    }
    return fraud_probability, details

class FraudDetectionService(fd_pb2_grpc.FraudDetectionServiceServicer):
    def __init__(self):
        self.orders = {}
        self.service_name = "fraud_detection"
        self.order_event_tracker = OrderEventTracker()
        self.order_counter = meter.create_counter("fraud_checks_total")
        self.fraud_score_hist = meter.create_histogram("fraud_score_distribution")

    def InitializeOrder(self, request, context):
        order_id = request.order_id
        self.orders[order_id] = {
            "amount": request.amount,
            "ip_address": request.ip_address,
            "email": request.email,
            "billing_country": request.billing_country,
            "billing_city": request.billing_city,
            "payment_method": request.payment_method,
        }
        received_clock = dict(request.vectorClock)
        if not self.order_event_tracker.order_exists(order_id):
            self.order_event_tracker.initialize_order(order_id)
        updated_clock = self.order_event_tracker.record_event(
            order_id, self.service_name, self.service_name + ".InitializeOrder", received_clock
        )
        return fd_pb2.FraudInitResponse(success=True, vectorClock=updated_clock)

    def CheckFraud(self, request, context):
        order_id = request.order_id
        stored = self.orders.get(order_id)
        received_clock = dict(request.vectorClock)

        if not stored:
            stored = {
                "amount": request.amount,
                "ip_address": request.ip_address,
                "email": request.email,
                "billing_country": request.billing_country,
                "billing_city": request.billing_city,
                "payment_method": request.payment_method,
            }

        with tracer.start_as_current_span("fraud_check"):
            fraud_probability, details = predict_fraud(stored)

        action = "APPROVE"
        reasons = []
        if fraud_probability > FRAUD_THRESHOLD:
            action = "REJECT"
            if details["model_score"] > 0.5:
                reasons.append("Transaction pattern matches known fraudulent behavior")
            if details["high_risk_country"]:
                reasons.append("High-risk country")
            if details["high_risk_payment"]:
                reasons.append("High-risk payment")
            if details["ip_country_mismatch"]:
                reasons.append("IP mismatch")

        self.order_counter.add(1, {"action": action})
        self.fraud_score_hist.record(fraud_probability, {"action": action})

        updated_clock = self.order_event_tracker.record_event(
            order_id, self.service_name, self.service_name + ".CheckFraud", received_clock
        )

        return fd_pb2.FraudResponse(
            fraud_probability=float(fraud_probability),
            action=action,
            details=details,
            reasons=reasons,
            vectorClock=updated_clock,
        )

    def ClearOrder(self, request, context):
        order_id = request.order_id
        received_clock = dict(request.vectorClock)
        if order_id in self.orders:
            del self.orders[order_id]
        updated_clock = self.order_event_tracker.record_event(
            order_id, self.service_name, self.service_name + ".ClearOrder", received_clock
        )
        return fd_pb2.ClearOrderResponse(success=True, vectorClock=updated_clock)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor())
    fd_pb2_grpc.add_FraudDetectionServiceServicer_to_server(FraudDetectionService(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    logging.info("[FraudDetection] Service running on port 50051")
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
