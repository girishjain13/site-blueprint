FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only needed if you enable render_js — installs Chromium + its OS-level
# dependencies (fonts, libgbm, etc.) for Playwright. Adds real build time
# and image size; comment this out if you never plan to use render_js.
RUN playwright install --with-deps chromium

COPY . .

# Hugging Face Spaces expects the container to listen on 7860 by default.
# Render / Cloud Run / Fly inject their own $PORT — the CMD below respects
# either, defaulting to 7860 if PORT isn't set.
ENV PORT=7860
EXPOSE 7860

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
