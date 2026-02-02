FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get remove -y build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Copy application
COPY . .

# Create a non-root user and fix ownership
RUN addgroup --system app && adduser --system --ingroup app app || true
RUN chown -R app:app /app

USER app
EXPOSE 5000

# Use gunicorn with eventlet worker to support Socket.IO
CMD ["gunicorn", "-k", "eventlet", "-w", "1", "--bind", "0.0.0.0:5000", "app:app"]
