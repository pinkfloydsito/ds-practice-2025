import sys
import os
import logging

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
models_path = os.path.abspath(os.path.join(FILE, "../../../utils/models"))
grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/suggestions"))
vector_clock_path = os.path.abspath(os.path.join(FILE, "../../../utils/vector_clock"))

sys.path.insert(0, vector_clock_path)
sys.path.insert(0, grpc_path)
sys.path.insert(0, models_path)

import suggestions_pb2 as book_suggestion
import suggestions_pb2_grpc as book_suggestion_grpc

from vector_clock import OrderEventTracker

import grpc
from concurrent import futures
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker
import os

from book import Book, engine
from typing import List

from sentence_transformers import SentenceTransformer

load_dotenv()

logger = logging.getLogger(__name__)

model_name = os.getenv("MODEL_NAME", "all-MiniLM-L6-v2")
model_path = "/app/ai/models/sentence-transformer"

try:
    model = SentenceTransformer(model_path)
    print(f"Model loaded from local path: {model_path}")
except:
    print(f"Model not found locally. Downloading {model_name}...")
    os.makedirs(model_path, exist_ok=True)
    model = SentenceTransformer(model_name)
    model.save(model_path)
    print(f"Model downloaded and saved to {model_path}")


def find_similar_books(tokens: List[str], top_n=5):
    """Find books similar to the given tokens using embeddings."""
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        joined_tokens = " ".join(tokens)
        query_text = model.encode(joined_tokens)

        similar_books = (
            session.query(Book)
            .filter(~Book.title.in_(tokens))
            .order_by(Book.embedding.cosine_distance(query_text))
            .limit(top_n + len(tokens))
            .all()
        )
        return similar_books[:top_n]
    finally:
        session.close()


class BookSuggestionService(book_suggestion_grpc.BookSuggestionServicer):
    def __init__(self):
        # Dictionary to store data from 'InitializeOrder' calls
        self.orders = {}
        self.service_name = "suggestions"
        self.order_event_tracker = OrderEventTracker()

    def InitializeOrder(self, request, context):
        """
        Cache the order data, so we won't do final logic now.
        For instance, store the tokens.
        """
        order_id = request.order_id
        received_clock = dict(request.vectorClock)

        if not self.order_event_tracker.order_exists(order_id):
            self.order_event_tracker.initialize_order(order_id)
            print(
                f"[Suggestions] Initialized order {order_id} with vector clock {received_clock}"
            )

        self.orders[order_id] = {
            "book_tokens": list(request.book_tokens),
            "limit": request.limit,
        }

        try:
            updated_clock = self.order_event_tracker.record_event(
                order_id=order_id,
                service=self.service_name,
                event_name=self.service_name + ".InitializeOrder",
                received_clock=received_clock,
            )
        except Exception as e:
            print(f"[Suggestions] Error recording event: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error")
            import traceback

            traceback.print_exc()
            raise

        return book_suggestion.SuggestionInitResponse(
            success=True, vectorClock=updated_clock
        )

    def GetSuggestions(self, request, context):
        received_clock = dict(request.vectorClock)

        print(
            f"[Suggestions] Received request: {request} with vector clock {dict(received_clock)}"
        )

        # If we had an InitializeOrder call, retrieve those tokens
        stored = self.orders.get(request.order_id)

        tokens = stored.get("book_tokens", [])
        books = find_similar_books(tokens, stored.get("limit", 3))
        recommendations = []
        for book in books:
            recommendations.append(
                book_suggestion.Recommendation(
                    book=book_suggestion.Book(
                        id=str(book.id),
                        author=book.author,
                        description=book.title,
                        genres=[book.genre, book.subgenre],
                    ),
                    confidence_score=0.9,
                    reason="Best Seller",
                )
            )

        updated_clock = self.order_event_tracker.record_event(
            order_id=request.order_id,
            service=self.service_name,
            event_name=self.service_name + ".CheckFraud",
            received_clock=received_clock,
        )
        try:
            response = book_suggestion.RecommendationResponse(vectorClock=updated_clock)
            response.recommendations.extend(recommendations)
            print(
                f"[Suggestions] order={request.order_id}, result: {books}, vector clock={updated_clock}"
            )
        except Exception as e:
            print(f"[Suggestions] Error creating response: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Internal error")
            import traceback

            traceback.print_exc()
            raise

        return response


def serve():
    server = grpc.server(futures.ThreadPoolExecutor())
    book_suggestion_grpc.add_BookSuggestionServicer_to_server(
        BookSuggestionService(), server
    )
    port = "50053"
    server.add_insecure_port("[::]:" + port)
    server.start()
    print("Server started. Listening on port 50053.")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
