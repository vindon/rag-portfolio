FROM python:3.12-slim

WORKDIR /app

COPY packages/model_gateway ./packages/model_gateway
COPY packages/spend_guard ./packages/spend_guard
COPY apps/api ./apps/api

RUN pip install --no-cache-dir ./packages/model_gateway ./packages/spend_guard ./apps/api

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8080

CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
