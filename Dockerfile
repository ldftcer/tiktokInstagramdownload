FROM python:3.9-slim


RUN pip install --no-cache-dir --upgrade yt-dlp

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "TgBotInstTik.py"]
