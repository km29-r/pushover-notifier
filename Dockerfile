FROM python:3.11-slim

# Create application directory
WORKDIR /app

# Copy application code into the container
COPY app.py notifier.py requirements.txt schema.sql README.md .env.example ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the default port
EXPOSE 8080

# The entrypoint runs the Flask server. Pass environment variables
# via `docker run --env-file .env` to configure credentials.
CMD ["python", "app.py"]