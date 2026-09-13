FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8200

# api.py expone el flow de flows.py como POST /transferencia + GET /transferencia/{id}/estado.
# flows.py también se puede seguir disparando manualmente dentro del contenedor:
#   docker compose exec saga-orchestrator python flows.py <origen> <destino> <monto> <idempotency_key> [--fraude] [--timeout]
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8200"]
