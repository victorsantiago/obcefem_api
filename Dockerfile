FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY front ./front

ENV CFEM_PASTA_CACHE=/data/cache
VOLUME ["/data"]
EXPOSE 8000

# 1 worker: os dados ficam em memória no processo (~400 MB de pico na primeira carga do arquivo 2022–2026;
# a leitura é em blocos, então a série histórica completa não multiplica esse pico)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
