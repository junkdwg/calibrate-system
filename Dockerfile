FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# LibreOffice (Excel -> PDF) + Thai fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-calc fonts-thai-tlwg fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Company fonts (AngsanaUPC) for PDF output - see fonts/README.txt
COPY fonts/ /usr/local/share/fonts/custom/
RUN fc-cache -f

RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app . .
# Windows-safe: strip CRLF from shell scripts; /app must be writable by the non-root user
# (collectstatic creates /app/staticfiles at start-up)
RUN sed -i 's/\r$//' scripts/*.sh && chmod +x scripts/*.sh \
    && mkdir -p /app/staticfiles && chown -R app:app /app
USER app
EXPOSE 8000
ENTRYPOINT ["scripts/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
