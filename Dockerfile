FROM python:3.13-slim

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt .
# Corporate TLS-inspection proxy (Zscaler) breaks cert verification for PyPI;
# trust the package hosts so the build works behind it.
RUN pip install --no-cache-dir \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    --trusted-host pypi.python.org \
    -r requirements.txt

# App code + data (JSON fixtures double as the Spanner seed source)
COPY server.py twin_app.py spanner_store.py seed_spanner.py synergy.py \
     pon_data.json malang_sto.json synergy_levers.json synergy_assumptions.json \
     entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 8520

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8520/_stcore/health').read()==b'ok' else 1)"

ENTRYPOINT ["./entrypoint.sh"]
