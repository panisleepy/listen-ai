#!/usr/bin/env python3
"""Compare lexicon baseline vs trained ML model on a labeled test set."""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from joblib import load
from sklearn.metrics import accuracy_score, classification_report, f1_score

from app import classify_text


def load_labeled_rows(csv_path: Path) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    labels: list[str] = []
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            text = (row.get("text") or "").strip()
            label = (row.get("label") or "").strip().lower()
            if not text or label not in {"positive", "neutral", "negative"}:
                continue
            texts.append(text)
            labels.append(label)
    return texts, labels


def predict_lexicon_labels(texts: list[str]) -> list[str]:
    return [classify_text(t)[0] for t in texts]


def predict_ml_labels(bundle: dict, texts: list[str]) -> list[str]:
    vectorizer = bundle["vectorizer"]
    classifier = bundle["classifier"]
    label_encoder = bundle["label_encoder"]
    X = vectorizer.transform(texts)
    y_idx = classifier.predict(X)
    return list(label_encoder.inverse_transform(y_idx))


def benchmark_latency(predict_fn, texts: list[str], rounds: int = 50) -> float:
    if not texts:
        return 0.0
    start = time.perf_counter()
    for _ in range(rounds):
        predict_fn(texts)
    elapsed = time.perf_counter() - start
    return elapsed / max(1, rounds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate sentiment models")
    parser.add_argument(
        "--test-csv",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "labeled_test.csv",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(__file__).resolve().parent / "artifacts" / "sentiment_model.joblib",
    )
    parser.add_argument("--latency-rounds", type=int, default=30)
    args = parser.parse_args()

    texts, y_true = load_labeled_rows(args.test_csv)
    if not texts:
        print("No labeled rows in test CSV.")
        return 1

    y_lex = predict_lexicon_labels(texts)
    acc_lex = accuracy_score(y_true, y_lex)
    f1_lex = f1_score(y_true, y_lex, average="macro", zero_division=0)

    if not args.model.exists():
        print("Model file missing; run: python train_sentiment_model.py")
        print(
            {
                "test_rows": len(texts),
                "lexicon": {"accuracy": round(acc_lex, 4), "macro_f1": round(f1_lex, 4)},
                "ml": None,
            }
        )
        return 0

    bundle = load(args.model)
    y_ml = predict_ml_labels(bundle, texts)
    acc_ml = accuracy_score(y_true, y_ml)
    f1_ml = f1_score(y_true, y_ml, average="macro", zero_division=0)

    def lex_batch(batch: list[str]) -> None:
        predict_lexicon_labels(batch)

    def ml_batch(batch: list[str]) -> None:
        predict_ml_labels(bundle, batch)

    t_lex = benchmark_latency(lex_batch, texts, args.latency_rounds)
    t_ml = benchmark_latency(ml_batch, texts, args.latency_rounds)

    print("=== Test set metrics ===")
    print(f"rows: {len(texts)}")
    print(f"lexicon accuracy: {acc_lex:.4f}  macro-F1: {f1_lex:.4f}")
    print(f"ml        accuracy: {acc_ml:.4f}  macro-F1: {f1_ml:.4f}")
    print("\n=== Lexicon classification report ===")
    print(classification_report(y_true, y_lex, digits=3, zero_division=0))
    print("=== ML classification report ===")
    print(classification_report(y_true, y_ml, digits=3, zero_division=0))
    print("\n=== Latency (avg seconds per full batch over test set) ===")
    print(f"lexicon: {t_lex:.6f}")
    print(f"ml:      {t_ml:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
