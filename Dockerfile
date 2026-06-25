FROM python:3.13-slim

# Dependencias de sistema para psycopg2 (cliente PostgreSQL / RDS)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias Python antes de copiar el codigo fuente
# para aprovechar la cache de capas de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el codigo fuente
COPY . .

# Usuario sin privilegios — nunca correr como root en produccion
RUN useradd --no-create-home --shell /bin/false botuser
USER botuser

# Migraciones: ejecutar manualmente antes de desplegar una nueva version
#   docker run --rm <imagen> python3 -m alembic upgrade head
# El contenedor principal solo arranca el bot
CMD ["python3", "-m", "scripts.run_paper"]