FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY common /app/common
COPY payment-service /app/service

ENV PYTHONPATH=/app
ENV SERVICE_NAME=payment-service

EXPOSE 8002

CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8002"]
