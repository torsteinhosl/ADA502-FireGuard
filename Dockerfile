FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY frcm-0.1.0-py3-none-any.whl .
RUN pip install --no-cache-dir frcm-0.1.0-py3-none-any.whl
COPY . .
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["python", "-m", "ada502_fireguard.main"]