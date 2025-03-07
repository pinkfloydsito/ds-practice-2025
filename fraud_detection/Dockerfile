
FROM python:3.11
WORKDIR /app

COPY fraud_detection/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY fraud_detection /app/fraud_detection

RUN ls -l /app/fraud_detection/

CMD ["python", "fraud_detection/src/app.py"]
