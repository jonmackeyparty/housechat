FROM python:3.11-slim

# small runtime niceties
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install minimal build tools for packages that may need compilation
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create a non-root user and fix ownership where possible
RUN addgroup --system app && adduser --system --ingroup app app || true
RUN chown -R app:app /app || true

USER app
EXPOSE 5000

# Use gunicorn with eventlet worker to support Socket.IO in production
CMD ["gunicorn", "-k", "eventlet", "-w", "1", "--bind", "0.0.0.0:5000", "app:app"]
