import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="listen-ai-nlp")

_SENTIMENT_BACKEND = os.getenv("SENTIMENT_BACKEND", "auto").lower()
_MODEL_PATH = Path(os.getenv("SENTIMENT_MODEL_PATH", "")).expanduser()
if str(_MODEL_PATH) == "." or str(_MODEL_PATH) == "":
    _MODEL_PATH = Path(__file__).resolve().parent / "artifacts" / "sentiment_model.joblib"

_ML_BUNDLE: dict[str, Any] | None = None


def _load_ml_bundle() -> dict[str, Any] | None:
    global _ML_BUNDLE
    if _ML_BUNDLE is not None:
        return _ML_BUNDLE
    if _SENTIMENT_BACKEND == "lexicon":
        return None
    if _SENTIMENT_BACKEND not in {"auto", "ml"}:
        return None
    if not _MODEL_PATH.exists():
        return None
    try:
        import joblib
    except ImportError:
        return None
    try:
        _ML_BUNDLE = joblib.load(_MODEL_PATH)
    except Exception:
        _ML_BUNDLE = None
        return None
    required = {"vectorizer", "classifier", "label_encoder"}
    if not required.issubset(_ML_BUNDLE.keys()):
        _ML_BUNDLE = None
        return None
    return _ML_BUNDLE


def classify_ml(text: str) -> tuple[str, int]:
    bundle = _load_ml_bundle()
    if bundle is None:
        return classify_text(text)
    vectorizer = bundle["vectorizer"]
    classifier = bundle["classifier"]
    label_encoder = bundle["label_encoder"]
    matrix = vectorizer.transform([text])
    proba = classifier.predict_proba(matrix)[0]
    best_idx = max(range(len(proba)), key=lambda i: proba[i])
    label = str(label_encoder.inverse_transform([best_idx])[0])
    score = int(round(float(proba[best_idx]) * 100))
    return label, score

POSITIVE_WORDS = {
    "good",
    "great",
    "excellent",
    "love",
    "awesome",
    "happy",
    "amazing",
    "nice",
    "best",
    "positive",
    "fast",
    "smooth",
    "reliable",
}

POSITIVE_WORDS_ZH_TW = {
    "好",
    "很好",
    "優秀",
    "喜歡",
    "讚",
    "開心",
    "高興",
    "棒",
    "最佳",
    "正面",
    "快速",
    "順暢",
    "可靠",
    "滿意",
    "推薦",
}

NEGATIVE_WORDS = {
    "bad",
    "terrible",
    "awful",
    "hate",
    "worst",
    "slow",
    "bug",
    "bugs",
    "issue",
    "issues",
    "angry",
    "broken",
    "negative",
    "expensive",
}

NEGATIVE_WORDS_ZH_TW = {
    "差",
    "糟糕",
    "很糟",
    "討厭",
    "最差",
    "慢",
    "錯誤",
    "問題",
    "生氣",
    "壞掉",
    "負面",
    "昂貴",
    "失望",
    "卡頓",
}

NEGATION_WORDS = {
    "not",
    "never",
    "no",
    "hardly",
    "不",
    "沒",
    "無",
    "未",
    "別",
    "不是",
}

POSITIVE_WORDS_ALL = POSITIVE_WORDS | POSITIVE_WORDS_ZH_TW
NEGATIVE_WORDS_ALL = NEGATIVE_WORDS | NEGATIVE_WORDS_ZH_TW

CJK_LEXICON_TERMS = sorted(
    POSITIVE_WORDS_ZH_TW | NEGATIVE_WORDS_ZH_TW | {w for w in NEGATION_WORDS if re.search(r"[\u4e00-\u9fff]", w)},
    key=len,
    reverse=True,
)


def _tokenize_cjk_segment(segment: str) -> list[str]:
    tokens: list[str] = []
    idx = 0

    # Use longest-match first so multi-character words (e.g. "不是", "很糟") are preserved.
    while idx < len(segment):
        match = ""
        for term in CJK_LEXICON_TERMS:
            if segment.startswith(term, idx):
                match = term
                break

        if match:
            tokens.append(match)
            idx += len(match)
        else:
            tokens.append(segment[idx])
            idx += 1

    return tokens


def tokenize(text: str) -> list[str]:
    raw_tokens = re.findall(r"[a-zA-Z']+|[\u4e00-\u9fff]+", text.lower())
    tokens: list[str] = []

    for raw in raw_tokens:
        if re.fullmatch(r"[\u4e00-\u9fff]+", raw):
            tokens.extend(_tokenize_cjk_segment(raw))
        else:
            tokens.append(raw)

    return tokens


def classify_text(text: str) -> tuple[str, int]:
    tokens = tokenize(text)
    score = 0
    previous_tokens = ["", ""]

    for token in tokens:
        is_negated = any(prev in NEGATION_WORDS for prev in previous_tokens)

        if token in POSITIVE_WORDS_ALL:
            score += -1 if is_negated else 1
        elif token in NEGATIVE_WORDS_ALL:
            score += 1 if is_negated else -1

        previous_tokens = [previous_tokens[-1], token]

    if score > 0:
        return "positive", score
    if score < 0:
        return "negative", score
    return "neutral", score


class SentimentRequest(BaseModel):
    texts: list[str]


class SentimentItem(BaseModel):
    text: str
    label: str
    score: int


class SentimentResponse(BaseModel):
    sentiment_percentage: dict[str, float]
    classifications: list[SentimentItem]


@app.get("/health")
def health() -> dict[str, str]:
    bundle = _load_ml_bundle()
    mode = "ml" if bundle is not None else "lexicon"
    return {
        "status": "ok",
        "service": "nlp",
        "port": os.getenv("NLP_PORT", "8001"),
        "sentiment": mode,
    }


@app.post("/sentiment", response_model=SentimentResponse)
def sentiment(req: SentimentRequest) -> SentimentResponse:
    results: list[SentimentItem] = []
    counts = Counter({"positive": 0, "neutral": 0, "negative": 0})
    use_ml = _SENTIMENT_BACKEND == "ml" or (_SENTIMENT_BACKEND == "auto" and _load_ml_bundle() is not None)

    for text in req.texts:
        label, score = classify_ml(text) if use_ml else classify_text(text)
        counts[label] += 1
        results.append(SentimentItem(text=text, label=label, score=score))

    total = max(1, len(req.texts))
    sentiment_percentage = {
        "positive": round((counts["positive"] / total) * 100, 2),
        "neutral": round((counts["neutral"] / total) * 100, 2),
        "negative": round((counts["negative"] / total) * 100, 2),
    }

    return SentimentResponse(
        sentiment_percentage=sentiment_percentage,
        classifications=results,
    )
