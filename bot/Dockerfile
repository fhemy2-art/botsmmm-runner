FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Remove any Procfile to prevent Railway from using wrong start command
RUN rm -f Procfile railway.json .python-version .mise.toml

CMD ["python", "run.py"]
