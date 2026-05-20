"""
Robust AWS documentation fetcher.

Strategy: detect AWS services mentioned in query, fetch their official docs landing
pages directly from docs.aws.amazon.com. Falls back to DuckDuckGo HTML search.

This is the SINGLE source of ground truth for AWS knowledge.
Every agent MUST consult it before responding.
"""
from __future__ import annotations
import re
import asyncio
from urllib.parse import quote
import httpx

# Canonical AWS docs landing pages — verified URLs
AWS_SERVICE_DOCS: dict[str, str] = {
    "ec2":            "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/concepts.html",
    "s3":             "https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html",
    "lambda":         "https://docs.aws.amazon.com/lambda/latest/dg/welcome.html",
    "rds":            "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Welcome.html",
    "aurora":         "https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_AuroraOverview.html",
    "dynamodb":       "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html",
    "iam":            "https://docs.aws.amazon.com/IAM/latest/UserGuide/introduction.html",
    "vpc":            "https://docs.aws.amazon.com/vpc/latest/userguide/what-is-amazon-vpc.html",
    "ecs":            "https://docs.aws.amazon.com/AmazonECS/latest/developerguide/Welcome.html",
    "fargate":        "https://docs.aws.amazon.com/AmazonECS/latest/userguide/what-is-fargate.html",
    "eks":            "https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html",
    "cloudwatch":     "https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/WhatIsCloudWatch.html",
    "cloudfront":     "https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Introduction.html",
    "sns":            "https://docs.aws.amazon.com/sns/latest/dg/welcome.html",
    "sqs":            "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/welcome.html",
    "route53":        "https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/Welcome.html",
    "api gateway":    "https://docs.aws.amazon.com/apigateway/latest/developerguide/welcome.html",
    "apigateway":     "https://docs.aws.amazon.com/apigateway/latest/developerguide/welcome.html",
    "elasticache":    "https://docs.aws.amazon.com/AmazonElastiCache/latest/red-ug/WhatIs.html",
    "bedrock":        "https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html",
    "sagemaker":      "https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html",
    "step functions": "https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html",
    "kinesis":        "https://docs.aws.amazon.com/streams/latest/dev/introduction.html",
    "msk":            "https://docs.aws.amazon.com/msk/latest/developerguide/what-is-msk.html",
    "glue":           "https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html",
    "athena":         "https://docs.aws.amazon.com/athena/latest/ug/what-is.html",
    "redshift":       "https://docs.aws.amazon.com/redshift/latest/mgmt/welcome.html",
    "cognito":        "https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html",
    "secrets manager":"https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html",
    "kms":            "https://docs.aws.amazon.com/kms/latest/developerguide/overview.html",
    "cloudformation": "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/Welcome.html",
    "cdk":            "https://docs.aws.amazon.com/cdk/v2/guide/home.html",
    "well-architected":"https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html",
    "organizations":  "https://docs.aws.amazon.com/organizations/latest/userguide/orgs_introduction.html",
    "control tower":  "https://docs.aws.amazon.com/controltower/latest/userguide/what-is-control-tower.html",
}

# Service aliases — map common terms to canonical keys
SERVICE_ALIASES: dict[str, str] = {
    "ec2 instance": "ec2",  "ec2 instances": "ec2",
    "lambdas": "lambda",    "lambda function": "lambda",
    "s3 bucket": "s3",      "buckets": "s3",
    "rds instance": "rds",  "database": "rds",
    "kubernetes": "eks",    "k8s": "eks",
    "container": "ecs",     "containers": "ecs",
    "nosql": "dynamodb",
    "redis": "elasticache", "memcached": "elasticache",
    "cdn": "cloudfront",
    "queue": "sqs",
    "pub/sub": "sns",       "pubsub": "sns",
    "warehouse": "redshift","data warehouse": "redshift",
    "etl": "glue",
    "auth": "cognito",      "authentication": "cognito",
    "encryption": "kms",
    "monitoring": "cloudwatch",
    "logs": "cloudwatch",
    "alarms": "cloudwatch",
    "metrics": "cloudwatch",
}


def detect_services(query: str) -> list[str]:
    """Extract AWS services mentioned in the query."""
    q = query.lower()
    found = []

    # Check direct service mentions
    for service in AWS_SERVICE_DOCS:
        if service in q and service not in found:
            found.append(service)

    # Check aliases
    for alias, canonical in SERVICE_ALIASES.items():
        if alias in q and canonical not in found:
            found.append(canonical)

    return found[:4]  # cap at 4 services


def _strip_html(html: str) -> str:
    """Extract readable text from HTML."""
    # Remove scripts, styles, navigation
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>",   " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>.*?</nav>",       " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<header[^>]*>.*?</header>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>.*?</footer>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Strip all tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode common entities
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'"))
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def _fetch_doc_page(client: httpx.AsyncClient, url: str) -> str:
    """Fetch a doc page and return readable text."""
    try:
        resp = await client.get(url, timeout=10.0)
        if resp.status_code != 200:
            return ""
        return _strip_html(resp.text)
    except Exception:
        return ""


async def search_aws_documentation(query: str, max_results: int = 3) -> dict:
    """
    Fetch authoritative AWS documentation for the query.
    Returns: { "sources": [{"service", "url", "excerpt"}], "summary": str }
    """
    services = detect_services(query)
    sources: list[dict] = []

    async with httpx.AsyncClient(
        timeout=12.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (cloud-agent)"},
    ) as client:

        # Strategy 1: direct service docs lookup
        if services:
            tasks = [
                _fetch_doc_page(client, AWS_SERVICE_DOCS[svc])
                for svc in services[:max_results]
            ]
            pages = await asyncio.gather(*tasks, return_exceptions=True)
            for svc, page in zip(services[:max_results], pages):
                if isinstance(page, str) and len(page) > 200:
                    sources.append({
                        "service": svc.upper() if len(svc) <= 4 else svc.title(),
                        "url":     AWS_SERVICE_DOCS[svc],
                        "excerpt": page[:2200],
                    })

        # Strategy 2: fallback to DuckDuckGo HTML if nothing found
        if not sources:
            try:
                resp = await client.get(
                    f"https://html.duckduckgo.com/html/?q={quote(query + ' site:docs.aws.amazon.com')}",
                )
                # Extract doc URLs from results
                urls = re.findall(r'uddg=(https%3A%2F%2Fdocs\.aws\.amazon\.com[^&"]+)', resp.text)
                from urllib.parse import unquote
                urls = [unquote(u) for u in urls[:max_results]]
                for u in urls:
                    page = await _fetch_doc_page(client, u)
                    if page and len(page) > 200:
                        sources.append({"service": "AWS Docs", "url": u, "excerpt": page[:2200]})
            except Exception:
                pass

    if not sources:
        return {
            "sources": [],
            "summary": f"No AWS documentation found for query: {query}",
        }

    # Build markdown summary for LLM context
    parts = ["## AWS Official Documentation (authoritative source)"]
    for s in sources:
        parts.append(f"\n### {s['service']}\n*Source: {s['url']}*\n\n{s['excerpt']}\n")

    return {
        "sources": sources,
        "summary": "\n".join(parts),
    }
