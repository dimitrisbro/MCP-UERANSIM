FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ueransim_mcp/ ./ueransim_mcp/
COPY main.py .

CMD ["python", "main.py"]
