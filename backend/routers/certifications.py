"""
AWS Certifications router v2 — exam-grade quiz generation.

- Question style matches Tutorials Dojo, Stephane Maarek, AWS sample questions:
  scenario + business constraints + MOST/BEST/LEAST → 4 plausible options.
- Stratified across ALL domain topics so every exam area is covered.
- User picks count: 5 / 10 / 25 / 50 / 100.
- Anti-duplication via seed + topic rotation + question hash.
- Streams progress so the user sees questions as they're generated.
"""
from __future__ import annotations
import json
import os
import random
import hashlib
from typing import List
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from core.config import settings
from core.docs_search import search_aws_documentation

router = APIRouter()


def _llm(temperature: float = 0.7):
    """High-temp LLM for question diversity. Non-streaming (we parse JSON)."""
    return ChatOpenAI(
        model=settings.default_model,
        api_key=os.environ.get("OPENAI_API_KEY", settings.openai_api_key),
        temperature=temperature,
        streaming=False,
        max_retries=5,
    )


# ── Certification catalog (unchanged content, kept for completeness) ──────────

CERTIFICATIONS = {
    "clf-c02": {
        "id": "clf-c02", "code": "CLF-C02", "name": "AWS Certified Cloud Practitioner",
        "tier": "Foundational", "duration": "90 min", "questions": 65,
        "passing_score": 700, "cost_usd": 100, "study_hours": "60-80 hours",
        "description": "Validates foundational knowledge of AWS Cloud concepts, services, security, architecture, pricing, and support.",
        "target": "Business and technical professionals new to AWS",
        "domains": [
            {"id": "cloud-concepts", "name": "Cloud Concepts", "weight": "24%",
             "topics": ["Define benefits of AWS Cloud", "Identify design principles of AWS Cloud (Well-Architected)", "Understand benefits of migration to AWS", "Identify cloud economics (TCO, OPEX vs CAPEX, elasticity)"],
             "key_services": ["Well-Architected Framework", "AWS Cloud Adoption Framework"]},
            {"id": "security-compliance", "name": "Security and Compliance", "weight": "30%",
             "topics": ["AWS shared responsibility model", "AWS Cloud security/governance/compliance", "Identity and access management", "Security tools (GuardDuty, Inspector, Shield, WAF, KMS)"],
             "key_services": ["IAM", "Organizations", "GuardDuty", "Shield", "WAF", "KMS", "CloudTrail", "Inspector", "Macie"]},
            {"id": "technology-services", "name": "Cloud Technology and Services", "weight": "34%",
             "topics": ["Methods of deploying on AWS", "Define AWS global infrastructure", "Compute services", "Database services", "Network services", "Storage services", "AI/ML services"],
             "key_services": ["EC2", "Lambda", "S3", "RDS", "DynamoDB", "VPC", "Route 53", "CloudFront", "SageMaker"]},
            {"id": "billing-pricing", "name": "Billing, Pricing, Support", "weight": "12%",
             "topics": ["AWS pricing models (OD/Reserved/Spot/Savings)", "Billing and cost management tools", "AWS support plans", "AWS Marketplace and partner network"],
             "key_services": ["Cost Explorer", "Budgets", "Pricing Calculator", "Trusted Advisor"]},
        ],
    },
    "saa-c03": {
        "id": "saa-c03", "code": "SAA-C03", "name": "AWS Certified Solutions Architect - Associate",
        "tier": "Associate", "duration": "130 min", "questions": 65,
        "passing_score": 720, "cost_usd": 150, "study_hours": "120-160 hours",
        "description": "Validates ability to design distributed systems on AWS following architectural best practices.",
        "target": "Solutions architects, IT professionals with 1+ year AWS experience",
        "domains": [
            {"id": "secure-architectures", "name": "Design Secure Architectures", "weight": "30%",
             "topics": ["Secure access (IAM, federation, Cognito)", "Secure workloads (VPC security, encryption, secrets)", "Data security controls (KMS, S3 encryption)", "Edge security (WAF, Shield, CloudFront)"],
             "key_services": ["IAM", "Cognito", "KMS", "Secrets Manager", "VPC", "WAF", "Shield", "Macie", "GuardDuty"]},
            {"id": "resilient-architectures", "name": "Design Resilient Architectures", "weight": "26%",
             "topics": ["Scalable, loosely coupled architectures", "HA and fault tolerance (Multi-AZ, Multi-Region)", "DR strategies (RPO/RTO, Pilot Light, Warm Standby)", "Auto Scaling, ELB, Route 53"],
             "key_services": ["Auto Scaling", "ELB", "Route 53", "RDS Multi-AZ", "Aurora Global Database", "Backup", "SQS", "SNS"]},
            {"id": "high-performance", "name": "Design High-Performing Architectures", "weight": "24%",
             "topics": ["Performant storage/database", "Performant compute", "Data ingestion/transformation", "Performant network architectures"],
             "key_services": ["S3", "EFS", "FSx", "DynamoDB DAX", "ElastiCache", "CloudFront", "Global Accelerator", "Kinesis"]},
            {"id": "cost-optimized", "name": "Design Cost-Optimized Architectures", "weight": "20%",
             "topics": ["Cost-optimized storage (S3 classes, lifecycle)", "Cost-optimized compute (Spot, RI, Savings Plans)", "Cost-optimized databases", "Cost-optimized networking"],
             "key_services": ["S3 Intelligent-Tiering", "EC2 Spot", "Savings Plans", "Reserved Instances", "Cost Explorer", "Trusted Advisor"]},
        ],
    },
    "sap-c02": {
        "id": "sap-c02", "code": "SAP-C02", "name": "AWS Certified Solutions Architect - Professional",
        "tier": "Professional", "duration": "180 min", "questions": 75,
        "passing_score": 750, "cost_usd": 300, "study_hours": "200-300 hours",
        "description": "Validates advanced technical skills and experience in designing optimized AWS solutions for complex organizational requirements.",
        "target": "Senior solutions architects with 2+ years AWS experience",
        "domains": [
            {"id": "complex-orgs", "name": "Design Solutions for Organizational Complexity", "weight": "26%",
             "topics": ["Network connectivity (Transit Gateway, PrivateLink, Direct Connect)", "Multi-account environments (Organizations, Control Tower, SCPs)", "Centralized governance/logging/identity", "Hybrid identity (IAM Identity Center, AD)"],
             "key_services": ["Transit Gateway", "PrivateLink", "Direct Connect", "Organizations", "Control Tower", "IAM Identity Center", "Config"]},
            {"id": "new-solutions", "name": "Design for New Solutions", "weight": "29%",
             "topics": ["Business continuity / DR strategies", "Security controls for new workloads", "Performance and cost optimization", "Compliance (HIPAA, PCI-DSS, FedRAMP)"],
             "key_services": ["Aurora Global", "Route 53 ARC", "Macie", "Audit Manager", "Backup"]},
            {"id": "continuous-improvement", "name": "Continuous Improvement for Existing Solutions", "weight": "25%",
             "topics": ["Operational excellence improvements", "Performance improvements", "Security improvements", "Reliability improvements"],
             "key_services": ["CloudWatch Insights", "X-Ray", "Compute Optimizer", "Trusted Advisor", "Security Hub"]},
            {"id": "migration-modernization", "name": "Accelerate Workload Migration and Modernization", "weight": "20%",
             "topics": ["6 Rs migration strategy", "Re-architecting for AWS", "Refactoring applications", "Cloud Adoption Framework"],
             "key_services": ["AWS Application Migration Service", "DMS", "Schema Conversion Tool", "Migration Hub", "AppFlow"]},
        ],
    },
    "dva-c02": {
        "id": "dva-c02", "code": "DVA-C02", "name": "AWS Certified Developer - Associate",
        "tier": "Associate", "duration": "130 min", "questions": 65,
        "passing_score": 720, "cost_usd": 150, "study_hours": "120-160 hours",
        "description": "Validates skills in developing, deploying, and debugging cloud-based applications.",
        "target": "Developers with 1+ year AWS application development experience",
        "domains": [
            {"id": "aws-development", "name": "Development with AWS Services", "weight": "32%",
             "topics": ["Code for AWS-hosted applications", "Code for Lambda (events, layers, env)", "Use data stores in app development", "API development with API Gateway"],
             "key_services": ["Lambda", "DynamoDB", "API Gateway", "S3", "SDK", "X-Ray", "Step Functions"]},
            {"id": "security", "name": "Security", "weight": "26%",
             "topics": ["Auth/authz (Cognito, IAM, STS)", "Encryption (KMS, envelope)", "Sensitive data in code (Secrets Manager, SSM)"],
             "key_services": ["Cognito", "IAM", "STS", "KMS", "Secrets Manager", "SSM Parameter Store"]},
            {"id": "deployment", "name": "Deployment", "weight": "24%",
             "topics": ["Prepare artifacts (SAM, CDK, CloudFormation)", "Test (canary, blue/green, A/B)", "Deploy (CodeDeploy, CodePipeline)"],
             "key_services": ["CloudFormation", "SAM", "CDK", "Elastic Beanstalk", "CodeDeploy", "CodePipeline"]},
            {"id": "troubleshooting", "name": "Troubleshooting and Optimization", "weight": "18%",
             "topics": ["Root cause analysis (Logs Insights, X-Ray)", "Code instrumentation", "Optimization with AWS services"],
             "key_services": ["CloudWatch Logs Insights", "X-Ray", "AWS Lambda Powertools"]},
        ],
    },
    "soa-c02": {
        "id": "soa-c02", "code": "SOA-C02", "name": "AWS Certified SysOps Administrator - Associate",
        "tier": "Associate", "duration": "180 min", "questions": 65,
        "passing_score": 720, "cost_usd": 150, "study_hours": "120-160 hours",
        "description": "Validates skills to deploy, manage, and operate workloads on AWS.",
        "target": "Systems administrators with 1+ year AWS operations experience",
        "domains": [
            {"id": "monitoring", "name": "Monitoring, Logging, Remediation", "weight": "20%",
             "topics": ["CloudWatch metrics/logs/alarms", "EventBridge", "X-Ray", "Systems Manager OpsCenter"],
             "key_services": ["CloudWatch", "EventBridge", "X-Ray", "Systems Manager", "CloudTrail"]},
            {"id": "reliability-ba", "name": "Reliability and Business Continuity", "weight": "16%",
             "topics": ["Scaling (Auto Scaling, ELB)", "HA (Multi-AZ)", "DR (Backup, CRR)", "Route 53 routing policies"],
             "key_services": ["Auto Scaling", "ELB", "Route 53", "RDS Multi-AZ", "Backup"]},
            {"id": "deployment-automation", "name": "Deployment, Provisioning, Automation", "weight": "18%",
             "topics": ["CloudFormation/CDK", "Multi-AZ/Region deployments", "Auto-remediation (SSM Automation)"],
             "key_services": ["CloudFormation", "CDK", "SSM Automation", "Elastic Beanstalk"]},
            {"id": "security-compliance", "name": "Security and Compliance", "weight": "16%",
             "topics": ["IAM policies/roles", "Data protection (KMS, S3)", "Compliance (Config, Trusted Advisor, Security Hub)"],
             "key_services": ["IAM", "Config", "Security Hub", "GuardDuty", "Inspector"]},
            {"id": "networking", "name": "Networking and Content Delivery", "weight": "18%",
             "topics": ["VPC config", "Hybrid (VPN, Direct Connect)", "Route 53", "CloudFront", "VPC endpoints"],
             "key_services": ["VPC", "Route 53", "CloudFront", "Transit Gateway", "VPN", "Direct Connect"]},
            {"id": "cost-performance", "name": "Cost and Performance Optimization", "weight": "12%",
             "topics": ["Cost Explorer", "Compute Optimizer", "Right-sizing", "Reserved/Spot/Savings Plans"],
             "key_services": ["Cost Explorer", "Compute Optimizer", "Trusted Advisor", "Savings Plans"]},
        ],
    },
}


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.get("/list")
async def list_certifications():
    return {
        "certifications": [
            {"id": c["id"], "code": c["code"], "name": c["name"],
             "tier": c["tier"], "duration": c["duration"], "study_hours": c["study_hours"],
             "cost_usd": c["cost_usd"], "questions": c["questions"],
             "description": c["description"], "domain_count": len(c["domains"])}
            for c in CERTIFICATIONS.values()
        ]
    }


@router.get("/{cert_id}")
async def get_certification(cert_id: str):
    cert = CERTIFICATIONS.get(cert_id.lower())
    if not cert: return {"error": f"Certification '{cert_id}' not found"}
    return cert


# ── EXAM-GRADE QUIZ GENERATION ────────────────────────────────────────────────

# Exam-style scenario openers used by real practice tests (Tutorials Dojo, Maarek, etc.)
SCENARIO_OPENERS = [
    "A company is migrating",
    "A solutions architect is designing",
    "A multinational corporation operates",
    "A startup is building",
    "A financial services company requires",
    "A healthcare organization needs to",
    "An e-commerce platform must handle",
    "A media company processes",
    "A SaaS provider serves",
    "An online gaming company runs",
    "A pharmaceutical company stores",
    "A retail chain manages",
    "A logistics company tracks",
    "A media-streaming company delivers",
    "A government agency mandates",
]

QUESTION_KEYWORDS = ["MOST cost-effective", "MOST scalable", "MOST secure", "BEST",
                     "LEAST operational overhead", "MOST resilient", "MOST highly available",
                     "MOST performant", "FEWEST changes", "MOST efficient"]


# This prompt is the heart of the quality. It mirrors real exam writing conventions.
EXAM_PROMPT = """You are an AWS Certification exam question writer.
You produce questions in the EXACT style of the official AWS exam — the style used by
Tutorials Dojo (Jon Bonso), Stephane Maarek, ExamTopics, and the AWS sample questions.

Generate {batch_size} EXAM-GRADE multiple-choice questions for:
- Certification: {cert_name} ({cert_code})
- Domain:        {domain_name} (weight {domain_weight})
- Specific topic focus: "{topic}"
- Difficulty:    {difficulty}

EXAM-STYLE RULES (non-negotiable — these match the real exam):

1. SCENARIO-BASED. Every question opens with a business scenario (2-4 sentences) describing:
   - A company / organization / use case
   - Specific technical requirements
   - Specific constraints (cost, compliance, latency, scale, ops burden, etc.)
   Example openers: {openers_examples}

2. QUESTION KEYWORD. Always use ONE qualifier from: MOST cost-effective, MOST scalable,
   MOST secure, BEST, LEAST operational overhead, MOST resilient, FEWEST changes.
   This is what makes real exam questions distinguishable.

3. 4 OPTIONS, ALL PLAUSIBLE. Distractors must be technically valid AWS solutions —
   they should solve the problem but fail one constraint (cost, ops burden, etc.).
   Common distractor patterns from real exams:
   - Over-engineering (e.g. Kinesis when SQS suffices)
   - Wrong service category (EFS instead of S3 for static content)
   - Self-managed when managed exists (running Cassandra on EC2 instead of Keyspaces)
   - Missing HA (single AZ when Multi-AZ required)
   - Missing encryption / public access (when compliance is mentioned)

4. ANSWER + EXPLANATION quality:
   - Explanation cites WHY the correct answer is correct
   - Explanation cites WHY each distractor fails (one sentence per distractor)
   - Reference an AWS doc URL

5. COVER THESE SERVICES (commonly tested in real exam pools for this topic):
   {key_services}

6. DIVERSITY: This batch is question seed #{seed}. Do NOT repeat scenarios from these
   recent themes (avoid duplicates):
   {avoid_themes}

{docs_context}

OUTPUT — STRICT JSON ONLY (no preamble, no ```json fences):

{{
  "questions": [
    {{
      "question": "<2-4 sentence scenario + question with MOST/BEST/LEAST keyword>",
      "options": {{"A": "<option>", "B": "<option>", "C": "<option>", "D": "<option>"}},
      "correct": "<A|B|C|D>",
      "explanation": "<Why correct is right (2 sentences). Then: A is wrong because... B is wrong because... C is wrong because... D is wrong because...>",
      "reference_url": "https://docs.aws.amazon.com/...",
      "topic_tag": "{topic}"
    }}
  ]
}}
"""


class QuizRequest(BaseModel):
    cert_id:        str
    domain_id:      str
    num_questions:  int = 10
    openai_api_key: str = ""


def _stratify(num_questions: int, num_topics: int) -> List[int]:
    """Distribute N questions across topics as evenly as possible."""
    if num_topics == 0: return []
    base = num_questions // num_topics
    extras = num_questions - base * num_topics
    return [base + (1 if i < extras else 0) for i in range(num_topics)]


def _question_hash(q: dict) -> str:
    """Fingerprint a question to detect duplicates."""
    text = (q.get("question", "") + str(q.get("options", "")))[:300].lower()
    return hashlib.md5(text.encode()).hexdigest()[:12]


@router.post("/quiz")
async def generate_quiz(req: QuizRequest):
    if req.openai_api_key:
        os.environ["OPENAI_API_KEY"] = req.openai_api_key

    cert = CERTIFICATIONS.get(req.cert_id.lower())
    if not cert: return {"error": f"Certification '{req.cert_id}' not found"}

    domain = next((d for d in cert["domains"] if d["id"] == req.domain_id), None)
    if not domain: return {"error": f"Domain '{req.domain_id}' not found"}

    num_questions = max(1, min(req.num_questions, 100))
    topics = domain.get("topics", [])
    key_services = domain.get("key_services", [])

    # Fetch official AWS docs ONCE per request (used for all batches)
    docs_query = f"{domain['name']} {' '.join(key_services[:5])}"
    docs_result = await search_aws_documentation(docs_query, max_results=4)
    docs_context = docs_result.get("summary", "")
    docs_sources = [{"service": s["service"], "url": s["url"]} for s in docs_result.get("sources", [])]

    # Stratify: distribute questions across all topics
    distribution = _stratify(num_questions, len(topics))

    difficulty_map = {
        "Foundational": "foundational (basic concepts, definitions, awareness of AWS services)",
        "Associate":    "associate-level (apply best practices, choose right service for scenario)",
        "Professional": "professional-level (multi-account, complex trade-offs, organizational design)",
    }
    difficulty = difficulty_map.get(cert["tier"], "associate-level")

    async def generator():
        seen_hashes: set[str] = set()
        recent_themes: List[str] = []
        master_seed = random.randint(100000, 999999)

        try:
            yield f"data: {json.dumps({'type': 'agent_start', 'agent': 'quiz_generator', 'label': f'Generating {num_questions} exam-grade questions'})}\n\n"

            if docs_sources:
                yield f"data: {json.dumps({'type': 'docs_sources', 'sources': docs_sources})}\n\n"

            all_questions: List[dict] = []
            llm = _llm(temperature=0.75)  # high temp for diversity

            for topic_idx, topic in enumerate(topics):
                count_for_topic = distribution[topic_idx]
                if count_for_topic == 0: continue

                # Progress for this topic
                yield f"data: {json.dumps({'type': 'quiz_progress', 'current': len(all_questions), 'total': num_questions, 'topic': topic})}\n\n"

                # Generate in batches of max 5 (keeps quality + avoids token limits)
                remaining = count_for_topic
                batch_num = 0
                while remaining > 0:
                    batch_size = min(5, remaining)
                    batch_num += 1
                    seed = master_seed + topic_idx * 100 + batch_num

                    prompt = EXAM_PROMPT.format(
                        batch_size=batch_size,
                        cert_name=cert["name"],
                        cert_code=cert["code"],
                        domain_name=domain["name"],
                        domain_weight=domain.get("weight", ""),
                        topic=topic,
                        difficulty=difficulty,
                        openers_examples=" / ".join(random.sample(SCENARIO_OPENERS, 4)),
                        key_services=", ".join(key_services),
                        seed=seed,
                        avoid_themes=", ".join(recent_themes[-8:]) if recent_themes else "(none yet)",
                        docs_context=docs_context,
                    )

                    try:
                        response = await llm.ainvoke([
                            SystemMessage(content=prompt),
                            HumanMessage(content=f"Generate {batch_size} exam-quality questions for topic: '{topic}'. Seed: {seed}."),
                        ])
                        raw = response.content.strip().strip("```json").strip("```").strip()
                        data = json.loads(raw)
                        new_questions = data.get("questions", [])

                        # Anti-duplication: hash and skip dupes
                        added_this_batch = 0
                        for q in new_questions:
                            h = _question_hash(q)
                            if h in seen_hashes: continue
                            seen_hashes.add(h)
                            q["domain_id"] = domain["id"]
                            q["topic_tag"] = q.get("topic_tag", topic)
                            all_questions.append(q)
                            added_this_batch += 1
                            # Track theme to avoid repetition in next batches
                            scenario_snippet = q.get("question", "")[:80]
                            recent_themes.append(scenario_snippet[:60])

                        remaining -= max(batch_size, added_this_batch)
                        if added_this_batch == 0:
                            # Bad batch — break out of inner loop for this topic
                            break

                        # Stream partial progress
                        yield f"data: {json.dumps({'type': 'quiz_progress', 'current': len(all_questions), 'total': num_questions, 'topic': topic})}\n\n"

                    except Exception as inner_e:
                        # Log + continue with next batch (don't kill the whole quiz)
                        yield f"data: {json.dumps({'type': 'quiz_warning', 'message': f'Batch failed: {str(inner_e)[:120]}'})}\n\n"
                        break

            # Shuffle the final pool so questions don't appear topic-by-topic
            random.shuffle(all_questions)
            # Trim to requested count (we may have ended up with slightly more/fewer)
            all_questions = all_questions[:num_questions]

            yield f"data: {json.dumps({'type': 'quiz', 'questions': all_questions, 'meta': {'requested': num_questions, 'generated': len(all_questions), 'topics_covered': len(topics)}})}\n\n"

            yield f"data: {json.dumps({'type': 'agent_end', 'agent': 'quiz_generator'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as exc:
            import traceback; traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
