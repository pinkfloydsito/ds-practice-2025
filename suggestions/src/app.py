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

model_name = os.getenv("MODEL_NAME", "all-MiniLM-L6-v2")

model = SentenceTransformer(model_name)


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
