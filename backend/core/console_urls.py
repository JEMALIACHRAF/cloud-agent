"""
AWS Console deep-link generator.
Returns the exact URL to view a resource in AWS Console.
"""
from __future__ import annotations
from urllib.parse import quote


def console_url(resource_type: str, resource_id: str, region: str = "us-east-1", **kwargs) -> str:
    """
    Generate the AWS Console deep link for a resource.

    Examples:
        console_url("ec2_instance", "i-abc", "eu-west-3")
        console_url("s3_bucket", "my-bucket")
        console_url("rds_instance", "db-1", "us-east-1")
    """
    rt = resource_type.lower()
    base = f"https://{region}.console.aws.amazon.com"
    global_base = "https://console.aws.amazon.com"

    builders = {
        # Compute
        "ec2_instance":  lambda: f"{base}/ec2/home?region={region}#InstanceDetails:instanceId={resource_id}",
        "ec2_volume":    lambda: f"{base}/ec2/home?region={region}#VolumeDetails:volumeId={resource_id}",
        "ec2_ami":       lambda: f"{base}/ec2/home?region={region}#ImageDetails:imageId={resource_id}",
        "ec2_sg":        lambda: f"{base}/ec2/home?region={region}#SecurityGroup:groupId={resource_id}",
        "ec2_keypair":   lambda: f"{base}/ec2/home?region={region}#KeyPairs:keyName={resource_id}",
        "ec2_eip":       lambda: f"{base}/ec2/home?region={region}#ElasticIpDetails:AllocationId={resource_id}",
        "ec2_vpc":       lambda: f"{base}/vpcconsole/home?region={region}#VpcDetails:VpcId={resource_id}",
        "ec2_subnet":    lambda: f"{base}/vpcconsole/home?region={region}#SubnetDetails:subnetId={resource_id}",
        "lambda":        lambda: f"{base}/lambda/home?region={region}#/functions/{resource_id}",

        # Containers
        "ecs_cluster":   lambda: f"{base}/ecs/v2/clusters/{resource_id}?region={region}",
        "ecs_service":   lambda: f"{base}/ecs/v2/clusters/{kwargs.get('cluster','')}/services/{resource_id}?region={region}",
        "eks_cluster":   lambda: f"{base}/eks/home?region={region}#/clusters/{resource_id}",

        # Storage
        "s3_bucket":     lambda: f"https://s3.console.aws.amazon.com/s3/buckets/{resource_id}?region={region}",
        "s3_object":     lambda: f"https://s3.console.aws.amazon.com/s3/object/{kwargs.get('bucket','')}?prefix={quote(resource_id)}&region={region}",

        # Database
        "rds_instance":  lambda: f"{base}/rds/home?region={region}#database:id={resource_id}",
        "rds_cluster":   lambda: f"{base}/rds/home?region={region}#database:id={resource_id};is-cluster=true",
        "rds_snapshot":  lambda: f"{base}/rds/home?region={region}#db-snapshot:engine=;id={resource_id}",
        "dynamodb_table":lambda: f"{base}/dynamodbv2/home?region={region}#table?name={resource_id}",
        "elasticache":   lambda: f"{base}/elasticache/home?region={region}#/redis/{resource_id}",

        # IAM (global)
        "iam_user":      lambda: f"{global_base}/iam/home#/users/{resource_id}",
        "iam_role":      lambda: f"{global_base}/iam/home#/roles/{resource_id}",
        "iam_group":     lambda: f"{global_base}/iam/home#/groups/{resource_id}",
        "iam_policy":    lambda: f"{global_base}/iam/home#/policies/{quote(resource_id, safe='')}",

        # Networking
        "route53_zone":  lambda: f"{global_base}/route53/v2/hostedzones#ListRecordSets/{resource_id}",
        "acm_cert":      lambda: f"{base}/acm/home?region={region}#/certificates/{resource_id}",
        "cloudfront":    lambda: f"{global_base}/cloudfront/v4/home#/distributions/{resource_id}",
        "apigw":         lambda: f"{base}/apigateway/main/apis/{resource_id}/resources?region={region}",

        # Ops
        "cloudwatch_alarm":   lambda: f"{base}/cloudwatch/home?region={region}#alarmsV2:alarm/{quote(resource_id)}",
        "cloudwatch_log":     lambda: f"{base}/cloudwatch/home?region={region}#logsV2:log-groups/log-group/{quote(resource_id, safe='')}",
        "cloudwatch_metric":  lambda: f"{base}/cloudwatch/home?region={region}#metricsV2:graph=~()",
        "sns_topic":          lambda: f"{base}/sns/v3/home?region={region}#/topic/{quote(resource_id, safe='')}",
        "sqs_queue":          lambda: f"{base}/sqs/v3/home?region={region}#/queues/{quote(resource_id, safe='')}",
        "secrets_manager":    lambda: f"{base}/secretsmanager/secret?name={quote(resource_id)}&region={region}",
        "ssm_parameter":      lambda: f"{base}/systems-manager/parameters/{quote(resource_id, safe='')}/description?region={region}",
        "stepfunctions":      lambda: f"{base}/states/home?region={region}#/statemachines/view/{quote(resource_id, safe='')}",
        "cloudformation":     lambda: f"{base}/cloudformation/home?region={region}#/stacks/stackinfo?stackId={quote(resource_id)}",

        # ML
        "sagemaker_endpoint": lambda: f"{base}/sagemaker/home?region={region}#/endpoints/{resource_id}",
        "bedrock":            lambda: f"{base}/bedrock/home?region={region}",

        # Cost
        "cost_explorer":      lambda: f"{global_base}/cost-management/home#/cost-explorer",
        "billing":            lambda: f"{global_base}/billing/home#/bills",

        # Generic dashboards (no specific ID)
        "ec2":  lambda: f"{base}/ec2/home?region={region}",
        "s3":   lambda: "https://s3.console.aws.amazon.com/s3/home",
        "iam":  lambda: f"{global_base}/iam/home",
        "rds":  lambda: f"{base}/rds/home?region={region}",
    }

    builder = builders.get(rt)
    return builder() if builder else f"{base}/console/home?region={region}"


def enrich_resource(resource_type: str, resource: dict, region: str = "us-east-1") -> dict:
    """Add `console_url` field to a resource dict if it has an id."""
    if not isinstance(resource, dict):
        return resource
    rid = resource.get("id") or resource.get("name") or resource.get("arn")
    if rid:
        # For ARNs, extract the resource name
        if isinstance(rid, str) and rid.startswith("arn:"):
            rid = rid.split(":")[-1].split("/")[-1]
        resource["console_url"] = console_url(resource_type, rid, region)
    return resource
