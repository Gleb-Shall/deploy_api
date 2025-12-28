FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости, Docker CLI и nginx (для проверки конфигов)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    curl \
    openssh-client \
    docker.io \
    nginx \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY src/ ./src/
COPY run.py .

# Создаем директорию для контейнеров
RUN mkdir -p /app/containers

# Переменные окружения (будут переопределены через docker-compose или при запуске)
ENV PYTHONUNBUFFERED=1
ENV DOMAIN=your-domain.com
ENV SSH_HOST=your-server-ip
ENV SSH_USER=root
# RUN_ON_SERVER=1 устанавливается автоматически при деплое на сервер

# Expose порт
EXPOSE 8000

# Запускаем приложение
CMD ["python", "run.py"]

