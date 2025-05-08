import json
from flask import Blueprint, jsonify, current_app

order_bp = Blueprint("order", __name__, url_prefix="/v2/orders")


@order_bp.route("/<order_id>", methods=["GET"])
def get_order_status(order_id):
    """Get status of a specific order."""
    try:
        database_service = current_app.database_service
        order_key = f"order:{order_id}"

        success, value, _, error = database_service.read_key(order_key)

        if success:
            order_data = json.loads(value)
            return jsonify(order_data)

        print(f"Error reading order {order_id}: {error}")

        return jsonify({"error": "Order not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500
