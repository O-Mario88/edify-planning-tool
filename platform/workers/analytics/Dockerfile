# Edify analytics worker image. Build context is platform/:
#   docker build --file platform/workers/analytics/Dockerfile --tag edify-analytics platform
#
# Internal only: publish its port on the private network, never to the
# internet. It has no database driver and refuses to start if it is given
# database connection settings.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/gen \
    EDIFY_ANALYTICS_ADDR=0.0.0.0:50061
WORKDIR /app
COPY workers/analytics/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY workers/analytics/edify_analytics ./edify_analytics
COPY workers/analytics/gen ./gen
RUN useradd --system --uid 10001 --no-create-home worker
USER 10001
EXPOSE 50061
CMD ["python", "-m", "edify_analytics.server"]
