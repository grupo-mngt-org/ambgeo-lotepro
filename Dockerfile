FROM python:3.12-slim

# Binário uv (gerenciador de deps)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Deps de sistema: libgomp1 (GDAL embutido no pyogrio) + libpq-dev (Postgres)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m appuser && mkdir -p /app && chown appuser:appuser /app
WORKDIR /app
USER appuser

# Instala deps a partir do lock (camada cacheável)
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY --chown=appuser:appuser . .

# Diretório de dados — default sensato; no compose é montado em volume nomeado.
# Criado aqui como appuser para o volume nomeado herdar o dono correto (senão
# o mount nasce como root e o app não-root não consegue escrever).
RUN mkdir -p /app/data
ENV LOTEPRO_DATA_DIR=/app/data

EXPOSE 8000

# Porta 8000 fixa no container (o compose mapeia 8040:8000).
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
