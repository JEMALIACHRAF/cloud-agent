"""
Cost Explorer — real AWS billing data via the ce:GetCostAndUsage API.

Tools registered:
    - ce_actual_costs:       per-service spend over a date range
    - ce_top_spenders:       top N services by spend last N days
    - ce_cost_forecast:      predicted spend for the next N days
    - ce_savings_opportunities: identify underutilized RIs / Savings Plans coverage

Requires IAM permission `ce:GetCostAndUsage` + `ce:GetCostForecast`.
Cost Explorer must be activated on the account (1-time setup in console).
"""
from __future__ import annotations
import asyncio
import functools
from datetime import datetime, timedelta
from langchain_core.tools import tool


def _run(fn, *a, **kw):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, functools.partial(fn, *a, **kw))


def _client():
    from core.session import get_client
    # Cost Explorer is a global service, accessed via us-east-1 endpoint
    return get_client("ce", "us-east-1")


def _date_str(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


# ── Actual costs by service ────────────────────────────────────────────────────

@tool
async def ce_actual_costs(
    days_back: int = 30,
    granularity: str = "DAILY",
    group_by: str = "SERVICE",
) -> dict:
    """Fetch ACTUAL AWS billing data via Cost Explorer.

    Args:
      days_back: how many days back from today (1-365)
      granularity: DAILY | MONTHLY | HOURLY (HOURLY only for last 14 days)
      group_by: SERVICE | REGION | INSTANCE_TYPE | LINKED_ACCOUNT | USAGE_TYPE

    Returns the unblended cost (what AWS actually charges, after applying RI/SP discounts).
    """
    ce = _client()
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days_back)
    try:
        resp = await _run(
            ce.get_cost_and_usage,
            TimePeriod={"Start": _date_str(start_date), "End": _date_str(end_date)},
            Granularity=granularity,
            Metrics=["UnblendedCost", "UsageQuantity"],
            GroupBy=[{"Type": "DIMENSION", "Key": group_by}],
        )
    except Exception as e:
        return {
            "error": str(e),
            "hint": ("Cost Explorer not activated yet? Enable it in AWS Console: "
                     "Billing → Cost Explorer → Launch. Wait 24h for data to populate."),
        }

    # Aggregate by group across all time periods
    agg = {}
    for period in resp.get("ResultsByTime", []):
        for group in period.get("Groups", []):
            key = group["Keys"][0] if group["Keys"] else "Unknown"
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            agg[key] = agg.get(key, 0) + amount

    total = sum(agg.values())
    breakdown = sorted(
        [{"group": k, "cost_usd": round(v, 2), "pct_of_total": round(v / total * 100, 1) if total > 0 else 0}
         for k, v in agg.items() if v > 0.01],
        key=lambda x: -x["cost_usd"],
    )

    return {
        "period":         f"{_date_str(start_date)} → {_date_str(end_date)}",
        "days_covered":   days_back,
        "granularity":    granularity,
        "group_by":       group_by,
        "total_usd":      round(total, 2),
        "daily_average":  round(total / days_back, 2),
        "monthly_proj":   round(total / days_back * 30, 2),
        "breakdown":      breakdown[:30],
        "source":         "AWS Cost Explorer (ce:GetCostAndUsage) — ACTUAL BILLING DATA",
        "note":           "UnblendedCost = what AWS actually charges, after RI/SP discounts applied.",
    }


# ── Top spenders ───────────────────────────────────────────────────────────────

@tool
async def ce_top_spenders(period_days: int = 30, top_n: int = 10) -> dict:
    """List the top N services by actual spend over the last N days.

    Useful for FinOps reviews — quickly identify where money goes.
    """
    result = await ce_actual_costs.ainvoke({
        "days_back":   period_days,
        "granularity": "MONTHLY" if period_days >= 60 else "DAILY",
        "group_by":    "SERVICE",
    })
    if "error" in result:
        return result
    return {
        "period":        result["period"],
        "total_usd":     result["total_usd"],
        "monthly_proj":  result["monthly_proj"],
        "top_spenders":  result["breakdown"][:top_n],
        "source":        result["source"],
    }


# ── Cost forecast ──────────────────────────────────────────────────────────────

@tool
async def ce_cost_forecast(days_ahead: int = 30) -> dict:
    """Predicted AWS spend for the next N days based on past usage.

    Uses Cost Explorer's ML forecast (ce:GetCostForecast).
    """
    ce = _client()
    start_date = datetime.utcnow().date() + timedelta(days=1)
    end_date = start_date + timedelta(days=days_ahead)
    try:
        resp = await _run(
            ce.get_cost_forecast,
            TimePeriod={"Start": _date_str(start_date), "End": _date_str(end_date)},
            Metric="UNBLENDED_COST",
            Granularity="MONTHLY" if days_ahead >= 30 else "DAILY",
            PredictionIntervalLevel=80,
        )
    except Exception as e:
        return {"error": str(e),
                "hint": "Forecast needs at least 30 days of historical data."}

    total = float(resp.get("Total", {}).get("Amount", 0))
    return {
        "forecast_period":  f"{_date_str(start_date)} → {_date_str(end_date)}",
        "days_ahead":       days_ahead,
        "predicted_usd":    round(total, 2),
        "confidence_level": "80%",
        "by_period":        [
            {"period": p["TimePeriod"]["Start"] + " → " + p["TimePeriod"]["End"],
             "mean":   round(float(p["MeanValue"]), 2)}
            for p in resp.get("ForecastResultsByTime", [])
        ],
        "source": "AWS Cost Explorer (ce:GetCostForecast) — ML PREDICTION",
    }


# ── Savings opportunities ──────────────────────────────────────────────────────

@tool
async def ce_savings_opportunities(days_back: int = 30) -> dict:
    """Identify potential savings: highlight services that would benefit most from RI/SP.

    Compares current on-demand spend on commitment-eligible services against
    what 1yr / 3yr commitments would have cost.
    """
    result = await ce_actual_costs.ainvoke({
        "days_back":   days_back,
        "granularity": "MONTHLY" if days_back >= 30 else "DAILY",
        "group_by":    "SERVICE",
    })
    if "error" in result:
        return result

    # Match services eligible for compute commitments
    ELIGIBLE = {
        "Amazon Elastic Compute Cloud - Compute": ("ec2",       0.33, 0.54),
        "Amazon Relational Database Service":     ("rds",       0.30, 0.60),
        "Amazon ElastiCache":                     ("elasticache", 0.30, 0.55),
        "AmazonCloudWatch":                       (None, 0, 0),  # not eligible
        "Amazon Simple Storage Service":          (None, 0, 0),  # not eligible
        "Amazon Redshift":                        ("redshift",  0.30, 0.65),
        "Amazon OpenSearch Service":              ("opensearch", 0.30, 0.60),
        "AWS Lambda":                             ("lambda_sp", 0.17, 0.28),
        "Amazon Elastic Container Service":       ("fargate_sp", 0.17, 0.28),
    }

    opportunities = []
    for item in result["breakdown"]:
        info = ELIGIBLE.get(item["group"])
        if info and info[0]:
            svc_key, disc_1yr, disc_3yr = info
            current_monthly = item["cost_usd"] / days_back * 30
            savings_1yr = current_monthly * disc_1yr
            savings_3yr = current_monthly * disc_3yr
            opportunities.append({
                "service":              item["group"],
                "current_monthly_usd":  round(current_monthly, 2),
                "savings_1yr_monthly":  round(savings_1yr, 2),
                "savings_1yr_yearly":   round(savings_1yr * 12, 2),
                "savings_3yr_monthly":  round(savings_3yr, 2),
                "savings_3yr_3year_total": round(savings_3yr * 36, 2),
                "discount_1yr_pct":     round(disc_1yr * 100, 1),
                "discount_3yr_pct":     round(disc_3yr * 100, 1),
            })
    opportunities.sort(key=lambda x: -x["savings_3yr_monthly"])

    total_1yr_savings = sum(o["savings_1yr_monthly"] for o in opportunities)
    total_3yr_savings = sum(o["savings_3yr_monthly"] for o in opportunities)

    return {
        "period_analyzed":     result["period"],
        "total_current_spend": result["total_usd"],
        "opportunities":       opportunities,
        "total_savings_1yr_monthly": round(total_1yr_savings, 2),
        "total_savings_3yr_monthly": round(total_3yr_savings, 2),
        "total_savings_3yr_3year":   round(total_3yr_savings * 36, 2),
        "recommendation": (
            f"Switching commitment-eligible workloads to 3yr Savings Plans would save "
            f"~${round(total_3yr_savings, 2)}/month "
            f"(~${round(total_3yr_savings * 36, 2)} over 3 years). "
            "Start with the top 3 services by savings_3yr_monthly."
        ),
        "source": "AWS Cost Explorer + commitment discount presets",
    }
