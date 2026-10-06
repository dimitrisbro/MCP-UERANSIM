FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ueransim_mcp/ ./ueransim_mcp/
# K8s tools build gNB/UE ConfigMaps from these templates (config_ops.load_template)
COPY config/ ./config/
COPY main.py .

CMD ["python", "main.py"]
