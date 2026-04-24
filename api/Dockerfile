FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# 1. Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential curl && rm -rf /var/lib/apt/lists/*

# 2. Install Python requirements
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Create models directory and copy ONLY the download script first
RUN mkdir -p /app/models
COPY api/models/download_model.py /app/models/

# 4. Download the model directly inside the image build process
# We temporarily install torch/optimum just for the download, then clean up to save space
RUN pip install --no-cache-dir optimum[onnxruntime] torch && \
  python /app/models/download_model.py && \
  pip uninstall -y optimum torch

# 5. NOW copy the rest of your application code
# Whenever you change main.py, Docker starts rebuilding FROM HERE.
# Steps 1-4 (including the 400MB download) remain cached!
COPY api/ /app/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
