
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
ENV DB_URL=sqlite:///./awm.db
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
