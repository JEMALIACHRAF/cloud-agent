"""
Learn router v3 — ReAct architecture advisor with explicit reasoning steps.

ADVISOR PIPELINE:
  docs → classifier → requirements → architect → cost → validator → iac → END

Each step builds on the previous with EXPLICIT structured reasoning.
The cost step receives a JSON component plan from the architect and calls
calculate_architecture_cost to get a real total covering ALL services.
"""
from __future__ import annotations
import json
import os
import re
from typing import Literal, TypedDict, Annotated
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode

from core.config import settings
from core.user_profile import LEVEL_ADDENDUMS, detect_level_from_text
from core.docs_search import search_aws_documentation
from tools.aws.pricing import (
    get_ec2_pricing, get_rds_pricing, calculate_architecture_cost,
)

router = APIRouter()


def _llm(temperature: float = 0.2, streaming: bool = True):
    return ChatOpenAI(
        model=settings.default_model,
        api_key=os.environ.get("OPENAI_API_KEY", settings.openai_api_key),
        temperature=temperature, streaming=streaming, max_retries=5,
    )


def _fast_llm():
    return ChatOpenAI(
        model=settings.fast_model,
        api_key=os.environ.get("OPENAI_API_KEY", settings.openai_api_key),
        temperature=0, streaming=False, max_retries=5,
    )


# ── State ──────────────────────────────────────────────────────────────────────

class LearnState(TypedDict):
    messages:        Annotated[list[BaseMessage], add_messages]
    intent:          str
    use_case:        str
    services:        list
    service_name:    str
    requirements:    dict      # Structured requirements extracted from request
    architecture:    str       # Markdown architecture description
    component_plan:  list      # JSON list of components for cost tool
    cost_breakdown:  dict      # Output of calculate_architecture_cost
    docs_context:    str
    docs_sources:    list
    user_level:      str


UC_SERVICES = {
    "ecommerce": "CloudFront ALB ECS Fargate RDS Aurora ElastiCache S3 Cognito SQS WAF CloudWatch Route53",
    "batch":     "S3 Glue Step Functions EventBridge Athena Redshift CloudWatch",
    "api":       "API Gateway Lambda DynamoDB Cognito CloudFront WAF CloudWatch",
    "ml":        "SageMaker Bedrock S3 Lambda CloudWatch",
    "realtime":  "Kinesis Lambda MSK DynamoDB CloudWatch",
    "saas":      "EKS RDS Aurora Cognito Organizations CloudFront WAF CloudWatch",
}


CLASSIFIER = """You are a router classifying AWS questions. Output STRICT JSON ONLY (no preamble, no markdown):

{"intent": "advisor"|"compare"|"explain", "use_case": "ecommerce"|"batch"|"api"|"ml"|"realtime"|"saas"|"custom", "services": [], "service_name": ""}

ROUTING RULES:

intent = "advisor" when user wants to DESIGN/BUILD/ARCHITECT a system. Triggers:
  - Describes a workload to build (e-commerce, SaaS, API, batch pipeline, ML platform)
  - Mentions traffic numbers (e.g. "50k users/day", "500 tenants", "1M req/sec")
  - Mentions a budget or cost constraint
  - Mentions compliance, SLA, regions, isolation
  - Words like: "design", "architect", "build", "I am building", "we need", "we are migrating"

intent = "compare" when explicitly comparing two named services:
  - "X vs Y", "should I use X or Y", "X or Y for ..."

intent = "explain" ONLY when asking pure conceptual question about ONE service:
  - "what is Aurora", "how does S3 work", "tell me about Lambda"
  - NO traffic numbers, NO build/design language, NO budget

EXAMPLES (study these carefully):

Input: "B2B SaaS with 500 enterprise tenants, hard isolation, custom domains, per-tenant billing"
Output: {"intent":"advisor","use_case":"saas","services":[],"service_name":""}
(Has tenants count + describes a SaaS to build → advisor)

Input: "I am building an e-commerce platform expecting 50k users/day"
Output: {"intent":"advisor","use_case":"ecommerce","services":[],"service_name":""}

Input: "Serverless REST API with auth, expecting 10M requests/day"
Output: {"intent":"advisor","use_case":"api","services":[],"service_name":""}

Input: "Multi-region streaming pipeline for 1M events/sec"
Output: {"intent":"advisor","use_case":"realtime","services":[],"service_name":""}

Input: "Aurora vs RDS for OLTP workloads"
Output: {"intent":"compare","use_case":"custom","services":["Aurora","RDS"],"service_name":""}

Input: "What is Amazon EKS?"
Output: {"intent":"explain","use_case":"custom","services":[],"service_name":"EKS"}

Input: "How does DynamoDB handle consistency?"
Output: {"intent":"explain","use_case":"custom","services":[],"service_name":"DynamoDB"}
"""


# ── PROMPTS ────────────────────────────────────────────────────────────────────

REQUIREMENTS_PROMPT = """You are a Senior AWS Solutions Architect performing requirements elicitation.

From the user's request, extract STRUCTURED requirements. Use sensible industry defaults
where the user didn't specify. Be specific with numbers.

{docs_context}

Return STRICT JSON ONLY (no markdown, no preamble):

{{
  "workload_summary": "1 sentence",
  "traffic": {{
    "users_per_day":           "<number or estimate>",
    "requests_per_second_avg": "<number>",
    "requests_per_second_peak":"<number, typically 3-5x avg>",
    "data_transfer_gb_month":  "<number>",
    "growth_factor_year":      "<e.g. 2x>"
  }},
  "budget": {{
    "monthly_usd":  <number or null>,
    "tolerance":    "strict|flexible"
  }},
  "geographic": {{
    "primary_region":  "<aws region>",
    "multi_region":    <bool>,
    "user_geography":  "<global|americas|europe|apac>"
  }},
  "compliance":      ["PCI-DSS"|"HIPAA"|"GDPR"|"SOC2"|"none"],
  "performance": {{
    "target_latency_p99_ms": <number>,
    "availability_sla":      "99.9%|99.99%|99.999%"
  }},
  "data": {{
    "primary_db_size_gb":     <number>,
    "cache_required":         <bool>,
    "object_storage_gb":      <number>,
    "characteristics":        "transactional|analytical|both"
  }},
  "team": {{
    "size":                <number>,
    "devops_maturity":     "low|medium|high"
  }},
  "ci_cd_needed":          <bool>,
  "disaster_recovery_rpo": "<e.g. 1h|24h>",
  "disaster_recovery_rto": "<e.g. 30min|4h>"
}}

Apply defaults when missing:
- If e-commerce with N users/day, assume avg 12 req/user, peak 5x average
- If no budget, set to null and tolerance "flexible"
- If no region specified, use us-east-1
- Compliance: "none" if not mentioned (don't invent)
- Availability default: 99.9%
- Latency default: 200ms
"""


ARCHITECT_PROMPT = """You are a Principal AWS Solutions Architect.

Design a PRODUCTION-GRADE architecture for the requirements below.
The user makes real business decisions on your output — be rigorous.

{docs_context}

REQUIREMENTS:
```json
{requirements_json}
```

{level_addendum}

NON-NEGOTIABLE RULES:
1. EVERY production architecture MUST address the categories below.
   Skip nothing. If a category isn't strictly needed, explain WHY explicitly.
2. SIZE each component from the traffic numbers in requirements.
3. Cite AWS docs URLs from the context for major choices.
4. NEVER write "based on pre-trained knowledge" or apologetic disclaimers.

MANDATORY COMPONENT CATEGORIES (address every one):
  Edge & Networking : Route 53, CloudFront, WAF (+Shield), ACM
  Load Balancing    : ALB / NLB / API Gateway / Global Accelerator
  Compute           : ECS Fargate / EKS / EC2 ASG / Lambda — pick + size
  Primary Database  : RDS / Aurora / DynamoDB — sized + multi-AZ + replicas
  Cache             : ElastiCache (Redis) for session/hot data
  Storage           : S3 buckets with lifecycle + KMS
  Authentication    : Cognito (or alternative justified)
  Async messaging   : SQS / SNS / EventBridge where applicable
  Email             : SES if transactional emails are part of the use case
  Secrets / Config  : Secrets Manager, Parameter Store, KMS
  Network           : VPC + public/private subnets + NAT GW + VPC endpoints
  Observability     : CloudWatch metrics + alarms + dashboards, X-Ray traces, structured logs
  CI/CD             : CodePipeline + CodeBuild + CodeDeploy (or alternative)
  Backup & DR       : AWS Backup, snapshots, S3 cross-region replication
  IAM               : least-privilege roles, federated identity

==== OUTPUT FORMAT (follow exactly) ====

## Architecture Overview
```
[ASCII diagram showing the full system, edge → compute → data → ops]
```

## Component Specification

Output a table with EVERY component. No skipping.

| # | Service | Purpose | Sizing | Multi-AZ | Reasoning (cite doc) |
|---|---------|---------|--------|----------|----------------------|

For sizing, be quantitative:
- "4× ECS Fargate tasks, 2 vCPU / 4 GB" (NOT "ECS")
- "Aurora MySQL db.r6g.large writer + 1 reader, 200GB" (NOT "RDS")
- "CloudFront with ~5TB transfer + 50M requests/month"
- "ElastiCache cache.r6g.large × 2, Multi-AZ" 

## Component Plan (JSON for cost calculation)

Output a JSON code block (REQUIRED) that the cost agent will parse. List EVERY priced
component with full sizing. Use these service keys:
ec2, aurora, rds, fargate, lambda, elasticache_redis, alb, nat, cloudfront, s3,
dynamodb, route53, cognito, waf, cloudwatch, xray, ses, sns, sqs, secrets_manager,
kms, eks.

```json
{{
  "components": [
    {{"service": "route53",  "purpose": "DNS",  "hosted_zones": 1, "queries_million": 5}},
    {{"service": "cloudfront", "purpose": "CDN", "data_transfer_gb": 5000, "requests_million": 50}},
    {{"service": "waf", "purpose": "Edge security", "acls": 1, "rules": 12, "requests_million": 50}},
    {{"service": "alb", "purpose": "App load balancer", "count": 1, "lcu_avg": 15}},
    {{"service": "fargate", "purpose": "App tier", "vcpu": 2, "memory_gb": 4, "task_count": 4}},
    {{"service": "aurora", "purpose": "Primary DB", "instance_class": "db.r6g.large", "count": 2, "storage_gb": 200}},
    {{"service": "elasticache_redis", "purpose": "Session+cart cache", "node_type": "cache.r6g.large", "count": 2}},
    {{"service": "s3", "purpose": "Static assets + media", "storage_gb": 500, "puts_million": 1, "gets_million": 30, "transfer_out_gb": 200}},
    {{"service": "dynamodb", "purpose": "Product catalog", "reads_million": 50, "writes_million": 5, "storage_gb": 50}},
    {{"service": "cognito", "purpose": "User auth", "monthly_active_users": 50000}},
    {{"service": "nat", "purpose": "Egress", "count": 2, "data_transfer_gb": 300}},
    {{"service": "cloudwatch", "purpose": "Observability", "custom_metrics": 200, "logs_gb": 100, "alarms": 30, "dashboards": 4}},
    {{"service": "xray", "purpose": "Distributed tracing", "traces_million": 10}},
    {{"service": "ses", "purpose": "Transactional email", "emails_thousand": 100}},
    {{"service": "sqs", "purpose": "Async jobs", "requests_million": 5}},
    {{"service": "secrets_manager", "purpose": "DB creds + API keys", "secrets": 8, "api_calls_thousand": 50}},
    {{"service": "kms", "purpose": "Encryption keys", "keys": 4, "requests_thousand": 100}}
  ]
}}
```

## Design Principles (Well-Architected pillars)
Concrete actions per pillar — not platitudes.

## Data Flow
Step-by-step request lifecycle (write path AND read path).

## Implementation Roadmap
Phase 1 (foundations), Phase 2 (app), Phase 3 (observability + DR).

## Trade-offs
Honest: what is sacrificed for cost/simplicity/performance?

## Sources
Cite the AWS doc URLs you used."""


COST_PROMPT = """You are a FinOps engineer pricing an AWS architecture.

YOUR ONLY JOB: extract the JSON `components` array from the architect's output below,
then call the tool `calculate_architecture_cost` with that exact list.

After the tool returns:
1. Render the breakdown as a markdown table (## Cost Breakdown).
2. State the total monthly + yearly + 3-year TCO.
3. If a budget was provided, COMPARE against it — show "within budget" or "OVER by $X" in bold.
4. List 3-5 SPECIFIC optimization actions with estimated $ savings:
   - "Use Reserved Instances on Aurora → save ~$X (40%)"
   - "Move dev/staging to t4g.* → save ~$Y"
   - "S3 Intelligent-Tiering for assets > 30 days old → save ~$Z"
5. Show a 3-year TCO table with 2x year-over-year traffic growth applied.

ABSOLUTE RULES:
- NEVER quote pricing from memory — only what the tool returns.
- If a component is missing from the JSON, flag it and propose what to add.
- The total MUST be the sum of components from the tool — do not edit.

Architect output:
---
{architecture}
---

Budget (from requirements): ${budget}
"""


COMPARATOR_PROMPT = """You are a Principal AWS Architect comparing services.

{docs_context}

{level_addendum}

ABSOLUTE PROHIBITIONS:
- NEVER write "based on pre-trained knowledge"
- NEVER write "Please verify against AWS docs" as a disclaimer

## Head-to-Head
| Dimension | A | B |
|---|---|---|
| Pricing model | | |
| Throughput | | |
| Latency p99 | | |
| Management | | |
| Best for | | |
| Avoid when | | |

## Decision Framework
- If [criterion] → choose X because (cite doc URL)
- If [criterion] → choose Y because (cite doc URL)

## Verdict
Direct recommendation. No hedging.

## Sources"""


EXPLAINER_PROMPT = """You are a Principal AWS Engineer explaining a service.

{docs_context}

{level_addendum}

ABSOLUTE PROHIBITIONS:
- NEVER write "based on pre-trained knowledge"
- NEVER write "I couldn't find docs"
- Every factual claim MUST cite [Source](url).

## What It Is
One precise paragraph (cite doc).

## Core Concepts
3-5 fundamental concepts.

## How It Works Internally
Data flow, consistency model, scaling.

## When to Use It / When NOT to
Concrete scenarios for each.

## Pricing Model
Pricing dimensions with concrete example numbers.

## Integration Patterns
Common AWS service combinations.

## Sources"""


IAC_PROMPT = """Generate production-ready Infrastructure as Code for the architecture.

CRITICAL:
- Use **CDK v2** syntax: `from aws_cdk import aws_s3 as s3, Stack, App` (NOT `from aws_cdk import core`)
- Apply security best practices: no public S3, encryption everywhere, least-privilege IAM
- Multi-AZ where appropriate, auto-scaling enabled
- Tag every resource

## Terraform (modular)
```hcl
# main.tf — VPC + networking
[code]
```

```hcl
# compute.tf — ECS/Fargate or EC2 ASG with proper SGs
[code]
```

```hcl
# data.tf — RDS Aurora Multi-AZ + ElastiCache + DynamoDB
[code]
```

```hcl
# observability.tf — CloudWatch alarms + dashboards
[code]
```

## AWS CDK v2 (Python)
```python
# Modern aws-cdk-lib syntax (CDK v2)
from aws_cdk import (Stack, App, aws_s3 as s3, aws_ec2 as ec2,
                     aws_ecs as ecs, aws_rds as rds, aws_dynamodb as dynamodb,
                     RemovalPolicy, Duration)
from constructs import Construct
[full stack code with all components]
```

## Deploy
```bash
# Terraform
terraform init && terraform plan && terraform apply
# CDK
cdk synth && cdk deploy
```

Architecture:
{architecture}"""


# ── NODES ──────────────────────────────────────────────────────────────────────

async def docs_researcher_node(state: LearnState) -> dict:
    last = next((m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    if not last: return {"docs_context": "", "docs_sources": []}

    use_case = state.get("use_case", "custom")
    expanded = last
    if use_case in UC_SERVICES:
        expanded = f"{last} {UC_SERVICES[use_case]}"

    result = await search_aws_documentation(expanded, max_results=4)
    user_level = state.get("user_level") or detect_level_from_text(last)
    return {
        "docs_context": result["summary"],
        "docs_sources": result["sources"],
        "user_level":   user_level,
    }


async def intent_classifier_node(state: LearnState) -> dict:
    # OVERRIDE: if user explicitly chose a non-custom use_case in the UI, force advisor.
    # The use_case picker is itself a strong design-intent signal.
    initial_use_case = state.get("use_case", "custom") or "custom"
    if initial_use_case != "custom":
        return {
            "intent":       "advisor",
            "use_case":     initial_use_case,
            "services":     [],
            "service_name": "",
        }

    last = next((m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    response = await _fast_llm().ainvoke([SystemMessage(content=CLASSIFIER), HumanMessage(content=last)])
    try:
        raw = response.content.strip().strip("```json").strip("```").strip()
        data = json.loads(raw)
        intent = data.get("intent", "advisor")
        use_case = data.get("use_case", "custom")
        # Fallback heuristic: if message contains design-intent language, force advisor
        text_lc = last.lower()
        DESIGN_SIGNALS = ["users/day", "users per day", "req/sec", "req/s", "tenants",
                          "budget", "we are building", "i am building", "i\'m building",
                          "we\'re building", "design", "architect for", "platform with",
                          "system for", "events/sec", "monthly active"]
        if intent == "explain" and any(sig in text_lc for sig in DESIGN_SIGNALS):
            intent = "advisor"
            if use_case == "custom":
                # Try to infer use_case from text
                if "saas" in text_lc or "multi-tenant" in text_lc or "tenants" in text_lc: use_case = "saas"
                elif "ecommerce" in text_lc or "e-commerce" in text_lc or "shop" in text_lc or "cart" in text_lc: use_case = "ecommerce"
                elif "api" in text_lc and "rest" in text_lc: use_case = "api"
                elif "batch" in text_lc or "etl" in text_lc: use_case = "batch"
                elif "real-time" in text_lc or "streaming" in text_lc or "kinesis" in text_lc: use_case = "realtime"
                elif "ml" in text_lc or "machine learning" in text_lc: use_case = "ml"
        return {
            "intent":       intent,
            "use_case":     use_case,
            "services":     data.get("services", []),
            "service_name": data.get("service_name", ""),
        }
    except Exception:
        return {"intent": "advisor", "use_case": initial_use_case}


async def requirements_node(state: LearnState) -> dict:
    """Step 1 of ReAct advisor: extract structured requirements."""
    last = next((m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    system = REQUIREMENTS_PROMPT.format(docs_context=state.get("docs_context", ""))
    # Use streaming=False to avoid leaking JSON tokens to UI
    llm = _llm(0.0, streaming=False)
    response = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=last)])
    try:
        raw = response.content.strip().strip("```json").strip("```").strip()
        return {"requirements": json.loads(raw)}
    except Exception as e:
        return {"requirements": {"workload_summary": last[:200], "error": str(e)}}


async def architect_node(state: LearnState) -> dict:
    """Step 2: design the architecture (streamed to user) + emit JSON plan."""
    reqs = state.get("requirements", {})
    system = ARCHITECT_PROMPT.format(
        docs_context=state.get("docs_context", ""),
        requirements_json=json.dumps(reqs, indent=2),
        level_addendum=LEVEL_ADDENDUMS.get(state.get("user_level", "intermediate"), ""),
    )
    response = await _llm(0.3).ainvoke([SystemMessage(content=system)] + state["messages"])
    arch_md = response.content

    # Extract the component JSON plan
    plan = []
    m = re.search(r"```json\s*(\{.*?\"components\".*?\})\s*```", arch_md, re.DOTALL)
    if m:
        try:
            plan = json.loads(m.group(1)).get("components", [])
        except Exception:
            pass

    return {"messages": [response], "architecture": arch_md, "component_plan": plan}


async def cost_node(state: LearnState) -> dict:
    """Step 3: call calculate_architecture_cost with the architect's JSON plan."""
    plan = state.get("component_plan", [])
    reqs = state.get("requirements", {})
    budget = (reqs.get("budget") or {}).get("monthly_usd")

    # Call the cost tool directly (deterministic, no LLM round-trip needed)
    if plan:
        from tools.aws.pricing import calculate_architecture_cost as _calc
        # _calc is a structured Tool — call its underlying function via ainvoke
        breakdown = await _calc.ainvoke({"components": plan})
    else:
        breakdown = {"components": [], "total_monthly_usd": 0, "total_yearly_usd": 0,
                     "tco_3y_usd": 0, "notes": "No component plan extracted from architect output."}

    # Now have the LLM render it nicely with budget analysis
    system = COST_PROMPT.format(
        architecture=state.get("architecture", "")[:4000],
        budget=budget if budget else "(not specified)",
    )

    cost_data_msg = (
        f"The calculate_architecture_cost tool returned this breakdown:\n\n"
        f"```json\n{json.dumps(breakdown, indent=2)}\n```\n\n"
        f"Now produce the markdown cost section as instructed."
    )

    response = await _llm(0.2).ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=cost_data_msg),
    ])

    final = AIMessage(content=f"\n\n---\n\n## 💰 Cost Estimate (calculated from full component plan)\n\n{response.content}")
    return {"messages": [final], "cost_breakdown": breakdown}


async def comparator_node(state: LearnState) -> dict:
    system = COMPARATOR_PROMPT.format(
        docs_context=state.get("docs_context", ""),
        level_addendum=LEVEL_ADDENDUMS.get(state.get("user_level", "intermediate"), ""),
    )
    subject = " vs ".join(state.get("services", [])) or next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    response = await _llm(0.2).ainvoke([SystemMessage(content=system), HumanMessage(content=f"Compare: {subject}")])
    return {"messages": [response]}


async def explainer_node(state: LearnState) -> dict:
    system = EXPLAINER_PROMPT.format(
        docs_context=state.get("docs_context", ""),
        level_addendum=LEVEL_ADDENDUMS.get(state.get("user_level", "intermediate"), ""),
    )
    service = state.get("service_name") or next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    response = await _llm(0.2).ainvoke([SystemMessage(content=system), HumanMessage(content=f"Explain AWS {service} in depth.")])
    return {"messages": [response]}


async def iac_node(state: LearnState) -> dict:
    arch = state.get("architecture", "")
    if not arch: return {}
    system = IAC_PROMPT.format(architecture=arch[:5000])
    response = await _llm(0.1).ainvoke([SystemMessage(content=system), HumanMessage(content="Generate the IaC.")])
    msg = AIMessage(content=f"\n\n---\n\n## 🏗️ Infrastructure as Code\n\n{response.content}")
    return {"messages": [msg]}


# ── ROUTING ────────────────────────────────────────────────────────────────────

def route_intent(state: LearnState) -> Literal["requirements", "comparator", "explainer"]:
    i = state.get("intent", "advisor")
    if i == "compare": return "comparator"
    if i == "explain": return "explainer"
    return "requirements"


def route_after_arch(state: LearnState) -> Literal["cost", "__end__"]:
    return "cost" if state.get("architecture") else END


def route_after_cost(state: LearnState) -> Literal["iac", "__end__"]:
    return "iac" if state.get("architecture") else END


# ── GRAPH ──────────────────────────────────────────────────────────────────────

def build_learn_graph():
    g = StateGraph(LearnState)
    g.add_node("docs",         docs_researcher_node)
    g.add_node("classifier",   intent_classifier_node)
    g.add_node("requirements", requirements_node)
    g.add_node("architect",    architect_node)
    g.add_node("comparator",   comparator_node)
    g.add_node("explainer",    explainer_node)
    g.add_node("cost",         cost_node)
    g.add_node("iac",          iac_node)

    g.add_edge(START, "docs")
    g.add_edge("docs", "classifier")
    g.add_conditional_edges("classifier", route_intent, {
        "requirements": "requirements", "comparator": "comparator", "explainer": "explainer",
    })
    g.add_edge("requirements", "architect")
    g.add_conditional_edges("architect", route_after_arch, {"cost": "cost", END: END})
    g.add_conditional_edges("cost",      route_after_cost, {"iac": "iac",   END: END})
    g.add_edge("iac",        END)
    g.add_edge("comparator", END)
    g.add_edge("explainer",  END)
    return g.compile(checkpointer=InMemorySaver())


_learn_graph = build_learn_graph()

# ── API ────────────────────────────────────────────────────────────────────────

class LearnRequest(BaseModel):
    message:           str
    thread_id:         str  = "learn-default"
    use_case:          str  = "custom"
    user_level:        str  = ""
    openai_api_key:    str  = ""
    anthropic_api_key: str  = ""


@router.post("/chat")
async def learn_chat(req: LearnRequest):
    if req.openai_api_key:    os.environ["OPENAI_API_KEY"]    = req.openai_api_key
    if req.anthropic_api_key: os.environ["ANTHROPIC_API_KEY"] = req.anthropic_api_key

    forced_level = req.user_level if req.user_level else detect_level_from_text(req.message)
    config = {"configurable": {"thread_id": req.thread_id}}

    input_state: LearnState = {
        "messages":       [HumanMessage(content=req.message)],
        "intent":         "advisor",
        "use_case":       req.use_case,
        "services":       [],
        "service_name":   "",
        "requirements":   {},
        "architecture":   "",
        "component_plan": [],
        "cost_breakdown": {},
        "docs_context":   "",
        "docs_sources":   [],
        "user_level":     forced_level,
    }

    # Only stream tokens from user-facing nodes — never from JSON-emitting nodes
    USER_FACING_NODES = {"architect", "comparator", "explainer", "cost", "iac"}

    async def generator():
        try:
            async for event in _learn_graph.astream_events(input_state, config=config, version="v2"):
                ev_type = event["event"]
                name    = event.get("name", "")
                data    = event.get("data", {})

                if ev_type == "on_chat_model_stream":
                    metadata = event.get("metadata", {}) or {}
                    node = metadata.get("langgraph_node", "")
                    if node in USER_FACING_NODES:
                        chunk = data.get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"

                elif ev_type == "on_tool_start":
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool': name, 'args': data.get('input', {})})}\n\n"

                elif ev_type == "on_tool_end":
                    output = data.get("output")
                    result = output.content if hasattr(output, "content") else str(output)
                    yield f"data: {json.dumps({'type': 'tool_end', 'tool': name, 'result': result[:500]})}\n\n"

                elif ev_type == "on_chain_end" and name == "docs":
                    output = data.get("output", {})
                    if isinstance(output, dict) and output.get("docs_sources"):
                        sources = [{"service": s["service"], "url": s["url"]} for s in output["docs_sources"]]
                        yield f"data: {json.dumps({'type': 'docs_sources', 'sources': sources})}\n\n"

                elif ev_type == "on_chain_start" and name in (
                    "docs", "classifier", "requirements", "architect", "comparator", "explainer", "cost", "iac",
                ):
                    labels = {
                        "docs":         "Fetching AWS docs",
                        "classifier":   "Analyzing intent",
                        "requirements": "Extracting requirements",
                        "architect":    "Designing architecture",
                        "comparator":   "Comparing services",
                        "explainer":    "Researching service",
                        "cost":         "Pricing every component",
                        "iac":          "Generating Terraform + CDK",
                    }
                    yield f"data: {json.dumps({'type': 'agent_start', 'agent': name, 'label': labels.get(name, name)})}\n\n"
                    # Emit a markdown separator before cost & iac so their H2 headers
                    # start on a fresh line (otherwise they collide with the previous
                    # node's last line, breaking section parsing in the UI).
                    if name in ("cost", "iac"):
                        yield f"data: {json.dumps({'type': 'token', 'content': chr(10)+chr(10)+'---'+chr(10)+chr(10)})}\n\n"

                elif ev_type == "on_chain_end" and name in (
                    "docs", "classifier", "requirements", "architect", "comparator", "explainer", "cost", "iac",
                ):
                    yield f"data: {json.dumps({'type': 'agent_end', 'agent': name})}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as exc:
            import traceback; traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/templates")
async def get_templates():
    return {"templates": TEMPLATES}


# Kept lean — full templates from earlier version
TEMPLATES = [
    {"id": "ecommerce", "name": "E-Commerce Platform", "icon": "🛒",
     "description": "Production e-commerce with flash sales, payments, global CDN",
     "traffic": "10k–1M users/day", "estimated_cost": "$500–5,000/month", "complexity": "High",
     "tags": ["web", "database", "cdn"], "diagram_text": "Route 53 → CloudFront + WAF → ALB → ECS Fargate → Aurora + ElastiCache + S3",
     "services": [
       {"name": "CloudFront",  "role": "CDN + WAF", "why": "Edge caching, DDoS protection"},
       {"name": "ALB",         "role": "Load balancer", "why": "Path-based routing, SSL"},
       {"name": "ECS Fargate", "role": "App tier",  "why": "Auto-scales for flash sales"},
       {"name": "RDS Aurora",  "role": "Database",  "why": "Multi-AZ, 15 read replicas"},
       {"name": "ElastiCache", "role": "Cache",     "why": "Sub-ms cart reads"},
       {"name": "S3",          "role": "Media",     "why": "Unlimited scale"},
       {"name": "Cognito",     "role": "Auth",      "why": "OAuth2, MFA"},
     ]},
    {"id": "batch", "name": "Batch Data Pipeline", "icon": "⚙️",
     "description": "Serverless ETL processing TBs daily",
     "traffic": "TBs/day", "estimated_cost": "$200–2,000/month", "complexity": "Medium",
     "tags": ["data", "etl", "s3"], "diagram_text": "EventBridge → Step Functions → Glue → S3 → Athena | Redshift",
     "services": [
       {"name": "S3",             "role": "Data lake",      "why": "Unlimited scale, lifecycle"},
       {"name": "Step Functions", "role": "Orchestration",  "why": "Visual DAG, retries"},
       {"name": "Glue",           "role": "Spark ETL",      "why": "Auto-scaling DPU"},
       {"name": "Athena",         "role": "SQL on S3",      "why": "$5/TB scanned"},
     ]},
    {"id": "api", "name": "Serverless API", "icon": "🔌",
     "description": "Zero-infra REST API with auth, caching",
     "traffic": "0–10M req/day", "estimated_cost": "$0–500/month", "complexity": "Low",
     "tags": ["api", "serverless"], "diagram_text": "Client → CloudFront → API Gateway → Lambda → DynamoDB",
     "services": [
       {"name": "API Gateway", "role": "API mgmt",  "why": "Throttling, validation"},
       {"name": "Lambda",      "role": "Logic",     "why": "Pay per 1ms"},
       {"name": "DynamoDB",    "role": "Data",      "why": "Single-digit ms at scale"},
     ]},
    {"id": "ml", "name": "ML Training & Serving", "icon": "🤖",
     "description": "End-to-end ML on SageMaker + Bedrock",
     "traffic": "Variable", "estimated_cost": "$1,000–10,000/month", "complexity": "High",
     "tags": ["ml", "sagemaker"], "diagram_text": "S3 → Feature Store → SageMaker Training → Endpoint (A/B)",
     "services": [
       {"name": "SageMaker", "role": "Training/serving", "why": "Spot training = -90%"},
       {"name": "Bedrock",   "role": "Foundation models", "why": "Claude/Titan API"},
     ]},
    {"id": "realtime", "name": "Real-time Streaming", "icon": "⚡",
     "description": "Sub-second event processing at 1M+ events/sec",
     "traffic": "100k–1M events/sec", "estimated_cost": "$500–5,000/month", "complexity": "High",
     "tags": ["streaming", "kinesis"], "diagram_text": "Producers → Kinesis → Lambda → DynamoDB | Firehose → S3",
     "services": [
       {"name": "Kinesis",  "role": "Event stream", "why": "Ordered, 7-day replay"},
       {"name": "Lambda",   "role": "Processing",   "why": "Parallel per shard"},
     ]},
    {"id": "saas", "name": "Multi-tenant SaaS", "icon": "🏢",
     "description": "Hard tenant isolation, custom domains",
     "traffic": "Variable per tenant", "estimated_cost": "$1,000–20,000/month", "complexity": "Very High",
     "tags": ["saas", "multitenant"], "diagram_text": "Per-tenant subdomain → CloudFront → API Gateway → EKS (namespace per tenant) → RDS per tenant",
     "services": [
       {"name": "EKS",        "role": "Runtime",       "why": "Namespace isolation"},
       {"name": "RDS Aurora", "role": "Per-tenant DB", "why": "Hard data isolation"},
       {"name": "Cognito",    "role": "Per-tenant pool","why": "Isolated identity"},
     ]},
]
