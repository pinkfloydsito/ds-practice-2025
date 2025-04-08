import sys
import os
import grpc
import logging

from typing import List

from utils.grpc_config import GrpcConfig
from google.protobuf.json_format import MessageToDict

logger = logging.getLogger(__name__)
config = GrpcConfig()
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
config.init_paths(FILE)
config.setup_paths()

models_path = os.path.abspath(os.path.join(FILE, "../../../../../../utils/models"))
sys.path.insert(0, models_path)

import suggestions_pb2 as suggestions
import suggestions_pb2_grpc as suggestions_grpc

from bookstore_models import ServiceResult


class SuggestionsService:
    """Client for the book suggestions service."""

    def __init__(self, grpc_factory, order_event_tracker):
        self.grpc_factory = grpc_factory
        self.order_event_tracker = order_event_tracker

    def initialize_order(
        self, order_id: str, book_tokens: List[str], limit: int
    ) -> bool:
        """Initialize a suggestions order."""
        try:
            stub = self.grpc_factory.get_stub(
                "suggestions",
                suggestions_grpc.BookSuggestionStub,
                secure=False,
            )

            current_clock = self.order_event_tracker.get_clock(order_id, "orchestrator")

            request = suggestions.SuggestionInitRequest(
                order_id=order_id,
                book_tokens=book_tokens,
                limit=limit,
                vectorClock=current_clock,
            )
            response = stub.InitializeOrder(request)

            self._record_vector_clock(order_id, "InitializeOrder", response.vectorClock)

            print(
                f"[Orchestrator] initialize_suggestions_order => success={response.success} and vectorClock={response.vectorClock}"
            )

            return response.success
        except grpc.RpcError as e:
            print(
                f"gRPC error in initialize_suggestions_order: {e.code()}: {e.details()}"
            )
            return False

    def get_suggestions(self, order_id: str) -> ServiceResult:
        """Get book suggestions."""
        result = ServiceResult()
        try:
            stub = self.grpc_factory.get_stub(
                "suggestions", suggestions_grpc.BookSuggestionStub, secure=False
            )

            current_clock = self.order_event_tracker.get_clock(order_id, "orchestrator")

            request = suggestions.RecommendationRequest(
                order_id=order_id, vectorClock=current_clock
            )
            response = stub.GetSuggestions(request)
            response_dict = MessageToDict(response)
            raw_recommendations = response_dict.get("recommendations", [])

            self._record_vector_clock(order_id, "GetSuggestions", response.vectorClock)

            formatted = []
            for rec in raw_recommendations:
                book_info = rec.get("book", {})
                formatted.append(
                    {
                        "productId": book_info.get("id", ""),
                        "title": book_info.get("description", ""),
                        "author": book_info.get("author", ""),
                    }
                )

            result.data = formatted
            result.success = True
            return result
        except grpc.RpcError as e:
            logger.error(f"gRPC error (get_suggestions): {e.code()}: {e.details()}")
            result.error = f"Suggestions service error: {e.details()}"
            return result

    def _record_vector_clock(self, order_id, event_name: str, clock):
        self.order_event_tracker.record_event(
            order_id=order_id,
            service="orchestrator",
            event_name=event_name,
            received_clock=dict(clock),
        )
