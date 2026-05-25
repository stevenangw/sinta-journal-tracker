FROM python:3.10-slim

WORKDIR /app

# Install system dependencies if any are needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files
COPY . .

# Make start.sh executable
RUN chmod +x start.sh

# Expose the default Hugging Face Spaces port
ENV PORT=7860
EXPOSE 7860

# Run the startup script to start both background scraper and Flask dashboard
CMD ["./start.sh"]
