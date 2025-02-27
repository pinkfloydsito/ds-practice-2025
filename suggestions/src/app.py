import sys
import os

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/suggestions"))
sys.path.insert(0, grpc_path)
import suggestions_pb2 as book_suggestion

import suggestions_pb2_grpc as book_suggestion_grpc

import grpc
from concurrent import futures


class BookSuggestionService(book_suggestion_grpc.BookSuggestionServicer):
    def GetSuggestions(self, request, context):
        response = book_suggestion.RecommendationResponse()
        recommendations = [
            book_suggestion.Recommendation(
                book=book_suggestion.Book(
                    id="1",
                    title="Book Title",
                    author="Author Name",
                    description="Book Description",
                    genres=["Genre1", "Genre2"],
                ),
                confidence_score=0.9,
                reason="Best Seller",
            )
        ]
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
