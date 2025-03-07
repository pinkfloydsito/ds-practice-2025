import logging
import random
import sys
import os
import grpc
import time
import re
from concurrent import futures
import pandas as pd

import joblib

# Insert the stubs path so we can import the generated modules
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/fraud_detection"))
sys.path.insert(0, grpc_path)

import fraud_detection_pb2 as fd_pb2
import fraud_detection_pb2_grpc as fd_pb2_grpc


MODEL_PATH = os.path.join(os.path.dirname(__file__), "fraud_model.pkl")

if not os.path.exists(MODEL_PATH):
    print(f"ERROR: fraud_model.pkl is missing at {MODEL_PATH}")
    exit(1)

print(f"Loading model from: {MODEL_PATH}")
model = joblib.load(MODEL_PATH)

LABEL_ENCODERS = os.path.join(os.path.dirname(__file__), "label_encoders.pkl")
if not os.path.exists(LABEL_ENCODERS):
    print(f"ERROR: label_encoders.pkl is missing at {LABEL_ENCODERS}")
    exit(1)

print(f"Loading encoders from: {LABEL_ENCODERS}")

label_encoders = joblib.load(LABEL_ENCODERS)


logging.basicConfig(level=logging.INFO)

class FraudDetectionService(fd_pb2_grpc.FraudDetectionServiceServicer):
    """
    Checks:
    1. If user_name is in a known blocklist (5 names).
    2. If user_email ends with .ru suffix.
    """

    BLOCKED_NAMES = {"alex", "john", "maria", "anna", "ivan"}

    def CheckFraud(self, request, context):
        print(
            f"[FraudDetection] CheckFraud request: user_name={request.user_name}, user_email={request.user_email}"
        )
        payment_method = label_encoders["payment_method"].transform([request.payment_method])[0] \
            if request.payment_method in label_encoders["payment_method"].classes_ else -1
        
        location = label_encoders["location"].transform([request.location])[0] \
            if request.location in label_encoders["location"].classes_ else -1

        # Prepare input for prediction
        features = pd.DataFrame([[request.amount, payment_method, location]],
                                columns=["amount", "payment_method", "location"])

        # Make prediction
        prediction = model.predict(features)[0]
        probability = model.predict_proba(features)[0][1] 

        reason = "AI Model Prediction" if prediction == 1 else "Transaction is safe"
        
        return fd_pb2.FraudResponse(is_fraudulent=bool(prediction), reason=reason)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
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
