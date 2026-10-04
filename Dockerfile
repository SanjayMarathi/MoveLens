# One container with Python + the Stockfish engine.
FROM python:3.12-slim

# The newest official Stockfish (a "universal" build that picks the best CPU instructions at run time) is
# downloaded to /opt/stockfish. Debian's older Stockfish is installed as well, as a fallback: the app switches to
# it automatically if the download fails or the new binary can't run on the host.
ARG STOCKFISH_TAG=sf_19
RUN apt-get update \
 && apt-get install -y --no-install-recommends stockfish curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && case "$(uname -m)" in \
      x86_64)  SF=linux-x86-64-universal ;; \
      aarch64) SF=linux-arm64-universal ;; \
      *)       SF="" ;; \
    esac \
 && if [ -n "$SF" ]; then \
      ( curl -fsSL "https://github.com/official-stockfish/Stockfish/releases/download/${STOCKFISH_TAG}/stockfish-${SF}.tar.gz" \
          | tar -xz -C /opt --strip-components=1 "stockfish/stockfish-${SF}" \
        && mv "/opt/stockfish-${SF}" /opt/stockfish && chmod +x /opt/stockfish \
        && echo uci | timeout 20 /opt/stockfish | grep -q uciok \
      ) || { echo "Could not install Stockfish ${STOCKFISH_TAG}; using Debian's build"; rm -f /opt/stockfish "/opt/stockfish-${SF}"; }; \
    fi

ENV STOCKFISH_PATH=/opt/stockfish \
    STOCKFISH_FALLBACK=/usr/games/stockfish \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /app
COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY data ./data
COPY ml ./ml

# The rating estimator is optional: its libraries are only installed if you have trained a model (ml/rating_model.joblib).
RUN if [ -f ml/rating_model.joblib ]; then pip install --no-cache-dir -r requirements-ml.txt; fi

# Run as a non-root user (required by Hugging Face Spaces, good practice everywhere)
RUN useradd -m appuser
USER appuser

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
