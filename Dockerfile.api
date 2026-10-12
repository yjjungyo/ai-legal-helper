FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    fontconfig \
    libfreetype6 \
    fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

# Pre-install fonts for Korean PDF support
RUN fc-cache -fv

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .
RUN pip install --no-cache-dir uvicorn httpx reportlab

COPY src /app/src
COPY data /app/data

ENV PYTHONPATH=/app/src

EXPOSE 8080

CMD ["uvicorn", "ai_legal_helper.api.main:app", "--host", "0.0.0.0", "--port", "8080"]

