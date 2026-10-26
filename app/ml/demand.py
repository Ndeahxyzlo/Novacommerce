import math
from pathlib import Path
from statistics import NormalDist

import joblib
import numpy as np
import pandas as pd
from flask import current_app
from sklearn.ensemble import HistGradientBoostingRegressor
from sqlalchemy import delete, select, text

from ..extensions import db
from ..models import Company, DemandForecast, Inventory, MlRun, Product
from ..services import etl
from ..utils import utcnow

LAGS = 4
MIN_TRAIN_ROWS = 150
VALIDATION_WEEKS = 8

FEATURES = [
    "lag_1",
    "lag_2",
    "lag_3",
    "lag_4",
    "mean_4",
    "mean_8",
    "std_8",
    "week_sin",
    "week_cos",
    "log_price",
]

WEEKLY_SQL = text(
    """
    select
        f.producto_id as product_id,
        date_trunc('week', t.fecha)::date as week_start,
        sum(f.cantidad)::float as units,
        avg(f.precio_unitario)::float as price
    from dw.fact_ventas f
    join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id
    where f.empresa_id = :company_id and f.estado <> 'cancelled' and f.producto_id is not null
    group by 1, 2
    order by 1, 2
    """
)


def model_dir():
    configured = current_app.config.get("MODEL_DIR")
    path = Path(configured) if configured else Path(current_app.instance_path) / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_panel(company_id):
    rows = db.session.execute(WEEKLY_SQL, {"company_id": company_id}).all()
    if not rows:
        return pd.DataFrame(columns=["product_id", "week_start", "units", "price"])
    frame = pd.DataFrame(rows, columns=["product_id", "week_start", "units", "price"])
    frame["week_start"] = pd.to_datetime(frame["week_start"])
    last_complete = pd.Timestamp(utcnow().date()) - pd.Timedelta(days=pd.Timestamp(utcnow().date()).weekday())
    frame = frame[frame["week_start"] < last_complete]
    if frame.empty:
        return frame

    last_week = frame["week_start"].max()
    parts = []
    for product_id, group in frame.groupby("product_id"):
        weeks = pd.date_range(group["week_start"].min(), last_week, freq="7D")
        dense = group.set_index("week_start").reindex(weeks)
        dense["units"] = dense["units"].fillna(0.0)
        dense["price"] = dense["price"].ffill().bfill()
        dense["product_id"] = product_id
        dense.index.name = "week_start"
        parts.append(dense.reset_index())
    return pd.concat(parts, ignore_index=True)


def build_features(panel):
    frame = panel.sort_values(["product_id", "week_start"]).copy()
    grouped = frame.groupby("product_id")["units"]
    for lag in range(1, LAGS + 1):
        frame["lag_{}".format(lag)] = grouped.shift(lag)
    shifted = grouped.shift(1)
    frame["mean_4"] = shifted.groupby(frame["product_id"]).transform(lambda s: s.rolling(4, min_periods=1).mean())
    frame["mean_8"] = shifted.groupby(frame["product_id"]).transform(lambda s: s.rolling(8, min_periods=1).mean())
    frame["std_8"] = shifted.groupby(frame["product_id"]).transform(lambda s: s.rolling(8, min_periods=2).std())
    week_number = frame["week_start"].dt.isocalendar().week.astype(float)
    frame["week_sin"] = np.sin(2 * np.pi * week_number / 52.0)
    frame["week_cos"] = np.cos(2 * np.pi * week_number / 52.0)
    frame["log_price"] = np.log1p(frame["price"].astype(float))
    return frame


def train_model(features):
    ready = features.dropna(subset=["lag_1", "lag_2", "lag_3", "lag_4", "mean_4", "mean_8"]).copy()
    ready["std_8"] = ready["std_8"].fillna(0.0)
    if len(ready) < MIN_TRAIN_ROWS:
        return None, {"trained": False, "reason": "historial insuficiente", "rows": int(len(ready))}

    cutoff = ready["week_start"].max() - pd.Timedelta(weeks=VALIDATION_WEEKS)
    train = ready[ready["week_start"] <= cutoff]
    valid = ready[ready["week_start"] > cutoff]
    if len(train) < MIN_TRAIN_ROWS or valid.empty:
        return None, {"trained": False, "reason": "historial insuficiente", "rows": int(len(ready))}

    model = HistGradientBoostingRegressor(
        loss="poisson",
        learning_rate=0.06,
        max_iter=250,
        max_depth=5,
        min_samples_leaf=20,
        l2_regularization=1.0,
        random_state=42,
    )
    model.fit(train[FEATURES], train["units"])

    predictions = np.clip(model.predict(valid[FEATURES]), 0, None)
    actual = valid["units"].to_numpy()
    baseline = valid["mean_4"].to_numpy()
    mae = float(np.mean(np.abs(actual - predictions)))
    rmse = float(np.sqrt(np.mean((actual - predictions) ** 2)))
    baseline_mae = float(np.mean(np.abs(actual - baseline)))
    residuals = pd.DataFrame(
        {"product_id": valid["product_id"].to_numpy(), "residual": actual - predictions}
    )
    residual_std = residuals.groupby("product_id")["residual"].std().fillna(0.0).to_dict()

    metrics = {
        "trained": True,
        "rows_train": int(len(train)),
        "rows_validation": int(len(valid)),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "baseline_mae": round(baseline_mae, 4),
        "improvement_pct": round(100.0 * (baseline_mae - mae) / baseline_mae, 2) if baseline_mae > 0 else 0.0,
    }
    if mae >= baseline_mae:
        metrics["trained"] = False
        metrics["reason"] = "el modelo no supera la linea base"
        return None, metrics

    final = HistGradientBoostingRegressor(
        loss="poisson",
        learning_rate=0.06,
        max_iter=250,
        max_depth=5,
        min_samples_leaf=20,
        l2_regularization=1.0,
        random_state=42,
    )
    final.fit(ready[FEATURES], ready["units"])
    return {"model": final, "residual_std": residual_std}, metrics


def forecast_units(panel, bundle, horizon):
    results = {}
    for product_id, group in panel.groupby("product_id"):
        history = list(group.sort_values("week_start")["units"].astype(float))
        price = float(group["price"].iloc[-1])
        last_week = group["week_start"].max()
        predicted = []
        for step in range(1, horizon + 1):
            week = last_week + pd.Timedelta(weeks=step)
            recent = history[-8:]
            row = {
                "lag_1": history[-1],
                "lag_2": history[-2] if len(history) > 1 else history[-1],
                "lag_3": history[-3] if len(history) > 2 else history[-1],
                "lag_4": history[-4] if len(history) > 3 else history[-1],
                "mean_4": float(np.mean(history[-4:])),
                "mean_8": float(np.mean(recent)),
                "std_8": float(np.std(recent, ddof=1)) if len(recent) > 1 else 0.0,
                "week_sin": math.sin(2 * math.pi * week.isocalendar().week / 52.0),
                "week_cos": math.cos(2 * math.pi * week.isocalendar().week / 52.0),
                "log_price": math.log1p(price),
            }
            if bundle is not None:
                value = float(max(bundle["model"].predict(pd.DataFrame([row])[FEATURES])[0], 0.0))
            else:
                value = row["mean_8"]
            predicted.append((week.date(), value))
            history.append(value)
        results[int(product_id)] = predicted
    return results


def inventory_policy(weekly_demand, sigma_week, cost, price, company):
    lead_weeks = max(company.lead_time_days / 7.0, 1.0 / 7.0)
    z = NormalDist().inv_cdf(float(company.service_level))
    safety = max(0, math.ceil(z * sigma_week * math.sqrt(lead_weeks)))
    reorder = max(0, math.ceil(weekly_demand * lead_weeks + safety))
    annual = weekly_demand * 52.0
    unit_cost = float(cost) if float(cost) > 0 else float(price) * 0.6
    holding = float(company.holding_rate) * unit_cost
    if annual <= 0 or holding <= 0:
        eoq = 0
    else:
        eoq = max(1, round(math.sqrt(2.0 * annual * float(company.order_cost) / holding)))
    return safety, reorder, eoq


def run_company_pipeline(company_id, refresh_warehouse=True):
    company = db.session.get(Company, company_id)
    if company is None:
        raise ValueError("Empresa no encontrada")

    if refresh_warehouse:
        etl.run_etl()

    panel = load_panel(company_id)
    if panel.empty:
        metrics = {"trained": False, "reason": "sin ventas", "products": 0}
        db.session.add(MlRun(company_id=company_id, kind="demand", status="skipped", metrics=metrics))
        db.session.commit()
        return metrics

    features = build_features(panel)
    bundle, metrics = train_model(features)
    horizon = current_app.config["FORECAST_HORIZON_WEEKS"]
    forecasts = forecast_units(panel, bundle, horizon)
    kind = "gradient_boosting" if bundle is not None else "baseline_mean"

    residual_std = bundle["residual_std"] if bundle is not None else {}
    fallback_std = panel.groupby("product_id")["units"].std().fillna(0.0).to_dict()

    products = {
        p.id: p
        for p in db.session.scalars(select(Product).where(Product.company_id == company_id))
    }
    inventories = {
        inv.product_id: inv
        for inv in db.session.scalars(select(Inventory).where(Inventory.company_id == company_id))
    }

    db.session.execute(delete(DemandForecast).where(DemandForecast.company_id == company_id))
    updated = 0
    for product_id, weeks in forecasts.items():
        product = products.get(product_id)
        inventory = inventories.get(product_id)
        if product is None or inventory is None:
            continue
        for week, value in weeks:
            db.session.add(
                DemandForecast(
                    company_id=company_id,
                    product_id=product_id,
                    week_start=week,
                    predicted_units=round(value, 3),
                    model_kind=kind,
                )
            )
        weekly_demand = float(np.mean([value for _, value in weeks]))
        sigma = float(residual_std.get(product_id, fallback_std.get(product_id, 0.0)))
        safety, reorder, eoq = inventory_policy(weekly_demand, sigma, product.cost, product.price, company)
        inventory.safety_stock = safety
        inventory.reorder_point = reorder
        inventory.eoq = eoq
        updated += 1

    if bundle is not None:
        joblib.dump(
            {"model": bundle["model"], "features": FEATURES, "trained_at": utcnow().isoformat()},
            model_dir() / "demand_company_{}.joblib".format(company_id),
        )

    metrics = dict(metrics)
    metrics.update({"model_kind": kind, "products": updated, "horizon_weeks": horizon})
    db.session.add(MlRun(company_id=company_id, kind="demand", status="ok", metrics=metrics))
    db.session.commit()
    return metrics


def run_all_companies():
    summary = {}
    etl.run_etl()
    for company_id in db.session.scalars(select(Company.id).where(Company.active.is_(True))).all():
        summary[company_id] = run_company_pipeline(company_id, refresh_warehouse=False)
    return summary


def latest_run(company_id, kind="demand"):
    return db.session.scalar(
        select(MlRun).where(MlRun.company_id == company_id, MlRun.kind == kind).order_by(MlRun.id.desc()).limit(1)
    )
