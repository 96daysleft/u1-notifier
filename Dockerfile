# Use Python 3.11 slim image for better performance
FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Create non-root user for security
RUN groupadd -g 1001 app && \
    useradd -r -u 1001 -g app app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        python3-dev && \
    rm -rf /var/lib/apt/lists/*

# setuptools-scm can't see .git inside the build: the release workflow
# passes the tag version here.
ARG VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}

# Copy package metadata and application code
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY main.py ./
COPY .env.example ./

# Install the package and its dependencies from pyproject.toml
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    rm -rf build *.egg-info

# Change ownership of app directory
RUN chown -R app:app /app

# Switch to non-root user
USER app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('localhost', 8000), timeout=5)" || exit 1

# Expose port (if needed for health checks)
EXPOSE 8000

# Set Python path
ENV PYTHONPATH=/app

# Start the application
CMD ["python", "main.py"]
