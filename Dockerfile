# Optima MCP server in a container.
# The server starts and answers MCP introspection (initialize, tools/list) with the
# standard library only. Browsing needs a real browser: in a container that is
# headless Chromium via Playwright (build with --build-arg WITH_BROWSER=1).
FROM python:3.12-slim

ARG WITH_BROWSER=0
WORKDIR /app
COPY requirements.txt ./
RUN if [ "$WITH_BROWSER" = "1" ]; then \
      pip install --no-cache-dir -r requirements.txt && \
      python -m playwright install --with-deps chromium; \
    fi
COPY src ./src
COPY skill ./skill

ENV PYTHONPATH=/app/src \
    OPTIMA_HOME=/data \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data && printf '{"language":"en","engine":"playwright","headless":true,"auto_handoff":false,"notify_desktop":false}\n' > /data/config.json

ENTRYPOINT ["python", "-m", "optima", "mcp"]
