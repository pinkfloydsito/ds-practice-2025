import os
import sys
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database_client import DatabaseClient


def initialize_database():
    """Initialize the database with sample books."""
    # Get database nodes from environment
    db_nodes_env = os.getenv("DB_NODES", "db-node1:50052,db-node2:50052,db-node3:50052")
    db_nodes = db_nodes_env.split(",")

    print(f"Initializing database with nodes: {db_nodes}")

    # Wait for database to be up
    time.sleep(10)

    # Create database client
    client = DatabaseClient(db_nodes)

    # Define sample books
    books = {
        "Book A": 100,
        "Book B": 175,
        "Book C": 150,
        "Book D": 125,
        "Book E": 110,
        "Book F": 1,
        "Harry Potter": 200,
        "The Great Gatsby": 150,
        "To Kill a Mockingbird": 120,
        "1984": 80,
        "Pride and Prejudice": 90,
    }

    # Initialize books
    if client.initialize_books(books):
        print("Database initialized successfully")
    else:
        print("Failed to initialize database")

    # Print database status
    print("\nDatabase nodes status:")
    for status in client.get_all_nodes_status():
        print(
            f"  - {status['node_id']} ({status['address']}): {status['role']}, primary: {status['primary_id']}"
        )


if __name__ == "__main__":
    initialize_database()
