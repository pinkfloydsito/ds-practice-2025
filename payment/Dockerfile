FROM python:3.11
WORKDIR /app

COPY ./payment/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY ./payment/src /app/payment/src

CMD python utils/other/hotreload.py "payment/src/app.py"
