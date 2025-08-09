FROM python:3.11-slim

WORKDIR /app

# System deps for asyncssh (libssl), psycopg/asyncpg, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev libssl-dev git openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure alembic scripts are executable in container context
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
