import logging
import sys
import os
import threading
from typing import Any, Dict, Tuple, List

from concurrent.futures import ThreadPoolExecutor, as_completed

from services.transaction_service import TransactionService
from services.suggestions_service import SuggestionsService
from services.fraud_service import FraudService

logger = logging.getLogger(__name__)


FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
models_path = os.path.abspath(os.path.join(FILE, "../../../../../../utils/models"))
sys.path.insert(0, models_path)

from bookstore_models import OrderInfo, UserInfo, BillingInfo, CreditCardInfo


class OrderOrchestratorService:
    """Orchestrates the checkout process across multiple microservices."""

    def __init__(self, grpc_factory, order_event_tracker):
        self.order_event_tracker = order_event_tracker
        self.transaction_service = TransactionService(grpc_factory, order_event_tracker)
        self.fraud_service = FraudService(grpc_factory, order_event_tracker)
        self.suggestions_service = SuggestionsService(grpc_factory, order_event_tracker)

    def initialize_services(
        self,
        order: OrderInfo,
        user: UserInfo,
        credit_card: CreditCardInfo,
        billing: BillingInfo,
    ) -> bool:
        """
        Initialize all required services before final processing.
        This calls InitializeOrder on transaction, fraud, and suggestions.
        """
        # first initialize the vector clock
        self.order_event_tracker.initialize_order(order.order_id)
        self.order_event_tracker.record_event(
            order.order_id, "orchestrator", "initialize_order"
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
        """Get the final vector clock for the order."""
        return self.order_event_tracker.get_clock(order_id, "orchestrator")

    def _clear_service_data(
        self, service, order_id: str, final_vector_clock: Dict[str, int]
    ) -> bool:
        """Clear data for a specific service with the final vector clock."""
        try:
            print(
                f"[Orchestrator] Broadcasting clear order to {service.__class__.__name__} for order {order_id}"
            )
            result = service.clear_order_data(order_id, final_vector_clock)
            print(
                f"[Orchestrator] Clear order result from {service.__class__.__name__}: {result}"
            )
            return result
        except Exception as e:
            logger.error(
                f"Error clearing data for service {service.__class__.__name__}: {str(e)}"
            )
            return False

    def broadcast_clear_order(self, order_id: str) -> Tuple[bool, List[str]]:
        """
        Broadcast to all services to clear the order data with the final vector clock.

        Args:
            order_id: The ID of the order to clear

        Returns:
            Tuple of (success, list of errors)
        """
        errors = []
        final_vector_clock = self._get_final_vector_clock(order_id)

        # Record final event before clearing
        self.order_event_tracker.record_event(
            order_id, "orchestrator", "broadcast_clear_order"
        )

        # Get the updated final vector clock after recording the event
        final_vector_clock = self._get_final_vector_clock(order_id)

        print(
            f"[Orchestrator] Broadcasting clear order for {order_id} with final vector clock: {final_vector_clock}"
        )

        # Clear data for each service
        services = [
            self.transaction_service,
            self.fraud_service,
            self.suggestions_service,
        ]

        success = True
        for service in services:
            if not self._clear_service_data(service, order_id, final_vector_clock):
                service_name = service.__class__.__name__
                error_msg = f"Failed to clear order data for {service_name}"
                errors.append(error_msg)
                success = False

        return success, errors

    def process_order(
        self,
        order: OrderInfo,
        user: UserInfo,
        credit_card: CreditCardInfo,
        billing: BillingInfo,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Process the order by splitting the transaction verification into:
          - billing check first,
          - then card check,
          - plus fraud in parallel,
          - suggestions after fraud & card are done if not terminated.
        """

        results = {"billing": None, "card": None, "fraud": None, "suggestions": None}
        errors = []

        # concurrency signals
        billing_flag = threading.Event()
        card_flag = threading.Event()
        fraud_flag = threading.Event()
        early_termination = threading.Event()
        results_lock = threading.Lock()

        # -------------------- WORKERS --------------------

        def billing_worker():
            """Check if billing address is complete, then set billing_flag."""
            try:
                print("[Orchestrator] Checking billing info...")
                billing_result = self.transaction_service.check_billing(order.order_id, billing)

                with results_lock:
                    results["billing"] = billing_result

                if not billing_result.success:
                    err = billing_result.error or "Billing check failed"
                    errors.append(err)
                    early_termination.set()
                    print(f"[Orchestrator] Billing check failed => {err}")
                else:
                    print("[Orchestrator] Billing check passed.")
            except Exception as e:
                errors.append(f"Billing worker error: {str(e)}")
                early_termination.set()
            finally:
                billing_flag.set()
                print("[Orchestrator] Billing worker completed.")

        def card_worker():
            """
            Waits for billing to finish. If not early-terminated, check card length/Luhn/expiry.
            """
            try:
                billing_flag.wait()
                if early_termination.is_set():
                    return  # skip if billing or something else failed

                print("[Orchestrator] Checking card info...")
                card_result = self.transaction_service.check_card(order.order_id, credit_card)

                with results_lock:
                    results["card"] = card_result

                if not card_result.success:
                    err = card_result.error or "Card check failed"
                    errors.append(err)
                    early_termination.set()
                    print(f"[Orchestrator] Card check failed => {err}")
                else:
                    print("[Orchestrator] Card check passed.")
            except Exception as e:
                errors.append(f"Card worker error: {str(e)}")
                early_termination.set()
            finally:
                card_flag.set()
                print("[Orchestrator] Card worker completed.")

        def fraud_worker():
            """
            Fraud check runs in parallel. If it fails, we set early_termination.
            """
            try:
                print("[Orchestrator] Checking fraud info...")
                fraud_result = self.fraud_service.check_fraud(order, user, billing)

                with results_lock:
                    results["fraud"] = fraud_result

                if not fraud_result.success:
                    err = fraud_result.error or "Fraud check failed"
                    errors.append(err)
                    early_termination.set()
                    print(f"[Orchestrator] Fraud detection failed => {err}")
                else:
                    print("[Orchestrator] Fraud detection passed.")
            except Exception as e:
                errors.append(f"Fraud worker error: {str(e)}")
                early_termination.set()
            finally:
                fraud_flag.set()
                print("[Orchestrator] Fraud worker completed.")

        def suggestions_worker():
            """
            Wait for both card & fraud checks. If no early termination, get suggestions.
            """
            try:
                fraud_flag.wait()
                card_flag.wait()
                if early_termination.is_set():
                    return

                print("[Orchestrator] Getting suggestions...")
                sugg_result = self.suggestions_service.get_suggestions(order.order_id)

                with results_lock:
                    results["suggestions"] = sugg_result

                cnt = len(sugg_result.data) if sugg_result.data else 0
                print(f"[Orchestrator] Retrieved {cnt} suggestions.")
            except Exception as e:
                errors.append(f"Suggestions worker error: {str(e)}")

        # -------------------- RUN CONCURRENCY --------------------
        futures = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures["billing"] = executor.submit(billing_worker)
            futures["card"] = executor.submit(card_worker)
            futures["fraud"] = executor.submit(fraud_worker)
            futures["suggestions"] = executor.submit(suggestions_worker)

            def check_early_termination():
                while not all(f.done() for f in futures.values()):
                    if early_termination.is_set():
                        # Cancel any not-done tasks
                        for name, fut in futures.items():
                            if not fut.done():
                                print(f"[Orchestrator] Canceling {name} due to early termination")
                                fut.cancel()
                        break
                    # short sleep
                    early_termination.wait(0.05)

            termination_checker = threading.Thread(target=check_early_termination, daemon=True)
            termination_checker.start()

            for _ in as_completed(list(futures.values())):
                pass
            termination_checker.join(timeout=1.0)

        # After concurrency, try clearing order data
        broadcast_success, broadcast_errors = self.broadcast_clear_order(order.order_id)
        if not broadcast_success:
            print(f"[Orchestrator] Failed to clear some order data: {broadcast_errors}")

        # If any errors or early termination
        if errors:
            return False, {
                "error": {"code": "ORDER_REJECTED", "message": " / ".join(errors)}
            }

        # Evaluate final results
        # - billing
        if not results["billing"] or not results["billing"].success:
            err = results["billing"].error if results["billing"] else "Billing check not completed"
            return False, {"error": {"code": "ORDER_REJECTED", "message": err}}

        # - card
        if not results["card"] or not results["card"].success:
            err = results["card"].error if results["card"] else "Card check not completed"
            return False, {"error": {"code": "ORDER_REJECTED", "message": err}}

        # - fraud
        if not results["fraud"] or not results["fraud"].success:
            err = results["fraud"].error if results["fraud"] else "Fraud check not completed"
            return False, {"error": {"code": "ORDER_REJECTED", "message": err}}

        # If we get here => Approved
        print(f"[Orchestrator] Order {order.order_id} APPROVED.")
        return True, {
            "orderId": order.order_id,
            "status": "Order Approved",
            "suggestedBooks": results["suggestions"].data
            if results["suggestions"] and results["suggestions"].data
            else [],
        }
