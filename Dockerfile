FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/app
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home catalogue
COPY app ./app
COPY catalogue ./catalogue
COPY data ./data
COPY migrations ./migrations
COPY alembic.ini .
RUN mkdir /srv/runtime && chown -R catalogue:catalogue /srv/runtime
USER catalogue
ENV STATE_DIR=/srv/runtime
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=2)"
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1"]
