FROM python:3.12-slim

WORKDIR /app

# Build tools needed for scipy + psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port $PORT"]
