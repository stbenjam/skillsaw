FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/stbenjam/skillsaw"
LABEL org.opencontainers.image.url="https://github.com/stbenjam/skillsaw"
LABEL org.opencontainers.image.description="A configurable linter for agent skills, plugins, and AI coding assistant context"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# Set working directory
WORKDIR /app

# Copy package files
COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md
COPY src/ /app/src/
COPY requirements/ /app/requirements/

# Install pinned dependencies then the package itself
RUN pip install --no-cache-dir --require-hashes -r /app/requirements/lock.txt \
                                                -r /app/requirements/llm-lock.txt && \
    pip install --no-cache-dir --no-deps /app

# Set default working directory for linting
WORKDIR /workspace

# Run linter by default
ENTRYPOINT ["skillsaw"]
CMD []
