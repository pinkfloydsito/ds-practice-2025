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
from opentelemetry.trace import Status, StatusCode

# FIXED: Updated OpenTelemetry setup with correct endpoint
resource = Resource.create(
    attributes={
        "service.name": "fraud_detection",
        "service.version": "1.0.0",
        "deployment.environment": "demo",
    }
)

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


# Trace-enabled helper functions
def get_country_from_ip(ip_address, reader):
    """Get country from IP address with tracing."""
    with tracer.start_as_current_span("fraud.get_country_from_ip") as span:
        span.set_attribute("ip.address", ip_address)
        try:
            if reader:
                response = reader.country(ip_address)
                country = response.country.name
                span.set_attribute("ip.country", country)
                span.set_status(Status(StatusCode.OK))
                return country
            else:
                span.set_attribute("geoip.available", False)
                return "Unknown - GeoIP not available"
        except Exception as e:
            error_msg = f"GeoIP lookup failed: {str(e)}"
            span.set_status(Status(StatusCode.ERROR, error_msg))
            span.record_exception(e)
            return f"Unknown - {str(e)}"


def predict_fraud(order_data):
    """Predict fraud probability with comprehensive tracing."""
    with tracer.start_as_current_span("fraud.predict_fraud") as span:
        # Set span attributes for order details
        span.set_attribute("order.amount", order_data["amount"])
        span.set_attribute("order.payment_method", order_data["payment_method"])
        span.set_attribute("order.billing_country", order_data["billing_country"])
        span.set_attribute("order.billing_city", order_data["billing_city"])
        span.set_attribute("order.ip_address", order_data["ip_address"])

        # Get country from IP with tracing
        ip_country = get_country_from_ip(order_data["ip_address"], geoip_reader)
        span.set_attribute("fraud.ip_country", ip_country)

        # Prepare model input data
        with tracer.start_as_current_span("fraud.prepare_model_input") as prep_span:
            input_data = pd.DataFrame(
                {
                    "billing_city": [order_data["billing_city"]],
                    "billing_country": [order_data["billing_country"]],
                    "amount": [order_data["amount"]],
                    "payment_method": [order_data["payment_method"]],
                }
            )

            # Apply label encoders
            encoded_features = 0
            for col, le in label_encoders.items():
                if col in input_data.columns:
                    try:
                        input_data[col] = le.transform(input_data[col])
                        encoded_features += 1
                    except ValueError:
                        input_data[col] = -1
                        prep_span.add_event(f"Unknown value for {col}, using -1")

            prep_span.set_attribute("model.encoded_features", encoded_features)

        # Model prediction with tracing
        with tracer.start_as_current_span("fraud.model_prediction") as model_span:
            fraud_probability = model.predict_proba(input_data)[0][1]
            model_span.set_attribute("model.base_score", float(fraud_probability))

        # Risk analysis with tracing
        with tracer.start_as_current_span("fraud.risk_analysis") as risk_span:
            ip_country_mismatch = (
                ip_country != order_data["billing_country"]
                and ip_country != "Unknown"
                and not ip_country.startswith("Unknown")
            )

            if ip_country_mismatch:
                fraud_probability = max(fraud_probability, 0.5)
                risk_span.add_event("IP country mismatch detected - score adjusted")

            is_high_risk_country = order_data["billing_country"] in [
                "Russia",
                "North Korea",
                "Syria",
            ]
            is_high_risk_payment = order_data["payment_method"] == "Crypto"

            # Set risk attributes
            risk_span.set_attribute("fraud.ip_country_mismatch", ip_country_mismatch)
            risk_span.set_attribute("fraud.high_risk_country", is_high_risk_country)
            risk_span.set_attribute("fraud.high_risk_payment", is_high_risk_payment)

        # Final fraud assessment
        details = {
            "ip_country": ip_country,
            "ip_country_mismatch": ip_country_mismatch,
            "high_risk_country": is_high_risk_country,
            "high_risk_payment": is_high_risk_payment,
            "model_score": float(fraud_probability),
            "final_score": float(fraud_probability),
        }

        # Set final span attributes
        span.set_attribute("fraud.final_score", float(fraud_probability))
        span.set_attribute("fraud.threshold", FRAUD_THRESHOLD)
        span.set_attribute(
            "fraud.is_fraudulent", float(fraud_probability) > FRAUD_THRESHOLD
        )

        if fraud_probability > FRAUD_THRESHOLD:
            span.set_status(Status(StatusCode.ERROR, "Fraudulent transaction detected"))
        else:
            span.set_status(Status(StatusCode.OK))

        return fraud_probability, details


class TracingServerInterceptor(grpc.ServerInterceptor):
    """Server interceptor to extract trace context from gRPC calls."""

    def intercept_service(self, continuation, handler_call_details):
        # Extract metadata
        metadata_dict = {}
        if handler_call_details.invocation_metadata:
            for key, value in handler_call_details.invocation_metadata:
                metadata_dict[key] = value

        # For now, we'll create a new span for each gRPC call
        # In a full implementation, you'd extract the trace context from metadata
        method_name = (
            handler_call_details.method.split("/")[-1]
            if handler_call_details.method
            else "unknown"
        )

        with tracer.start_as_current_span(f"grpc.{method_name}") as span:
            span.set_attribute("rpc.system", "grpc")
            span.set_attribute("rpc.service", "FraudDetectionService")
            span.set_attribute("rpc.method", method_name)

            try:
                return continuation(handler_call_details)
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise


class FraudDetectionService(fd_pb2_grpc.FraudDetectionServiceServicer):
    def __init__(self):
        self.orders = {}
        self.service_name = "fraud_detection"
        self.order_event_tracker = OrderEventTracker()

        # UPDATED: Enhanced metrics with better labels
        self.order_counter = meter.create_counter(
            "fraud_checks_total", description="Total fraud checks performed", unit="1"
        )
        self.fraud_score_hist = meter.create_histogram(
            "fraud_score_distribution",
            description="Distribution of fraud scores",
            unit="1",
        )
        self.processing_duration = meter.create_histogram(
            "fraud_processing_duration_seconds",
            description="Time taken to process fraud checks",
            unit="s",
        )

    def InitializeOrder(self, request, context):
        """Initialize order with comprehensive tracing."""
        with tracer.start_as_current_span("fraud.initialize_order") as span:
            order_id = request.order_id

            # Set span attributes
            span.set_attribute("order.id", order_id)
            span.set_attribute("order.amount", request.amount)
            span.set_attribute("order.payment_method", request.payment_method)
            span.set_attribute("order.billing_country", request.billing_country)

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
                span.add_event("Order initialized in event tracker")

            updated_clock = self.order_event_tracker.record_event(
                order_id,
                self.service_name,
                self.service_name + ".InitializeOrder",
                received_clock,
            )

            span.set_attribute("vector_clock.updated", True)
            span.set_status(Status(StatusCode.OK))

            return fd_pb2.FraudInitResponse(success=True, vectorClock=updated_clock)

    def CheckFraud(self, request, context):
        """Check fraud with comprehensive tracing and metrics."""
        import time

        start_time = time.time()

        with tracer.start_as_current_span("fraud.check_fraud") as span:
            order_id = request.order_id
            span.set_attribute("order.id", order_id)

            # Get or create order data
            stored = self.orders.get(order_id)
            if not stored:
                span.add_event("Order not found in cache, using request data")
                stored = {
                    "amount": request.amount,
                    "ip_address": request.ip_address,
                    "email": request.email,
                    "billing_country": request.billing_country,
                    "billing_city": request.billing_city,
                    "payment_method": request.payment_method,
                }
            else:
                span.add_event("Order found in cache")

            received_clock = dict(request.vectorClock)

            # Predict fraud with tracing
            fraud_probability, details = predict_fraud(stored)

            # Decision logic with tracing
            with tracer.start_as_current_span("fraud.make_decision") as decision_span:
                action = "APPROVE"
                reasons = []

                if fraud_probability > FRAUD_THRESHOLD:
                    action = "REJECT"
                    decision_span.add_event(
                        "Transaction rejected due to high fraud score"
                    )

                    if details["model_score"] > 0.5:
                        reasons.append(
                            "Transaction pattern matches known fraudulent behavior"
                        )
                    if details["high_risk_country"]:
                        reasons.append("High-risk country")
                    if details["high_risk_payment"]:
                        reasons.append("High-risk payment method")
                    if details["ip_country_mismatch"]:
                        reasons.append("IP country mismatch with billing country")

                # Email-based fraud detection
                email = stored["email"]
                if ".fraud" in email or "test" in email:
                    action = "REJECT"
                    reasons.append("Email domain indicates potential fraud")
                    decision_span.add_event(
                        "Transaction rejected due to suspicious email"
                    )

                decision_span.set_attribute("fraud.action", action)
                decision_span.set_attribute("fraud.reasons_count", len(reasons))

                if action == "REJECT":
                    decision_span.set_status(
                        Status(StatusCode.ERROR, "Transaction rejected")
                    )
                else:
                    decision_span.set_status(Status(StatusCode.OK))

            # Record metrics
            processing_time = time.time() - start_time
            self.order_counter.add(1, {"action": action})
            self.fraud_score_hist.record(fraud_probability, {"action": action})
            self.processing_duration.record(processing_time, {"action": action})

            # Update vector clock
            updated_clock = self.order_event_tracker.record_event(
                order_id,
                self.service_name,
                self.service_name + ".CheckFraud",
                received_clock,
            )

            # Set final span attributes
            span.set_attribute("fraud.action", action)
            span.set_attribute("fraud.score", fraud_probability)
            span.set_attribute("fraud.processing_time_seconds", processing_time)
            span.set_status(Status(StatusCode.OK))

            print(
                f"[FraudDetection] Order {order_id}: {action} (score: {fraud_probability:.3f})"
            )

            return fd_pb2.FraudResponse(
                fraud_probability=float(fraud_probability),
                action=action,
                details=details,
                reasons=reasons,
                vectorClock=updated_clock,
            )

    def ClearOrder(self, request, context):
        """Clear order with tracing."""
        with tracer.start_as_current_span("fraud.clear_order") as span:
            order_id = request.order_id
            span.set_attribute("order.id", order_id)

            received_clock = dict(request.vectorClock)

            if order_id in self.orders:
                del self.orders[order_id]
                span.add_event("Order data cleared from cache")
            else:
                span.add_event("Order not found in cache")

            updated_clock = self.order_event_tracker.record_event(
                order_id,
                self.service_name,
                self.service_name + ".ClearOrder",
                received_clock,
            )

            span.set_status(Status(StatusCode.OK))

            return fd_pb2.ClearOrderResponse(success=True, vectorClock=updated_clock)


def serve():
    """Start the fraud detection service with tracing."""
    tracing_interceptor = TracingServerInterceptor()

    # Create server with interceptor
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10), interceptors=[tracing_interceptor]
    )

    fd_pb2_grpc.add_FraudDetectionServiceServicer_to_server(
        FraudDetectionService(), server
    )
    server.add_insecure_port("[::]:50051")
    server.start()

    print("[FraudDetection] Service running on port 50051 with tracing enabled")
    logging.info("[FraudDetection] Service running on port 50051 with tracing enabled")

    server.wait_for_termination()


if __name__ == "__main__":
    serve()
