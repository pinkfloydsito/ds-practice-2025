FROM python:3.11
WORKDIR /app

RUN pip install --no-cache-dir grpcio==1.70.0 grpcio-tools==1.70.0 protobuf==5.29.3 watchdog==6.0.0

COPY ./payment/src /app/payment/src

CMD python utils/other/hotreload.py "payment/src/app.py"
