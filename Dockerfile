FROM python:3.12-slim

WORKDIR /app

RUN pip install --upgrade pip

# Install torch CPU-only first (avoids pulling the ~2.5 GB CUDA wheel)
RUN pip install --no-cache-dir \
    torch>=2.3.0 \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
# Install remaining deps; torch is already satisfied, so it won't be re-downloaded
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
