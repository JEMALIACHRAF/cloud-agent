"""
AWS Pricing API tools — uses regional index files (much smaller than global).
No boto3 credentials needed — pricing API is public.
"""
from __future__ import annotations
import asyncio
import httpx
from langchain_core.tools import tool

REGION_MAP = {
    "us-east-1":      "US East (N. Virginia)",
    "us-east-2":      "US East (Ohio)",
    "us-west-1":      "US West (N. California)",
    "us-west-2":      "US West (Oregon)",
    "eu-west-1":      "Europe (Ireland)",
    "eu-west-2":      "Europe (London)",
    "eu-west-3":      "Europe (Paris)",
    "eu-central-1":   "Europe (Frankfurt)",
    "eu-north-1":     "Europe (Stockholm)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-south-1":     "Asia Pacific (Mumbai)",
    "sa-east-1":      "South America (Sao Paulo)",
    "ca-central-1":   "Canada (Central)",
}


@tool
async def get_ec2_pricing(instance_type: str, region: str = "us-east-1", os: str = "Linux") -> dict:
    """Get real EC2 instance on-demand pricing from AWS official pricing API."""
    region_name = REGION_MAP.get(region, "US East (N. Virginia)")
    try:
        # Use the regional index file (5-10MB vs 500MB+ global index)
        url = f"https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/{region}/index.json"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                return {"error": f"Pricing API returned {resp.status_code}", "instance_type": instance_type}
            data = resp.json()

        products = data.get("products", {})
        terms = data.get("terms", {}).get("OnDemand", {})

        for sku, product in products.items():
            attrs = product.get("attributes", {})
            if (
                attrs.get("instanceType") == instance_type
                and attrs.get("operatingSystem") == os
                and attrs.get("tenancy") == "Shared"
                and attrs.get("preInstalledSw", "NA") == "NA"
                and attrs.get("capacitystatus", "Used") == "Used"
            ):
                if sku in terms:
                    for term_data in terms[sku].values():
                        for pd in term_data.get("priceDimensions", {}).values():
                            price_per_hr = float(pd.get("pricePerUnit", {}).get("USD", 0))
                            if price_per_hr > 0:
                                return {
                                    "instance_type":       instance_type,
                                    "region":              region,
                                    "os":                  os,
                                    "price_per_hour_usd":  price_per_hr,
                                    "price_per_day_usd":   round(price_per_hr * 24, 4),
                                    "price_per_month_usd": round(price_per_hr * 730, 2),
                                    "vcpu":                attrs.get("vcpu"),
                                    "memory":              attrs.get("memory"),
                                    "source":              "AWS Price List API (official)",
                                    "ri_1yr_savings":      f"~{round((1 - 0.40) * 100)}% with 1yr Reserved Instance",
                                    "spot_savings":        "~70-90% with Spot (interruptible)",
                                }

        return {"error": f"No pricing found for {instance_type} in {region}", "instance_type": instance_type}
    except Exception as e:
        return {"error": str(e), "instance_type": instance_type}


@tool
async def get_rds_pricing(db_instance_class: str, engine: str = "mysql", region: str = "us-east-1") -> dict:
    """Get RDS instance on-demand pricing."""
    region_name = REGION_MAP.get(region, "US East (N. Virginia)")
    try:
        url = f"https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/{region}/index.json"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                return {"error": f"Pricing API returned {resp.status_code}"}
            data = resp.json()

        products = data.get("products", {})
        terms = data.get("terms", {}).get("OnDemand", {})

        for sku, product in products.items():
            attrs = product.get("attributes", {})
            if (
                attrs.get("instanceType") == db_instance_class
                and engine.lower() in attrs.get("databaseEngine", "").lower()
                and attrs.get("deploymentOption") == "Single-AZ"
            ):
                if sku in terms:
                    for term_data in terms[sku].values():
                        for pd in term_data.get("priceDimensions", {}).values():
                            price_per_hr = float(pd.get("pricePerUnit", {}).get("USD", 0))
                            if price_per_hr > 0:
                                return {
                                    "instance_class":      db_instance_class,
                                    "engine":              engine,
                                    "region":              region,
                                    "price_per_hour_usd":  price_per_hr,
                                    "price_per_month_usd": round(price_per_hr * 730, 2),
                                    "multi_az_multiplier": "~2x for Multi-AZ deployment",
                                    "source":              "AWS Price List API (official)",
                                }

        return {"error": f"No pricing found for {db_instance_class} {engine} in {region}"}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# COMPLETE ARCHITECTURE COST CALCULATOR
# Reference pricing for 18+ AWS services (US-East-1, on-demand, late 2024).
# Use this for production-grade architecture costing.
# ─────────────────────────────────────────────────────────────────────────────

# Regional price factors relative to us-east-1 baseline.
# Source: averaged across compute/storage/network from AWS pricing docs (Q4 2024).
# Apply as multiplier on hardcoded reference prices for non-baseline regions.
REGION_FACTORS = {
    # Americas
    "us-east-1":      1.00,
    "us-east-2":      1.00,
    "us-west-1":      1.05,
    "us-west-2":      1.00,
    "ca-central-1":   1.05,
    "sa-east-1":      1.25,
    # Europe
    "eu-west-1":      1.05,
    "eu-west-2":      1.07,
    "eu-west-3":      1.10,
    "eu-central-1":   1.08,
    "eu-north-1":     1.05,
    "eu-south-1":     1.10,
    # Asia-Pacific
    "ap-northeast-1": 1.12,
    "ap-northeast-2": 1.10,
    "ap-southeast-1": 1.13,
    "ap-southeast-2": 1.15,
    "ap-south-1":     0.95,
    # Middle East / Africa
    "me-south-1":     1.15,
    "af-south-1":     1.20,
}

# Commitment discount presets — empirical % off On-Demand
# Sources: AWS pricing pages Q4 2024, averaged across compute-eligible families.
# These are realistic ranges, not exact per-SKU offers.
COMMITMENT_DISCOUNTS = {
    "on_demand":                0.00,   # baseline
    "ri_1yr_no_upfront":         0.30,   # ~30% off
    "ri_1yr_all_upfront":        0.40,   # ~40% off (effective)
    "ri_3yr_no_upfront":         0.45,   # ~45% off
    "ri_3yr_all_upfront":        0.60,   # ~60% off
    "sp_compute_1yr_no_upfront": 0.17,   # ~17% off, broader applicability than RI
    "sp_compute_3yr_all_upfront": 0.28,  # ~28% off
    "sp_ec2_1yr_no_upfront":     0.33,   # ~33% off, EC2-only SP
    "sp_ec2_3yr_all_upfront":    0.54,   # ~54% off
    "spot":                      0.70,   # ~70% off, high variability + interruption risk
}

# Services that support RI/SP discounts
COMMITMENT_ELIGIBLE_SERVICES = {
    "ec2", "rds", "rds_mysql", "rds_postgres",
    "aurora", "aurora_mysql", "aurora_postgresql",
    "elasticache", "elasticache_redis", "redis",
    "fargate", "eks", "redshift",
}

REFERENCE_PRICING_USD = {
    # Compute
    "ec2": {
        "t3.nano": 0.0052, "t3.micro": 0.0104, "t3.small": 0.0208,
        "t3.medium": 0.0416, "t3.large": 0.0832, "t3.xlarge": 0.1664, "t3.2xlarge": 0.3328,
        "t4g.micro": 0.0084, "t4g.small": 0.0168, "t4g.medium": 0.0336,
        "m5.large": 0.096, "m5.xlarge": 0.192, "m5.2xlarge": 0.384, "m5.4xlarge": 0.768,
        "m6i.large": 0.0864, "m6i.xlarge": 0.1728, "m6i.2xlarge": 0.3456,
        "c5.large": 0.085, "c5.xlarge": 0.17, "c5.2xlarge": 0.34, "c5.4xlarge": 0.68,
        "r5.large": 0.126, "r5.xlarge": 0.252, "r5.2xlarge": 0.504,
        "r6g.large": 0.1008, "r6g.xlarge": 0.2016,
    },
    "aurora_mysql": {
        "db.t3.medium": 0.073, "db.t3.large": 0.146,
        "db.r6g.large": 0.29, "db.r6g.xlarge": 0.58, "db.r6g.2xlarge": 1.16, "db.r6g.4xlarge": 2.32,
        "db.r5.large": 0.29, "db.r5.xlarge": 0.58, "db.r5.2xlarge": 1.16,
    },
    "rds_mysql": {
        "db.t3.micro": 0.017, "db.t3.small": 0.034, "db.t3.medium": 0.068,
        "db.m5.large": 0.171, "db.m5.xlarge": 0.342,
        "db.r5.large": 0.252, "db.r5.xlarge": 0.504,
    },
    "elasticache_redis": {
        "cache.t3.micro": 0.017, "cache.t3.small": 0.034, "cache.t3.medium": 0.068,
        "cache.t3.large": 0.136, "cache.r6g.large": 0.226, "cache.r6g.xlarge": 0.452,
        "cache.r6g.2xlarge": 0.904, "cache.m6g.large": 0.156, "cache.m6g.xlarge": 0.312,
    },
    # Compute (serverless / variable)
    "fargate_vcpu_hour": 0.04048,
    "fargate_gb_hour":   0.004445,
    "lambda_request_per_million": 0.20,
    "lambda_gb_second":           0.0000166667,
    # Networking
    "alb_hour":          0.0225,
    "alb_lcu_hour":      0.008,
    "nat_hour":          0.045,
    "nat_gb":            0.045,
    "cloudfront_gb_out": 0.085,
    "cloudfront_request_per_10k_https": 0.01,
    "route53_zone_month":  0.50,
    "route53_query_per_million": 0.40,
    "transit_gateway_attach_hour": 0.05,
    # Storage
    "s3_standard_gb":    0.023,
    "s3_put_per_1k":     0.005,
    "s3_get_per_1k":     0.0004,
    "s3_transfer_out_gb":0.09,
    "ebs_gp3_gb":        0.08,
    "ebs_snapshot_gb":   0.05,
    # NoSQL / Caching
    "dynamodb_read_per_million":  0.25,
    "dynamodb_write_per_million": 1.25,
    "dynamodb_storage_gb":         0.25,
    # Observability
    "cloudwatch_metric_month":     0.30,
    "cloudwatch_logs_ingest_gb":   0.50,
    "cloudwatch_logs_storage_gb":  0.03,
    "cloudwatch_alarm":            0.10,
    "cloudwatch_dashboard":        3.00,
    "xray_traces_per_million":     5.00,
    # Security
    "waf_acl_month":            5.00,
    "waf_rule_month":            1.00,
    "waf_request_per_million":   0.60,
    "cognito_mau_under_50k":     0.0055,
    "cognito_mau_over_50k":      0.0046,
    "secrets_manager_per_secret":     0.40,
    "secrets_manager_per_10k_api":    0.05,
    "kms_key_month":              1.00,
    "kms_per_10k_requests":       0.03,
    # Messaging
    "ses_per_1k_emails": 0.10,
    "sns_per_million":   0.50,
    "sqs_per_million":   0.40,
    # Containers
    "eks_cluster_hour":  0.10,
    # ─── v16 additions ───
    # Glue
    "glue_dpu_hour":        0.44,
    "glue_data_catalog_per_100k_objects": 1.00,
    # Step Functions (Standard)
    "stepfn_per_1k_transitions": 0.025,
    "stepfn_express_per_million": 1.00,
    "stepfn_express_gb_hour":    0.04,
    # Redshift (per-node hourly, on-demand)
    "redshift_ra3_xlplus":       1.086,
    "redshift_ra3_4xlarge":      3.26,
    "redshift_ra3_16xlarge":     13.04,
    "redshift_dc2_large":        0.25,
    "redshift_managed_storage_gb": 0.024,
    # ACM
    "acm_public_cert":           0.00,
    "acm_private_ca_month":      400.00,
    "acm_private_cert_issued":   0.75,
    # MSK
    "msk_m5_large_hour":         0.21,
    "msk_m5_xlarge_hour":        0.42,
    "msk_m5_2xlarge_hour":       0.84,
    "msk_storage_gb":            0.10,
    # Athena
    "athena_per_tb_scanned":     5.00,
    # Kinesis Data Streams
    "kinesis_shard_hour":        0.015,
    "kinesis_put_per_million":   0.014,
    # EFS
    "efs_standard_gb":           0.30,
    "efs_ia_gb":                 0.025,
    "efs_one_zone_gb":           0.16,
    # EBS standalone
    "ebs_gp2_gb":                0.10,
    "ebs_io2_gb":                0.125,
    "ebs_io2_iops":              0.065,
    # ECR
    "ecr_storage_gb":            0.10,
    # SageMaker
    "sagemaker_ml_t3_medium_hour": 0.0582,
    "sagemaker_ml_m5_large_hour":  0.115,
    "sagemaker_ml_m5_xlarge_hour": 0.23,
    "sagemaker_endpoint_storage_gb": 0.10,
    # VPN
    "vpn_connection_hour":       0.05,
    # Transit Gateway
    "tgw_attachment_hour":       0.05,
    "tgw_per_gb":                0.02,
    # Cost Explorer / Backup
    "backup_per_gb_warm":        0.05,
    "backup_per_gb_cold":        0.01,
    # Database engines (additional storage)
    "rds_storage_gp3_gb":  0.115,
    "aurora_storage_gb":   0.10,
}


@tool
async def calculate_architecture_cost(components: list, region: str = "us-east-1") -> dict:
    """
    Compute the FULL monthly cost of a complete architecture in USD.

    region: AWS region for price adjustment (default us-east-1 baseline).
            Other regions are scaled via REGION_FACTORS multiplier.

    Pass a LIST of dicts. Every dict MUST have a `service` field. Examples below.
    Always include sizing fields — sensible defaults are applied if missing.

    Supported services (case-insensitive):
      • ec2                {instance_type, count, hours_month=730}
      • aurora             {instance_class, count=2, storage_gb=100}  (count=2 means writer + reader)
      • rds                {instance_class, count=1, storage_gb=100, multi_az=true}
      • fargate            {vcpu, memory_gb, task_count, hours_month=730}
      • lambda             {memory_mb=512, invocations_million=1, avg_duration_ms=200}
      • elasticache_redis  {node_type, count}
      • alb                {count=1, lcu_avg=5}
      • nat                {count=2, data_transfer_gb=100}
      • cloudfront         {data_transfer_gb, requests_million}
      • s3                 {storage_gb, puts_million=0, gets_million=0, transfer_out_gb=0}
      • dynamodb           {reads_million=0, writes_million=0, storage_gb=0}
      • route53            {hosted_zones=1, queries_million=1}
      • cognito            {monthly_active_users}
      • waf                {acls=1, rules=10, requests_million=10}
      • cloudwatch         {custom_metrics=0, logs_gb=0, alarms=10, dashboards=1}
      • xray               {traces_million=1}
      • ses                {emails_thousand=1}
      • sns                {publishes_million=0}
      • sqs                {requests_million=0}
      • secrets_manager    {secrets=5, api_calls_thousand=10}
      • kms                {keys=2, requests_thousand=10}
      • eks                {clusters=1}

    Optional per-component field: `purpose` (string) and `name` (string).
    Returns breakdown per component + total monthly/yearly/3y TCO.
    """
    pricing = REFERENCE_PRICING_USD
    breakdown = []
    total = 0.0

    for comp in components or []:
        if not isinstance(comp, dict): continue
        svc = (comp.get("service") or "").lower().strip()
        cost, detail = 0.0, ""

        try:
            if svc == "ec2":
                t = comp.get("instance_type", "t3.medium")
                n = comp.get("count", 1); h = comp.get("hours_month", 730)
                rate = pricing["ec2"].get(t, 0.05)
                cost = rate * n * h
                detail = f"{n}× {t} × {h}h @ ${rate}/h"

            elif svc in ("aurora", "rds_aurora", "aurora_mysql", "aurora_postgresql"):
                ic = comp.get("instance_class", "db.r6g.large")
                n = max(comp.get("count", 2), 1)
                storage = comp.get("storage_gb", 100)
                rate = pricing["aurora_mysql"].get(ic, 0.29)
                cost = rate * n * 730 + storage * pricing["aurora_storage_gb"]
                detail = f"{n}× {ic} × 730h + {storage}GB"

            elif svc in ("rds", "rds_mysql", "rds_postgres"):
                ic = comp.get("instance_class", "db.t3.medium")
                n = comp.get("count", 1)
                storage = comp.get("storage_gb", 100)
                multi_az = comp.get("multi_az", True)
                rate = pricing["rds_mysql"].get(ic, 0.068)
                multiplier = 2 if multi_az else 1
                cost = rate * n * 730 * multiplier + storage * pricing["rds_storage_gp3_gb"]
                detail = f"{n}× {ic} × 730h × {'Multi-AZ' if multi_az else 'Single-AZ'} + {storage}GB"

            elif svc == "fargate":
                v = comp.get("vcpu", 1); m = comp.get("memory_gb", 2)
                t = comp.get("task_count", 1); h = comp.get("hours_month", 730)
                cost = (v * pricing["fargate_vcpu_hour"] + m * pricing["fargate_gb_hour"]) * t * h
                detail = f"{t} tasks × ({v} vCPU + {m}GB) × {h}h"

            elif svc == "lambda":
                inv = comp.get("invocations_million", 1)
                mem = comp.get("memory_mb", 512); dur = comp.get("avg_duration_ms", 200)
                req_cost = inv * pricing["lambda_request_per_million"]
                gb_sec = inv * 1_000_000 * (mem / 1024) * (dur / 1000)
                cost = req_cost + gb_sec * pricing["lambda_gb_second"]
                detail = f"{inv}M invocations @ {mem}MB × {dur}ms"

            elif svc in ("elasticache", "elasticache_redis", "redis"):
                nt = comp.get("node_type", "cache.t3.medium")
                n = comp.get("count", 1)
                rate = pricing["elasticache_redis"].get(nt, 0.068)
                cost = rate * n * 730
                detail = f"{n}× {nt} × 730h"

            elif svc in ("alb", "load_balancer"):
                n = comp.get("count", 1); lcu = comp.get("lcu_avg", 5)
                cost = (pricing["alb_hour"] + lcu * pricing["alb_lcu_hour"]) * 730 * n
                detail = f"{n} ALB × 730h + ~{lcu} LCU avg"

            elif svc in ("nat", "nat_gateway"):
                n = comp.get("count", 2); gb = comp.get("data_transfer_gb", 100)
                cost = pricing["nat_hour"] * 730 * n + gb * pricing["nat_gb"]
                detail = f"{n} NAT × 730h + {gb}GB"

            elif svc in ("cloudfront", "cdn"):
                gb = comp.get("data_transfer_gb", 100); req = comp.get("requests_million", 10)
                cost = gb * pricing["cloudfront_gb_out"] + (req * 100) * pricing["cloudfront_request_per_10k_https"]
                detail = f"{gb}GB transfer + {req}M HTTPS requests"

            elif svc == "s3":
                st = comp.get("storage_gb", 100); puts = comp.get("puts_million", 0)
                gets = comp.get("gets_million", 0); tr = comp.get("transfer_out_gb", 0)
                cost = (st * pricing["s3_standard_gb"] + puts * 1000 * pricing["s3_put_per_1k"]
                        + gets * 1000 * pricing["s3_get_per_1k"] + tr * pricing["s3_transfer_out_gb"])
                detail = f"{st}GB + {puts}M PUTs + {gets}M GETs + {tr}GB out"

            elif svc in ("dynamodb", "ddb"):
                r = comp.get("reads_million", 0); w = comp.get("writes_million", 0)
                st = comp.get("storage_gb", 0)
                cost = (r * pricing["dynamodb_read_per_million"] + w * pricing["dynamodb_write_per_million"]
                        + st * pricing["dynamodb_storage_gb"])
                detail = f"{r}M reads + {w}M writes + {st}GB"

            elif svc == "route53":
                z = comp.get("hosted_zones", 1); q = comp.get("queries_million", 1)
                cost = z * pricing["route53_zone_month"] + q * pricing["route53_query_per_million"]
                detail = f"{z} zone(s) + {q}M queries"

            elif svc == "cognito":
                mau = comp.get("monthly_active_users", 1000)
                t1 = min(mau, 50000) * pricing["cognito_mau_under_50k"]
                t2 = max(0, mau - 50000) * pricing["cognito_mau_over_50k"]
                cost = t1 + t2
                detail = f"{mau} MAUs"

            elif svc == "waf":
                a = comp.get("acls", 1); r = comp.get("rules", 10); req = comp.get("requests_million", 10)
                cost = (a * pricing["waf_acl_month"] + r * pricing["waf_rule_month"]
                        + req * pricing["waf_request_per_million"])
                detail = f"{a} ACL + {r} rules + {req}M requests"

            elif svc == "cloudwatch":
                m = comp.get("custom_metrics", 0); lg = comp.get("logs_gb", 0)
                a = comp.get("alarms", 10); d = comp.get("dashboards", 1)
                cost = (m * pricing["cloudwatch_metric_month"]
                        + lg * (pricing["cloudwatch_logs_ingest_gb"] + pricing["cloudwatch_logs_storage_gb"])
                        + a * pricing["cloudwatch_alarm"] + d * pricing["cloudwatch_dashboard"])
                detail = f"{m} metrics + {lg}GB logs + {a} alarms + {d} dashboards"

            elif svc == "xray":
                t = comp.get("traces_million", 1)
                cost = t * pricing["xray_traces_per_million"]
                detail = f"{t}M traces"

            elif svc == "ses":
                e = comp.get("emails_thousand", 1)
                cost = e * pricing["ses_per_1k_emails"]
                detail = f"{e}k emails"

            elif svc == "sns":
                p = comp.get("publishes_million", 0)
                cost = p * pricing["sns_per_million"]
                detail = f"{p}M publishes"

            elif svc == "sqs":
                r = comp.get("requests_million", 0)
                cost = r * pricing["sqs_per_million"]
                detail = f"{r}M requests"

            elif svc in ("secrets_manager", "secretsmanager"):
                s = comp.get("secrets", 5); c = comp.get("api_calls_thousand", 10)
                cost = s * pricing["secrets_manager_per_secret"] + (c / 10) * pricing["secrets_manager_per_10k_api"]
                detail = f"{s} secrets + {c}k API calls"

            elif svc == "kms":
                k = comp.get("keys", 2); r = comp.get("requests_thousand", 10)
                cost = k * pricing["kms_key_month"] + (r / 10) * pricing["kms_per_10k_requests"]
                detail = f"{k} keys + {r}k requests"

            elif svc == "eks":
                n = comp.get("clusters", 1)
                cost = n * pricing["eks_cluster_hour"] * 730
                detail = f"{n} cluster(s) × 730h × $0.10/h"

            elif svc == "glue":
                dpu_hours = comp.get("dpu_hours", 100)  # default: 100 DPU-hours/month
                catalog_objects = comp.get("catalog_objects_thousand", 0) / 100
                cost = dpu_hours * pricing["glue_dpu_hour"] + catalog_objects * pricing["glue_data_catalog_per_100k_objects"]
                detail = f"{dpu_hours} DPU-hours @ $0.44/DPU-h"

            elif svc in ("stepfunctions", "step_functions", "sfn"):
                mode = comp.get("mode", "standard")
                if mode == "express":
                    requests_m = comp.get("requests_million", 1)
                    gb_hours = comp.get("gb_hours", 100)
                    cost = requests_m * pricing["stepfn_express_per_million"] + gb_hours * pricing["stepfn_express_gb_hour"]
                    detail = f"Express: {requests_m}M req + {gb_hours}GB-hr"
                else:
                    transitions_k = comp.get("transitions_thousand", 1000)
                    cost = transitions_k * pricing["stepfn_per_1k_transitions"]
                    detail = f"Standard: {transitions_k}k state transitions"

            elif svc == "redshift":
                node_type = comp.get("node_type", "ra3.xlplus")
                node_count = comp.get("node_count", 2)
                storage_gb = comp.get("rms_storage_gb", 100)
                rate_key = f"redshift_{node_type.replace('.', '_')}"
                rate = pricing.get(rate_key, 1.086)
                cost = rate * node_count * 730 + storage_gb * pricing["redshift_managed_storage_gb"]
                detail = f"{node_count}× {node_type} × 730h + {storage_gb}GB RMS"

            elif svc == "acm":
                public_certs = comp.get("public_certs", 1)
                private_ca = comp.get("private_ca", 0)
                private_certs = comp.get("private_certs_issued", 0)
                cost = public_certs * 0 + private_ca * pricing["acm_private_ca_month"] + private_certs * pricing["acm_private_cert_issued"]
                detail = f"{public_certs} public (free)" + (f" + {private_ca} private CA" if private_ca else "")

            elif svc == "msk":
                broker_type = comp.get("broker_type", "kafka.m5.large")
                broker_count = comp.get("broker_count", 3)
                storage_gb = comp.get("storage_gb_per_broker", 100)
                rate_key = f"msk_{broker_type.replace('kafka.', '').replace('.', '_')}_hour"
                rate = pricing.get(rate_key, 0.21)
                cost = rate * broker_count * 730 + storage_gb * broker_count * pricing["msk_storage_gb"]
                detail = f"{broker_count}× {broker_type} × 730h + {storage_gb}GB/broker"

            elif svc == "athena":
                tb_scanned = comp.get("tb_scanned", 1)
                cost = tb_scanned * pricing["athena_per_tb_scanned"]
                detail = f"{tb_scanned}TB scanned @ $5/TB"

            elif svc in ("kinesis", "kinesis_streams"):
                shards = comp.get("shards", 1)
                put_million = comp.get("put_million", 1)
                cost = shards * pricing["kinesis_shard_hour"] * 730 + put_million * pricing["kinesis_put_per_million"]
                detail = f"{shards} shards × 730h + {put_million}M PUT payloads"

            elif svc == "efs":
                storage_gb = comp.get("storage_gb", 100)
                tier = comp.get("tier", "standard")
                rate = pricing.get(f"efs_{tier}_gb", pricing["efs_standard_gb"])
                cost = storage_gb * rate
                detail = f"{storage_gb}GB {tier}"

            elif svc == "ebs":
                gp3_gb = comp.get("gp3_gb", 0)
                gp2_gb = comp.get("gp2_gb", 0)
                io2_gb = comp.get("io2_gb", 0)
                io2_iops = comp.get("io2_iops", 0)
                cost = (gp3_gb * pricing["ebs_gp3_gb"] + gp2_gb * pricing["ebs_gp2_gb"]
                        + io2_gb * pricing["ebs_io2_gb"] + io2_iops * pricing["ebs_io2_iops"])
                detail = f"gp3={gp3_gb}GB gp2={gp2_gb}GB io2={io2_gb}GB/{io2_iops}IOPS"

            elif svc == "ecr":
                storage_gb = comp.get("storage_gb", 10)
                cost = storage_gb * pricing["ecr_storage_gb"]
                detail = f"{storage_gb}GB image storage"

            elif svc == "sagemaker":
                instance = comp.get("instance_type", "ml.m5.large")
                hours = comp.get("hours_month", 730)
                count = comp.get("count", 1)
                rate_key = f"sagemaker_{instance.replace('.', '_')}_hour"
                rate = pricing.get(rate_key, 0.115)
                cost = rate * count * hours
                detail = f"{count}× {instance} × {hours}h"

            elif svc == "vpn":
                connections = comp.get("connections", 1)
                cost = connections * pricing["vpn_connection_hour"] * 730
                detail = f"{connections} VPN connection(s) × 730h"

            elif svc in ("tgw", "transit_gateway"):
                attachments = comp.get("attachments", 1)
                data_gb = comp.get("data_gb", 100)
                cost = attachments * pricing["tgw_attachment_hour"] * 730 + data_gb * pricing["tgw_per_gb"]
                detail = f"{attachments} attachments × 730h + {data_gb}GB processed"

            elif svc == "backup":
                warm_gb = comp.get("warm_gb", 100)
                cold_gb = comp.get("cold_gb", 0)
                cost = warm_gb * pricing["backup_per_gb_warm"] + cold_gb * pricing["backup_per_gb_cold"]
                detail = f"{warm_gb}GB warm + {cold_gb}GB cold storage"

            else:
                detail = f"⚠ Unknown service '{svc}' — pricing skipped"
                cost = 0
        except Exception as e:
            detail = f"⚠ Calculation error: {e}"
            cost = 0

        total += cost
        breakdown.append({
            "service":     svc,
            "name":        comp.get("name", ""),
            "purpose":     comp.get("purpose", ""),
            "monthly_usd": round(cost, 2),
            "detail":      detail,
        })

    # Apply regional adjustment to all hardcoded reference prices
    region_factor = REGION_FACTORS.get(region, 1.00)
    if region_factor != 1.00:
        for comp in breakdown:
            comp["monthly_usd"] = round(comp["monthly_usd"] * region_factor, 2)
        total = total * region_factor

    # Compute commitment-eligible portion (only services that support RI/SP)
    eligible_total = sum(
        c["monthly_usd"] for c in breakdown
        if c.get("service") in COMMITMENT_ELIGIBLE_SERVICES
    )
    ineligible_total = total - eligible_total

    # Project commitment savings: discount applied only to eligible portion
    def _project(label, pct):
        new_eligible = eligible_total * (1 - pct)
        new_total = ineligible_total + new_eligible
        return {
            "label":               label,
            "discount_pct":        round(pct * 100, 1),
            "monthly_usd":         round(new_total, 2),
            "yearly_usd":          round(new_total * 12, 2),
            "savings_vs_ondemand": round(total - new_total, 2),
            "savings_pct_total":   round((total - new_total) / total * 100, 1) if total > 0 else 0,
        }

    commitment_projections = []
    if eligible_total > 0:
        commitment_projections = [
            _project("On-Demand (baseline)",                COMMITMENT_DISCOUNTS["on_demand"]),
            _project("Reserved 1yr No-Upfront",             COMMITMENT_DISCOUNTS["ri_1yr_no_upfront"]),
            _project("Reserved 3yr All-Upfront",            COMMITMENT_DISCOUNTS["ri_3yr_all_upfront"]),
            _project("Savings Plan Compute 1yr No-Upfront", COMMITMENT_DISCOUNTS["sp_compute_1yr_no_upfront"]),
            _project("Savings Plan Compute 3yr All-Upfront", COMMITMENT_DISCOUNTS["sp_compute_3yr_all_upfront"]),
            _project("Savings Plan EC2 1yr No-Upfront",     COMMITMENT_DISCOUNTS["sp_ec2_1yr_no_upfront"]),
            _project("Spot (variable, interruption risk)",  COMMITMENT_DISCOUNTS["spot"]),
        ]

    return {
        "components":              breakdown,
        "total_monthly_usd":       round(total, 2),
        "total_yearly_usd":        round(total * 12, 2),
        "tco_3y_usd":              round(total * 36, 2),
        "currency":                "USD",
        "region":                  region,
        "region_factor":           region_factor,
        "pricing_source":          "reference (hardcoded Q4 2024) × region factor",
        "as_of":                   "2024-Q4",
        "commitment_eligible_usd": round(eligible_total, 2),
        "commitment_ineligible_usd": round(ineligible_total, 2),
        "commitment_projections":  commitment_projections,
        "disclaimer": (
            f"Reference pricing for {region} (×{region_factor:.2f} vs us-east-1). "
            "Actual cost may vary ±5% based on instance generation. "
            "See `commitment_projections` for realistic RI/Savings Plans savings on "
            "eligible compute. Run `python scripts/refresh_pricing.py` to refresh from "
            "AWS Pricing API."
        ),
    }
