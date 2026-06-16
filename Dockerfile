FROM python:3.12-slim-bookworm

# Deps de sistema mínimas (libgomp p/ GDAL embutido no pyogrio)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala deps Python (pyogrio/geopandas trazem GDAL/PROJ embutidos via wheel)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Diretório de dados efêmero (tier grátis não tem disco persistente)
ENV LOTEPRO_DATA_DIR=/tmp/lotepro-data

EXPOSE 8000

# Render injeta $PORT; fallback 8000 para dev local
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
