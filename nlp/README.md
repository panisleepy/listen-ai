# NLP Service

This module performs sentiment analysis for English and Traditional Chinese text.

- **Default**: lexicon-based classifier (always available).
- **Optional**: TF-IDF + LogisticRegression model loaded from `artifacts/sentiment_model.joblib` when present (or when `SENTIMENT_BACKEND=ml`).

## Prerequisites

- Python 3.11+

## Run Without Docker

1. Open a terminal in this folder:

```bash
cd nlp
```

2. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. (Optional) Configure port:

```bash
export NLP_PORT=8001
```

5. Start the API:

```bash
uvicorn app:app --host 0.0.0.0 --port ${NLP_PORT:-8001}
```

## Health Check

```bash
curl http://localhost:8001/health
```

## Example Request

```bash
curl -X POST http://localhost:8001/sentiment \
  -H "Content-Type: application/json" \
  -d '{"texts":["great update","bad experience","這次更新很好","體驗很糟"]}'
```

## ML model bundle (optional)

Train from labeled CSV (see `data/labeled_train.csv`), evaluate on `data/labeled_test.csv`:

```bash
pip install -r requirements.txt
python train_sentiment_model.py
python evaluate_sentiment.py
uvicorn app:app --host 0.0.0.0 --port 8001
```

When `artifacts/sentiment_model.joblib` exists, `/health` reports `sentiment: ml` under `SENTIMENT_BACKEND=auto`.

### Environment variables

- `SENTIMENT_BACKEND`: `auto` (default), `lexicon`, or `ml`
- `SENTIMENT_MODEL_PATH`: optional override path to the joblib bundle
