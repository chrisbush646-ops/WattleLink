FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system --gid 1001 django \
    && adduser --system --uid 1001 --gid 1001 django

# ---- dependencies ----
FROM base AS deps
COPY requirements/base.txt requirements/production.txt ./requirements/
RUN pip install -r requirements/production.txt

# ---- final ----
FROM base AS final
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY . .

# collectstatic needs a SECRET_KEY — use a build-time placeholder (not used at runtime)
ARG BUILD_SECRET_KEY=build-time-placeholder-not-used-in-production
RUN SECRET_KEY=$BUILD_SECRET_KEY \
    python manage.py collectstatic --noinput --settings=config.settings.production

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER django

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
