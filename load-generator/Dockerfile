FROM python:3.12-slim

WORKDIR /app
COPY services/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY load-generator/main.py /app/main.py
CMD ["python", "-u", "/app/main.py"]
