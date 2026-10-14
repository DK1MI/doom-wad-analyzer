FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir pillow \
 && useradd --create-home --uid 10001 wad
WORKDIR /app
COPY --chown=wad:wad server.py ./
COPY --chown=wad:wad app ./app
USER wad
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/')" || exit 1
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8000"]
