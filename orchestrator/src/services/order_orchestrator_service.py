import logging
import sys
import os
import threading
import time
from typing import Any, Dict, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from services.transaction_service import TransactionService
from services.suggestions_service import SuggestionsService
from services.fraud_service import FraudService
from services.raft_service import RaftService

# OpenTelemetry
from opentelemetry import trace, metrics
from opentelemetry.trace import get_tracer
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

# Setup OpenTelemetry
resource = Resource.create(attributes={"service.name": "order_orchestrator"})
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = get_tracer(__name__)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://observability:4318/v1/traces"))
)

reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint="http://observability:4318/v1/metrics")
)
metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
meter = metrics.get_meter(__name__)

# Metrics
orders_processed = meter.create_counter(
    "orchestrator.orders_processed", description="Total processed orders"
)
failed_orders = meter.create_counter(
    "orchestrator.orders_failed", description="Failed order attempts"
)
order_duration = meter.create_histogram("orchestrator.order_duration_ms", unit="ms")
active_orders = meter.create_up_down_counter(
    "orchestrator.active_orders", description="Orders being processed"
)

# Path fix
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
models_path = os.path.abspath(os.path.join(FILE, "../../../../../../utils/models"))
sys.path.insert(0, models_path)

from bookstore_models import OrderInfo, UserInfo, BillingInfo, CreditCardInfo

logger = logging.getLogger(__name__)


class OrderOrchestratorService:
    def __init__(self, grpc_factory, order_event_tracker):
        self.order_event_tracker = order_event_tracker
        self.transaction_service = TransactionService(grpc_factory, order_event_tracker)
        self.fraud_service = FraudService(grpc_factory, order_event_tracker)
        self.suggestions_service = SuggestionsService(grpc_factory, order_event_tracker)
        self.raft_service = RaftService(grpc_factory)

    def initialize_services(self, order, user, credit_card, billing) -> bool:
        self.order_event_tracker.initialize_order(order.order_id)
        self.order_event_tracker.record_event(
            order.order_id, "orchestrator", "initializer"
        )

        tx_init_ok = self.transaction_service.initialize_order(
            order.order_id, credit_card, billing
        )
        fraud_init_ok = self.fraud_service.initialize_order(order, user, billing)
        sugg_init_ok = self.suggestions_service.initialize_order(
            order.order_id, order.book_tokens, limit=3
        )

        return tx_init_ok and fraud_init_ok and sugg_init_ok

    def _get_final_vector_clock(self, order_id: str) -> Dict[str, int]:
        return self.order_event_tracker.get_clock(order_id, "orchestrator")

    def _clear_service_data(
        self, service, order_id: str, final_vector_clock: Dict[str, int]
    ) -> bool:
        try:
            print(f"[Orchestrator] Clearing data for {service.__class__.__name__}")
            return service.clear_order_data(order_id, final_vector_clock)
        except Exception as e:
            logger.error(f"Error clearing data for {service.__class__.__name__}: {e}")
            return False

    def broadcast_clear_order(self, order_id: str) -> Tuple[bool, List[str]]:
        errors = []
        final_vector_clock = self._get_final_vector_clock(order_id)
        self.order_event_tracker.record_event(
            order_id, "orchestrator", "broadcast_clear_order"
        )

        services = [
            self.transaction_service,
            self.fraud_service,
            self.suggestions_service,
        ]

        # Record final event before clearing
        self.order_event_tracker.record_event(
            order_id, "orchestrator", "broadcast_clear_order"
        )

        # Get the updated final vector clock after recording the event
        final_vector_clock = self._get_final_vector_clock(order_id)

        print(
            f"[Orchestrator] Broadcasting clear order for {order_id} with final vector clock: {final_vector_clock}"
        )

        success = True
        for service in services:
            if not self._clear_service_data(service, order_id, final_vector_clock):
                errors.append(f"Failed to clear data for {service.__class__.__name__}")
                success = False

        return success, errors

    def process_order(
        self,
        order: OrderInfo,
        user: UserInfo,
        credit_card: CreditCardInfo,
        billing: BillingInfo,
    ) -> Tuple[bool, Dict[str, Any]]:
        with tracer.start_as_current_span("orchestrator.process_order") as span:
            span.set_attribute("order_id", order.order_id)
            start_time = time.time()
            active_orders.add(1)

            results = {
                "billing": None,
                "card": None,
                "fraud": None,
                "suggestions": None,
            }
            errors = []

            billing_flag = threading.Event()
            card_flag = threading.Event()
            fraud_flag = threading.Event()
            early_termination = threading.Event()
            results_lock = threading.Lock()

            def billing_worker():
                with tracer.start_as_current_span("orchestrator.billing_check"):
                    try:
                        billing_result = self.transaction_service.check_billing(
                            order.order_id, billing
                        )
                        with results_lock:
                            results["billing"] = billing_result
                        if not billing_result.success:
                            errors.append(billing_result.error or "Billing failed")
                            early_termination.set()
                    finally:
                        billing_flag.set()

            def card_worker():
                billing_flag.wait()
                if early_termination.is_set():
                    return
                with tracer.start_as_current_span("orchestrator.card_check"):
                    try:
                        card_result = self.transaction_service.check_card(
                            order.order_id, credit_card
                        )
                        with results_lock:
                            results["card"] = card_result
                        if not card_result.success:
                            errors.append(card_result.error or "Card failed")
                            early_termination.set()
                    finally:
                        card_flag.set()

            def fraud_worker():
                with tracer.start_as_current_span("orchestrator.fraud_check"):
                    try:
                        fraud_result = self.fraud_service.check_fraud(
                            order, user, billing
                        )
                        with results_lock:
                            results["fraud"] = fraud_result
                        if not fraud_result.success:
                            errors.append(fraud_result.error or "Fraud failed")
                            early_termination.set()
                    finally:
                        fraud_flag.set()

            def suggestions_worker():
                fraud_flag.wait()
                card_flag.wait()
                if early_termination.is_set():
                    return
                with tracer.start_as_current_span("orchestrator.suggestions"):
                    try:
                        suggestions = self.suggestions_service.get_suggestions(
                            order.order_id
                        )
                        with results_lock:
                            results["suggestions"] = suggestions
                    except Exception as e:
                        errors.append(str(e))

            futures = {}
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures["billing"] = executor.submit(billing_worker)
                futures["card"] = executor.submit(card_worker)
                futures["fraud"] = executor.submit(fraud_worker)
                futures["suggestions"] = executor.submit(suggestions_worker)

                def monitor():
                    while not all(f.done() for f in futures.values()):
                        if early_termination.is_set():
                            for name, f in futures.items():
                                if not f.done():
                                    f.cancel()
                            break
                        time.sleep(0.05)

                termination_thread = threading.Thread(target=monitor, daemon=True)
                termination_thread.start()
                for _ in as_completed(futures.values()):
                    pass
                termination_thread.join(timeout=1)

            broadcast_success, broadcast_errors = self.broadcast_clear_order(
                order.order_id
            )

            elapsed = (time.time() - start_time) * 1000
            order_duration.record(elapsed)
            active_orders.add(-1)

            if errors:
                failed_orders.add(1)
                return False, {
                    "error": {"code": "ORDER_REJECTED", "message": " / ".join(errors)}
                }

            orders_processed.add(1)
            return True, {
                "orderId": order.order_id,
                "status": "Order Approved",
                "suggestedBooks": results["suggestions"].data
                if results["suggestions"]
                else [],
            }
