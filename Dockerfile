FROM python:3.10-slim

# Set environment variables
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.5.1 \
    RELIA_ENV=prod \
    # Don't run the container as root
    RELIA_USER=relia \
    RELIA_UID=10001

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ansible \
    procps \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install "poetry==$POETRY_VERSION"

# Set working directory
WORKDIR /app

# Create non-root user
RUN groupadd -g $RELIA_UID $RELIA_USER && \
    useradd -m -u $RELIA_UID -g $RELIA_UID -s /bin/bash $RELIA_USER

# Copy only requirements to cache them in docker layer
COPY poetry.lock pyproject.toml /app/

# Configure poetry to not use virtualenvs
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root --without dev

# Copy project
COPY . /app/

# Create directories for data with proper permissions
RUN mkdir -p /app/.relia-playbooks /app/.relia-data \
    && chown -R $RELIA_USER:$RELIA_USER /app

# Set permissions
RUN chmod -R 755 /app

# Only retain write permissions where necessary
RUN chmod -R 775 /app/.relia-playbooks /app/.relia-data

# Switch to non-root user
USER $RELIA_USER

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Use tini as init system to handle signals properly
ENTRYPOINT ["/usr/bin/tini", "--"]

# Set default command
CMD ["poetry", "run", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]