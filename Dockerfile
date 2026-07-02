# Railway 배포용 — 저장소 루트 대신 backend/를 앱 루트로 사용 (docs/05).
# Nixpacks 자동 감지에 의존하지 않고 backend/ 하나만 명시적으로 빌드한다.
FROM python:3.13-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
