# ---- build stage: install dependencies into a virtualenv ----
FROM python:3.12-slim AS build
WORKDIR /build
RUN python -m venv /venv
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# ---- runtime stage: only the venv and our code, no compilers or pip cache ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH" \
    NETAUTO_DATA_DIR=/app/data/racks

# Never run as root inside the container.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin netauto
WORKDIR /app
COPY --from=build /venv /venv
COPY --chown=netauto:netauto app ./app
COPY --chown=netauto:netauto data/racks ./data/racks

USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
