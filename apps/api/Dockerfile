FROM python:3.12-slim
ARG CONTROL_PLANE_VERSION=unset
ARG CONTROL_PLANE_COMMIT_SHA=unknown-build
ARG CONTROL_PLANE_BUILD_TIME=unknown-build-time
ENV CONTROL_PLANE_VERSION=${CONTROL_PLANE_VERSION} \
    CONTROL_PLANE_COMMIT_SHA=${CONTROL_PLANE_COMMIT_SHA} \
    CONTROL_PLANE_BUILD_TIME=${CONTROL_PLANE_BUILD_TIME}
LABEL org.opencontainers.image.version=${CONTROL_PLANE_VERSION} \
      org.opencontainers.image.revision=${CONTROL_PLANE_COMMIT_SHA} \
      org.opencontainers.image.created=${CONTROL_PLANE_BUILD_TIME}
WORKDIR /app
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
