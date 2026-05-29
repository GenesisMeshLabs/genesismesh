FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x start.sh examples/quickstart.sh \
    && addgroup --system genesis \
    && adduser --system --ingroup genesis genesis

USER genesis

EXPOSE 8443

ENTRYPOINT ["./start.sh"]
