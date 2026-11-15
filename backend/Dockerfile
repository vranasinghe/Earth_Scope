# Earth Scope backend image: used by the API, the RQ workers, the reconciler and migrations.
# Python matches the development virtual environment (3.14) so results come from the same library versions.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home --uid 10001 earthscope \
    && mkdir -p /data/artifacts /data/boundaries \
    && chown -R earthscope:earthscope /data /app \
    && chmod +x /app/docker-entrypoint.sh

USER earthscope
ENV EARTHSCOPE_ARTIFACT_DIR=/data/artifacts \
    EARTHSCOPE_BOUNDARY_CACHE_DIR=/data/boundaries \
    EARTHSCOPE_JOB_WORKER_CLASS=fork

EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
