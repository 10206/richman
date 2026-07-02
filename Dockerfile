# Railway 배포용. richman 서비스의 Root Directory가 이미 backend/로 설정돼 있어
# 빌드 컨텍스트가 backend/ 자체이므로 경로에 backend/ 접두사를 붙이지 않는다 (docs/05).
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
