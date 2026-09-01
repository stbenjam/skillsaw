FROM python:3.14.7-slim@sha256:656d12e70054d5fda18a045e2494c96701e9792dd1445f95b3d038df954f57e9

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

# Install the package
RUN pip install --no-cache-dir /app

# Set default working directory for linting
RUN groupadd --system skillsaw \
    && useradd --system --gid skillsaw --home-dir /nonexistent --shell /usr/sbin/nologin skillsaw \
    && mkdir -p /workspace \
    && chown skillsaw:skillsaw /workspace
WORKDIR /workspace
USER skillsaw

# Run linter by default
ENTRYPOINT ["skillsaw"]
CMD []
