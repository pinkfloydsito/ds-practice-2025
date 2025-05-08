from flask import Blueprint, jsonify, request, current_app

database_bp = Blueprint("database", __name__, url_prefix="/api/database")


@database_bp.route("/stock/<book_name>", methods=["GET"])
def get_book_stock(book_name):
    """Get stock for a specific book."""
    try:
        database_service = current_app.database_service
        success, stock, error = database_service.read_book_stock(book_name)

        if success:
            return jsonify({"book": book_name, "stock": stock, "available": stock > 0})
        else:
            return jsonify({"error": error}), 404

    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@database_bp.route("/stock", methods=["POST"])
def get_multiple_books_stock():
    """Get stock for multiple books."""
    try:
        data = request.get_json()
        book_names = data.get("books", [])

        if not book_names:
            return jsonify({"error": "No books specified"}), 400

        database_service = current_app.database_service
        result = database_service.get_all_books_stock(book_names)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@database_bp.route("/status", methods=["GET"])
def get_database_status():
    """Get status of all database nodes."""
    try:
        database_service = current_app.database_service
        status = database_service.get_database_status()

        return jsonify(
            {
                "nodes": status,
                "total": len(status),
                "online": len([n for n in status if n.get("status") == "online"]),
            }
        )

    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500
