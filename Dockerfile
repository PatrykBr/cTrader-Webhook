# Use the official Python image from the Docker Hub
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install the required packages
RUN pip install --no-cache-dir -r requirements.txt

# Expose port 5000 for Flask app
EXPOSE 5000

# Define environment variables for Render
ENV FLASK_APP=webhook_listener.py

# Run the application
CMD ["python", "webhook_listener.py"]
