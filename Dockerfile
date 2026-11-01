FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
RUN useradd --create-home contest
USER contest
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
