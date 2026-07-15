FROM python:3.10-slim

WORKDIR /app

# Copiar requerimientos e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del proyecto
COPY . .

# Comando por defecto (ejecuta el scraper una vez)
CMD ["python", "main.py"]
