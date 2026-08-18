FROM python:3.12-slim

# Node.js/npm are required so the app can launch the real MCP filesystem
# server (via npx) instead of falling back to a stub inside the container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY mcp_sandbox/ mcp_sandbox/
COPY policies.json sequence_rules.json ./

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
