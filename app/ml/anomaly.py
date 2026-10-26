from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from flask import current_app
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import bindparam, select, update

from ..extensions import db
from ..models import AccessLog, MlRun

FEATURES = [
    "hour_sin",
    "hour_cos",
    "failures_ip_15m",
    "failures_email_15m",
    "distinct_emails_ip_15m",
    "success",
    "night",
    "empty_agent",
]


def model_path():
    configured = current_app.config.get("MODEL_DIR")
    base = Path(configured) if configured else Path(current_app.instance_path) / "models"
    base.mkdir(parents=True, exist_ok=True)
    return base / "access_anomaly.joblib"


def load_logs(limit=None):
    query = select(
        AccessLog.id,
        AccessLog.email,
        AccessLog.ip,
        AccessLog.success,
        AccessLog.user_agent,
        AccessLog.created_at,
        AccessLog.label,
    ).where(AccessLog.event == "login").order_by(AccessLog.created_at)
    if limit:
        query = query.limit(limit)
    rows = db.session.execute(query).all()
    frame = pd.DataFrame(rows, columns=["id", "email", "ip", "success", "user_agent", "created_at", "label"])
    if frame.empty:
        return frame
    frame["created_at"] = pd.to_datetime(frame["created_at"], utc=True)
    return frame


def build_features(frame):
    frame = frame.sort_values("created_at").reset_index(drop=True).copy()
    hours = frame["created_at"].dt.hour + frame["created_at"].dt.minute / 60.0
    frame["hour_sin"] = np.sin(2 * np.pi * hours / 24.0)
    frame["hour_cos"] = np.cos(2 * np.pi * hours / 24.0)
    frame["night"] = ((frame["created_at"].dt.hour < 6) | (frame["created_at"].dt.hour >= 23)).astype(int)
    frame["success"] = frame["success"].astype(int)
    frame["empty_agent"] = frame["user_agent"].fillna("").str.len().lt(5).astype(int)
    frame["email"] = frame["email"].fillna("")

    window = pd.Timedelta(minutes=15)
    failures_ip = np.zeros(len(frame))
    failures_email = np.zeros(len(frame))
    distinct_emails = np.zeros(len(frame))

    for ip, group in frame.groupby("ip"):
        times = group["created_at"].to_numpy()
        fails = (1 - group["success"].to_numpy()).astype(int)
        emails = group["email"].to_numpy()
        indices = group.index.to_numpy()
        start = 0
        for pos in range(len(group)):
            while times[pos] - times[start] > window:
                start += 1
            failures_ip[indices[pos]] = fails[start : pos + 1].sum()
            distinct_emails[indices[pos]] = len(set(emails[start : pos + 1]))

    for email, group in frame.groupby("email"):
        times = group["created_at"].to_numpy()
        fails = (1 - group["success"].to_numpy()).astype(int)
        indices = group.index.to_numpy()
        start = 0
        for pos in range(len(group)):
            while times[pos] - times[start] > window:
                start += 1
            failures_email[indices[pos]] = fails[start : pos + 1].sum()

    frame["failures_ip_15m"] = failures_ip
    frame["failures_email_15m"] = failures_email
    frame["distinct_emails_ip_15m"] = distinct_emails
    return frame


def train():
    frame = load_logs()
    labeled = frame[frame["label"].notna()] if not frame.empty else frame
    if labeled.empty or labeled["label"].nunique() < 2:
        metrics = {"trained": False, "reason": "sin datos etiquetados"}
        db.session.add(MlRun(company_id=None, kind="anomaly", status="skipped", metrics=metrics))
        db.session.commit()
        return metrics

    features = build_features(frame)
    features = features[features["label"].notna()]
    x = features[FEATURES]
    y = features["label"].astype(int)
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.25, random_state=42, stratify=y)

    pipeline = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced"))
    pipeline.fit(x_train, y_train)
    predicted = pipeline.predict(x_test)
    probabilities = pipeline.predict_proba(x_test)[:, 1]

    metrics = {
        "trained": True,
        "rows": int(len(features)),
        "attack_rate": round(float(y.mean()), 4),
        "accuracy": round(float(accuracy_score(y_test, predicted)), 4),
        "precision": round(float(precision_score(y_test, predicted, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, predicted, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_test, probabilities)), 4),
    }

    final = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced"))
    final.fit(x, y)
    joblib.dump({"model": final, "features": FEATURES}, model_path())

    db.session.add(MlRun(company_id=None, kind="anomaly", status="ok", metrics=metrics))
    db.session.commit()
    return metrics


def score_recent(days=7, limit=2000):
    path = model_path()
    if not path.exists():
        return []
    bundle = joblib.load(path)
    frame = load_logs()
    if frame.empty:
        return []
    features = build_features(frame)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    recent = features[features["created_at"] >= cutoff].tail(limit).copy()
    if recent.empty:
        return []
    recent["risk"] = bundle["model"].predict_proba(recent[bundle["features"]])[:, 1]
    updates = [{"b_id": int(row.id), "b_risk": float(row.risk)} for row in recent.itertuples()]
    table = AccessLog.__table__
    db.session.connection().execute(
        update(table).where(table.c.id == bindparam("b_id")).values(risk=bindparam("b_risk")),
        updates,
    )
    db.session.commit()
    ranked = recent.sort_values("risk", ascending=False).head(50)
    return [
        {
            "id": int(row.id),
            "email": row.email,
            "ip": row.ip,
            "success": bool(row.success),
            "created_at": row.created_at.to_pydatetime(),
            "risk": float(row.risk),
        }
        for row in ranked.itertuples()
    ]
