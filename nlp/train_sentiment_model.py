#!/usr/bin/env python3
"""Train TF-IDF + LogisticRegression sentiment model from labeled CSV.

Default paths:
  data/labeled_train.csv -> artifacts/sentiment_model.joblib
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from joblib import dump
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder


def load_labeled_rows(csv_path: Path) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    labels: list[str] = []
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "text" not in reader.fieldnames or "label" not in reader.fieldnames:
            raise ValueError("CSV must have columns: text,label")
        for row in reader:
            text = (row.get("text") or "").strip()
            label = (row.get("label") or "").strip().lower()
            if not text or label not in {"positive", "neutral", "negative"}:
                continue
            texts.append(text)
            labels.append(label)
    if len(texts) < 10:
        raise ValueError("Need at least 10 labeled rows to train.")
    return texts, labels


def main() -> int:
    parser = argparse.ArgumentParser(description="Train sentiment TF-IDF model")
    parser.add_argument(
        "--train-csv",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "labeled_train.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "artifacts" / "sentiment_model.joblib",
    )
    args = parser.parse_args()

    texts, labels = load_labeled_rows(args.train_csv)
    label_encoder = LabelEncoder()
    y = label_encoder.fit_transform(labels)

    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 5),
        min_df=1,
        sublinear_tf=True,
    )
    X = vectorizer.fit_transform(texts)

    classifier = LogisticRegression(
        max_iter=3000,
        class_weight="balanced",
        solver="lbfgs",
    )
    classifier.fit(X, y)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "vectorizer": vectorizer,
        "classifier": classifier,
        "label_encoder": label_encoder,
    }
    dump(bundle, args.output)

    print(
        {
            "train_csv": str(args.train_csv),
            "rows": len(texts),
            "output": str(args.output),
            "classes": [str(c) for c in label_encoder.classes_],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
