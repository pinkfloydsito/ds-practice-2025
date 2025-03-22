import logging
import sys
import os
import grpc
from concurrent import futures
import pandas as pd
import geoip2.database

import joblib

FRAUD_THRESHOLD = float(os.environ.get("FRAUD_THRESHOLD", "0.7"))

# Insert the stubs path so we can import the generated modules
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/fraud_detection"))
sys.path.insert(0, grpc_path)

import fraud_detection_pb2 as fd_pb2
import fraud_detection_pb2_grpc as fd_pb2_grpc

GEOIP_PATH = os.path.join(os.path.dirname(__file__), "GeoLite2-Country.mmdb")
MODEL_PATH = os.path.join(os.path.dirname(__file__), "fraud_model.pkl")

if not os.path.exists(MODEL_PATH):
    print(f"ERROR: fraud_model.pkl is missing at {MODEL_PATH}")
    exit(1)

print(f"Loading model from: {MODEL_PATH}")
model = joblib.load(MODEL_PATH)

ENCODERS_PATH = os.path.join(os.path.dirname(__file__), "label_encoders.pkl")
if not os.path.exists(ENCODERS_PATH):
    print(f"ERROR: label_encoders.pkl is missing at {ENCODERS_PATH}")
    exit(1)

print(f"Loading encoders from: {ENCODERS_PATH}")


logging.basicConfig(level=logging.INFO)

# Global variables for loaded models
model = None
label_encoders = None
geoip_reader = None


def load_models():
    """Load models and dependencies on startup"""
    global model, label_encoders, geoip_reader

    try:
        model = joblib.load(MODEL_PATH)
        label_encoders = joblib.load(ENCODERS_PATH)
        print("Model and encoders loaded successfully")
    except Exception as e:
        print(f"Failed to load model or encoders: {e}")
        raise

    try:
        geoip_reader = geoip2.database.Reader(GEOIP_PATH)
        print("GeoIP database loaded successfully")
    except Exception as e:
        print(f"Could not load GeoIP database: {e}. IP verification will be disabled.")
        geoip_reader = None


load_models()


def predict_fraud(request, model, label_encoders, geoip_reader):
    """
    Function to predict fraud for a new transaction in production

    Parameters:
    - request: contains transaction details
    - model: trained model
    - label_encoders: fitted label encoders
    - geoip_reader: geoip database reader

    Returns:
    - fraud_probability: probability of fraud (0-1)
    """
    # 1. Extract country from IP address
    ip_country = get_country_from_ip(request.ip_address, geoip_reader)

    # 2. Prepare the input data
    input_data = pd.DataFrame(
        {
            "billing_city": [request.billing_city],
            "billing_country": [request.billing_country],
            "amount": [request.amount],
            "payment_method": [request.payment_method],
        }
    )

    print(f"Inferencee - Input data: {input_data}")

    # 3. Transform categorical variables using saved encoders
    for col, le in label_encoders.items():
        if col in input_data.columns:
            # Handle unseen categories gracefully
            try:
                input_data[col] = le.transform(input_data[col])
            except ValueError:
                # If unseen category, assign a default value (e.g., -1)
                input_data[col] = -1

    # 4. Make prediction
    fraud_probability = model.predict_proba(input_data)[0][1]

    # flag if IP country doesn't match billing country
    if ip_country != request.billing_country:
        fraud_probability = max(fraud_probability, 0.5)  # Increase suspicion

    return fraud_probability


def get_country_from_ip(ip_address, reader):
    try:
        response = reader.country(ip_address)
        return response.country.name
    except:
        return "Unknown"


class FraudDetectionService(fd_pb2_grpc.FraudDetectionServiceServicer):
    def CheckFraud(self, request, context):
        print(
            f"[FraudDetection] Request params: billing_city={request.billing_city} billing_country={request.billing_country},amount={request.amount},payment_method={request.payment_method},ip_address={request.ip_address}, "
        )

        ip_country = get_country_from_ip(request.ip_address, geoip_reader)

        # inference
        fraud_probability = predict_fraud(request, model, label_encoders, geoip_reader)

        # Rule-based checks
        is_high_risk_country = request.billing_country in [
            "Russia",
            "North Korea",
            "Syria",
        ]
        is_high_risk_payment = request.payment_method == "Crypto"

        ip_country_mismatch = (
            ip_country != request.billing_country and ip_country != "Unknown"
        )

        # Adjust probability based on rules
        if ip_country_mismatch:
            fraud_probability = max(fraud_probability, 0.5)

        # Collect details
        details = {
            "ip_country": ip_country,
            "ip_country_mismatch": ip_country_mismatch,
            "high_risk_country": is_high_risk_country,
            "high_risk_payment": is_high_risk_payment,
            "model_score": float(fraud_probability),
            "final_score": float(fraud_probability),
        }

        # Determine action
        action = "REJECT" if fraud_probability > FRAUD_THRESHOLD else "APPROVE"

        # Collect reasons if rejected
        reasons = []
        if action == "REJECT":
            if details["model_score"] > 0.5:
                reasons.append("Transaction pattern matches known fraudulent behavior")
            if details["high_risk_country"]:
                reasons.append("Transaction originates from a high-risk country")
            if details["high_risk_payment"]:
                reasons.append("High-risk payment method")
            if details["ip_country_mismatch"]:
                reasons.append(
                    f"IP location ({details['ip_country']}) doesn't match billing country ({request.billing_country})"
                )

        print(
            f"[FraudDetection] Response: action={action}, reasons={reasons}, details={details}"
        )

        response = fd_pb2.FraudResponse(
            fraud_probability=float(fraud_probability),
            action=action,
            details=details,
            reasons=reasons,
        )

        return response


def serve():
    server = grpc.server(futures.ThreadPoolExecutor())

    fd_pb2_grpc.add_FraudDetectionServiceServicer_to_server(
        FraudDetectionService(), server
    )

    port = "50051"
    server.add_insecure_port(f"[::]:{port}")
    server.start()

    logging.info(f"Fraud Detection service listening on port {port}")

    # Keep thread alive
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
