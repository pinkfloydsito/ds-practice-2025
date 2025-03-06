
FROM python:3.11


WORKDIR /app

COPY ./fraud_detection/requirements.txt requirements.txt


RUN pip install --no-cache-dir -r requirements.txt


ENV PYTHONPATH="/app/utils:${PYTHONPATH}"

CMD ["python", "utils/other/hotreload.py", "fraud_detection/src/app.py"]
