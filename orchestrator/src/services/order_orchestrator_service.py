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
from opentelemetry.trace import get_tracer, Status, StatusCode
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
trace.get_tracer_provider().add_span_processor(  # type: ignore [reportAttributeAccessIssue]
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://observability:4318/v1/traces"))
)

reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint="http://observability:4318/v1/metrics")
)
metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
meter = metrics.get_meter(__name__)

# Metrics
orders_processed_total = meter.create_counter(
    "orchestrator_orders_processed_total",
    description="Total processed orders",
    unit="1",
)

orders_failed_total = meter.create_counter(
    "orchestrator_orders_failed_total", description="Failed order attempts", unit="1"
)

orders_by_status = meter.create_counter(
    "orchestrator_orders_by_status", description="Orders by final status", unit="1"
)

order_duration_histogram = meter.create_histogram(
    "orchestrator_order_duration_seconds",
    description="Order processing duration",
    unit="s",
)

service_call_duration = meter.create_histogram(
    "orchestrator_service_call_duration_seconds",
    description="Individual service call duration",
    unit="s",
)

active_orders_gauge = meter.create_up_down_counter(
    "orchestrator_active_orders", description="Currently active orders", unit="1"
)

# Path fix
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
models_path = os.path.abspath(os.path.join(FILE, "../../../../../../utils/models"))
sys.path.insert(0, models_path)

from bookstore_models import OrderInfo, UserInfo, BillingInfo, CreditCardInfo  # type: ignore [reportAttributeAccessIssue]

logger = logging.getLogger(__name__)


class OrderOrchestratorService:
    def __init__(self, grpc_factory, order_event_tracker):
        self.order_event_tracker = order_event_tracker
        self.transaction_service = TransactionService(grpc_factory, order_event_tracker)
        self.fraud_service = FraudService(grpc_factory, order_event_tracker)
        self.suggestions_service = SuggestionsService(grpc_factory, order_event_tracker)
        self.raft_service = RaftService(grpc_factory)

    def initialize_services(self, order, user, credit_card, billing) -> bool:
        with tracer.start_as_current_span("orchestrator.initialize_services") as span:
            self.order_event_tracker.initialize_order(order.order_id)
            self.order_event_tracker.record_event(
                order.order_id, "orchestrator", "initializer"
            )

            with tracer.start_as_current_span("orchestrator.init_transaction_service"):
                tx_init_ok = self.transaction_service.initialize_order(
                    order.order_id, credit_card, billing
                )

                span.set_attribute("transaction_service.init_success", tx_init_ok)

            with tracer.start_as_current_span("orchestrator.init_fraud_service"):
                fraud_init_ok = self.fraud_service.initialize_order(
                    order, user, billing
                )
                span.set_attribute("fraud_service.init_success", fraud_init_ok)

            with tracer.start_as_current_span("orchestrator.init_suggestions_service"):
                sugg_init_ok = self.suggestions_service.initialize_order(
                    order.order_id, order.book_tokens, limit=3
                )
                span.set_attribute("suggestions_service.init_success", sugg_init_ok)

        overall_success = tx_init_ok and fraud_init_ok and sugg_init_ok
        span.set_attribute("overall_init_success", overall_success)

        if not overall_success:
            span.set_status(Status(StatusCode.ERROR, "Service initialization failed"))

        return overall_success

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
        with tracer.start_as_current_span("orchestrator.process_order") as main_span:
            main_span.set_attribute("order_id", order.order_id)
            main_span.set_attribute("order.id", order.order_id)
            main_span.set_attribute("order.amount", order.amount)
            main_span.set_attribute("order.items_count", len(order.book_tokens))
            main_span.set_attribute("user.id", user.user_id)
            main_span.set_attribute("user.ip", user.ip_address)
            main_span.set_attribute("billing.country", billing.country)
            main_span.set_attribute("billing.city", billing.city)

            start_time = time.time()
            active_orders_gauge.add(1)

            for i, item in enumerate(order.book_tokens):
                main_span.set_attribute(f"order.item.{i}", item)

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
                billing_result = None
                with tracer.start_as_current_span("orchestrator.billing_check") as span:
                    span.set_attribute("order.id", order.order_id)
                    service_start = time.time()

                    try:
                        billing_result = self.transaction_service.check_billing(
                            order.order_id, billing
                        )
                        with results_lock:
                            results["billing"] = billing_result

                        span.set_attribute("billing.success", billing_result.success)
                        if not billing_result.success:
                            errors.append(billing_result.error or "Billing failed")

                            span.set_status(
                                Status(StatusCode.ERROR, billing_result.error)
                            )
                            early_termination.set()
                        else:
                            span.set_status(Status(StatusCode.OK))
                    except Exception as e:
                        span.set_status(Status(StatusCode.ERROR, str(e)))
                        span.record_exception(e)

                        errors.append(f"Billing service error: {str(e)}")
                        early_termination.set()

                    finally:
                        service_duration = time.time() - service_start
                        service_call_duration.record(
                            service_duration,
                            {
                                "service": "billing",
                                "success": str(
                                    billing_result.success if billing_result else False
                                ),
                            },
                        )
                        billing_flag.set()

            def card_worker():
                billing_flag.wait()
                if early_termination.is_set():
                    return
                with tracer.start_as_current_span("orchestrator.card_check") as span:
                    span.set_attribute("order.id", order.order_id)
                    service_start = time.time()
                    card_result = None

                    try:
                        card_result = self.transaction_service.check_card(
                            order.order_id, credit_card
                        )
                        with results_lock:
                            results["card"] = card_result

                        span.set_attribute("card.success", card_result.success)

                        if not card_result.success:
                            errors.append(card_result.error or "Card failed")

                            span.set_status(Status(StatusCode.ERROR, card_result.error))

                            early_termination.set()
                        else:
                            span.set_status(Status(StatusCode.OK))

                    except Exception as e:
                        span.set_status(Status(StatusCode.ERROR, str(e)))
                        span.record_exception(e)
                        errors.append(f"Card service error: {str(e)}")
                        early_termination.set()

                    finally:
                        service_duration = time.time() - service_start
                        service_call_duration.record(
                            service_duration,
                            {
                                "service": "card",
                                "success": str(
                                    card_result.success if card_result else False
                                ),
                            },
                        )
                        card_flag.set()

            def fraud_worker():
                fraud_result = None
                with tracer.start_as_current_span("orchestrator.fraud_check") as span:
                    span.set_attribute("order.id", order.order_id)
                    service_start = time.time()

                    try:
                        fraud_result = self.fraud_service.check_fraud(
                            order, user, billing
                        )

                        with results_lock:
                            results["fraud"] = fraud_result

                        span.set_attribute("fraud.success", fraud_result.success)

                        if not fraud_result.success:
                            errors.append(fraud_result.error or "Fraud failed")
                            early_termination.set()
                            span.set_status(
                                Status(StatusCode.ERROR, fraud_result.error)
                            )
                        else:
                            span.set_status(Status(StatusCode.OK))

                    except Exception as e:
                        span.set_status(Status(StatusCode.ERROR, str(e)))
                        span.record_exception(e)
                        errors.append(f"Fraud service error: {str(e)}")
                        early_termination.set()
                    finally:
                        service_duration = time.time() - service_start
                        service_call_duration.record(
                            service_duration,
                            {
                                "service": "fraud",
                                "success": str(
                                    fraud_result.success if fraud_result else False
                                ),
                            },
                        )
                        fraud_flag.set()

            def suggestions_worker():
                fraud_flag.wait()
                card_flag.wait()
                if early_termination.is_set():
                    return

                with tracer.start_as_current_span("orchestrator.suggestions") as span:
                    span.set_attribute("order.id", order.order_id)
                    service_start = time.time()

                    try:
                        suggestions = self.suggestions_service.get_suggestions(
                            order.order_id
                        )

                        with results_lock:
                            results["suggestions"] = suggestions

                        span.set_attribute(
                            "suggestions.count",
                            len(suggestions.data if suggestions.data else []),
                        )
                        span.set_status(Status(StatusCode.OK))

                    except Exception as e:
                        span.set_status(Status(StatusCode.ERROR, str(e)))
                        span.record_exception(e)
                        errors.append(f"Suggestions service error: {str(e)}")
                    finally:
                        service_duration = time.time() - service_start
                        service_call_duration.record(
                            service_duration,
                            {"service": "suggestions", "success": "true"},
                        )

            futures = {}
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures["billing"] = executor.submit(billing_worker)
                futures["card"] = executor.submit(card_worker)
                futures["fraud"] = executor.submit(fraud_worker)
                futures["suggestions"] = executor.submit(suggestions_worker)

                def monitor():
                    while not all(f.done() for f in futures.values()):
                        if early_termination.is_set():
                            for _, f in futures.items():
                                if not f.done():
                                    f.cancel()
                            break
                        time.sleep(0.05)

                termination_thread = threading.Thread(target=monitor, daemon=True)
                termination_thread.start()
                for _ in as_completed(futures.values()):
                    pass
                termination_thread.join(timeout=1)

            _, _ = self.broadcast_clear_order(order.order_id)

            # Calculate final metrics
            elapsed = time.time() - start_time
            order_duration_histogram.record(elapsed)
            active_orders_gauge.add(-1)

            # Determine final status and record metrics
            if errors:
                orders_failed_total.add(1)
                orders_by_status.add(1, {"status": "FAILED"})
                main_span.set_status(Status(StatusCode.ERROR, " / ".join(errors)))
                main_span.set_attribute("order.final_status", "FAILED")
                main_span.set_attribute("order.error_count", len(errors))

                return False, {
                    "error": {"code": "ORDER_REJECTED", "message": " / ".join(errors)}
                }

            orders_processed_total.add(1)
            orders_by_status.add(1, {"status": "APPROVED"})
            main_span.set_status(Status(StatusCode.OK))
            main_span.set_attribute("order.final_status", "APPROVED")
            main_span.set_attribute(
                "order.suggestions_count",
                len(
                    results["suggestions"].data
                    if results["suggestions"] and results["suggestions"].data
                    else []
                ),
            )

            return True, {
                "orderId": order.order_id,
                "status": "Order Approved",
                "suggestedBooks": results["suggestions"].data
                if results["suggestions"]
                else [],
            }
