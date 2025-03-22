import sys
import os

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
models_path = os.path.abspath(os.path.join(FILE, "../../../utils/models"))
grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/suggestions"))
sys.path.insert(0, grpc_path)
sys.path.insert(0, models_path)
import suggestions_pb2 as book_suggestion

import suggestions_pb2_grpc as book_suggestion_grpc

import grpc
from concurrent import futures
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker
import os

from book import Book, engine
from typing import List

from sentence_transformers import SentenceTransformer

load_dotenv()

import os
from sentence_transformers import SentenceTransformer
from sentence_transformers import util

model_name = os.getenv("MODEL_NAME", "all-MiniLM-L6-v2")
model_path = "/app/ai/models/sentence-transformer"

try:
    model = SentenceTransformer(model_path)
    print(f"Model loaded from local path: {model_path}")
except:
    # If loading fails download model
    print(f"Model not found locally. Downloading {model_name}...")

    # Create directory if it doesn't exist
    os.makedirs(model_path, exist_ok=True)

    model = SentenceTransformer(model_name)
    model.save(model_path)
    print(f"Model downloaded and saved to {model_path}")


def find_similar_books(tokens: List[str], top_n=5):
    """Find books similar to the given title"""

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        joined_tokens = " ".join(tokens)
        query_text = model.encode(joined_tokens)
        # Find similar books using cosine similarity
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
    def GetSuggestions(self, request, context):
        print(f"[Suggestions] Received request: {request}")
        tokens = request.book_tokens
        books = find_similar_books(tokens, request.limit)

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
                    confidence_score=0.9,  # check this
                    reason="Best Seller",  # check this param as well
                )
            )
        response = book_suggestion.RecommendationResponse()
        response.recommendations.extend(recommendations)

        print(f"[Suggestions] result: {books}")
        return response


def serve():
    # Create a gRPC server
    server = grpc.server(futures.ThreadPoolExecutor())
    book_suggestion_grpc.add_BookSuggestionServicer_to_server(
        BookSuggestionService(), server
    )
    port = "50053"
    server.add_insecure_port("[::]:" + port)
    # Start the server
    server.start()
    print("Server started. Listening on port 50053.")
    # Keep thread alive
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
