# order_executor/Dockerfile
FROM python:3.11
WORKDIR /app

COPY ./order_executor/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Install the Python dependencies
RUN pip install --no-cache-dir --default-timeout=300 -r requirements.txt

# Set the command to run the application
CMD python utils/other/hotreload.py "order_executor/src/app.py"
