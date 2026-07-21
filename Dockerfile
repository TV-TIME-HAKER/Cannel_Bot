# ИСПОЛЬЗУЕМ ОФИЦИАЛЬНЫЙ СЛИМ-ОБРАЗ PYTHON
FROM python:3.10-slim

# УСТАНАВЛИВАЕМ РАБОЧУЮ ДИРЕКТОРИЮ ВНУТРИ КОНТЕЙНЕРА
WORKDIR /app

# КОПИРУЕМ СПИСОК ЗАВИСИМОСТЕЙ И УСТАНАВЛИВАЕМ ИХ
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# КОПИРУЕМ ОСТАЛЬНОЙ КОД ПРОЕКТА
COPY . .

# ОТКРЫВАЕМ ПОРТ ДЛЯ ВЕБ-СЕРВЕРА (Render/Koyeb используют его)
EXPOSE 10000

# КОМАНДА ЗАПУСКА НАШЕГО СКРИПТА
CMD ["python", "main.py"]
