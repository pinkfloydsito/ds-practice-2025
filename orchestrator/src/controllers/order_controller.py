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
            stored_result = get_stored_order_result(order_id)

            if stored_result:
                order_data.update(stored_result)

                if "suggestedBooks" in stored_result:
                    order_data["suggestedBooks"] = stored_result["suggestedBooks"]

            return jsonify(order_data)

        print(f"Error reading order {order_id}: {error}")

        return jsonify({"error": "Order not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_stored_order_result(order_id: str) -> dict:
    """Get stored order result from Flask app context."""
    return current_app.order_results.get(order_id, None)
