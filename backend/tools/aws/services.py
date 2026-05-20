"""AWS IAM, Lambda, RDS, EKS, ECS, CloudWatch, SNS, SQS, DynamoDB tools — fixed asyncio."""
from __future__ import annotations
import asyncio
import functools
import json
from langchain_core.tools import tool


def _run(fn, *a, **kw):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, functools.partial(fn, *a, **kw))


def _client(service, region="us-east-1"):
    from core.session import get_client
    return get_client(service, region)


# ── IAM ────────────────────────────────────────────────────────────────────────

@tool
async def iam_list_users() -> dict:
    """List all IAM users with creation date and last login."""
    iam = _client("iam")
    resp = await _run(iam.list_users)
    import datetime
    now = datetime.datetime.utcnow()
    users = []
    for u in resp["Users"]:
        created = u["CreateDate"].replace(tzinfo=None)
        age_days = (now - created).days
        last_used = u.get("PasswordLastUsed")
        users.append({
            "username":  u["UserName"],
            "id":        u["UserId"],
            "arn":       u["Arn"],
            "created":   str(u["CreateDate"]),
            "age_days":  age_days,
            "last_login": str(last_used) if last_used else "Never",
        })
    return {"users": users, "count": len(users)}


@tool
async def iam_list_roles() -> dict:
    """List all IAM roles."""
    iam = _client("iam")
    resp = await _run(iam.list_roles)
    return {
        "roles": [
            {
                "name":        r["RoleName"],
                "arn":         r["Arn"],
                "created":     str(r["CreateDate"]),
                "description": r.get("Description", ""),
            }
            for r in resp["Roles"]
        ]
    }


@tool
async def iam_list_groups() -> dict:
    """List all IAM groups."""
    iam = _client("iam")
    resp = await _run(iam.list_groups)
    return {"groups": [{"name": g["GroupName"], "id": g["GroupId"], "arn": g["Arn"]} for g in resp["Groups"]]}


@tool
async def iam_list_policies(scope: str = "Local") -> dict:
    """List IAM policies. scope: Local (custom) or AWS (managed)."""
    iam = _client("iam")
    resp = await _run(iam.list_policies, Scope=scope)
    return {
        "policies": [
            {"name": p["PolicyName"], "arn": p["Arn"], "attached_count": p["AttachmentCount"]}
            for p in resp["Policies"][:30]
        ]
    }


@tool
async def iam_get_user(username: str) -> dict:
    """Get details, attached policies, and group memberships for an IAM user."""
    iam = _client("iam")
    user     = await _run(iam.get_user, UserName=username)
    policies = await _run(iam.list_attached_user_policies, UserName=username)
    inline   = await _run(iam.list_user_policies, UserName=username)
    groups   = await _run(iam.list_groups_for_user, UserName=username)
    return {
        "user":              user["User"],
        "attached_policies": [p["PolicyName"] for p in policies["AttachedPolicies"]],
        "inline_policies":   inline["PolicyNames"],
        "groups":            [g["GroupName"] for g in groups["Groups"]],
    }


@tool
async def iam_get_account_summary() -> dict:
    """Get account-level IAM summary: user count, MFA status, etc."""
    iam = _client("iam")
    resp = await _run(iam.get_account_summary)
    s = resp["SummaryMap"]
    return {
        "summary": s,
        "critical_checks": {
            "mfa_enabled_on_root": s.get("AccountMFAEnabled", 0) == 1,
            "users_without_mfa":   s.get("MFADevicesInUse", 0),
            "total_users":         s.get("Users", 0),
        }
    }


@tool
async def iam_list_access_keys(username: str) -> dict:
    """List access keys for an IAM user with status and age in days."""
    import datetime
    iam = _client("iam")
    resp = await _run(iam.list_access_keys, UserName=username)
    now = datetime.datetime.utcnow()
    keys = []
    for k in resp["AccessKeyMetadata"]:
        created = k["CreateDate"].replace(tzinfo=None)
        age_days = (now - created).days
        keys.append({
            "id":       k["AccessKeyId"],
            "status":   k["Status"],
            "created":  str(k["CreateDate"]),
            "age_days": age_days,
            "risk":     "HIGH — rotate immediately" if age_days > 90 and k["Status"] == "Active" else "OK",
        })
    return {"access_keys": keys}


# ── Lambda ─────────────────────────────────────────────────────────────────────

@tool
async def lambda_list_functions(region: str = "us-east-1") -> dict:
    """List all Lambda functions with runtime, memory, and last modified."""
    lmb = _client("lambda", region)
    resp = await _run(lmb.list_functions)
    return {
        "functions": [
            {
                "name":          f["FunctionName"],
                "runtime":       f.get("Runtime"),
                "memory_mb":     f.get("MemorySize"),
                "timeout_s":     f.get("Timeout"),
                "last_modified": f.get("LastModified"),
                "handler":       f.get("Handler"),
                "arn":           f["FunctionArn"],
            }
            for f in resp["Functions"]
        ]
    }


@tool
async def lambda_get_function(function_name: str, region: str = "us-east-1") -> dict:
    """Get full configuration for a Lambda function."""
    lmb = _client("lambda", region)
    resp = await _run(lmb.get_function, FunctionName=function_name)
    cfg = resp["Configuration"]
    return {
        "name":          cfg["FunctionName"],
        "runtime":       cfg.get("Runtime"),
        "handler":       cfg.get("Handler"),
        "memory_mb":     cfg.get("MemorySize"),
        "timeout_s":     cfg.get("Timeout"),
        "role":          cfg.get("Role"),
        "env_vars":      list(cfg.get("Environment", {}).get("Variables", {}).keys()),
        "layers":        [l["Arn"] for l in cfg.get("Layers", [])],
        "vpc":           cfg.get("VpcConfig"),
        "code_size_bytes": cfg.get("CodeSize"),
        "architectures": cfg.get("Architectures", ["x86_64"]),
    }


@tool
async def lambda_invoke(function_name: str, payload: dict = {}, region: str = "us-east-1") -> dict:
    """Invoke a Lambda function synchronously. REQUIRES CONFIRMATION."""
    lmb = _client("lambda", region)
    resp = await _run(
        lmb.invoke,
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    body = resp["Payload"].read().decode()
    return {
        "status_code":    resp["StatusCode"],
        "function_error": resp.get("FunctionError"),
        "response":       json.loads(body) if body else None,
    }


@tool
async def lambda_list_event_source_mappings(function_name: str, region: str = "us-east-1") -> dict:
    """List event source mappings (triggers) for a Lambda function."""
    lmb = _client("lambda", region)
    resp = await _run(lmb.list_event_source_mappings, FunctionName=function_name)
    return {
        "triggers": [
            {
                "uuid":       m["UUID"],
                "source":     m["EventSourceArn"],
                "state":      m["State"],
                "batch_size": m.get("BatchSize"),
            }
            for m in resp["EventSourceMappings"]
        ]
    }


# ── RDS ────────────────────────────────────────────────────────────────────────

@tool
async def rds_list_instances(region: str = "us-east-1") -> dict:
    """List all RDS instances with engine, status, encryption, and multi-AZ status."""
    rds = _client("rds", region)
    resp = await _run(rds.describe_db_instances)
    return {
        "instances": [
            {
                "id":           i["DBInstanceIdentifier"],
                "engine":       f"{i['Engine']} {i.get('EngineVersion', '')}",
                "class":        i["DBInstanceClass"],
                "status":       i["DBInstanceStatus"],
                "endpoint":     i.get("Endpoint", {}).get("Address"),
                "port":         i.get("Endpoint", {}).get("Port"),
                "multi_az":     i.get("MultiAZ"),
                "encrypted":    i.get("StorageEncrypted"),
                "backup_days":  i.get("BackupRetentionPeriod"),
                "storage_gb":   i.get("AllocatedStorage"),
                "risk_flags":   [
                    "NOT encrypted" if not i.get("StorageEncrypted") else None,
                    "Single-AZ — no automatic failover" if not i.get("MultiAZ") else None,
                    "No automated backup" if i.get("BackupRetentionPeriod", 0) == 0 else None,
                ],
            }
            for i in resp["DBInstances"]
        ]
    }


@tool
async def rds_list_clusters(region: str = "us-east-1") -> dict:
    """List all RDS Aurora clusters."""
    rds = _client("rds", region)
    resp = await _run(rds.describe_db_clusters)
    return {
        "clusters": [
            {
                "id":       c["DBClusterIdentifier"],
                "engine":   c["Engine"],
                "status":   c["Status"],
                "endpoint": c.get("Endpoint"),
                "members":  len(c.get("DBClusterMembers", [])),
                "encrypted": c.get("StorageEncrypted"),
            }
            for c in resp["DBClusters"]
        ]
    }


@tool
async def rds_list_snapshots(region: str = "us-east-1") -> dict:
    """List RDS manual snapshots."""
    rds = _client("rds", region)
    resp = await _run(rds.describe_db_snapshots, SnapshotType="manual")
    return {
        "snapshots": [
            {
                "id":         s["DBSnapshotIdentifier"],
                "instance":   s["DBInstanceIdentifier"],
                "status":     s["Status"],
                "created":    str(s.get("SnapshotCreateTime")),
                "size_gb":    s.get("AllocatedStorage"),
            }
            for s in resp["DBSnapshots"]
        ]
    }


# ── EKS ────────────────────────────────────────────────────────────────────────

@tool
async def eks_list_clusters(region: str = "us-east-1") -> dict:
    """List all EKS Kubernetes clusters."""
    eks = _client("eks", region)
    resp = await _run(eks.list_clusters)
    return {"clusters": resp["clusters"]}


@tool
async def eks_describe_cluster(cluster_name: str, region: str = "us-east-1") -> dict:
    """Get details of an EKS cluster: version, status, endpoint, logging."""
    eks = _client("eks", region)
    resp = await _run(eks.describe_cluster, name=cluster_name)
    c = resp["cluster"]
    return {
        "name":     c["name"],
        "status":   c["status"],
        "version":  c["version"],
        "endpoint": c.get("endpoint"),
        "role_arn": c.get("roleArn"),
        "logging":  c.get("logging"),
        "tags":     c.get("tags", {}),
    }


@tool
async def eks_list_nodegroups(cluster_name: str, region: str = "us-east-1") -> dict:
    """List node groups in an EKS cluster."""
    eks = _client("eks", region)
    resp = await _run(eks.list_nodegroups, clusterName=cluster_name)
    return {"nodegroups": resp["nodegroups"]}


# ── ECS ────────────────────────────────────────────────────────────────────────

@tool
async def ecs_list_clusters(region: str = "us-east-1") -> dict:
    """List all ECS clusters."""
    ecs = _client("ecs", region)
    resp = await _run(ecs.list_clusters)
    arns = resp["clusterArns"]
    if not arns:
        return {"clusters": []}
    details = await _run(ecs.describe_clusters, clusters=arns)
    return {
        "clusters": [
            {
                "name":                 c["clusterName"],
                "status":               c["status"],
                "running_tasks":        c["runningTasksCount"],
                "pending_tasks":        c["pendingTasksCount"],
                "registered_instances": c["registeredContainerInstancesCount"],
            }
            for c in details["clusters"]
        ]
    }


@tool
async def ecs_list_services(cluster: str, region: str = "us-east-1") -> dict:
    """List services in an ECS cluster."""
    ecs = _client("ecs", region)
    resp = await _run(ecs.list_services, cluster=cluster)
    arns = resp["serviceArns"]
    if not arns:
        return {"services": []}
    details = await _run(ecs.describe_services, cluster=cluster, services=arns)
    return {
        "services": [
            {
                "name":            s["serviceName"],
                "status":          s["status"],
                "desired":         s["desiredCount"],
                "running":         s["runningCount"],
                "task_definition": s["taskDefinition"].split("/")[-1],
            }
            for s in details["services"]
        ]
    }


@tool
async def ecs_list_tasks(cluster: str, region: str = "us-east-1") -> dict:
    """List running tasks in an ECS cluster."""
    ecs = _client("ecs", region)
    resp = await _run(ecs.list_tasks, cluster=cluster)
    arns = resp["taskArns"]
    if not arns:
        return {"tasks": []}
    details = await _run(ecs.describe_tasks, cluster=cluster, tasks=arns)
    return {
        "tasks": [
            {
                "task_id": t["taskArn"].split("/")[-1],
                "status":  t["lastStatus"],
                "desired": t["desiredStatus"],
                "cpu":     t.get("cpu"),
                "memory":  t.get("memory"),
            }
            for t in details["tasks"]
        ]
    }


# ── CloudWatch ─────────────────────────────────────────────────────────────────

@tool
async def cloudwatch_list_alarms(region: str = "us-east-1") -> dict:
    """List all CloudWatch alarms with their current states."""
    cw = _client("cloudwatch", region)
    resp = await _run(cw.describe_alarms)
    alarms = [
        {
            "name":       a["AlarmName"],
            "state":      a["StateValue"],
            "metric":     a["MetricName"],
            "namespace":  a["Namespace"],
            "threshold":  a.get("Threshold"),
            "comparison": a.get("ComparisonOperator"),
        }
        for a in resp["MetricAlarms"]
    ]
    in_alarm = [a for a in alarms if a["state"] == "ALARM"]
    return {
        "alarms": alarms,
        "in_alarm_count": len(in_alarm),
        "in_alarm": in_alarm,
    }


@tool
async def cloudwatch_get_metric(
    namespace: str, metric_name: str,
    dimensions: list = [], hours: int = 1, region: str = "us-east-1",
) -> dict:
    """Get CloudWatch metric statistics. dimensions: [{'Name': 'InstanceId', 'Value': 'i-xxx'}]"""
    import datetime
    cw = _client("cloudwatch", region)
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(hours=hours)
    resp = await _run(
        cw.get_metric_statistics,
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=start,
        EndTime=end,
        Period=300,
        Statistics=["Average", "Maximum", "Minimum"],
    )
    datapoints = sorted(resp["Datapoints"], key=lambda x: x["Timestamp"])
    return {
        "metric":     metric_name,
        "namespace":  namespace,
        "datapoints": [
            {
                "time":    str(d["Timestamp"]),
                "average": d.get("Average"),
                "maximum": d.get("Maximum"),
                "minimum": d.get("Minimum"),
            }
            for d in datapoints
        ],
    }


@tool
async def cloudwatch_list_log_groups(region: str = "us-east-1") -> dict:
    """List CloudWatch Log Groups with retention policy."""
    cw = _client("logs", region)
    resp = await _run(cw.describe_log_groups)
    groups = [
        {
            "name":              g["logGroupName"],
            "retention_days":    g.get("retentionInDays", "Never expires"),
            "size_bytes":        g.get("storedBytes", 0),
            "size_gb":           round(g.get("storedBytes", 0) / 1e9, 3),
        }
        for g in resp["logGroups"]
    ]
    no_retention = [g for g in groups if g["retention_days"] == "Never expires"]
    return {
        "log_groups": groups,
        "no_retention_count": len(no_retention),
        "cost_warning": f"{len(no_retention)} log groups have no retention policy — data stored indefinitely" if no_retention else None,
    }


# ── SNS / SQS ─────────────────────────────────────────────────────────────────

@tool
async def sns_list_topics(region: str = "us-east-1") -> dict:
    """List all SNS topics."""
    sns = _client("sns", region)
    resp = await _run(sns.list_topics)
    return {"topics": [{"arn": t["TopicArn"]} for t in resp["Topics"]]}


@tool
async def sns_list_subscriptions(region: str = "us-east-1") -> dict:
    """List all SNS subscriptions."""
    sns = _client("sns", region)
    resp = await _run(sns.list_subscriptions)
    return {
        "subscriptions": [
            {
                "arn":       s["SubscriptionArn"],
                "topic":     s["TopicArn"],
                "protocol":  s["Protocol"],
                "endpoint":  s["Endpoint"],
            }
            for s in resp["Subscriptions"]
        ]
    }


@tool
async def sqs_list_queues(region: str = "us-east-1") -> dict:
    """List all SQS queues with approximate message counts."""
    sqs = _client("sqs", region)
    resp = await _run(sqs.list_queues)
    queues = []
    for url in resp.get("QueueUrls", [])[:20]:
        try:
            attrs = await _run(
                sqs.get_queue_attributes,
                QueueUrl=url,
                AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
            )
            a = attrs.get("Attributes", {})
            queues.append({
                "url":               url,
                "name":              url.split("/")[-1],
                "messages":          int(a.get("ApproximateNumberOfMessages", 0)),
                "messages_in_flight": int(a.get("ApproximateNumberOfMessagesNotVisible", 0)),
                "is_dlq":            "dlq" in url.lower() or "dead" in url.lower(),
            })
        except Exception:
            queues.append({"url": url, "name": url.split("/")[-1]})
    return {"queues": queues}


# ── DynamoDB ───────────────────────────────────────────────────────────────────

@tool
async def dynamodb_list_tables(region: str = "us-east-1") -> dict:
    """List all DynamoDB tables."""
    ddb = _client("dynamodb", region)
    resp = await _run(ddb.list_tables)
    return {"tables": resp["TableNames"], "count": len(resp["TableNames"])}


@tool
async def dynamodb_describe_table(table_name: str, region: str = "us-east-1") -> dict:
    """Get full details of a DynamoDB table including billing mode and capacity."""
    ddb = _client("dynamodb", region)
    resp = await _run(ddb.describe_table, TableName=table_name)
    t = resp["Table"]
    return {
        "name":             t["TableName"],
        "status":           t["TableStatus"],
        "billing_mode":     t.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED"),
        "item_count":       t.get("ItemCount"),
        "size_bytes":       t.get("TableSizeBytes"),
        "read_capacity":    t.get("ProvisionedThroughput", {}).get("ReadCapacityUnits"),
        "write_capacity":   t.get("ProvisionedThroughput", {}).get("WriteCapacityUnits"),
        "global_indexes":   [i["IndexName"] for i in t.get("GlobalSecondaryIndexes", [])],
        "encryption":       t.get("SSEDescription", {}).get("Status"),
    }


# ── CloudFormation ─────────────────────────────────────────────────────────────

@tool
async def cloudformation_list_stacks(region: str = "us-east-1") -> dict:
    """List CloudFormation stacks (excluding deleted)."""
    cf = _client("cloudformation", region)
    resp = await _run(cf.list_stacks, StackStatusFilter=[
        "CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE",
        "ROLLBACK_COMPLETE", "CREATE_FAILED", "UPDATE_FAILED",
    ])
    return {
        "stacks": [
            {
                "name":       s["StackName"],
                "status":     s["StackStatus"],
                "created":    str(s.get("CreationTime")),
                "updated":    str(s.get("LastUpdatedTime")),
            }
            for s in resp["StackSummaries"]
        ]
    }


@tool
async def cloudformation_describe_stack(stack_name: str, region: str = "us-east-1") -> dict:
    """Get full details of a CloudFormation stack including outputs."""
    cf = _client("cloudformation", region)
    resp = await _run(cf.describe_stacks, StackName=stack_name)
    if not resp["Stacks"]:
        return {"error": f"Stack {stack_name} not found"}
    s = resp["Stacks"][0]
    return {
        "name":        s["StackName"],
        "status":      s["StackStatus"],
        "description": s.get("Description"),
        "parameters":  [{"key": p["ParameterKey"], "value": p.get("ParameterValue")} for p in s.get("Parameters", [])],
        "outputs":     [{"key": o["OutputKey"], "value": o["OutputValue"]} for o in s.get("Outputs", [])],
        "tags":        {t["Key"]: t["Value"] for t in s.get("Tags", [])},
    }


# ── Secrets Manager ────────────────────────────────────────────────────────────

@tool
async def secretsmanager_list_secrets(region: str = "us-east-1") -> dict:
    """List all secrets in Secrets Manager (names only, no values)."""
    sm = _client("secretsmanager", region)
    resp = await _run(sm.list_secrets)
    import datetime
    now = datetime.datetime.utcnow()
    secrets = []
    for s in resp["SecretList"]:
        last_rotated = s.get("LastRotatedDate")
        age_days = (now - last_rotated.replace(tzinfo=None)).days if last_rotated else None
        secrets.append({
            "name":           s["Name"],
            "arn":            s["ARN"],
            "last_changed":   str(s.get("LastChangedDate")),
            "rotation_enabled": s.get("RotationEnabled", False),
            "last_rotated":   str(last_rotated) if last_rotated else "Never",
            "rotation_age_days": age_days,
            "risk":           "MEDIUM — rotation disabled" if not s.get("RotationEnabled") else "OK",
        })
    return {"secrets": secrets}


# ── Cost ───────────────────────────────────────────────────────────────────────

@tool
async def cost_get_monthly_cost(months: int = 3) -> dict:
    """Get AWS costs for the last N months from Cost Explorer."""
    import datetime
    from botocore.exceptions import ClientError

    ce = _client("ce", "us-east-1")
    end = datetime.date.today().replace(day=1)
    start = (end - datetime.timedelta(days=months * 31)).replace(day=1)

    try:
        resp = await _run(
            ce.get_cost_and_usage,
            TimePeriod={"Start": str(start), "End": str(end)},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("AccessDeniedException", "OptInRequired"):
            return {
                "error":          "Cost Explorer is not enabled or your IAM user lacks `ce:GetCostAndUsage` permission.",
                "fix_user_side":  "Activate AWS Cost Explorer in the billing console (it takes ~24h to populate data after first activation).",
                "console_url":    "https://console.aws.amazon.com/cost-management/home#/cost-explorer",
                "alternative":    "Without Cost Explorer, use get_ec2_pricing and get_rds_pricing for forward-looking estimates based on the AWS Price List API.",
                "iam_policy_needed": {
                    "Effect":   "Allow",
                    "Action":   ["ce:GetCostAndUsage", "ce:GetCostForecast", "ce:GetDimensionValues"],
                    "Resource": "*",
                },
            }
        return {"error": f"AWS error {code}: {e}"}
    except Exception as e:
        return {"error": str(e)}

    monthly = []
    for result in resp["ResultsByTime"]:
        period = result["TimePeriod"]["Start"]
        services = {
            g["Keys"][0]: round(float(g["Metrics"]["UnblendedCost"]["Amount"]), 2)
            for g in result["Groups"]
        }
        total = sum(services.values())
        top_services = sorted(services.items(), key=lambda x: x[1], reverse=True)[:5]
        monthly.append({
            "period":       period,
            "total_usd":    round(total, 2),
            "top_services": [{"service": k, "cost_usd": v} for k, v in top_services],
        })

    return {"monthly_costs": monthly}


# ── Route 53 ───────────────────────────────────────────────────────────────────

@tool
async def route53_list_hosted_zones() -> dict:
    """List all Route 53 hosted zones."""
    r53 = _client("route53")
    resp = await _run(r53.list_hosted_zones)
    return {
        "zones": [
            {
                "id":      z["Id"].split("/")[-1],
                "name":    z["Name"],
                "private": z["Config"]["PrivateZone"],
                "records": z["ResourceRecordSetCount"],
            }
            for z in resp["HostedZones"]
        ]
    }


@tool
async def route53_list_records(hosted_zone_id: str) -> dict:
    """List all DNS records in a Route 53 hosted zone."""
    r53 = _client("route53")
    resp = await _run(r53.list_resource_record_sets, HostedZoneId=hosted_zone_id)
    return {
        "records": [
            {
                "name":  r["Name"],
                "type":  r["Type"],
                "ttl":   r.get("TTL"),
                "value": [rv["Value"] for rv in r.get("ResourceRecords", [])],
            }
            for r in resp["ResourceRecordSets"]
        ]
    }


# ── ElastiCache ────────────────────────────────────────────────────────────────

@tool
async def elasticache_list_clusters(region: str = "us-east-1") -> dict:
    """List all ElastiCache clusters."""
    ec = _client("elasticache", region)
    resp = await _run(ec.describe_cache_clusters)
    return {
        "clusters": [
            {
                "id":           c["CacheClusterId"],
                "engine":       c["Engine"],
                "engine_version": c.get("EngineVersion"),
                "node_type":    c["CacheNodeType"],
                "status":       c["CacheClusterStatus"],
                "nodes":        c["NumCacheNodes"],
            }
            for c in resp["CacheClusters"]
        ]
    }


# ── Glue ───────────────────────────────────────────────────────────────────────

@tool
async def glue_list_databases(region: str = "us-east-1") -> dict:
    """List all Glue databases."""
    glue = _client("glue", region)
    resp = await _run(glue.get_databases)
    return {"databases": [{"name": d["Name"], "location": d.get("LocationUri")} for d in resp["DatabaseList"]]}


@tool
async def glue_list_jobs(region: str = "us-east-1") -> dict:
    """List all Glue ETL jobs."""
    glue = _client("glue", region)
    resp = await _run(glue.get_jobs)
    return {
        "jobs": [
            {
                "name":       j["Name"],
                "type":       j.get("Command", {}).get("Name"),
                "glue_version": j.get("GlueVersion"),
                "worker_type": j.get("WorkerType"),
                "num_workers": j.get("NumberOfWorkers"),
            }
            for j in resp["Jobs"]
        ]
    }


# ── Athena ─────────────────────────────────────────────────────────────────────

@tool
async def athena_list_workgroups(region: str = "us-east-1") -> dict:
    """List all Athena workgroups."""
    athena = _client("athena", region)
    resp = await _run(athena.list_work_groups)
    return {
        "workgroups": [
            {"name": w["Name"], "state": w["State"], "description": w.get("Description")}
            for w in resp["WorkGroups"]
        ]
    }


# ── ACM ────────────────────────────────────────────────────────────────────────

@tool
async def acm_list_certificates(region: str = "us-east-1") -> dict:
    """List ACM SSL/TLS certificates with expiry dates."""
    import datetime
    acm = _client("acm", region)
    resp = await _run(acm.list_certificates)
    now = datetime.datetime.utcnow()
    certs = []
    for c in resp["CertificateSummaryList"]:
        expiry = c.get("NotAfter")
        days_until_expiry = (expiry.replace(tzinfo=None) - now).days if expiry else None
        certs.append({
            "arn":               c["CertificateArn"],
            "domain":            c["DomainName"],
            "status":            c["Status"],
            "expires":           str(expiry) if expiry else None,
            "days_until_expiry": days_until_expiry,
            "risk":              f"CRITICAL — expires in {days_until_expiry} days" if days_until_expiry and days_until_expiry < 30 else "OK",
        })
    return {"certificates": certs}


# ── SSM ────────────────────────────────────────────────────────────────────────

@tool
async def ssm_list_parameters(region: str = "us-east-1") -> dict:
    """List SSM Parameter Store parameters (names only, no values)."""
    ssm = _client("ssm", region)
    resp = await _run(ssm.describe_parameters)
    return {
        "parameters": [
            {"name": p["Name"], "type": p["Type"], "last_modified": str(p.get("LastModifiedDate"))}
            for p in resp["Parameters"]
        ]
    }


@tool
async def ssm_list_managed_instances(region: str = "us-east-1") -> dict:
    """List EC2 instances managed by SSM (Systems Manager)."""
    ssm = _client("ssm", region)
    resp = await _run(ssm.describe_instance_information)
    return {
        "managed_instances": [
            {
                "instance_id":   i["InstanceId"],
                "ping_status":   i["PingStatus"],
                "platform":      i.get("PlatformType"),
                "agent_version": i.get("AgentVersion"),
                "last_ping":     str(i.get("LastPingDateTime")),
            }
            for i in resp["InstanceInformationList"]
        ]
    }


# ── Bedrock ────────────────────────────────────────────────────────────────────

@tool
async def bedrock_list_foundation_models(region: str = "us-east-1") -> dict:
    """List available Amazon Bedrock foundation models."""
    bedrock = _client("bedrock", region)
    resp = await _run(bedrock.list_foundation_models)
    models = [
        {
            "id":         m["modelId"],
            "name":       m.get("modelName"),
            "provider":   m.get("providerName"),
            "input_modalities":  m.get("inputModalities", []),
            "output_modalities": m.get("outputModalities", []),
            "inference_types":   m.get("inferenceTypesSupported", []),
        }
        for m in resp["modelSummaries"]
    ]
    return {"foundation_models": models, "count": len(models)}
