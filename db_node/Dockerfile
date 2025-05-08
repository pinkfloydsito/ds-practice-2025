FROM python:3.11
WORKDIR /app

COPY ./db_node/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir --default-timeout=300 -r requirements.txt

CMD python utils/other/hotreload.py "db_node/src/app.py"
