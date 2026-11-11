FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
EXPOSE 3000
CMD ["uvicorn", "sicai.api:app", "--host", "0.0.0.0", "--port", "3000"]
