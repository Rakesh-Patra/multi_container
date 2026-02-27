# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install docker CLI to allow the agent to manage host docker containers
# We don't install the daemon, just the CLI. Host daemon will be mounted.
RUN apt-get update && \
    apt-get install -y --no-install-recommends docker.io && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Initialize log and backup directories
RUN mkdir -p logs/sessions backups compose_files && \
    chmod -R 777 logs backups compose_files

# Ensure output is not buffered so logs are written immediately
ENV PYTHONUNBUFFERED=1

# Command to run the agent REPL
ENTRYPOINT ["python", "main.py"]
