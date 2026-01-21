FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if any (e.g., for pynacl build)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Environment setup
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Make scripts executable
RUN chmod +x start.sh examples/quickstart.sh

# Expose the standard port for NA service
EXPOSE 5000

ENTRYPOINT ["./start.sh"]
