<div align="center">

# CloudAgent — Portfolio Overview

**AI-powered conversational assistant for AWS operations**
Designed and built end-to-end during my apprenticeship as Data & AI Consultant at Capgemini SogetiLabs

</div>

---

## TL;DR

CloudAgent is a desktop application that lets engineers operate, audit, and provision AWS infrastructure through natural-language conversation — with documentation-grounded answers, real billing data, and human-in-the-loop approval gates for every destructive action.

**The numbers:**

| Metric | Value |
|---|---|
| **Lines of code** | ~12,000 (Python backend) + ~4,500 (React frontend) |
| **Total tools exposed to LLM** | 150+ across 30+ AWS services |
| **Lifecycle tools (stop/delete)** | 54 with safety-by-default patterns |
| **Provisioning tools** | 16 with AWS Well-Architected defaults |
| **AWS regions supported** | 19 commercial regions with cost factors |
| **AWS certifications covered** | 9 paths (CLF-C02 to SAP-C02) |
| **AWS docs cited per response** | 1-5 (live retrieval, not training data) |
| **Time from concept to production-grade MVP** | ~3 months of iterative development |

**Stack:** Python 3.11 · FastAPI · LangGraph · LangChain · React 18 · Electron · OpenAI GPT-4o / Anthropic Claude · boto3 · SQLite · AWS Pricing API · AWS Cost Explorer

---

## Why I built this

During my apprenticeship as Data & AI Consultant at Capgemini SogetiLabs, I work daily with AWS — sometimes designing architectures, sometimes auditing client environments, often explaining trade-offs to non-technical stakeholders. Three pain points kept recurring:

1. **The console is slow.** Every list, describe, or audit requires clicking through 4-5 panels.
2. **Cost estimates are fiction.** Marketing pages, blog posts, and even the AWS Pricing Calculator give numbers that diverge from actual billing by ±30%.
3. **Safety is mostly trust-based.** A senior engineer can run `aws cloudformation delete-stack` and cascade-delete a production VPC. There's no second layer of "are you really sure".

I wanted to see if a well-designed LLM agent could collapse these three problems into one conversational interface — provided the agent was grounded in official documentation (no hallucination), computed cost from code (not from the LLM), and asked for explicit approval before mutating anything.

CloudAgent is the result.

---

## What it does

### 1. Conversational AWS inspection
*"How many DPU-hours did my Glue jobs consume this month?"*

Agent calls `glue_total_dpu_usage(region="eu-west-1", days_back=30)` → returns 54.43 DPU-hours, $23.95 actual cost, per-job breakdown. Compare to the alternative: open CloudWatch, build a Metric Insights query, manually compute the cost.

### 2. FinOps audit with real billing
*"Audit FinOps de mes ressources eu-west-1, montre-moi les économies possibles"*

Agent calls `cleanup_recommendations_deep(region="eu-west-1")` → returns a ranked table:

```
| # | Tier | Action               | Target               | $/mo |
|---|------|----------------------|----------------------|------|
| 1 | T1   | glue_disable_trigger | trigger-iot-prod     | Var. |
| 2 | T2   | ec2_release_address  | eipalloc-XYZ         | $3.60|
| 3 | T3   | ec2_terminate_instance | i-0a1b2c3d         | $45  |
```

Then: "Walk me through these one by one?" → per-action approval cards.

### 3. Plan-first provisioning
*"Crée moi une table DynamoDB pour stocker des sessions utilisateur"*

Three-step deterministic pipeline produces a Provisioning Plan card showing:
- Parameter table (chosen + alternatives + per-component cost)
- AWS Well-Architected defaults applied automatically (encryption, PITR, tags, etc.)
- Real cost computed from `calculate_architecture_cost` (not LLM)
- Commitment savings table (RI 1yr/3yr, SP, Spot)
- Dev/staging cheaper alternative with $ savings
- Full CloudFormation YAML embedded
- `[Confirm and create]` button

Nothing is provisioned until the user clicks Confirm → approval card → click Approve.

### 4. Tiered lifecycle management
*"Stop all my running EC2 instances in eu-west-1 one by one"*

Three risk tiers enforced by workflow:
- **T1 reversible** — `stop_instance`, `disable_trigger` — zero data loss
- **T2 low-risk waste** — `release_eip`, `delete_unattached_volume` — config recreatable
- **T3 destructive** — `terminate_instance`, `delete_rds_instance` — data loss possible

Each action requires explicit user approval via an in-chat card. Mass-execution without input is architecturally impossible.

### 5. Architecture Advisor
*"What's the most cost-effective architecture for a SaaS dashboard at 50k MAU?"*

Multi-phase pipeline:
1. Extract 14 normalized criteria from natural language input
2. Retrieve relevant AWS Well-Architected pillars + service docs
3. LLM composes components, topology, justification, alternatives
4. Deterministic cost computation with RI/SP projections
5. CloudFormation YAML generation, cfn-lint validated

Output adapts depth from beginner (1-paragraph explanations) to CTO-level (failure mode analysis + trade-off matrices).

### 6. AWS Certifications quiz
*"Quiz me on SAA-C03, mixed difficulty"*

9 certification paths supported. Each question is grounded in official AWS documentation (whitepapers + service docs + FAQs). User answers stored locally; weak topics resurface in subsequent rounds (spaced repetition). Mock exam mode aggregates 65 questions across 5 domains with timed delivery.

---

## Architecture

### High-level system

![Global architecture](docs/diagrams/01_architecture_global.png)

A four-layer system: desktop client (Electron + React) → API layer (FastAPI + SSE) → agent core (LangGraph multi-agent) → AWS APIs (boto3 + Pricing + Cost Explorer).

### Multi-agent chat flow

![Chat flow](docs/diagrams/02_architecture_chat.png)

Every request goes through a documentation researcher first, then routes to one of 6 domain specialists based on intent + supervisor LLM decision. Destructive operations pause at an `interrupt_before` checkpoint and emit an approval card to the UI.

### Provisioning pipeline

![Provisioning](docs/diagrams/03_architecture_provisioning.png)

When the user asks to create a resource, the supervisor is bypassed in favor of a deterministic ReAct pipeline. The key engineering insight: **the LLM never computes cost**. A dedicated `provisioning_pricing` node calls the deterministic `calculate_architecture_cost` tool with the LLM's structured JSON output. The Plan card then receives both the LLM's design *and* the deterministic cost as context. This eliminates an entire class of hallucination.

### Lifecycle management

![Lifecycle](docs/diagrams/04_architecture_lifecycle.png)

Three-tier risk model with workflow enforcement. The agent's system prompt is dynamically modified when `cleanup_intent` is detected, forcing the agent to follow the audit → plan → one-by-one execution sequence.

### Architecture Advisor

![Advisor](docs/diagrams/05_architecture_advisor.png)

### Certifications quiz

![Certifications](docs/diagrams/06_architecture_certifications.png)

### FinOps subsystem

![FinOps](docs/diagrams/07_architecture_finops.png)

---

## Key engineering decisions

### 1. Documentation-first routing

Every conversation starts with a `docs_researcher` node that retrieves relevant AWS documentation *before* routing to a specialist. This forces the LLM to ground every response in authoritative sources. Sources are cited in the UI with clickable links.

**Why it matters:** LLM training data on AWS is months to years out of date. Service announcements, pricing changes, and feature deprecations happen weekly. Grounding in live docs is the only honest way to give AWS advice.

### 2. Deterministic cost computation

The LLM never produces dollar amounts. A dedicated `provisioning_pricing` node calls a pure Python `calculate_architecture_cost` function that combines:

- Live AWS Pricing API (5 services cached with 7-day TTL in SQLite)
- Reference pricing for 36 services with `REGION_FACTORS` for 19 regions
- Empirical commitment discounts (17–60% for RI/SP/Spot)

The LLM receives the cost as context for composing the Plan card. It can describe the cost, justify it, compare alternatives — but it cannot invent it.

**Why it matters:** Hallucinated cost estimates are one of the most damaging failures for an AWS assistant. A user trusting "$50/month" when reality is $500/month makes business decisions on false data.

### 3. Approval as a graph interrupt

LangGraph's `interrupt_before` mechanism is used to pause the graph at a `human_review` node for every tool call in the `DESTRUCTIVE_TOOLS` set. The frontend renders an approval card with the exact tool name + args. The user must explicitly resume the graph (by clicking Approve or replying "approve") for the tool to execute.

**Why it matters:** Approval as a graph primitive rather than an application-level check means it's architecturally impossible to bypass. No combination of prompt injection or LLM creativity can skip it.

### 4. Intent detection by regex, not by LLM

Critical state transitions (`creation_intent`, `cleanup_intent`, `deletion_intent`, `confirmation_intent`) are detected by Python regex on the user message, not by LLM classification. The routing decisions then bypass the supervisor when needed.

**Why it matters:** LLM-based routing has a 5-10% misclassification rate. For destructive operations that's unacceptable. Regex matching gives 100% determinism on the routing layer; the LLM handles only the open-ended generation that suits it.

### 5. Region inference per thread

The `last_region` field in `AgentState` persists across turns. The agent extracts regions from natural language ("in eu-west-1") and reuses them automatically. If a user starts a thread by saying "Show me my Glue jobs in eu-west-1", subsequent queries inherit that region without repetition.

**Why it matters:** Mistyped or absent regions are a common source of "but I have no resources there!" confusion. Region stickiness eliminates this for entire chat sessions.

### 6. Symmetric CREATE ↔ DELETE coverage

Every tool that creates an AWS resource has a corresponding delete tool. This isn't just convenience — it's a forcing function. If a new creation tool is added, the workflow forces creating its delete counterpart in the same PR. The lifecycle of every resource is fully operable from the chat.

**Why it matters:** Half-finished tooling is the silent killer of productivity. "I can create it but I have to use the console to delete it" breaks the conversational paradigm entirely.

---

## Production-grade patterns

These patterns aren't from textbooks. Each one was added in response to a real bug observed during iteration:

| Pattern | Triggered by | Implementation |
|---|---|---|
| **Approval interrupts** | "Production VPC deleted by mistake" anti-pattern | LangGraph `interrupt_before` on every destructive tool |
| **Documentation grounding** | LLM hallucinated a non-existent EC2 instance type | `docs_researcher` retrieves AWS docs before routing |
| **Deterministic pricing** | LLM said "approximately $20/month" for a $200/month workload | Dedicated `provisioning_pricing` node calls Python code |
| **Regex intent detection** | LLM router routed "delete the DynamoDB table" to Data specialist (no delete tool) | `DELETION_KEYWORDS` regex + routing override to Infra |
| **Region inference** | User asked "list my Glue crawlers" → defaulted to eu-north-1 → 0 results | Extract region from message, persist as `last_region` |
| **Safety-by-default flags** | `dynamodb_delete_table` permanently deleted data with no backup | `backup_first=True` default, requires explicit `False` to skip |
| **Error transparency** | User saw infinite loading dots when a tool failed | Try/except wraps streaming loop, emits `error` event with stack trace |
| **Completion rule** | Agent stopped at "Let me proceed with that" without making the next tool call | Prompt rule + concrete examples of required pattern |
| **Plan card before execution** | User confirmed creation without seeing cost | 3-step deterministic pipeline produces Plan card before any AWS call |

---

## What I learned

### About building agents

- **Routing layer must be deterministic.** LLM-based routing has too much variance for state machines that need to be reliable. Use regex for state transitions; use LLM for content generation.
- **Tool design is API design.** Tool function signatures, default values, return shapes, and error messages all directly affect agent behavior. A poorly-shaped tool produces poorly-shaped responses.
- **Documentation grounding is non-negotiable.** Without live doc retrieval, an AWS assistant is just a confidence-inflated training-data parrot. With it, answers are checkable and citeable.
- **Approval interrupts > approval prompts.** A "are you sure?" string in the system prompt can be bypassed. A graph interrupt cannot.

### About AWS

- **Pricing is the hardest problem.** Live Pricing API is incomplete and slow. Reference pricing goes stale. Cost Explorer has 24-48h lag. The honest answer is "blend all three with explicit caveats", and that's what production FinOps tools do.
- **Production-grade defaults are 40% of the work.** Spinning up an RDS instance is one API call. Spinning up an RDS instance with encryption, Multi-AZ, automated backups, parameter group, subnet group, security group, CloudWatch alarms, and tags is 8-10 API calls and a lot of decision-making.
- **Safety is asymmetric.** The cost of refusing an action you should have allowed is annoyance. The cost of executing an action you shouldn't have is data loss. Default to refusal + clear explanation.

### About full-stack iteration

- **Surface bugs visibly or they hide forever.** v19's transparency fix (emit `error` events with stack traces) led to discovering 3 latent bugs in subsequent versions. Silent failures multiply.
- **The user's casual phrasings are your test suite.** I designed the deletion intent regex against my mental model. The user typed "Delete the DynamoDB table UserSessions" and broke it. Test against natural language, not against assumptions.
- **README is code.** A README without a real architecture diagram, real metrics, and real limits is marketing copy. A README with all three is documentation that recruiters, contributors, and future-you can actually use.

---

## What's next

CloudAgent is functional but has clear limits I'm honest about:

- **Single-account** — multi-account support via `AssumeRole` is on the roadmap but not yet implemented
- **No mobile or web client** — Electron-only currently
- **No Slack/Teams approval bridge** — all approvals must happen in the desktop UI
- **No Terraform/CDK adapter** — CloudFormation is the only IaC path supported
- **Cost estimates ±10%** — useful for decisions, not for invoicing

I'm continuing to iterate on this as a learning project and as a daily-driver tool for my consulting work.

---

## Stack & technologies

### Backend
- **Python 3.11** with type hints throughout
- **FastAPI** for the HTTP/SSE API layer
- **LangGraph** (LangChain) for multi-agent orchestration with state + interrupts
- **boto3** for AWS API calls (60+ services touched)
- **pydantic** for structured I/O validation
- **SQLite** for local caches (pricing + audit trail)

### Frontend
- **React 18** with hooks-based architecture
- **Electron** for desktop packaging (macOS + Windows + Linux)
- **TailwindCSS** for styling with custom design tokens
- **lucide-react** for iconography
- **Server-Sent Events** for streaming token + tool events from backend

### LLM
- **OpenAI GPT-4o** / **GPT-4o-mini** (primary)
- **Anthropic Claude Sonnet** (secondary, configurable per request)
- Multi-provider failover not yet implemented

### AWS APIs touched
EC2, RDS, S3, Lambda, IAM, KMS, CloudFormation, CloudWatch, Logs, Glue, Athena, Redshift, DynamoDB, Kinesis, MSK, EKS, ECS, Fargate, Cost Explorer, Pricing, Secrets Manager, Cognito, Route 53, ElastiCache, EFS, OpenSearch, SageMaker, Step Functions, EventBridge, API Gateway, CloudFront, AWS Backup, Auto Scaling, SQS, SNS

### Development workflow
- **Conda** environment for Python
- **npm** for frontend
- **GitHub Actions** for CI (lint + tests)
- **uvicorn** for backend hot-reload during dev
- Local Windows 11 development, AWS account 506250256605 (eu-west-1 primary)

---

## Contact & links

**Achraf Jemali** — Data & AI Consultant
Paris/Île-de-France · Capgemini SogetiLabs apprenticeship · M2 DataScale @ CentraleSupélec / Paris-Saclay

- GitHub: [github.com/JEMALIACHRAF](https://github.com/JEMALIACHRAF)
- Repo: [github.com/JEMALIACHRAF/cloud-agent-v2](https://github.com/JEMALIACHRAF/cloud-agent-v2)
- LinkedIn: [linkedin.com/in/jemaliachraf](https://linkedin.com/in/jemaliachraf)

---

<div align="center">

*Open to CDI opportunities in AI Engineering / Data Science / Cloud Consulting — Paris region*

</div>
