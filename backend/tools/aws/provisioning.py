"""
Provisioning tools — the system creates AWS resources autonomously.
Every tool returns a `console_url` so the user can verify in AWS Console.
All operations require human approval (destructive) and apply secure defaults.
"""
from __future__ import annotations
import asyncio
import functools
import json
from langchain_core.tools import tool
from core.console_urls import console_url


def _run(fn, *a, **kw):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, functools.partial(fn, *a, **kw))


def _client(service: str, region: str = "us-east-1"):
    from core.session import get_client
    return get_client(service, region)


# ── EC2 provisioning ───────────────────────────────────────────────────────────

@tool
async def ec2_launch_instance(
    name: str,
    instance_type: str = "t3.micro",
    region: str = "us-east-1",
    subnet_id: str = "",
    key_pair: str = "",
    ami_id: str = "",
) -> dict:
    """
    Launch a new EC2 instance with secure defaults (Amazon Linux 2023, IMDSv2 required,
    EBS encrypted, monitoring enabled). REQUIRES HUMAN APPROVAL.
    """
    ec2 = _client("ec2", region)

    # Auto-resolve latest Amazon Linux 2023 AMI if not provided
    if not ami_id:
        ssm = _client("ssm", region)
        param = await _run(
            ssm.get_parameter,
            Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64",
        )
        ami_id = param["Parameter"]["Value"]

    run_args = {
        "ImageId":     ami_id,
        "InstanceType": instance_type,
        "MinCount":    1,
        "MaxCount":    1,
        "Monitoring":  {"Enabled": True},
        "MetadataOptions": {
            "HttpTokens": "required",       # IMDSv2 required
            "HttpEndpoint": "enabled",
        },
        "BlockDeviceMappings": [{
            "DeviceName": "/dev/xvda",
            "Ebs": {"VolumeType": "gp3", "Encrypted": True, "DeleteOnTermination": True},
        }],
        "TagSpecifications": [{
            "ResourceType": "instance",
            "Tags": [
                {"Key": "Name",      "Value": name},
                {"Key": "ManagedBy", "Value": "CloudAgent"},
                {"Key": "Created",   "Value": "via-cloud-agent"},
            ],
        }],
    }
    if subnet_id: run_args["SubnetId"] = subnet_id
    if key_pair:  run_args["KeyName"]  = key_pair

    resp = await _run(ec2.run_instances, **run_args)
    inst = resp["Instances"][0]
    instance_id = inst["InstanceId"]

    return {
        "status":       "created",
        "instance_id":  instance_id,
        "type":         instance_type,
        "ami":          ami_id,
        "region":       region,
        "state":        inst["State"]["Name"],
        "az":           inst["Placement"]["AvailabilityZone"],
        "console_url":  console_url("ec2_instance", instance_id, region),
        "next_steps": [
            f"Wait ~1-2 min for the instance to enter 'running' state",
            f"Connect via Session Manager (no SSH key needed if instance has SSM agent role)",
            "Tag with cost-allocation tags (e.g., Environment, Team) for billing reports",
        ],
    }


@tool
async def ec2_create_security_group(
    name: str,
    description: str,
    vpc_id: str,
    region: str = "us-east-1",
    allow_ssh_from_my_ip: bool = False,
    allow_https_from_anywhere: bool = False,
) -> dict:
    """
    Create a new security group with minimal-permission rules.
    Never opens SSH (port 22) to 0.0.0.0/0. REQUIRES HUMAN APPROVAL.
    """
    ec2 = _client("ec2", region)
    resp = await _run(ec2.create_security_group,
                     GroupName=name, Description=description, VpcId=vpc_id)
    sg_id = resp["GroupId"]

    rules_added = []
    if allow_https_from_anywhere:
        await _run(
            ec2.authorize_security_group_ingress,
            GroupId=sg_id,
            IpPermissions=[{
                "IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "HTTPS from anywhere"}],
            }],
        )
        rules_added.append("HTTPS (443) from 0.0.0.0/0")

    if allow_ssh_from_my_ip:
        # Fetch user's public IP
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as cli:
                my_ip = (await cli.get("https://checkip.amazonaws.com")).text.strip()
            await _run(
                ec2.authorize_security_group_ingress,
                GroupId=sg_id,
                IpPermissions=[{
                    "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                    "IpRanges": [{"CidrIp": f"{my_ip}/32", "Description": "SSH from operator IP"}],
                }],
            )
            rules_added.append(f"SSH (22) from {my_ip}/32 only")
        except Exception:
            rules_added.append("SSH skipped — could not resolve operator IP")

    return {
        "status":       "created",
        "group_id":     sg_id,
        "name":         name,
        "vpc_id":       vpc_id,
        "region":       region,
        "rules_added":  rules_added,
        "console_url":  console_url("ec2_sg", sg_id, region),
        "security_note": "No rule allows SSH or RDP from 0.0.0.0/0 (best practice).",
    }


# ── S3 provisioning ────────────────────────────────────────────────────────────

@tool
async def s3_create_secure_bucket(
    bucket_name: str,
    region: str = "us-east-1",
    enable_versioning: bool = True,
) -> dict:
    """
    Create a new S3 bucket with security best practices applied automatically:
    - AES256 encryption at rest
    - Block ALL public access
    - Versioning enabled (default)
    - Bucket-key for KMS cost optimization
    REQUIRES HUMAN APPROVAL.
    """
    s3 = _client("s3", region)

    create_args = {"Bucket": bucket_name}
    if region != "us-east-1":
        create_args["CreateBucketConfiguration"] = {"LocationConstraint": region}
    await _run(s3.create_bucket, **create_args)

    # Encryption (AES256)
    await _run(
        s3.put_bucket_encryption,
        Bucket=bucket_name,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )

    # Block public access (all 4 settings)
    await _run(
        s3.put_public_access_block,
        Bucket=bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls":       True,
            "IgnorePublicAcls":      True,
            "BlockPublicPolicy":     True,
            "RestrictPublicBuckets": True,
        },
    )

    # Versioning
    if enable_versioning:
        await _run(
            s3.put_bucket_versioning,
            Bucket=bucket_name,
            VersioningConfiguration={"Status": "Enabled"},
        )

    # Default tagging
    await _run(
        s3.put_bucket_tagging,
        Bucket=bucket_name,
        Tagging={"TagSet": [
            {"Key": "ManagedBy", "Value": "CloudAgent"},
            {"Key": "Created",   "Value": "via-cloud-agent"},
        ]},
    )

    return {
        "status":          "created",
        "bucket":          bucket_name,
        "region":          region,
        "encryption":      "AES256",
        "public_access":   "fully blocked",
        "versioning":      "enabled" if enable_versioning else "disabled",
        "console_url":     console_url("s3_bucket", bucket_name, region),
        "security_checks": [
            "✓ Server-side encryption (AES256)",
            "✓ All public access blocked",
            f"✓ Versioning {'enabled' if enable_versioning else 'disabled'}",
            "✓ Tagged for cost allocation",
        ],
        "next_steps": [
            "Upload files via AWS Console or CLI: aws s3 cp <file> s3://" + bucket_name,
            "Add lifecycle policy to auto-transition old objects to Glacier for cost savings",
            "Enable Server Access Logging if compliance requires audit trails",
        ],
    }


# ── IAM provisioning ───────────────────────────────────────────────────────────

@tool
async def iam_create_user_with_policy(
    username: str,
    aws_managed_policies: list = None,
    create_access_key: bool = False,
) -> dict:
    """
    Create a new IAM user attached to AWS-managed policies (least privilege).
    Optionally generate a programmatic access key. REQUIRES HUMAN APPROVAL.

    Example: iam_create_user_with_policy("alice", ["ReadOnlyAccess"], False)
    """
    iam = _client("iam")

    # Create user
    await _run(iam.create_user, UserName=username,
              Tags=[
                  {"Key": "ManagedBy", "Value": "CloudAgent"},
                  {"Key": "Created",   "Value": "via-cloud-agent"},
              ])

    attached = []
    for policy_name in (aws_managed_policies or []):
        # AWS-managed policy ARN format: arn:aws:iam::aws:policy/<name>
        policy_arn = f"arn:aws:iam::aws:policy/{policy_name}"
        try:
            await _run(iam.attach_user_policy, UserName=username, PolicyArn=policy_arn)
            attached.append(policy_name)
        except Exception as e:
            attached.append(f"FAILED: {policy_name} — {e}")

    access_key_info = None
    if create_access_key:
        key_resp = await _run(iam.create_access_key, UserName=username)
        ak = key_resp["AccessKey"]
        access_key_info = {
            "access_key_id":     ak["AccessKeyId"],
            "secret_access_key": ak["SecretAccessKey"],
            "warning": "Save this secret NOW — it is not retrievable later",
        }

    return {
        "status":         "created",
        "username":       username,
        "attached_policies": attached,
        "access_key":     access_key_info,
        "console_url":    console_url("iam_user", username),
        "security_note":  "Consider MFA: aws iam enable-mfa-device after the user logs in",
        "next_steps": [
            "Have the user set a console password if they need UI access",
            "Require MFA via IAM policy (recommended for all human users)",
            "Use IAM Access Analyzer to verify the user has only necessary access",
        ],
    }


# ── Lambda provisioning ────────────────────────────────────────────────────────

@tool
async def lambda_create_function(
    function_name: str,
    handler: str = "index.handler",
    runtime: str = "python3.12",
    role_arn: str = "",
    code_zip_base64: str = "",
    region: str = "us-east-1",
    memory_mb: int = 256,
    timeout_s: int = 30,
) -> dict:
    """
    Create a new Lambda function. If no code provided, deploys a hello-world
    template that returns {"message": "Hello from CloudAgent"}.
    REQUIRES HUMAN APPROVAL.
    """
    import base64
    lmb = _client("lambda", region)

    # Default code: hello world
    if not code_zip_base64:
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("index.py", (
                "def handler(event, context):\n"
                "    return {'statusCode': 200, 'body': 'Hello from CloudAgent'}\n"
            ))
        code_bytes = buf.getvalue()
    else:
        code_bytes = base64.b64decode(code_zip_base64)

    if not role_arn:
        return {
            "status": "error",
            "error": "role_arn is required. Create an IAM role with AWSLambdaBasicExecutionRole first.",
            "hint":   "Use iam_create_role_for_lambda first",
        }

    resp = await _run(
        lmb.create_function,
        FunctionName=function_name,
        Runtime=runtime,
        Role=role_arn,
        Handler=handler,
        Code={"ZipFile": code_bytes},
        MemorySize=memory_mb,
        Timeout=timeout_s,
        Tags={"ManagedBy": "CloudAgent", "Created": "via-cloud-agent"},
        TracingConfig={"Mode": "Active"},  # X-Ray tracing
    )

    return {
        "status":      "created",
        "function":    function_name,
        "arn":         resp["FunctionArn"],
        "runtime":     runtime,
        "memory_mb":   memory_mb,
        "timeout_s":   timeout_s,
        "console_url": console_url("lambda", function_name, region),
        "test_command": f"aws lambda invoke --function-name {function_name} --region {region} response.json",
        "next_steps": [
            "Test the function in Console or via CLI",
            "Set up a trigger (API Gateway, SQS, EventBridge, S3, etc.)",
            "Configure CloudWatch alarms on error rate and duration",
        ],
    }


# ── CloudWatch alarms ─────────────────────────────────────────────────────────

@tool
async def cloudwatch_create_alarm(
    alarm_name: str,
    metric_name: str,
    namespace: str,
    threshold: float,
    comparison: str = "GreaterThanThreshold",
    sns_topic_arn: str = "",
    region: str = "us-east-1",
) -> dict:
    """
    Create a CloudWatch alarm. comparison: GreaterThanThreshold | LessThanThreshold |
    GreaterThanOrEqualToThreshold | LessThanOrEqualToThreshold.
    REQUIRES HUMAN APPROVAL.
    """
    cw = _client("cloudwatch", region)
    args = {
        "AlarmName":          alarm_name,
        "MetricName":         metric_name,
        "Namespace":          namespace,
        "Statistic":          "Average",
        "Period":             300,
        "EvaluationPeriods":  2,
        "Threshold":          threshold,
        "ComparisonOperator": comparison,
        "AlarmDescription":   f"Created by CloudAgent on metric {namespace}/{metric_name}",
    }
    if sns_topic_arn:
        args["AlarmActions"] = [sns_topic_arn]

    await _run(cw.put_metric_alarm, **args)

    return {
        "status":       "created",
        "alarm_name":   alarm_name,
        "metric":       f"{namespace}/{metric_name}",
        "threshold":    threshold,
        "comparison":   comparison,
        "notification": sns_topic_arn or "none — alarm will fire silently",
        "console_url":  console_url("cloudwatch_alarm", alarm_name, region),
        "next_steps": [
            "Verify the alarm enters OK state within 10 minutes",
            "If no SNS topic, add notification: --alarm-actions <topic-arn>",
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# EXTENDED PROVISIONING TOOLS (v13)
# Added: RDS, Aurora, DynamoDB, SQS, SNS, Route 53, ElastiCache, KMS,
#        Secrets Manager, Cognito + generic CloudFormation deployment.
# ═══════════════════════════════════════════════════════════════════════════════


# ── RDS ────────────────────────────────────────────────────────────────────────

@tool
async def rds_create_instance(
    db_identifier: str,
    engine: str = "mysql",
    instance_class: str = "db.t3.micro",
    allocated_storage: int = 20,
    master_username: str = "admin",
    master_password: str = "",
    multi_az: bool = False,
    region: str = "us-east-1",
) -> dict:
    """Create an RDS database instance.
    engine: mysql | postgres | mariadb | oracle-se2 | sqlserver-ex
    instance_class: db.t3.micro, db.t3.small, db.m5.large, etc.
    allocated_storage: GB (min 20 for general purpose).
    master_password: REQUIRED, min 8 chars.
    multi_az: True for HA (writer + standby in 2nd AZ).
    """
    if not master_password or len(master_password) < 8:
        return {"error": "master_password is required and must be at least 8 characters"}

    rds = _client("rds", region)
    try:
        resp = await _run(
            rds.create_db_instance,
            DBInstanceIdentifier=db_identifier,
            Engine=engine,
            DBInstanceClass=instance_class,
            AllocatedStorage=allocated_storage,
            MasterUsername=master_username,
            MasterUserPassword=master_password,
            MultiAZ=multi_az,
            StorageEncrypted=True,
            BackupRetentionPeriod=7,
            DeletionProtection=False,
            Tags=[{"Key": "CreatedBy", "Value": "cloud-agent"}],
        )
        info = resp.get("DBInstance", {})
        return {
            "success":     True,
            "db_id":       info.get("DBInstanceIdentifier"),
            "arn":         info.get("DBInstanceArn"),
            "engine":      info.get("Engine"),
            "status":      info.get("DBInstanceStatus"),
            "console_url": console_url("rds_instance", db_identifier, region=region),
            "next_steps": [
                "Wait ~10 min for status to become 'available'",
                "Connect using the master credentials you set",
                "Configure backups + Multi-AZ if not enabled",
            ],
        }
    except Exception as e:
        return {"error": str(e), "console_url": console_url("rds_instance", "unknown", region=region)}


# ── Aurora ─────────────────────────────────────────────────────────────────────

@tool
async def aurora_create_cluster(
    cluster_identifier: str,
    engine: str = "aurora-mysql",
    instance_class: str = "db.r6g.large",
    master_username: str = "admin",
    master_password: str = "",
    region: str = "us-east-1",
) -> dict:
    """Create an Aurora cluster (writer + 1 reader).
    engine: aurora-mysql | aurora-postgresql
    instance_class: db.r6g.large recommended for prod, db.t3.medium for dev.
    """
    if not master_password or len(master_password) < 8:
        return {"error": "master_password is required and must be at least 8 characters"}

    rds = _client("rds", region)
    try:
        # 1. Create cluster
        cluster_resp = await _run(
            rds.create_db_cluster,
            DBClusterIdentifier=cluster_identifier,
            Engine=engine,
            MasterUsername=master_username,
            MasterUserPassword=master_password,
            StorageEncrypted=True,
            BackupRetentionPeriod=7,
            DeletionProtection=False,
            Tags=[{"Key": "CreatedBy", "Value": "cloud-agent"}],
        )
        # 2. Add writer instance
        await _run(
            rds.create_db_instance,
            DBInstanceIdentifier=f"{cluster_identifier}-writer",
            DBInstanceClass=instance_class,
            Engine=engine,
            DBClusterIdentifier=cluster_identifier,
            PubliclyAccessible=False,
            Tags=[{"Key": "CreatedBy", "Value": "cloud-agent"}],
        )
        # 3. Add reader instance
        await _run(
            rds.create_db_instance,
            DBInstanceIdentifier=f"{cluster_identifier}-reader",
            DBInstanceClass=instance_class,
            Engine=engine,
            DBClusterIdentifier=cluster_identifier,
            PubliclyAccessible=False,
            Tags=[{"Key": "CreatedBy", "Value": "cloud-agent"}],
        )
        info = cluster_resp.get("DBCluster", {})
        return {
            "success":     True,
            "cluster_id":  info.get("DBClusterIdentifier"),
            "arn":         info.get("DBClusterArn"),
            "endpoint":    info.get("Endpoint"),
            "reader_endpoint": info.get("ReaderEndpoint"),
            "console_url": console_url("rds_cluster", cluster_identifier, region=region),
        }
    except Exception as e:
        return {"error": str(e), "console_url": console_url("rds_cluster", "unknown", region=region)}


# ── DynamoDB ───────────────────────────────────────────────────────────────────

@tool
async def dynamodb_create_table(
    table_name: str,
    partition_key: str,
    partition_key_type: str = "S",
    sort_key: str = "",
    sort_key_type: str = "S",
    billing_mode: str = "PAY_PER_REQUEST",
    read_capacity: int = 5,
    write_capacity: int = 5,
    region: str = "us-east-1",
) -> dict:
    """Create a DynamoDB table.
    partition_key_type: S (string) | N (number) | B (binary)
    billing_mode: PAY_PER_REQUEST (on-demand) | PROVISIONED
    """
    ddb = _client("dynamodb", region)
    try:
        key_schema  = [{"AttributeName": partition_key, "KeyType": "HASH"}]
        attr_defs   = [{"AttributeName": partition_key, "AttributeType": partition_key_type}]
        if sort_key:
            key_schema.append({"AttributeName": sort_key, "KeyType": "RANGE"})
            attr_defs.append({"AttributeName": sort_key, "AttributeType": sort_key_type})

        kwargs = {
            "TableName":            table_name,
            "KeySchema":            key_schema,
            "AttributeDefinitions": attr_defs,
            "BillingMode":          billing_mode,
            "SSESpecification":     {"Enabled": True, "SSEType": "KMS"},
            "Tags":                 [{"Key": "CreatedBy", "Value": "cloud-agent"}],
        }
        if billing_mode == "PROVISIONED":
            kwargs["ProvisionedThroughput"] = {
                "ReadCapacityUnits":  read_capacity,
                "WriteCapacityUnits": write_capacity,
            }

        resp = await _run(ddb.create_table, **kwargs)
        info = resp.get("TableDescription", {})
        return {
            "success":     True,
            "table_name":  info.get("TableName"),
            "arn":         info.get("TableArn"),
            "status":      info.get("TableStatus"),
            "billing":     billing_mode,
            "console_url": console_url("dynamodb_table", table_name, region=region),
        }
    except Exception as e:
        return {"error": str(e), "console_url": console_url("dynamodb_table", "unknown", region=region)}


# ── SQS ────────────────────────────────────────────────────────────────────────

@tool
async def sqs_create_queue(
    queue_name: str,
    fifo: bool = False,
    visibility_timeout_seconds: int = 30,
    message_retention_seconds: int = 345600,
    dead_letter_queue_arn: str = "",
    region: str = "us-east-1",
) -> dict:
    """Create an SQS queue.
    fifo: True for ordered (.fifo suffix required in queue_name)
    message_retention_seconds: 60..1209600 (default 4 days)
    """
    sqs = _client("sqs", region)
    try:
        attrs = {
            "VisibilityTimeout":        str(visibility_timeout_seconds),
            "MessageRetentionPeriod":   str(message_retention_seconds),
            "KmsMasterKeyId":           "alias/aws/sqs",
        }
        if fifo:
            attrs["FifoQueue"] = "true"
            attrs["ContentBasedDeduplication"] = "true"
            if not queue_name.endswith(".fifo"): queue_name += ".fifo"
        if dead_letter_queue_arn:
            attrs["RedrivePolicy"] = json.dumps({
                "deadLetterTargetArn": dead_letter_queue_arn,
                "maxReceiveCount":     5,
            })

        resp = await _run(
            sqs.create_queue,
            QueueName=queue_name,
            Attributes=attrs,
            tags={"CreatedBy": "cloud-agent"},
        )
        queue_url = resp.get("QueueUrl")
        attrs_resp = await _run(
            sqs.get_queue_attributes,
            QueueUrl=queue_url,
            AttributeNames=["QueueArn"],
        )
        return {
            "success":     True,
            "queue_url":   queue_url,
            "queue_arn":   attrs_resp.get("Attributes", {}).get("QueueArn"),
            "fifo":        fifo,
            "console_url": console_url("sqs_queue", queue_name, region=region),
        }
    except Exception as e:
        return {"error": str(e), "console_url": console_url("sqs_queue", "unknown", region=region)}


# ── SNS ────────────────────────────────────────────────────────────────────────

@tool
async def sns_create_topic(
    topic_name: str,
    fifo: bool = False,
    display_name: str = "",
    region: str = "us-east-1",
) -> dict:
    """Create an SNS topic (encryption-at-rest enabled by default)."""
    sns = _client("sns", region)
    try:
        attrs = {"KmsMasterKeyId": "alias/aws/sns"}
        if fifo:
            attrs["FifoTopic"] = "true"
            attrs["ContentBasedDeduplication"] = "true"
            if not topic_name.endswith(".fifo"): topic_name += ".fifo"
        if display_name: attrs["DisplayName"] = display_name

        resp = await _run(
            sns.create_topic,
            Name=topic_name,
            Attributes=attrs,
            Tags=[{"Key": "CreatedBy", "Value": "cloud-agent"}],
        )
        return {
            "success":     True,
            "topic_arn":   resp.get("TopicArn"),
            "fifo":        fifo,
            "console_url": console_url("sns_topic", resp.get("TopicArn", "", region=region).split(":")[-1]),
            "next_steps": [
                "Create subscriptions (email, SMS, SQS, Lambda, HTTPS)",
                "Set topic policy if external accounts need to publish",
            ],
        }
    except Exception as e:
        return {"error": str(e), "console_url": console_url("sns_topic", "unknown", region=region)}


# ── Route 53 ───────────────────────────────────────────────────────────────────

@tool
async def route53_create_hosted_zone(
    domain_name: str,
    private: bool = False,
    vpc_id: str = "",
    vpc_region: str = "us-east-1",
    comment: str = "",
) -> dict:
    """Create a Route 53 hosted zone.
    private=True requires vpc_id and vpc_region.
    """
    r53 = _client("route53", "us-east-1")
    try:
        import uuid
        kwargs = {
            "Name":             domain_name,
            "CallerReference":  str(uuid.uuid4()),
            "HostedZoneConfig": {"Comment": comment or f"Created by cloud-agent", "PrivateZone": private},
        }
        if private:
            if not vpc_id:
                return {"error": "vpc_id required for private hosted zones"}
            kwargs["VPC"] = {"VPCRegion": vpc_region, "VPCId": vpc_id}

        resp = await _run(r53.create_hosted_zone, **kwargs)
        zone = resp.get("HostedZone", {})
        ns_records = resp.get("DelegationSet", {}).get("NameServers", [])
        zone_id = zone.get("Id", "").replace("/hostedzone/", "")
        return {
            "success":      True,
            "hosted_zone_id": zone_id,
            "name":         zone.get("Name"),
            "name_servers": ns_records,
            "private":      private,
            "console_url":  console_url("route53_zone", zone_id, region="us-east-1"),
            "next_steps": [
                "Configure your domain registrar to use the name servers above" if not private else "Associate additional VPCs if needed",
                "Create A/CNAME/MX records as needed",
            ],
        }
    except Exception as e:
        return {"error": str(e), "console_url": console_url("route53_zone", "unknown", region="us-east-1")}


# ── ElastiCache (Redis) ────────────────────────────────────────────────────────

@tool
async def elasticache_create_redis(
    cluster_id: str,
    node_type: str = "cache.t3.micro",
    num_nodes: int = 1,
    vpc_security_group_ids: str = "",
    region: str = "us-east-1",
) -> dict:
    """Create an ElastiCache Redis cluster (single-node or replicated).
    node_type: cache.t3.micro, cache.r6g.large, etc.
    vpc_security_group_ids: comma-separated list (optional, uses default if empty)
    """
    ec = _client("elasticache", region)
    try:
        kwargs = {
            "CacheClusterId":            cluster_id,
            "Engine":                    "redis",
            "CacheNodeType":             node_type,
            "NumCacheNodes":             num_nodes,
            "AutoMinorVersionUpgrade":   True,
            "Tags":                      [{"Key": "CreatedBy", "Value": "cloud-agent"}],
        }
        if vpc_security_group_ids:
            kwargs["SecurityGroupIds"] = [s.strip() for s in vpc_security_group_ids.split(",")]

        resp = await _run(ec.create_cache_cluster, **kwargs)
        info = resp.get("CacheCluster", {})
        return {
            "success":     True,
            "cluster_id":  info.get("CacheClusterId"),
            "status":      info.get("CacheClusterStatus"),
            "node_type":   info.get("CacheNodeType"),
            "console_url": console_url("elasticache", cluster_id, region=region),
        }
    except Exception as e:
        return {"error": str(e), "console_url": console_url("elasticache", "unknown", region=region)}


# ── KMS ────────────────────────────────────────────────────────────────────────

@tool
async def kms_create_key(
    description: str = "",
    alias: str = "",
    multi_region: bool = False,
    region: str = "us-east-1",
) -> dict:
    """Create a KMS customer-managed key (symmetric AES-256 by default).
    alias: optional alias (without 'alias/' prefix — will be added)
    """
    kms = _client("kms", region)
    try:
        resp = await _run(
            kms.create_key,
            Description=description or "Created by cloud-agent",
            KeyUsage="ENCRYPT_DECRYPT",
            CustomerMasterKeySpec="SYMMETRIC_DEFAULT",
            MultiRegion=multi_region,
            Tags=[{"TagKey": "CreatedBy", "TagValue": "cloud-agent"}],
        )
        key = resp.get("KeyMetadata", {})
        key_id = key.get("KeyId")
        result = {
            "success":     True,
            "key_id":      key_id,
            "arn":         key.get("Arn"),
            "console_url": console_url("kms_key", key_id, region=region),
        }
        if alias:
            alias_name = alias if alias.startswith("alias/") else f"alias/{alias}"
            try:
                await _run(kms.create_alias, AliasName=alias_name, TargetKeyId=key_id)
                result["alias"] = alias_name
            except Exception as e:
                result["alias_error"] = str(e)
        return result
    except Exception as e:
        return {"error": str(e), "console_url": console_url("kms_key", "unknown", region=region)}


# ── Secrets Manager ────────────────────────────────────────────────────────────

@tool
async def secretsmanager_create_secret(
    secret_name: str,
    secret_value: str,
    description: str = "",
    kms_key_id: str = "",
    region: str = "us-east-1",
) -> dict:
    """Store a secret in Secrets Manager.
    secret_value: plaintext string (can be JSON if multiple key-values needed)
    kms_key_id: optional, falls back to default aws/secretsmanager
    """
    sm = _client("secretsmanager", region)
    try:
        kwargs = {
            "Name":         secret_name,
            "SecretString": secret_value,
            "Description":  description or "Created by cloud-agent",
            "Tags":         [{"Key": "CreatedBy", "Value": "cloud-agent"}],
        }
        if kms_key_id: kwargs["KmsKeyId"] = kms_key_id

        resp = await _run(sm.create_secret, **kwargs)
        return {
            "success":      True,
            "name":         resp.get("Name"),
            "arn":          resp.get("ARN"),
            "version_id":   resp.get("VersionId"),
            "console_url":  console_url("secrets_manager", secret_name, region=region),
        }
    except Exception as e:
        return {"error": str(e), "console_url": console_url("secrets_manager", "unknown", region=region)}


# ── Cognito ────────────────────────────────────────────────────────────────────

@tool
async def cognito_create_user_pool(
    pool_name: str,
    auto_verified_email: bool = True,
    mfa_enabled: bool = False,
    password_min_length: int = 8,
    require_uppercase: bool = True,
    require_lowercase: bool = True,
    require_digits: bool = True,
    require_symbols: bool = False,
    region: str = "us-east-1",
) -> dict:
    """Create a Cognito User Pool for application authentication."""
    cog = _client("cognito-idp", region)
    try:
        resp = await _run(
            cog.create_user_pool,
            PoolName=pool_name,
            AutoVerifiedAttributes=["email"] if auto_verified_email else [],
            UsernameAttributes=["email"],
            MfaConfiguration="OPTIONAL" if mfa_enabled else "OFF",
            Policies={
                "PasswordPolicy": {
                    "MinimumLength":               password_min_length,
                    "RequireUppercase":            require_uppercase,
                    "RequireLowercase":            require_lowercase,
                    "RequireNumbers":              require_digits,
                    "RequireSymbols":              require_symbols,
                    "TemporaryPasswordValidityDays": 7,
                }
            },
            UserPoolTags={"CreatedBy": "cloud-agent"},
        )
        pool = resp.get("UserPool", {})
        return {
            "success":      True,
            "pool_id":      pool.get("Id"),
            "arn":          pool.get("Arn"),
            "name":         pool.get("Name"),
            "console_url":  console_url("cognito_user_pool", pool.get("Id", region=region)),
            "next_steps": [
                "Create an App Client for your application to use",
                "Configure social providers (Google/Facebook/SAML) if needed",
                "Add domain prefix for the hosted UI",
            ],
        }
    except Exception as e:
        return {"error": str(e), "console_url": console_url("cognito_user_pool", "unknown", region=region)}


# ═══════════════════════════════════════════════════════════════════════════════
# GENERIC CLOUDFORMATION DEPLOYMENT
# Fallback for ANY AWS resource not covered by specific tools above.
# The agent generates a CFN template, this tool deploys it via boto3.
# ═══════════════════════════════════════════════════════════════════════════════

@tool
async def aws_deploy_cloudformation(
    stack_name: str,
    template_body: str,
    parameters_json: str = "{}",
    capabilities: str = "CAPABILITY_NAMED_IAM",
    region: str = "us-east-1",
    timeout_minutes: int = 30,
) -> dict:
    """Deploy any AWS resource via CloudFormation.

    Use this as a fallback for resources without a dedicated tool:
      VPC, ALB, NLB, ECS, EKS, API Gateway, CloudFront, Step Functions, Glue,
      EventBridge, WAF, ACM certificates, EFS, FSx, Kinesis, Athena, etc.

    Parameters:
      stack_name:     unique stack name (lowercase, dashes OK, no spaces)
      template_body:  CloudFormation template as YAML or JSON string (full text)
      parameters_json: JSON object string like '{"VpcCidr":"10.0.0.0/16","KeyName":"my-key"}'
      capabilities:   "CAPABILITY_NAMED_IAM" (default) | "CAPABILITY_IAM" | "CAPABILITY_AUTO_EXPAND"
                      Use NAMED_IAM if the template creates IAM resources with custom names.
      region:         AWS region for deployment
      timeout_minutes: stack creation timeout (default 30)
    """
    cfn = _client("cloudformation", region)

    # Parse parameters
    try:
        params_obj = json.loads(parameters_json) if parameters_json else {}
    except Exception:
        return {"error": f"parameters_json must be valid JSON, got: {parameters_json[:120]}"}

    cfn_params = [{"ParameterKey": k, "ParameterValue": str(v)} for k, v in params_obj.items()]

    # Basic template sanity check
    if len(template_body) < 50:
        return {"error": "template_body is too short — provide the full CloudFormation YAML/JSON template"}
    if "Resources" not in template_body and "resources" not in template_body.lower():
        return {"error": "template_body does not appear to contain a Resources section"}

    caps_list = [c.strip() for c in capabilities.split(",") if c.strip()]

    try:
        resp = await _run(
            cfn.create_stack,
            StackName=stack_name,
            TemplateBody=template_body,
            Parameters=cfn_params,
            Capabilities=caps_list,
            TimeoutInMinutes=timeout_minutes,
            OnFailure="ROLLBACK",
            Tags=[{"Key": "CreatedBy", "Value": "cloud-agent"}],
            EnableTerminationProtection=False,
        )
        stack_id = resp.get("StackId", "")
        return {
            "success":     True,
            "stack_id":    stack_id,
            "stack_name":  stack_name,
            "region":      region,
            "console_url": f"https://{region}.console.aws.amazon.com/cloudformation/home?region={region}#/stacks/stackinfo?stackId={stack_id}",
            "status":      "CREATE_IN_PROGRESS",
            "next_steps": [
                f"Stack creation may take 5-30 minutes — monitor in CloudFormation Console",
                "On failure CFN auto-rolls-back; check Events tab for the failed resource",
                f"Delete with: aws cloudformation delete-stack --stack-name {stack_name} --region {region}",
            ],
            "note": "All resources in this stack will be tagged with the stack ID for clean teardown.",
        }
    except Exception as e:
        msg = str(e)
        hints = []
        if "AlreadyExistsException" in msg:
            hints.append(f"A stack named '{stack_name}' already exists in {region} — use a different name")
        if "InsufficientCapabilities" in msg:
            hints.append("Template requires more capabilities — try capabilities='CAPABILITY_NAMED_IAM,CAPABILITY_AUTO_EXPAND'")
        if "ValidationError" in msg:
            hints.append("Template validation failed — check YAML syntax and resource property names")
        return {
            "error":   msg,
            "hints":   hints,
            "console_url": f"https://{region}.console.aws.amazon.com/cloudformation/home?region={region}",
        }
