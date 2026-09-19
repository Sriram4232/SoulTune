FROM node:22-alpine AS frontend
WORKDIR /build
COPY Frontend/package*.json ./
RUN npm ci
COPY Frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY Backend/requirements.txt Backend/requirements.txt
RUN pip install --no-cache-dir -r Backend/requirements.txt
COPY Backend/ Backend/
COPY --from=frontend /build/dist Frontend/dist/
RUN mkdir -p /app/fallback_songs /app/Backend/data && useradd --uid 10001 --create-home curator && chown -R curator:curator /app
USER curator
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "Backend", "--host", "0.0.0.0", "--port", "8000"]

