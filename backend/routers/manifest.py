"""Manifest router — lists available resource types and regions."""
from fastapi import APIRouter

router = APIRouter()

RESOURCE_CATALOG = [
    {"category": "Compute",   "service": "EC2",         "tool": "ec2_list_instances"},
    {"category": "Compute",   "service": "Lambda",      "tool": "lambda_list_functions"},
    {"category": "Compute",   "service": "ECS",         "tool": "ecs_list_clusters"},
    {"category": "Compute",   "service": "EKS",         "tool": "eks_list_clusters"},
    {"category": "Database",  "service": "RDS",         "tool": "rds_list_instances"},
    {"category": "Database",  "service": "DynamoDB",    "tool": "dynamodb_list_tables"},
    {"category": "Database",  "service": "ElastiCache", "tool": "elasticache_list_clusters"},
    {"category": "Storage",   "service": "S3",          "tool": "s3_list_buckets"},
    {"category": "Network",   "service": "VPC",         "tool": "ec2_list_vpcs"},
    {"category": "Network",   "service": "Route53",     "tool": "route53_list_hosted_zones"},
    {"category": "Security",  "service": "IAM",         "tool": "iam_list_users"},
    {"category": "Security",  "service": "ACM",         "tool": "acm_list_certificates"},
    {"category": "DevOps",    "service": "CloudWatch",  "tool": "cloudwatch_list_alarms"},
    {"category": "DevOps",    "service": "SNS",         "tool": "sns_list_topics"},
    {"category": "DevOps",    "service": "SQS",         "tool": "sqs_list_queues"},
    {"category": "Data",      "service": "Glue",        "tool": "glue_list_databases"},
    {"category": "Data",      "service": "Athena",      "tool": "athena_list_workgroups"},
]

@router.get("/catalog")
async def get_catalog():
    return {"catalog": RESOURCE_CATALOG}
