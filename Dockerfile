FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app
COPY .env.example ./

CMD ["python", "-m", "app.main"]
