FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
WORKDIR /app/backend
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
ENV SEXTO_DB=/data/historial.db
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
