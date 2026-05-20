"""
Cloud Agent v3 — Mandatory docs-first multi-agent architecture.

Pipeline:
  START → docs_researcher (REQUIRED) → supervisor → specialist → [tools|END]
                                                       ↓
                                                  human_review (if destructive)

Every specialist receives AWS official documentation context.
LLMs are forbidden from answering from training-only knowledge.
"""
from __future__ import annotations

import os
import re
import uuid
import sqlite3
import asyncio
from typing import Annotated, AsyncIterator, Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command

from core.config import settings
from core.session import set_session
from core.audit import AuditLogger
from core.user_profile import update_profile, get_profile, LEVEL_ADDENDUMS
from core.proactive import get_scanner
from core.docs_search import search_aws_documentation

# ── Tool imports ───────────────────────────────────────────────────────────────

from tools.aws.ec2 import (
    ec2_list_instances, ec2_start_instance, ec2_stop_instance,
    ec2_reboot_instance, ec2_describe_instance, ec2_list_amis,
    ec2_list_security_groups, ec2_describe_security_group,
    ec2_list_vpcs, ec2_list_subnets, ec2_list_key_pairs, ec2_list_elastic_ips,
)
from tools.aws.s3 import (
    s3_list_buckets, s3_list_objects, s3_get_bucket_size,
    s3_get_bucket_policy, s3_get_bucket_acl, s3_get_bucket_versioning,
    s3_get_bucket_encryption, s3_create_bucket, s3_delete_object,
    s3_get_public_access_block,
)
from tools.aws.services import (
    iam_list_users, iam_list_roles, iam_list_groups, iam_list_policies,
    iam_get_user, iam_get_account_summary, iam_list_access_keys,
    lambda_list_functions, lambda_get_function, lambda_invoke,
    lambda_list_event_source_mappings,
    rds_list_instances, rds_list_clusters, rds_list_snapshots,
    eks_list_clusters, eks_describe_cluster, eks_list_nodegroups,
    ecs_list_clusters, ecs_list_services, ecs_list_tasks,
    cloudwatch_list_alarms, cloudwatch_get_metric, cloudwatch_list_log_groups,
    sns_list_topics, sns_list_subscriptions,
    sqs_list_queues,
    dynamodb_list_tables, dynamodb_describe_table,
    cloudformation_list_stacks, cloudformation_describe_stack,
    secretsmanager_list_secrets,
    cost_get_monthly_cost,
    route53_list_hosted_zones, route53_list_records,
    elasticache_list_clusters,
    glue_list_databases, glue_list_jobs,
    athena_list_workgroups,
    acm_list_certificates,
    ssm_list_parameters, ssm_list_managed_instances,
    bedrock_list_foundation_models,
)
from tools.aws.pricing import get_ec2_pricing, get_rds_pricing
from tools.aws.glue_extended import (
    glue_list_crawlers, glue_list_triggers, glue_get_job_runs, glue_total_dpu_usage,
    glue_inspect_job_pipeline,
)
from tools.aws.lifecycle import (
    # Tier 1 — reversible
    rds_stop_instance, rds_start_instance,
    glue_disable_trigger, cloudwatch_disable_alarm,
    # Tier 2 — low-risk
    ec2_release_address, ec2_delete_volume, ec2_delete_snapshot,
    # Tier 3 — destructive
    ec2_terminate_instance, rds_delete_instance, lambda_delete_function,
    glue_delete_job, glue_delete_crawler, glue_delete_trigger,
    cloudformation_delete_stack,
    # v23 — delete counterparts for v13 provisioning tools
    dynamodb_delete_table, dynamodb_delete_backup, dynamodb_list_backups,
    s3_delete_bucket, iam_delete_user,
    # v26 — comprehensive service coverage
    rds_delete_db_snapshot, elasticache_delete_snapshot, backup_delete_recovery_point,
    efs_delete_file_system, redshift_delete_cluster, redshift_delete_snapshot,
    athena_delete_workgroup, eks_delete_cluster, eks_delete_nodegroup,
    ecs_delete_service, ecs_delete_cluster, autoscaling_delete_group,
    ec2_delete_nat_gateway, ec2_delete_internet_gateway, ec2_delete_subnet,
    ec2_delete_vpc, kinesis_delete_stream, firehose_delete_delivery_stream,
    msk_delete_cluster, events_delete_rule, opensearch_delete_domain,
    sagemaker_delete_endpoint, stepfunctions_delete_state_machine,
    apigateway_delete_rest_api, cloudfront_delete_distribution,
    sqs_delete_queue, sns_delete_topic, route53_delete_hosted_zone,
    elasticache_delete_cluster, kms_schedule_key_deletion,
    secretsmanager_delete_secret, cognito_delete_user_pool,
    ec2_delete_security_group,
    # Audit (read-only)
    cleanup_recommendations, cleanup_recommendations_deep,
)
from tools.aws.ec2_inspection import (
    ec2_list_volumes, ec2_list_addresses, ec2_list_snapshots,
)
from tools.aws.cost_explorer import (
    ce_actual_costs, ce_top_spenders, ce_cost_forecast, ce_savings_opportunities,
)
from tools.aws.provisioning import (
    ec2_launch_instance, ec2_create_security_group,
    s3_create_secure_bucket, iam_create_user_with_policy,
    lambda_create_function, cloudwatch_create_alarm,
    # v13 additions
    rds_create_instance, aurora_create_cluster,
    dynamodb_create_table,
    sqs_create_queue, sns_create_topic,
    route53_create_hosted_zone,
    elasticache_create_redis,
    kms_create_key, secretsmanager_create_secret,
    cognito_create_user_pool,
    aws_deploy_cloudformation,
)

audit = AuditLogger()

# ── Tool groups ────────────────────────────────────────────────────────────────

INFRA_TOOLS = [
    ec2_list_instances, ec2_start_instance, ec2_stop_instance,
    ec2_reboot_instance, ec2_describe_instance, ec2_list_amis,
    ec2_list_vpcs, ec2_list_subnets, ec2_list_key_pairs, ec2_list_elastic_ips,
    ec2_launch_instance, ec2_create_security_group,
    rds_list_instances, rds_list_clusters, rds_list_snapshots,
    eks_list_clusters, eks_describe_cluster, eks_list_nodegroups,
    ecs_list_clusters, ecs_list_services, ecs_list_tasks,
    elasticache_list_clusters,
    cloudformation_list_stacks, cloudformation_describe_stack,
    ssm_list_managed_instances, ssm_list_parameters,
    route53_list_hosted_zones, route53_list_records,
    acm_list_certificates,
    # v13 provisioning tools
    rds_create_instance, aurora_create_cluster, dynamodb_create_table,
    sqs_create_queue, sns_create_topic, route53_create_hosted_zone,
    elasticache_create_redis, kms_create_key, secretsmanager_create_secret,
    cognito_create_user_pool, aws_deploy_cloudformation,
    # v20 — EC2 inspection (FinOps quick wins)
    ec2_list_volumes, ec2_list_addresses, ec2_list_snapshots,
    # v21 — lifecycle / cleanup
    rds_stop_instance, rds_start_instance, rds_delete_instance,
    glue_disable_trigger, glue_delete_trigger, glue_delete_job, glue_delete_crawler,
    cloudwatch_disable_alarm,
    ec2_release_address, ec2_delete_volume, ec2_delete_snapshot, ec2_terminate_instance,
    lambda_delete_function, cloudformation_delete_stack,
    # v23 — delete counterparts
    dynamodb_delete_table, dynamodb_delete_backup, dynamodb_list_backups,
    s3_delete_bucket, iam_delete_user,
    # v26 — comprehensive coverage
    rds_delete_db_snapshot, elasticache_delete_snapshot, backup_delete_recovery_point, efs_delete_file_system, redshift_delete_cluster, redshift_delete_snapshot, athena_delete_workgroup, eks_delete_cluster, eks_delete_nodegroup, ecs_delete_service, ecs_delete_cluster, autoscaling_delete_group, ec2_delete_nat_gateway, ec2_delete_internet_gateway, ec2_delete_subnet, ec2_delete_vpc, kinesis_delete_stream, firehose_delete_delivery_stream, msk_delete_cluster, events_delete_rule, opensearch_delete_domain, sagemaker_delete_endpoint, stepfunctions_delete_state_machine, apigateway_delete_rest_api, cloudfront_delete_distribution,
    sqs_delete_queue, sns_delete_topic, route53_delete_hosted_zone,
    elasticache_delete_cluster, kms_schedule_key_deletion,
    secretsmanager_delete_secret, cognito_delete_user_pool,
    ec2_delete_security_group,
    cleanup_recommendations, cleanup_recommendations_deep,
]

SECURITY_TOOLS = [
    iam_list_users, iam_list_roles, iam_list_groups, iam_list_policies,
    iam_get_user, iam_get_account_summary, iam_list_access_keys,
    ec2_list_security_groups, ec2_describe_security_group,
    s3_get_bucket_policy, s3_get_bucket_acl,
    s3_get_bucket_encryption, s3_get_public_access_block,
    s3_get_bucket_versioning,
    secretsmanager_list_secrets,
    cloudwatch_list_alarms,
    iam_create_user_with_policy, ec2_create_security_group,
]

# COST agent: pricing tools FIRST (preferred over LLM knowledge)
COST_TOOLS = [
    get_ec2_pricing, get_rds_pricing,
    cost_get_monthly_cost,
    ec2_list_instances, rds_list_instances, s3_get_bucket_size,
    # Real billing via Cost Explorer (v19)
    ce_actual_costs, ce_top_spenders, ce_cost_forecast, ce_savings_opportunities,
]

DATA_TOOLS = [
    dynamodb_list_backups,
    s3_list_buckets, s3_list_objects, s3_get_bucket_size,
    s3_create_bucket, s3_delete_object, s3_create_secure_bucket,
    dynamodb_list_tables, dynamodb_describe_table,
    glue_list_databases, glue_list_jobs,
    glue_list_crawlers, glue_list_triggers, glue_get_job_runs, glue_total_dpu_usage,
    glue_inspect_job_pipeline,
    athena_list_workgroups,
    rds_list_instances, rds_list_clusters,
]

DEVOPS_TOOLS = [
    lambda_list_functions, lambda_get_function, lambda_invoke,
    lambda_list_event_source_mappings, lambda_create_function,
    cloudwatch_create_alarm,
    ecs_list_clusters, ecs_list_services, ecs_list_tasks,
    cloudwatch_list_alarms, cloudwatch_get_metric, cloudwatch_list_log_groups,
    sns_list_topics, sns_list_subscriptions,
    sqs_list_queues,
    ssm_list_parameters, ssm_list_managed_instances,
    bedrock_list_foundation_models,
]

# Deduplicate by tool name
_seen = set()
ALL_TOOLS = []
for t in INFRA_TOOLS + SECURITY_TOOLS + COST_TOOLS + DATA_TOOLS + DEVOPS_TOOLS:
    if t.name not in _seen:
        _seen.add(t.name)
        ALL_TOOLS.append(t)

DESTRUCTIVE_TOOLS = {
    "ec2_stop_instance", "ec2_start_instance", "ec2_reboot_instance",
    "s3_delete_object", "s3_create_bucket", "lambda_invoke",
    # Provisioning — always require approval
    "ec2_launch_instance", "ec2_create_security_group",
    "s3_create_secure_bucket", "iam_create_user_with_policy",
    "lambda_create_function", "cloudwatch_create_alarm",
    # v13 — extended provisioning
    "rds_create_instance", "aurora_create_cluster", "dynamodb_create_table",
    "sqs_create_queue", "sns_create_topic", "route53_create_hosted_zone",
    "elasticache_create_redis", "kms_create_key", "secretsmanager_create_secret",
    "cognito_create_user_pool",
    # Generic catch-all for any other AWS resource type
    "aws_deploy_cloudformation",
    # v21 — lifecycle / cleanup tools (all require approval)
    "rds_stop_instance", "rds_start_instance",
    "glue_disable_trigger", "cloudwatch_disable_alarm",
    "ec2_release_address", "ec2_delete_volume", "ec2_delete_snapshot",
    "ec2_terminate_instance", "rds_delete_instance", "lambda_delete_function",
    "glue_delete_job", "glue_delete_crawler", "glue_delete_trigger",
    "cloudformation_delete_stack",
    # v23 — delete counterparts for v13 provisioning tools
    "dynamodb_delete_table", "dynamodb_delete_backup",
    "s3_delete_bucket", "iam_delete_user",
    # v26 — comprehensive coverage
    "rds_delete_db_snapshot",
    "elasticache_delete_snapshot",
    "backup_delete_recovery_point",
    "efs_delete_file_system",
    "redshift_delete_cluster",
    "redshift_delete_snapshot",
    "athena_delete_workgroup",
    "eks_delete_cluster",
    "eks_delete_nodegroup",
    "ecs_delete_service",
    "ecs_delete_cluster",
    "autoscaling_delete_group",
    "ec2_delete_nat_gateway",
    "ec2_delete_internet_gateway",
    "ec2_delete_subnet",
    "ec2_delete_vpc",
    "kinesis_delete_stream",
    "firehose_delete_delivery_stream",
    "msk_delete_cluster",
    "events_delete_rule",
    "opensearch_delete_domain",
    "sagemaker_delete_endpoint",
    "stepfunctions_delete_state_machine",
    "apigateway_delete_rest_api",
    "cloudfront_delete_distribution",
    "sqs_delete_queue", "sns_delete_topic", "route53_delete_hosted_zone",
    "elasticache_delete_cluster", "kms_schedule_key_deletion",
    "secretsmanager_delete_secret", "cognito_delete_user_pool",
    "ec2_delete_security_group",
}

COST_KEYWORDS = re.compile(
    r"\b(cost|price|pricing|spend|billing|cheap|expensive|estimate|tco|budget|"
    r"savings|reserved|spot|on.?demand|month|hour|\$|usd|euro|€)\b",
    re.IGNORECASE,
)

CREATION_KEYWORDS = re.compile(
    r"\b(create|creat|launch|provision|deploy|spin\s*up|set\s*up|build\s*me|"
    r"make\s*me|start\s+a\s+new|add\s+a\s+new|cr[eé]e[rz]?|lance[rz]?|"
    r"d[eé]ploye[rz]?|cr[eé]ation|provision\w*)\b",
    re.IGNORECASE,
)

DELETION_KEYWORDS = re.compile(
    r"\b(delete|drop|destroy|terminate|supprime[rz]?|efface[rz]?|d[eé]truire|kill)\b"
    r"[\s\w/-]{0,50}?\b"
    r"(table|bucket|secret|topic|queue|cluster|database|stack|function|"
    r"lambda|instance|pool|hosted\s+zone|trigger|crawler|job|alarm|snapshot|"
    r"volume|address|eip|security\s+group|kms\s+key|user\s+pool)\b",
    re.IGNORECASE,
)

CLEANUP_KEYWORDS = re.compile(
    r"\b(cleanup|clean[- ]?up|nettoie[rz]?|nettoyage|stop\s+all|delete\s+all|"
    r"remove\s+unused|kill\s+all|d[eé]sactiver?\s+tout|supprime[rz]?\s+tout|"
    r"one\s+by\s+one|un\s+par\s+un|cleanup\s+recommendations?|"
    r"que\s+je\s+(?:n['e ])*utilise\s+plus|don['']t\s+use\s+anymore|"
    r"audit\s+finops|opportunit[eé]s?\s+d['e ]?[eé]conomie)",
    re.IGNORECASE,
)

CONFIRMATION_KEYWORDS = re.compile(
    r"^\s*(confirm[a-z]*|yes\b|go\b|proceed|create\s+it|deploy\s+it|"
    r"vas[\- ]?y|oui\b|ok\b|d'accord|accepted?|approved?|lance[\- ]le)",
    re.IGNORECASE,
)

# ── State ──────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages:          Annotated[list[BaseMessage], add_messages]
    selected_agent:    str
    user_level:        str
    proactive_context: str
    region:            str
    docs_context:      str   # AUTHORITATIVE AWS docs — required
    docs_sources:      list  # [{service, url, excerpt}]
    cost_query:        bool  # forces pricing tool usage
    creation_intent:     bool  # triggers plan-first provisioning ReAct pipeline
    confirmation_intent: bool  # user confirmed a Plan — execute now
    cleanup_intent:      bool  # user wants to audit/stop unused resources
    deletion_intent:     bool  # user wants to delete a specific named resource
    last_region:         str   # last region mentioned/used in this thread
    prov_reasoning:    dict  # output of provisioning_reasoning_node (JSON)
    prov_cost:         dict  # output of provisioning_pricing_node (calculate_architecture_cost result)

# ── Prompts ────────────────────────────────────────────────────────────────────

SUPERVISOR_PROMPT = """Route this AWS query to the right specialist. Return ONLY JSON:
{"agent": "infra"|"security"|"cost"|"data"|"devops"|"general"}

- infra: EC2, VPC, ECS, EKS, RDS, networking
- security: IAM, security groups, S3 permissions, MFA, encryption, secrets
- cost: any question about price, billing, savings, budget — always use cost agent
- data: S3 objects, DynamoDB, Glue, Athena, data pipelines
- devops: Lambda, CloudWatch, SNS, SQS, monitoring, deployments
- general: cross-domain or general questions"""

BASE_PROMPT = """You are an expert AWS engineer.

CRITICAL RULES — NON-NEGOTIABLE:
1. The AWS Official Documentation section below is your AUTHORITATIVE source.
   You MUST use it as ground truth. Do NOT contradict it or claim "I couldn't find docs."
2. ALWAYS cite the doc URLs you use, like: "Per AWS docs ([source](URL))…"
3. For ANY pricing or cost question: call the pricing tool (get_ec2_pricing,
   get_rds_pricing, cost_get_monthly_cost). NEVER quote prices from training data.
4. When tools return live AWS data, ALWAYS prefer it over your priors.
5. Format with markdown: tables for lists, code blocks for IDs/ARNs/commands.

ABSOLUTE PROHIBITIONS:
- NEVER write "based on my pre-trained knowledge" or "based on pre-existing knowledge"
- NEVER write "I couldn't retrieve specific AWS documentation"
- NEVER write "Please verify this against official AWS documentation" as a disclaimer
- If docs below seem partial, USE WHAT IS PROVIDED and cite the URLs — do not apologize.
- Every architectural claim MUST be followed by [Source](url) from the docs context.

WHEN YOU CREATE OR FETCH RESOURCES:
- The tools return `console_url` fields with deep links to AWS Console.
- ALWAYS include these as clickable markdown: "[Open in Console](url)"
- Structure your response with H2 sections: ## Summary, ## Resources, ## Next Steps, ## Sources
- For each created/fetched resource, list its ID and Console URL.
- For monthly/yearly costs, render them prominently in the response.

Region: **{region}**

{docs_context}

{proactive_context}

{level_addendum}


## CRITICAL COMPLETION RULE

When the user asks a multi-part question or a question that requires multiple
data points (e.g. "list my X and show their schedule" / "what's running and
since when" / "compare X and Y"), you MUST call ALL the tools needed to
answer fully BEFORE producing your final response.

Forbidden patterns:
- ❌ "Let me proceed with that" — do it NOW, in this same turn
- ❌ "I will list X next" — call the tool NOW
- ❌ "To find Y, I need to..." then stopping — call the next tool NOW
- ❌ Suggesting the user re-ask for the part you didn't answer

Required pattern:
- ✅ See that the question has multiple parts
- ✅ Call tool 1 → see result → call tool 2 (in the SAME turn, via successive
     tool_calls)
- ✅ Only produce the final structured response when ALL parts are answered

You can make MANY tool calls per turn. The graph loops back to you after each
tool result. Use this. Don't be shy.

## NEXT STEPS RULE — STRICT

If you produce a "Next Steps" section, every item MUST be:
  - A specific, actionable command the user can run/say next
  - With a clear value-add: a $ saved, a risk fixed, a faster path

FORBIDDEN boilerplate that means NOTHING:
  ❌ "Monitor your usage"
  ❌ "Review your X configuration"
  ❌ "Ensure your X aligns with your needs"
  ❌ "Consider optimizing your X for cost and performance"

If you cannot propose a CONCRETE next step, OMIT the Next Steps section
entirely. Empty is better than vague.

Example GOOD next step:
  ✓ "Disable trigger 'trigger-iot-transformer-prod' (runs every 15 min) —
     saves an estimated $19/month based on current DPU consumption."

Example — User: "List my Glue crawlers and their schedule":
  Turn 1: tool_call glue_list_crawlers → result includes schedule fields → final response ✓
  NOT: tool_call glue_list_jobs (wrong tool) → text "let me proceed to crawlers next" ✗

Example — User: "What's running on EC2 and what unattached EIPs do I have":
  Turn 1: tool_call ec2_list_instances → got instances. Tool_call ec2_list_addresses
          → got EIPs. Final response combining both ✓
  NOT: list instances, say "I will check EIPs next", stop ✗"""

SPECIALIST_INSTRUCTIONS = {
    "infra": "Focus on compute/networking/databases. Flag single-AZ, missing encryption, unmanaged inventory.",
    "security": "Apply least-privilege. Highlight CRITICAL with 🔴, HIGH with 🟠. Reference CIS AWS Benchmark when relevant.",
    "cost": "MUST call pricing tools first. Show monthly/yearly figures. Compare On-Demand vs Reserved vs Spot. Never quote prices from memory.",
    "data": "Report S3 sizes in human-readable units. Flag missing versioning, missing lifecycle. Check DynamoDB capacity mode.",
    "devops": "Check Lambda error rates, DLQ growth, alarm states, cold starts. Surface anomalies.",
    "general": "Pick the right tool for the question. If costs are mentioned, call pricing tool first.",
}

PROVISIONING_WORKFLOW = """

═══════════════════════════════════════════════════════════════════════════════
PROVISIONING WORKFLOW — MANDATORY when user requests creating an AWS resource
═══════════════════════════════════════════════════════════════════════════════

You are a Principal AWS Solutions Architect provisioning resources for a
production environment. EVERY resource you propose must respect AWS Well-
Architected Framework — security, reliability, operational excellence, and
cost optimization — REGARDLESS of what the user explicitly asks for.

You MUST follow this 2-phase workflow STRICTLY. Skipping is forbidden.

──────────── TOOL SELECTION (decide BEFORE Phase 1) ────────────

Specific tools (preferred — better UX):
  EC2 instance         → ec2_launch_instance
  EC2 security group   → ec2_create_security_group
  S3 bucket            → s3_create_secure_bucket
  IAM user             → iam_create_user_with_policy
  Lambda function      → lambda_create_function
  CloudWatch alarm     → cloudwatch_create_alarm
  RDS instance         → rds_create_instance
  Aurora cluster       → aurora_create_cluster
  DynamoDB table       → dynamodb_create_table
  SQS queue            → sqs_create_queue
  SNS topic            → sns_create_topic
  Route 53 zone        → route53_create_hosted_zone
  ElastiCache Redis    → elasticache_create_redis
  KMS key              → kms_create_key
  Secret               → secretsmanager_create_secret
  Cognito user pool    → cognito_create_user_pool

Generic CloudFormation fallback (everything else):
  ANY OTHER resource → aws_deploy_cloudformation with a complete YAML template
  Includes: VPC, ALB/NLB, ECS service, EKS, API Gateway, CloudFront,
            Step Functions, Glue, EventBridge, WAF, ACM, EFS/FSx, Kinesis,
            Athena, MSK, Backup, Backup Vault, multi-resource stacks.

═══════════════════════════════════════════════════════════════════════════════
UNIVERSAL DEFAULTS — APPLY TO EVERY RESOURCE (no exceptions)
═══════════════════════════════════════════════════════════════════════════════

SECURITY
  • Encryption at rest with KMS — use service-default key (aws/<svc>) if no
    specific key, or create a CMK if requested
  • No public access by default — private subnets for data tier, no public S3
  • IAM least-privilege — never use Resource: "*" with Action: "*", scope to
    specific ARNs and actions
  • Secrets via Secrets Manager — never hardcode credentials in templates
  • TLS 1.2+ for all in-transit traffic (HTTPS, TLS DBs)
  • IMDSv2 only on EC2 (HttpTokens: required)
  • Block all public access on every new S3 bucket (4 settings)

OBSERVABILITY
  • CloudWatch alarms for critical metrics (CPU >80%, errors, 5xx, throttles)
  • CloudWatch Logs with retention 30 days minimum (never infinite)
  • VPC Flow Logs to CloudWatch Logs for every new VPC
  • Access logs to S3 for ALB, NLB, CloudFront, public-facing S3
  • X-Ray active tracing for Lambda, ECS, EKS, API Gateway, Step Functions
  • Container Insights for ECS/EKS clusters

RELIABILITY
  • Multi-AZ for any stateful resource (RDS, Aurora, ElastiCache, MSK, FSx)
  • Multi-AZ for ALB, NLB, NAT (unless explicit dev/staging downgrade)
  • Auto-scaling for ECS/EKS services with min 2 tasks, target CPU 70%
  • Backup retention 7 days minimum on databases, PITR for DynamoDB
  • Health checks on every load balancer target group
  • DLQ (SQS) for async Lambda invocations + SNS deliveries

COST OPTIMIZATION
  • Tag every resource: Environment, Project, Owner, CostCenter, CreatedBy
  • Gateway VPC Endpoints S3 + DynamoDB on every new VPC (FREE, big savings)
  • S3 lifecycle: → IA after 30d, Glacier IR after 90d for buckets storing
    logs/backups/archives
  • Right-sized instances — never propose m5.xlarge when t3.medium suffices
  • Reserved Instances / Savings Plans mention when on-demand > $50/mo
  • Cost estimate MUST include data transfer (NAT egress, CloudFront out,
    S3 transfer out), not just compute/storage hours

REUSABILITY (CFN templates only)
  • Use Parameters for tunable values (CIDR, instance type, name prefix, env)
  • Always include Outputs section exposing key resource IDs/ARNs/endpoints
  • Use !Ref / !GetAtt / !Sub / !Cidr / !GetAZs — never hardcode account/region
  • Mappings for environment-specific values (dev/staging/prod)

═══════════════════════════════════════════════════════════════════════════════
PER-CATEGORY CHECKLISTS — APPLY THE RELEVANT ONE
═══════════════════════════════════════════════════════════════════════════════

VPC:
  • Flow Logs to CloudWatch Logs (capture REJECTED traffic minimum)
  • S3 + DynamoDB Gateway endpoints (FREE — saves NAT egress $)
  • Default SG with no inbound rules (force explicit SGs)
  • DNS hostnames + DNS support both enabled
  • Outputs: VpcId, PublicSubnetIds, PrivateSubnetIds, VpcCidr
  • Cost: NAT egress $0.045/GB — must be in estimate
  • Dev alt: 1 NAT instead of 2, OR NAT instance t3.nano ($5/mo vs $32/mo)

RDS / Aurora:
  • StorageEncrypted: true
  • BackupRetentionPeriod: 7 (minimum)
  • Multi-AZ for prod (single-AZ alt for dev)
  • PerformanceInsights enabled (free 7-day retention)
  • EnhancedMonitoring at 60s interval
  • AutoMinorVersionUpgrade: true
  • Database in PRIVATE subnets, PubliclyAccessible: false
  • Master password in Secrets Manager — never inline in template
  • Parameter group with slow_query_log + general_log (MySQL) or
    log_statement=all (Postgres)
  • CloudWatch alarms: CPUUtilization, FreeableMemory, FreeStorageSpace,
    DatabaseConnections, ReadLatency, WriteLatency
  • Cost: include IO ($0.20/M for Aurora), snapshots ($0.095/GB after retention)

S3:
  • Versioning: Enabled
  • PublicAccessBlock: all 4 true
  • BucketEncryption SSE-S3 minimum, SSE-KMS if compliance
  • ServerAccessLogging to dedicated logs bucket
  • LifecycleConfiguration: IA after 30d, Glacier IR after 90d, expire
    incomplete multipart uploads after 7d
  • Object Lock for compliance buckets (mention as option)
  • CORS only if explicitly needed
  • Cost: $0.005/1k PUT, $0.0004/1k GET, transfer out $0.09/GB

ALB / NLB:
  • AccessLogs to S3 enabled
  • drop_invalid_header_fields: true
  • DeletionProtection: true (prod)
  • TLS 1.2 minimum (SecurityPolicy: ELBSecurityPolicy-TLS13-1-2-2021-06)
  • HTTP listener → redirect to HTTPS (301)
  • ACM cert if domain provided
  • WAF association recommended for public-facing
  • Target group health check /health, 30s interval
  • Cost: $22.50/mo base + LCU; high-traffic 5-15 LCU = +$30-100/mo

ECS / EKS:
  • Container Insights enabled
  • Capacity provider mix: FARGATE + FARGATE_SPOT (70% spot for stateless)
  • Task role with least-privilege, separate from execution role
  • ExecRole with KMS decrypt if secrets used + ECR pull
  • ECR scan on push enabled
  • CloudWatch Logs group per service, 30d retention
  • Service auto-scaling: min 2, max 10, target CPU 70%
  • Deployment circuit breaker enabled

Lambda:
  • DeadLetterConfig (SQS DLQ) for async invocations
  • TracingConfig Mode: Active (X-Ray)
  • CloudWatch Logs retention 30d (avoid infinite default)
  • Environment variables encrypted (KMS)
  • Timeout: realistic (not default 3s, not max 900s)
  • Memory tuned per workload (mention Lambda Power Tuning)
  • Reserved/Provisioned concurrency for predictable workloads
  • Architectures: arm64 (Graviton, 20% cheaper) when supported

API Gateway:
  • AccessLogSettings to CloudWatch
  • LoggingLevel: INFO with DataTraceEnabled (mask sensitive)
  • TracingEnabled: true (X-Ray)
  • ThrottlingBurstLimit/RateLimit set (defaults: 5000 burst, 10000 sustained)
  • Caching for GET endpoints (mention if read-heavy)
  • Usage plans + API keys for partner/customer access
  • Custom domain with ACM cert if domain provided
  • WAF association for public APIs

CloudFront:
  • ViewerProtocolPolicy: redirect-to-https (HTTPS only)
  • MinimumProtocolVersion: TLSv1.2_2021
  • Origin Access Control (OAC) for S3 origins (NEVER OAI — deprecated)
  • Logging.IncludeCookies + S3 bucket destination
  • WAF WebAclId association
  • Compress: true
  • Custom error responses (200 → /index.html for SPA on 403/404)
  • ACM cert MUST be in us-east-1 (CloudFront requirement)

DynamoDB:
  • PointInTimeRecoverySpecification.PointInTimeRecoveryEnabled: true
  • SSESpecification with KMS
  • Streams (NEW_AND_OLD_IMAGES) when change capture needed
  • TTL attribute on session/cache tables
  • Auto-scaling for provisioned mode (target 70%)
  • Or PAY_PER_REQUEST for variable traffic
  • Global tables for multi-region apps
  • Contributor Insights for hot-key detection

SQS:
  • KmsMasterKeyId: alias/aws/sqs (or CMK)
  • RedrivePolicy with DLQ + maxReceiveCount 5
  • VisibilityTimeout = 6× expected processing time
  • MessageRetentionPeriod: 4 days minimum
  • FIFO with ContentBasedDeduplication when ordering required

SNS:
  • KmsMasterKeyId: alias/aws/sns
  • DeliveryPolicy with retries for HTTP/HTTPS subs
  • DLQ on subscriptions (RedrivePolicy)
  • Subscription FilterPolicy to reduce noise

Cognito:
  • MfaConfiguration OPTIONAL minimum (ON for B2B)
  • PasswordPolicy: 8+ chars, mixed case, digits, symbols
  • AccountRecoverySetting: verified email (avoid phone — SIM swapping)
  • TokenValidityUnits: access 1h, refresh 30d max
  • UserPoolAddOns with AdvancedSecurityMode: AUDIT (or ENFORCED)
  • Lambda triggers for custom flows (pre-signup, post-confirmation)
  • Custom domain with ACM cert
  • App client: no client secret for JS/mobile (PKCE flow)

KMS:
  • EnableKeyRotation: true (annual auto-rotation)
  • MultiRegion for DR scope
  • KeyPolicy: specific principals, NOT just root account "*"
  • Alias for human-readable reference
  • PendingWindowInDays: 30 (max recovery window)

Step Functions:
  • TracingConfiguration.Enabled: true (X-Ray)
  • LoggingConfiguration: ALL, IncludeExecutionData: true
  • StateMachineType: STANDARD (long workflows) or EXPRESS (high-volume short)
  • CloudWatch alarms on ExecutionsFailed, ExecutionsTimedOut

EventBridge:
  • DeadLetterConfig on rules
  • CloudWatch alarms on FailedInvocations
  • Retry policies on targets (max 24h, max attempts 185)
  • Schemas registry enabled

ACM:
  • ValidationMethod: DNS (auto-renewal possible)
  • SubjectAlternativeNames for multi-domain
  • CertificateTransparencyLoggingPreference: ENABLED

WAF (WebACL):
  • Managed rule groups: AWSManagedRulesCommonRuleSet + AWSManagedRulesKnownBadInputs
  • Rate limiting rule: 2000 req/5min per IP
  • Geo block for restricted regions if relevant
  • CloudWatch metrics enabled

═══════════════════════════════════════════════════════════════════════════════
PHASE 1 — PROPOSE A PLAN (this turn, NO tool call yet)
═══════════════════════════════════════════════════════════════════════════════

DO NOT call any creation tool. Output a Plan in EXACTLY this structure:

## Provisioning Plan: [Resource description]

| Parameter | Chosen Value | Alternatives | Monthly Cost |
|---|---|---|---|
| [Primary params with sizing and cost impact] |

**Total estimated cost: $X.XX/month**

### Production-grade defaults applied
✓ [Security default 1, e.g. "Encryption at rest with KMS aws/rds"]
✓ [Security default 2, e.g. "Storage in private subnets"]
✓ [Observability, e.g. "CloudWatch alarms: CPU, FreeMemory, FreeStorage"]
✓ [Observability, e.g. "Performance Insights (7-day free retention)"]
✓ [Reliability, e.g. "Multi-AZ deployment"]
✓ [Reliability, e.g. "Automated backups, 7-day retention"]
✓ [Cost, e.g. "All resources tagged Environment/Project/Owner"]

### Cost breakdown
- Base (compute/storage): $X/month
- Variable (data transfer, requests): ~$Y/month for typical usage
- **Total range: $A–$B/month** depending on traffic

### Dev/staging cheaper alternative
For non-prod, you could save by:
- [Specific change, e.g. "Single-AZ instead of Multi-AZ → -50% RDS cost"]
- [Specific change, e.g. "1 NAT instead of 2 → save $32/month"]
- [Specific change, e.g. "Smaller instance class db.t3.small → save $200/month"]
**Dev total: ~$N/month**

### Template preview (only if using aws_deploy_cloudformation)
```yaml
[Complete CloudFormation template — no truncation, no placeholders]
```

**Reply `confirm` to proceed, or specify changes**
(e.g. "single-AZ for dev", "remove Flow Logs", "change CIDR to 172.16.0.0/16").

═══════════════════════════════════════════════════════════════════════════════
PHASE 2 — EXECUTE (next turn after user confirms)
═══════════════════════════════════════════════════════════════════════════════

After user replies confirm/yes/go: call the chosen tool with the agreed
parameters. The system shows one final safety interrupt before execution.

═══════════════════════════════════════════════════════════════════════════════
ABSOLUTE RULES
═══════════════════════════════════════════════════════════════════════════════

1. Even if user gives full specs, STILL show the Plan first. Never skip.
2. Use pricing tools to fill the cost column. NEVER invent numbers.
3. If request is ambiguous, pick sensible defaults and list them explicitly.
4. Quantities: 1 resource unless user explicitly said multiple.
5. When listing alternatives, include real $ delta for the user to decide.
6. ALWAYS apply the Universal Defaults — they are non-negotiable.
7. The "Production-grade defaults applied" section is MANDATORY in every Plan.
   The user needs to see what they get out of the box.
8. The "Dev/staging cheaper alternative" section is MANDATORY when monthly
   cost > $30 — show the user what they could save in non-prod.
9. If user requests "minimal" or "cheapest possible", you MAY disable some
   defaults but EXPLICITLY name which security/reliability you removed and the
   risk it creates.
10. WHEN USING aws_deploy_cloudformation: the YAML template MUST include all
    relevant universal + per-category defaults baked in (Flow Logs, encryption,
    Outputs, Parameters, tags, etc.). Generate the COMPLETE template, no
    placeholders like "# add more here".
"""


PROVISIONING_EXECUTE_PHASE_2 = """

═══════════════════════════════════════════════════════════════════════════════
PROVISIONING WORKFLOW — PHASE 2: EXECUTE NOW
═══════════════════════════════════════════════════════════════════════════════

The user has CONFIRMED the Provisioning Plan you presented in your previous
assistant message. Your ONLY job now is to CALL THE APPROPRIATE TOOL with the
exact parameters that were agreed in that Plan.

──────────── CRITICAL: READ YOUR PREVIOUS MESSAGE ────────────

Look at the most recent assistant message in the conversation history. It contains:
- The chosen resource type (DynamoDB table, EC2 instance, VPC stack, etc.)
- The chosen parameters table (table name, partition key, region, etc.)
- For CFN cases, the full YAML template

──────────── TOOL SELECTION ────────────

Match the resource type from the Plan to the appropriate tool:

  DynamoDB table       → dynamodb_create_table
  EC2 instance         → ec2_launch_instance
  Security group       → ec2_create_security_group
  S3 bucket            → s3_create_secure_bucket
  IAM user             → iam_create_user_with_policy
  Lambda function      → lambda_create_function
  CloudWatch alarm     → cloudwatch_create_alarm
  RDS instance         → rds_create_instance
  Aurora cluster       → aurora_create_cluster
  SQS queue            → sqs_create_queue
  SNS topic            → sns_create_topic
  Route 53 zone        → route53_create_hosted_zone
  ElastiCache Redis    → elasticache_create_redis
  KMS key              → kms_create_key
  Secrets Manager      → secretsmanager_create_secret
  Cognito user pool    → cognito_create_user_pool
  ANYTHING ELSE / CFN  → aws_deploy_cloudformation
                          (pass the YAML template from your previous message
                           as template_body, and a stack_name derived from the
                           resource description)

──────────── ABSOLUTE RULES ────────────

1. CALL THE TOOL NOW. Do NOT show another Plan. Do NOT ask for confirmation again.
2. Use the EXACT parameters from the Plan in your previous message.
3. For CFN tool: copy the FULL YAML from the previous message as the template_body
   argument. Do not summarize or modify it.
4. The system shows ONE final safety interrupt before the tool actually runs —
   that's expected and the user will see it.
5. If the user asked for modifications instead of pure confirmation ("use t3.small
   instead", "change region"), apply those changes to the tool call parameters
   rather than calling with the original Plan values.
"""


CLEANUP_WORKFLOW = """

═══════════════════════════════════════════════════════════════════════════════
CLEANUP WORKFLOW — user wants to stop / delete unused resources
═══════════════════════════════════════════════════════════════════════════════

The user wants to clean up AWS resources they no longer use. Follow this
structured workflow STRICTLY:

──────────── STEP 1 — AUDIT FIRST (always) ────────────

ALWAYS start by calling `cleanup_recommendations(region=...)` to get a ranked,
audit-style list of actions. This tool returns:
  - All EBS volumes detached (waste $)
  - All Elastic IPs unattached (waste $3.60/mo each)
  - Active Glue scheduled triggers (potentially overshooting)
  - EBS snapshots older than 180 days
  - Total estimated monthly savings

If no actions returned, tell the user the environment looks clean and stop.

──────────── STEP 2 — SHOW THE PLAN BEFORE ACTING ────────────

Present the audit results as a table:

| # | Tier | Action | Target | Monthly $ Saved | Reason |
|---|------|--------|--------|------------------|--------|
| 1 | T1   | glue_disable_trigger | factory-daily | Variable | Cron job — verify still needed |
| 2 | T2   | ec2_release_address  | eipalloc-XYZ  | $3.60    | Unattached EIP |
| 3 | T2   | ec2_delete_volume    | vol-ABC       | $8.00    | gp3 100GB detached |
| ...

Then ask: "Should I walk through these one by one with your approval for each,
or do you want to skip some (specify by number)?"

──────────── STEP 3 — EXECUTE ONE BY ONE ────────────

For each action the user agrees to:
  1. Call the specific tool (each is in DESTRUCTIVE_TOOLS → triggers approval card)
  2. The user sees the approval card in chat → clicks Approve / Cancel
  3. After execution, report success + running savings total
  4. Move to next action

Order:
  - Tier 1 (reversible) FIRST — safest. Glue triggers, RDS stop.
  - Tier 2 (low-risk) NEXT — EIPs, detached volumes, old snapshots.
  - Tier 3 (destructive) LAST and only if user EXPLICITLY confirms — terminate,
    delete RDS without snapshot, etc.

──────────── ABSOLUTE RULES ────────────

1. NEVER mass-execute without per-action user approval. "One by one" is the
   contract — respect it.
2. For Tier 3 (data-loss risk), ALWAYS warn the user explicitly before the
   approval card. Example: "⚠ This will TERMINATE i-XXX — data on instance
   store is lost. Continue?"
3. For RDS delete, default to skip_final_snapshot=False (snapshot taken).
4. After each successful action, append to a running summary the user can
   refer to. Format:
   "✓ Released EIP eipalloc-XYZ — saved $3.60/month. Running total: $11.60/mo saved."
5. Resources behind CloudFormation stacks should usually be deleted via
   cloudformation_delete_stack (cascades) — not individually.
"""


DELETION_PROMPT = """

═══════════════════════════════════════════════════════════════════════════════
DELETION INTENT — user wants to delete a SPECIFIC named resource
═══════════════════════════════════════════════════════════════════════════════

The user identified a specific resource to delete. You MUST execute the
deletion via the appropriate tool — DO NOT give them an AWS CLI command,
DO NOT just describe the resource, DO NOT defer to the AWS Console.

Required actions:
1. Identify which delete tool matches the resource type:
   - DynamoDB table → dynamodb_delete_table
   - S3 bucket → s3_delete_bucket
   - RDS instance → rds_delete_instance (or rds_stop_instance for reversible)
   - EC2 instance → ec2_terminate_instance (or ec2_stop_instance for reversible)
   - Lambda → lambda_delete_function
   - IAM user → iam_delete_user
   - KMS key → kms_schedule_key_deletion
   - Secrets Manager → secretsmanager_delete_secret
   - Cognito pool → cognito_delete_user_pool
   - SQS queue → sqs_delete_queue
   - SNS topic → sns_delete_topic
   - Route 53 zone → route53_delete_hosted_zone
   - ElastiCache → elasticache_delete_cluster
   - Security group → ec2_delete_security_group
   - CloudFormation stack → cloudformation_delete_stack (cascades!)
   - Glue job/crawler/trigger → glue_delete_job / _crawler / _trigger
   - EFS → efs_delete_file_system
   - Redshift cluster → redshift_delete_cluster (final snapshot default)
   - Redshift snapshot → redshift_delete_snapshot
   - EKS cluster → eks_delete_cluster (nodegroups first)
   - EKS nodegroup → eks_delete_nodegroup
   - ECS service → ecs_delete_service
   - ECS cluster → ecs_delete_cluster
   - Auto Scaling group → autoscaling_delete_group
   - NAT gateway → ec2_delete_nat_gateway (saves $32/mo!)
   - Internet gateway → ec2_delete_internet_gateway
   - Subnet → ec2_delete_subnet
   - VPC → ec2_delete_vpc (or cloudformation_delete_stack for cascade)
   - Kinesis stream → kinesis_delete_stream
   - Firehose → firehose_delete_delivery_stream
   - MSK cluster → msk_delete_cluster
   - EventBridge rule → events_delete_rule
   - OpenSearch domain → opensearch_delete_domain
   - SageMaker endpoint → sagemaker_delete_endpoint
   - Step Functions → stepfunctions_delete_state_machine
   - API Gateway REST → apigateway_delete_rest_api
   - CloudFront distribution → cloudfront_delete_distribution (disable first!)
   - Athena workgroup → athena_delete_workgroup
   - RDS snapshot → rds_delete_db_snapshot
   - ElastiCache snapshot → elasticache_delete_snapshot
   - AWS Backup recovery point → backup_delete_recovery_point

2. Call the tool with the resource identifier extracted from user message.

3. For tools with safety params (backup_first, final_snapshot, force_delete):
   - Default to the SAFER option (backup_first=True, final_snapshot=True)
   - If user explicitly said "without backup" / "force" / "no snapshot",
     then pass the unsafe param.

4. The tool call will pause at human_review → user clicks Approve → action runs.

5. Report the result (ARN of backup if taken, status, etc.) — not a CLI command.

CRITICAL: do NOT respond with `aws <service> delete-...` shell commands.
The whole point of this system is that YOU execute the deletion safely with
an approval card. Telling the user to run CLI defeats the purpose.
"""


def _get_llm(model: str, tools: list = None, temperature: float = 0, streaming: bool = True):
    if model.startswith(("gpt", "o")):
        llm = ChatOpenAI(model=model, api_key=os.environ.get("OPENAI_API_KEY", settings.openai_api_key),
                        temperature=temperature, streaming=streaming)
    elif model.startswith("claude"):
        llm = ChatAnthropic(model=model, api_key=os.environ.get("ANTHROPIC_API_KEY", settings.anthropic_api_key),
                           temperature=temperature, streaming=streaming)
    else:
        raise ValueError(f"Unknown model: {model}")
    return llm.bind_tools(tools) if tools else llm


# ── Nodes ──────────────────────────────────────────────────────────────────────

async def docs_researcher_node(state: AgentState) -> dict:
    """MANDATORY first step — fetches AWS docs before any reasoning."""
    last_human = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        ""
    )
    if not last_human:
        return {"docs_context": "", "docs_sources": [], "cost_query": False}

    result = await search_aws_documentation(last_human, max_results=3)
    cost_query = bool(COST_KEYWORDS.search(last_human))

    creation_intent = bool(CREATION_KEYWORDS.search(last_human))

    # Confirmation detection: user said confirm/yes/go AND a recent assistant
    # message contained a Provisioning Plan (multiple marker variants).
    PLAN_MARKERS = (
        "Provisioning Plan",  # English standard
        "Plan de provisionnement",  # French
        "Plan de provisioning",
        "## Provisioning",
        "Template Preview",  # CFN template section
        "Production-grade defaults applied",
    )
    is_cleanup = bool(CLEANUP_KEYWORDS.search(last_human))
    is_deletion = bool(DELETION_KEYWORDS.search(last_human))
    is_confirmation = bool(CONFIRMATION_KEYWORDS.search(last_human))

    # ─── Region inference ──────────────────────────────────────────────
    # Match patterns like "eu-west-1", "in us-east-2", "at ap-south-1"
    REGION_PAT = re.compile(r"\b(us|eu|ap|ca|sa|me|af)-(east|west|north|south|northeast|northwest|southeast|southwest|central)-\d\b")
    region_match = REGION_PAT.search(last_human)
    if region_match:
        last_region = region_match.group(0).lower()
    else:
        # Inherit from previous turn in this thread
        last_region = state.get("last_region", state.get("region", "us-east-1"))
    recent_window = state.get("messages", [])[-10:]  # widened from 6 to 10
    has_recent_plan = any(
        isinstance(m, AIMessage) and any(mk in (m.content or "") for mk in PLAN_MARKERS)
        for m in recent_window
    )
    confirmation_intent = is_confirmation and has_recent_plan

    # When confirming, the request is no longer a "create new" intent
    if confirmation_intent:
        creation_intent = False
        print(f"[docs_researcher] confirmation_intent=True (msg: {last_human[:60]!r})")
    elif is_confirmation and not has_recent_plan:
        print(f"[docs_researcher] confirm-like message but NO recent plan → routing as normal")
    elif creation_intent:
        print(f"[docs_researcher] creation_intent=True (msg: {last_human[:60]!r})")

    return {
        "docs_context":         result["summary"],
        "docs_sources":         result["sources"],
        "cost_query":           cost_query,
        "creation_intent":      creation_intent,
        "confirmation_intent":  confirmation_intent,
        "cleanup_intent":       is_cleanup,
        "deletion_intent":      is_deletion,
        "last_region":          last_region,
        "region":               last_region,  # override default for downstream tools
    }


async def supervisor_node(state: AgentState) -> dict:
    """Route to specialist."""
    import json
    last_human = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        ""
    )

    # Force cost agent if cost keywords detected (but not if also a creation intent)
    if state.get("cost_query") and not state.get("creation_intent"):
        return {"selected_agent": "cost"}

    # Force infra agent for creation requests — it has the right provisioning tools
    if state.get("creation_intent"):
        return {"selected_agent": "infra"}

    # Non-streaming — supervisor output is internal JSON, not for user
    llm = _get_llm(settings.fast_model, streaming=False)
    response = await llm.ainvoke([
        SystemMessage(content=SUPERVISOR_PROMPT),
        HumanMessage(content=last_human),
    ])
    try:
        raw = response.content.strip().strip("```json").strip("```").strip()
        data = json.loads(raw)
        return {"selected_agent": data.get("agent", "general")}
    except Exception:
        return {"selected_agent": "general"}


def _make_specialist_node(domain: str, tools: list):
    async def specialist_node(state: AgentState) -> dict:
        from langgraph.config import get_config
        config = get_config()
        model = config.get("configurable", {}).get("model", settings.default_model)

        region        = state.get("region", "us-east-1")
        user_level    = state.get("user_level", "intermediate")
        docs_context  = state.get("docs_context", "")
        proactive_ctx = state.get("proactive_context", "")
        level_addendum = LEVEL_ADDENDUMS.get(user_level, "")

        system_content = BASE_PROMPT.format(
            region=region,
            docs_context=docs_context if docs_context else "## AWS Official Documentation\n(No specific docs retrieved — answer carefully and cite where possible.)\n",
            proactive_context=proactive_ctx,
            level_addendum=level_addendum,
        ) + "\n## Your Domain\n" + SPECIALIST_INSTRUCTIONS.get(domain, "")

        # FORCE pricing tool usage for cost queries
        if state.get("cost_query") and domain == "cost":
            system_content += (
                "\n\n## MANDATORY PRICING TOOL USAGE\n"
                "The user asked about cost/pricing. You MUST call get_ec2_pricing or "
                "get_rds_pricing or cost_get_monthly_cost BEFORE responding with any price. "
                "Do NOT quote prices from your training data — they are outdated and incorrect."
            )

        # FORCE plan-first workflow when user wants to CREATE a resource
        if state.get("creation_intent") and domain in ("infra", "devops", "general"):
            system_content += PROVISIONING_WORKFLOW

        # FORCE Phase 2 execute when user confirmed a previous Plan
        if state.get("confirmation_intent") and domain in ("infra", "devops", "general"):
            system_content += PROVISIONING_EXECUTE_PHASE_2

        # FORCE cleanup workflow when user asks for resource cleanup
        if state.get("cleanup_intent") and domain in ("infra", "cost", "general"):
            system_content += CLEANUP_WORKFLOW

        # FORCE direct execution when user asks to delete a specific resource
        if state.get("deletion_intent") and domain in ("infra", "general"):
            system_content += DELETION_PROMPT

        llm = _get_llm(model, tools)
        messages = [SystemMessage(content=system_content)] + list(state["messages"])
        response = await llm.ainvoke(messages)
        return {"messages": [response]}

    specialist_node.__name__ = f"{domain}_agent"
    return specialist_node


async def human_review_node(state: AgentState) -> Command:
    last = state["messages"][-1]
    tool_calls = last.tool_calls if isinstance(last, AIMessage) else []
    decision = interrupt({
        "type": "human_review_required",
        "message": "Approval required before execution.",
        "pending_tool_calls": [
            {"name": tc["name"], "args": tc["args"]} for tc in tool_calls
        ],
    })
    if decision == "approve":
        return Command(goto="tools")
    rejection = [ToolMessage(content="User rejected the operation.", tool_call_id=tc["id"]) for tc in tool_calls]
    return Command(goto="supervisor", update={"messages": rejection})


def _is_destructive(state: AgentState) -> bool:
    last = state["messages"][-1]
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return False
    return any(tc["name"] in DESTRUCTIVE_TOOLS for tc in last.tool_calls)




# ═══════════════════════════════════════════════════════════════════════════════
# PROVISIONING ReAct PIPELINE (3 explicit reasoning steps)
# Triggered when creation_intent is detected.
# Pipeline: reasoning → pricing → plan_composition
# ═══════════════════════════════════════════════════════════════════════════════

PROVISIONING_REASONING_PROMPT = """You are a Principal AWS Solutions Architect doing explicit reasoning
before producing a provisioning plan. Output STRICT JSON ONLY (no markdown, no preamble).

The user wants to create an AWS resource. Analyze the request and produce structured
reasoning the next steps will use.

{{
  "resource_type":     "ec2 | s3 | rds | aurora | dynamodb | sqs | sns | lambda | iam | route53 | elasticache | kms | secret | cognito | vpc | alb | nlb | ecs | eks | apigateway | cloudfront | stepfunctions | eventbridge | other",
  "use_case":          "<1 sentence describing what the resource is for>",
  "access_patterns":   [
    "<dominant access pattern, e.g. 'GetItem by SessionId — 90% of traffic'>",
    "<secondary pattern>"
  ],
  "schema_or_arch_decision": {{
    "<key>": "<chosen value>",
    "<key>": "<chosen value>",
    "_justification": "<why these choices given the access patterns>"
  }},
  "traffic_assumptions": {{
    "users":                     <number>,
    "reads_per_user_per_day":    <number>,
    "writes_per_user_per_day":   <number>,
    "avg_item_size_kb":          <number>,
    "data_transfer_gb_month":    <number>,
    "_source":                   "<'user-specified' or 'reasonable-default-for-<usecase>'>"
  }},
  "cost_components": [
    {{
      "service": "<key matching calculate_architecture_cost tool: ec2, dynamodb, s3, fargate, lambda, etc.>",
      "<service-specific params with computed values>": "<...>"
    }}
  ],
  "production_defaults_to_apply": [
    "<concrete default 1>",
    "<concrete default 2>"
  ],
  "use_case_specific_recommendations": [
    "<e.g. 'DAX for sub-ms session validation if >1k req/s'>",
    "<e.g. 'GSI on UserId for admin queries'>"
  ],
  "dev_alternative": {{
    "changes": ["<change 1>", "<change 2>"],
    "savings_estimate_usd_per_month": <number>
  }},
  "tool_selection": "<specific tool name from registry, or 'aws_deploy_cloudformation'>"
}}

CRITICAL — for cost_components, use these service keys and params (matches calculate_architecture_cost tool):
  ec2:                {{instance_type, count, hours_month=730}}
  rds:                {{instance_class, count=1, storage_gb=100, multi_az=true}}
  aurora:             {{instance_class, count=2, storage_gb=100}}
  fargate:            {{vcpu, memory_gb, task_count, hours_month=730}}
  lambda:             {{memory_mb=512, invocations_million=1, avg_duration_ms=200}}
  elasticache_redis:  {{node_type, count}}
  alb:                {{count=1, lcu_avg=5}}
  nat:                {{count=2, data_transfer_gb=100}}
  cloudfront:         {{data_transfer_gb, requests_million}}
  s3:                 {{storage_gb, puts_million=0, gets_million=0, transfer_out_gb=0}}
  dynamodb:           {{reads_million=0, writes_million=0, storage_gb=0}}
  route53:            {{hosted_zones=1, queries_million=1}}
  cognito:            {{monthly_active_users}}
  waf:                {{acls=1, rules=10, requests_million=10}}
  cloudwatch:         {{custom_metrics=0, logs_gb=0, alarms=10, dashboards=1}}
  ses, sns, sqs:      {{<see tool docstring>}}
  secrets_manager:    {{secrets, api_calls_thousand}}
  kms:                {{keys, requests_thousand}}

For DynamoDB session storage example (10k users, 100 reads + 5 writes per user/day):
  - reads_million = 10000 × 100 × 30 / 1_000_000 = 30
  - writes_million = 10000 × 5 × 30 / 1_000_000 = 1.5
  - storage_gb = 10000 × 1KB / (1024×1024) = 0.01

Use industry-typical assumptions when user didn't specify. Be explicit about defaults via "_source" field.
"""


async def provisioning_reasoning_node(state: AgentState) -> dict:
    """Step 1 — Extract structured requirements + design decisions as JSON."""
    from langgraph.config import get_config
    config = get_config()
    model = config.get("configurable", {}).get("model", settings.default_model)

    llm = _get_llm(model, streaming=False)  # JSON output, no streaming
    last_human = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        ""
    )
    response = await llm.ainvoke([
        SystemMessage(content=PROVISIONING_REASONING_PROMPT),
        HumanMessage(content=last_human),
    ])
    try:
        raw = response.content.strip().strip("```json").strip("```").strip()
        reasoning = json.loads(raw)
    except Exception as e:
        reasoning = {
            "error":          str(e),
            "raw":            response.content[:500],
            "resource_type":  "unknown",
        }
    return {"prov_reasoning": reasoning}


async def provisioning_pricing_node(state: AgentState) -> dict:
    """Step 2 — Compute deterministic cost from extracted components."""
    reasoning = state.get("prov_reasoning") or {}
    components = reasoning.get("cost_components", [])

    if not components:
        return {"prov_cost": {
            "components":        [],
            "total_monthly_usd": 0,
            "note":              "No cost components extracted in reasoning step",
        }}

    from tools.aws.pricing import calculate_architecture_cost as _calc
    try:
        result = await _calc.ainvoke({"components": components})
    except Exception as e:
        result = {"error": str(e), "components": components}
    return {"prov_cost": result}


PROVISIONING_PLAN_COMPOSITION_PROMPT = """You are a Principal AWS Solutions Architect composing a provisioning plan.

You have ALREADY done the reasoning work — see the structured analysis below.
Your only job now is to format it as a clean Plan card for the user.

## Reasoning from analysis step (use this as ground truth — do NOT recompute)

```json
{reasoning_json}
```

## Cost calculation (from calculate_architecture_cost tool — use these EXACT numbers)

```json
{cost_json}
```

## Output format — EXACTLY this structure:

## Provisioning Plan: [Resource type — concrete description from reasoning.use_case]

| Parameter | Chosen Value | Alternatives | Monthly Cost |
|---|---|---|---|
| [Fill from reasoning.schema_or_arch_decision + traffic_assumptions] |
| [Show real $ in Cost column, derived from cost.components] |

**Total estimated cost: $X.XX/month** ← from cost.total_monthly_usd

### Why this design
Quote from reasoning.schema_or_arch_decision._justification.
Explain access patterns from reasoning.access_patterns.

### Production-grade defaults applied
List every item from reasoning.production_defaults_to_apply with a ✓ prefix.
Include:
✓ Tags: Environment, Project, Owner, CostCenter, CreatedBy

### Use-case-specific recommendations
List items from reasoning.use_case_specific_recommendations.

### Cost breakdown
For each item in cost.components, show: `service` purpose: $X.XX/month — `detail`
Then:
- **Total: ${total}/month (On-Demand)**
- **Yearly: ${yearly}/year**
- **3-year TCO: ${tco}**

### Commitment savings (RI / Savings Plans)
Render the table below ONLY if cost.commitment_projections is non-empty.
Use the exact numbers from cost.commitment_projections — do NOT recompute.

| Commitment | Monthly | Yearly | Savings vs On-Demand |
|---|---|---|---|
| For each entry in commitment_projections (skip "On-Demand baseline"): one row with monthly_usd, yearly_usd, "-X%" |

Annotate the table with: "Eligible for commitments: $X.XX/mo ; ineligible (S3, data transfer, etc.): $Y.YY/mo"
(Use cost.commitment_eligible_usd and cost.commitment_ineligible_usd)

Always recommend the best fit based on workload predictability:
- Steady production workload → 3yr Savings Plan Compute (28% off)
- Predictable 1-year horizon → 1yr Reserved Instance (30% off)
- Stateless / non-critical → Spot (70% off, accept interruption)

### Dev/staging cheaper alternative
From reasoning.dev_alternative — list the changes and total savings.

### Template preview (only if reasoning.tool_selection == "aws_deploy_cloudformation")
Generate a complete YAML CFN template in a code block, applying ALL production defaults
listed above. Include Parameters + Outputs sections.

**Reply `confirm` to proceed, or specify changes.**

ABSOLUTE RULES:
1. NEVER write "Variable" in cost columns. Use the exact $ from cost.components.
2. Include the assumptions from reasoning.traffic_assumptions in the "Why this design" section.
3. Do NOT call any tool — execution is in the next turn after user confirms.
"""


async def provisioning_plan_node(state: AgentState) -> dict:
    """Step 3 — Compose final user-facing Plan card with reasoning + cost as context."""
    from langgraph.config import get_config
    config = get_config()
    model = config.get("configurable", {}).get("model", settings.default_model)

    reasoning = state.get("prov_reasoning") or {}
    cost      = state.get("prov_cost") or {}

    system_content = PROVISIONING_PLAN_COMPOSITION_PROMPT.format(
        reasoning_json=json.dumps(reasoning, indent=2, ensure_ascii=False)[:3000],
        cost_json=json.dumps(cost, indent=2, ensure_ascii=False)[:2000],
        total=cost.get("total_monthly_usd", "?"),
        yearly=cost.get("total_yearly_usd", "?"),
        tco=cost.get("tco_3y_usd", "?"),
    )

    llm = _get_llm(model, streaming=True)
    response = await llm.ainvoke([
        SystemMessage(content=system_content),
        *state["messages"],
    ])
    return {"messages": [response]}


def route_to_specialist(state: AgentState) -> str:
    # CREATION: route to ReAct planning pipeline
    if state.get("creation_intent"):
        return "provisioning_reasoning"
    # CONFIRMATION: user agreed to a previous Plan — route to infra which holds
    # every provisioning tool, with Phase 2 execute prompt injected.
    if state.get("confirmation_intent"):
        return "infra_agent"
    # CLEANUP: route to infra (has all lifecycle tools) with cleanup workflow
    if state.get("cleanup_intent"):
        return "infra_agent"
    # DELETION: route to infra (has ALL delete tools across services)
    if state.get("deletion_intent"):
        return "infra_agent"
    return f"{state.get('selected_agent', 'general')}_agent"


def route_after_specialist(state: AgentState) -> str:
    last = state["messages"][-1]
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return END
    if _is_destructive(state):
        return "human_review"
    return "tools"


# ── Build Graph ────────────────────────────────────────────────────────────────

def build_graph():
    # InMemorySaver — async-compatible, no extra deps.
    # Loses cross-restart memory but the app is single-session anyway.
    from langgraph.checkpoint.memory import InMemorySaver
    memory = InMemorySaver()
    tool_node = ToolNode(ALL_TOOLS)

    g = StateGraph(AgentState)
    g.add_node("docs_researcher", docs_researcher_node)
    g.add_node("supervisor",      supervisor_node)

    specialists = {
        "infra":    (INFRA_TOOLS,    "infra_agent"),
        "security": (SECURITY_TOOLS, "security_agent"),
        "cost":     (COST_TOOLS,     "cost_agent"),
        "data":     (DATA_TOOLS,     "data_agent"),
        "devops":   (DEVOPS_TOOLS,   "devops_agent"),
        "general":  (ALL_TOOLS,      "general_agent"),
    }
    for domain, (tools, node_name) in specialists.items():
        g.add_node(node_name, _make_specialist_node(domain, tools))

    g.add_node("tools",        tool_node)
    g.add_node("human_review", human_review_node)

    # ReAct provisioning pipeline (creation_intent path)
    g.add_node("provisioning_reasoning", provisioning_reasoning_node)
    g.add_node("provisioning_pricing",   provisioning_pricing_node)
    g.add_node("provisioning_plan",      provisioning_plan_node)

    # Flow: docs FIRST, always
    g.add_edge(START, "docs_researcher")
    g.add_edge("docs_researcher", "supervisor")

    # Supervisor branches: provisioning ReAct pipeline OR regular specialist
    routing_map = {f"{d}_agent": f"{d}_agent" for d in specialists}
    routing_map["provisioning_reasoning"] = "provisioning_reasoning"
    g.add_conditional_edges("supervisor", route_to_specialist, routing_map)

    # Chain provisioning pipeline
    g.add_edge("provisioning_reasoning", "provisioning_pricing")
    g.add_edge("provisioning_pricing",   "provisioning_plan")
    g.add_edge("provisioning_plan",      END)

    for _, (_, node_name) in specialists.items():
        g.add_conditional_edges(
            node_name,
            route_after_specialist,
            {"human_review": "human_review", "tools": "tools", END: END},
        )

    g.add_edge("tools", "supervisor")

    return g.compile(checkpointer=memory, interrupt_before=["human_review"])


_graph = None
def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


# ── Public stream API ──────────────────────────────────────────────────────────

def _build_approval_event(state) -> dict:
    """Build the approval_required event from a paused graph state.

    Called when astream_events completes and the graph is paused at
    interrupt_before=["human_review"]. Extracts the pending tool_calls
    from the last AI message and returns the event dict for the frontend.
    """
    pending = []
    try:
        msgs = state.values.get("messages", []) if hasattr(state, "values") else state.get("messages", [])
        last = msgs[-1] if msgs else None
        if last and hasattr(last, "tool_calls") and last.tool_calls:
            for tc in last.tool_calls:
                pending.append({
                    "name": tc.get("name"),
                    "args": tc.get("args", {}),
                    "id":   tc.get("id", ""),
                })
    except Exception:
        pass
    return {
        "type":         "approval_required",
        "tool_calls":   pending,
        "message":      "Awaiting your approval — reply 'approve' to execute, anything else to cancel.",
        "interrupt":    "human_review",
    }


async def _process_event(event, run_id):
    """Yield client events from a single graph event. Used inside resume path."""
    ev_type = event["event"]
    name    = event.get("name", "")
    data    = event.get("data", {})

    if ev_type == "on_chat_model_stream":
        metadata = event.get("metadata", {}) or {}
        node = metadata.get("langgraph_node", "")
        SPECIALIST_NODES = {"infra_agent", "security_agent", "cost_agent",
                            "data_agent", "devops_agent", "general_agent",
                            "provisioning_plan"}
        if node in SPECIALIST_NODES:
            chunk = data.get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                yield {"type": "token", "content": chunk.content}

    elif ev_type == "on_tool_start":
        yield {"type": "tool_start", "tool": name, "args": data.get("input", {})}

    elif ev_type == "on_tool_end":
        output = data.get("output")
        yield {"type": "tool_end", "tool": name,
               "result": output.content if hasattr(output, "content") else str(output)}

    elif ev_type == "on_chain_start" and name in (
        "docs_researcher", "supervisor", "infra_agent", "security_agent",
        "cost_agent", "data_agent", "devops_agent", "general_agent",
        "provisioning_reasoning", "provisioning_pricing", "provisioning_plan",
        "tools", "human_review",
    ):
        labels = {
            "docs_researcher": "Fetching AWS docs", "supervisor": "Routing",
            "infra_agent": "Infrastructure", "security_agent": "Security",
            "cost_agent": "Cost & Pricing", "data_agent": "Data & Analytics",
            "devops_agent": "DevOps", "general_agent": "Generalist",
            "provisioning_reasoning": "Analyzing requirements",
            "provisioning_pricing":   "Computing cost",
            "provisioning_plan":      "Composing plan",
            "tools": "Executing tool", "human_review": "Awaiting approval",
        }
        yield {"type": "agent_start", "agent": name, "label": labels.get(name, name)}


async def stream_agent(
    user_input: str,
    thread_id: str,
    credentials: dict,
    profile: str = "default",
    model: str | None = None,
    resume_value: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    set_session(credentials, profile)
    region = credentials.get("aws_region", "us-east-1") or "us-east-1"

    user_profile = update_profile(thread_id, user_input) if user_input else get_profile(thread_id)
    scanner = get_scanner()
    cached_scan = scanner.get_cached_result()
    proactive_context = cached_scan.to_context_string() if cached_scan else ""

    if user_input and (not cached_scan or not cached_scan.alerts) and credentials.get("aws_access_key_id"):
        asyncio.create_task(scanner.scan(credentials, region))

    config = {"configurable": {"thread_id": thread_id, "model": model or settings.default_model, "region": region}}
    run_id = str(uuid.uuid4())

    try:
        audit.log("run_start", run_id=run_id, thread_id=thread_id, input=user_input[:200],
                  region=region, user_level=user_profile.level)
    except Exception:
        pass

    yield {"type": "profile_update", "level": user_profile.level,
           "level_confidence": user_profile.level_confidence}

    graph = get_graph()

    try:
        if resume_value:
            input_data = Command(resume=resume_value)
        else:
            input_data = {
                "messages":          [HumanMessage(content=user_input)],
                "user_level":        user_profile.level,
                "proactive_context": proactive_context,
                "region":            region,
                "selected_agent":    "",
                "docs_context":      "",
                "docs_sources":      [],
                "cost_query":        False,
            }

        # ── Resume from pending interrupt? ───────────────────────────────
        # If the previous turn paused at human_review, the user's new message
        # decides: approve → resume; reject/anything else → cancel + new turn.
        try:
            existing_state = await graph.aget_state(config)
            is_paused = existing_state and existing_state.next and "human_review" in existing_state.next
        except Exception:
            is_paused = False

        if is_paused:
            last_user_text = ""
            if isinstance(input_data, dict):
                msgs = input_data.get("messages", [])
                if msgs and hasattr(msgs[-1], "content"):
                    last_user_text = (msgs[-1].content or "").strip().lower()

            APPROVE_PAT = re.compile(r"^\s*(approve[d]?|yes|ok|confirm|go|proceed|d'accord|oui|vas[- ]?y)\b", re.IGNORECASE)
            if APPROVE_PAT.search(last_user_text):
                yield {"type": "status", "label": "Approval received — executing tool"}
                # Resume from interrupt with no new input (langgraph picks up where it left off)
                async for event in graph.astream_events(None, config=config, version="v2"):
                    async for ev in _process_event(event, run_id):
                        yield ev
                # After resume, check state again for completion or another interrupt
                try:
                    final_state = await graph.aget_state(config)
                    if final_state and final_state.next and "human_review" in final_state.next:
                        yield _build_approval_event(final_state)
                    else:
                        yield {"type": "run_end", "run_id": run_id, "status": "success"}
                except Exception as e:
                    yield {"type": "error", "message": f"Resume completed but state check failed: {e}"}
                return
            else:
                yield {"type": "status", "label": "Cancelled previous pending action"}
                # Drop the interrupt by overwriting state (the new user message takes over)
                # Continue with fresh graph run below.

        # ── Main streaming with full error capture ───────────────────────
        try:
            async for event in graph.astream_events(input_data, config=config, version="v2"):
                ev_type = event["event"]
                name    = event.get("name", "")
                data    = event.get("data", {})

                if ev_type == "on_chat_model_stream":
                    # Only stream tokens from user-facing specialists, NOT supervisor/docs/router.
                    # Without this, internal JSON like {"agent":"cost"} leaks into the response.
                    metadata = event.get("metadata", {}) or {}
                    node = metadata.get("langgraph_node", "")
                    SPECIALIST_NODES = {
                        "infra_agent", "security_agent", "cost_agent",
                        "data_agent", "devops_agent", "general_agent",
                        # Provisioning plan is user-facing too; reasoning node is JSON-only (internal)
                        "provisioning_plan",
                    }
                    if node in SPECIALIST_NODES:
                        chunk = data.get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            yield {"type": "token", "content": chunk.content}

                elif ev_type == "on_tool_start":
                    yield {"type": "tool_start", "tool": name, "args": data.get("input", {})}

                elif ev_type == "on_tool_end":
                    output = data.get("output")
                    yield {"type": "tool_end", "tool": name,
                           "result": output.content if hasattr(output, "content") else str(output)}
                    try: audit.log("tool_executed", run_id=run_id, tool=name)
                    except Exception: pass

                elif ev_type == "on_chain_end" and name == "docs_researcher":
                    # Emit docs sources for the frontend
                    output = data.get("output", {})
                    if isinstance(output, dict) and output.get("docs_sources"):
                        yield {"type": "docs_sources", "sources": [
                            {"service": s["service"], "url": s["url"]}
                            for s in output["docs_sources"]
                        ]}

                elif ev_type == "on_chain_start" and name in (
                    "docs_researcher", "supervisor",
                    "infra_agent", "security_agent", "cost_agent",
                    "data_agent", "devops_agent", "general_agent",
                    "provisioning_reasoning", "provisioning_pricing", "provisioning_plan",
                ):
                    labels = {
                        "docs_researcher":         "Fetching AWS docs",
                        "supervisor":              "Routing",
                        "infra_agent":             "Infrastructure",
                        "security_agent":          "Security",
                        "cost_agent":              "Cost & Pricing",
                        "data_agent":              "Data & Analytics",
                        "devops_agent":            "DevOps",
                        "general_agent":           "Generalist",
                        "provisioning_reasoning":  "Analyzing requirements",
                        "provisioning_pricing":    "Computing cost",
                        "provisioning_plan":       "Composing plan",
                    }
                    yield {"type": "agent_start", "agent": name, "label": labels.get(name, name)}

                elif ev_type == "on_chain_end" and name in (
                    "docs_researcher", "supervisor",
                    "infra_agent", "security_agent", "cost_agent",
                    "data_agent", "devops_agent", "general_agent",
                    "provisioning_reasoning", "provisioning_pricing", "provisioning_plan",
                ):
                    yield {"type": "agent_end", "agent": name}

        except Exception as e:
            import traceback
            err_msg = f"{type(e).__name__}: {e}"
            tb = traceback.format_exc()[:500]
            yield {"type": "error",
                   "message": f"Agent encountered an error: {err_msg}",
                   "details": tb,
                   "fatal":   True}
            try: audit.log("run_end", run_id=run_id, status="error", error=err_msg)
            except Exception: pass
            return

        # After streaming completes: detect if graph paused at human_review interrupt.
        # This is the critical fix for the "infinite loading on confirm" bug.
        try:
            final_state = await graph.aget_state(config)
            if final_state and final_state.next and "human_review" in final_state.next:
                yield _build_approval_event(final_state)
                try: audit.log("run_end", run_id=run_id, status="awaiting_approval")
                except Exception: pass
                return
        except Exception as e:
            yield {"type": "error", "message": f"State check failed: {e}", "fatal": False}

        yield {"type": "run_end", "run_id": run_id, "status": "success"}
        try: audit.log("run_end", run_id=run_id, status="success")
        except Exception: pass

    except Exception as exc:
        import traceback
        traceback.print_exc()
        yield {"type": "run_end", "run_id": run_id, "status": "error", "error": str(exc)}
        try: audit.log("run_end", run_id=run_id, status="error", error=str(exc))
        except Exception: pass


async def get_thread_history(thread_id: str) -> list[dict]:
    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    state = graph.get_state(config)
    if not state or not state.values:
        return []
    messages = state.values.get("messages", [])
    return [
        {"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": m.content}
        for m in messages if (isinstance(m, HumanMessage) or (isinstance(m, AIMessage) and m.content))
    ]
