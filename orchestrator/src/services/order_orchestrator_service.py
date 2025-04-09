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
        """Initialize all required services before final processing."""

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
        """Process the order concurrently across all microservices."""
        # Results containers
        results = {"verification": None, "fraud": None, "suggestions": None}
        errors = []

        # event signaling
        # event_completed = {
        #     "fraud": threading.Event(),
        #     "verify": threading.Event(),
        # }

        fraud_flag = threading.Event()
        verify_flag = threading.Event()
        early_termination = threading.Event()
        results_lock = threading.Lock()

        # workers
        def verification_worker():
            try:
                print(
                    f"[Orchestrator] Starting final VerifyTransaction for card: {credit_card.number}"
                )
                verification_result = self.transaction_service.verify_transaction(
                    order.order_id, credit_card, billing
                )

                with results_lock:
                    results["verification"] = verification_result

                    print(
                        f"[Orchestrator] Verification final result: {results['verification'].success}"
                    )

                    if not verification_result.success:
                        error_msg = (
                            verification_result.error
                            if verification_result
                            else "Transaction verification failed"
                        )
                        errors.append(error_msg)
                        early_termination.set()
                        print(
                            "[Orchestrator] Transaction verification failed - signaling early termination"
                        )
            except Exception as e:
                errors.append(f"Transaction verification error: {str(e)}")

            finally:
                # signal
                verify_flag.set()
                print("[Orchestrator] Verification worker completed")

        def fraud_worker():
            try:
                print("[Orchestrator] Starting final fraud_detection analysis")
                results["fraud"] = self.fraud_service.check_fraud(order, user, billing)
                print(
                    f"[Orchestrator] Fraud detection final result: {results['fraud'].success}"
                )
            except Exception as e:
                errors.append(f"Fraud detection error: {str(e)}")

            finally:
                # signal
                fraud_flag.set()
                print("[Orchestrator] Fraud worker completed")

        def suggestions_worker():
            try:
                fraud_flag.wait()
                verify_flag.wait()

                if early_termination.is_set():
                    return

                print("[Orchestrator] Starting final suggestions retrieval")
                results["suggestions"] = self.suggestions_service.get_suggestions(
                    order.order_id
                )
                count = (
                    len(results["suggestions"].data)
                    if results["suggestions"].data
                    else 0
                )
                print(f"[Orchestrator] Retrieved {count} suggestions")
            except Exception as e:
                errors.append(f"Suggestions error: {str(e)}")

        futures = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures["verification"] = executor.submit(verification_worker)
            futures["fraud"] = executor.submit(fraud_worker)
            futures["suggestions"] = executor.submit(suggestions_worker)

            # check for early termination
            def check_early_termination():
                while not all(future.done() for future in futures.values()):
                    if early_termination.is_set():
                        # cancel pending futures
                        for name, future in futures.items():
                            if not future.done():
                                print(
                                    f"[Orchestrator] Canceling {name} worker due to early termination"
                                )
                                future.cancel()
                        break
                    # timeout to avoid busy waiting
                    early_termination.wait(0.05)

            # Start the early termination checker
            termination_checker = threading.Thread(target=check_early_termination)
            termination_checker.daemon = True
            termination_checker.start()

            # Wait for all futures to complete (or be canceled)
            for _ in as_completed(list(futures.values())):
                pass

            # Wait for the termination checker to finish
            termination_checker.join(timeout=1.0)

        # worker threads completed. Now we try to clear the order data
        broadcast_success, broadcast_errors = self.broadcast_clear_order(order.order_id)

        if not broadcast_success:
            print(
                f"Failed to clear some order data: {broadcast_errors}"
            )  # not hard-fail

        # errors (?)
        if errors:
            return False, {
                "error": {"code": "ORDER_REJECTED", "message": " / ".join(errors)}
            }

        # validation of results
        if not results["fraud"] or not results["fraud"].success:
            error_msg = (
                results["fraud"].error
                if results["fraud"]
                else "Fraud detection not completed"
            )
            return False, {"error": {"code": "ORDER_REJECTED", "message": error_msg}}

        if not results["verification"] or not results["verification"].success:
            error_msg = (
                results["verification"].error
                if results["verification"]
                else "Transaction verification failed"
            )
            return False, {"error": {"code": "ORDER_REJECTED", "message": error_msg}}

        print(
            f"[Orchestrator] Order {order.order_id} approved. Final vector clock. {self.order_event_tracker.get_clock(order.order_id, 'orchestrator')}"
        )

        # XXX: enqueue the message to send to the order_executor

        # Success response
        return True, {
            "orderId": order.order_id,
            "status": "Order Approved",
            "suggestedBooks": results["suggestions"].data
            if results["suggestions"]
            else [],
        }
