# 1. Базовый образ с Python
FROM python:3.12-slim

# 2. Установка системных библиотек для работы с PostgreSQL
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 3. Установка рабочей директории внутри контейнера
WORKDIR /app

# 4. Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Копируем весь остальной код проекта в контейнер
COPY . .

# 6. Создаем папку для загрузок, чтобы она точно была
RUN mkdir -p backend/uploads

# 7. Команда для запуска приложения
# Мы указываем путь backend.main:app, так как файл main.py в папке backend
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "80"]