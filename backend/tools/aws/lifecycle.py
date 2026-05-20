"""
Lifecycle tools — stop, terminate, delete AWS resources safely.

All operations are DESTRUCTIVE → require human_review approval at runtime.

Tiers of risk:
  Tier 1 (reversible):    stop_instance, disable_trigger, disable_alarm
  Tier 2 (low-risk loss): release_eip, delete_unattached_volume, delete_old_snapshot
  Tier 3 (data loss):     terminate_instance, delete_rds, delete_function,
                          delete_stack, delete_glue_job, delete_glue_crawler

Each tool returns a structured dict with `success`, the action performed,
and `next_steps` for the user.
"""
from __future__ import annotations
import asyncio
import functools
from langchain_core.tools import tool
from core.console_urls import console_url


def _run(fn, *a, **kw):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, functools.partial(fn, *a, **kw))


def _c(svc: str, region: str = "us-east-1"):
    from core.session import get_client
    return get_client(svc, region)


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 1 — Reversible (stop, disable)
# ═══════════════════════════════════════════════════════════════════════════════

@tool
async def rds_stop_instance(db_identifier: str, region: str = "us-east-1") -> dict:
    """Stop an RDS instance (reversible).
    Stops compute billing; storage still bills. Auto-restarts after 7 days.
    """
    try:
        resp = await _run(_c("rds", region).stop_db_instance, DBInstanceIdentifier=db_identifier)
        return {
            "success": True, "db_id": db_identifier,
            "status":  resp.get("DBInstance", {}).get("DBInstanceStatus"),
            "savings_note": "Compute billing stops. Storage + backups continue. AWS auto-restarts after 7 days.",
            "console_url": console_url("rds_instance", region=region, name=db_identifier),
        }
    except Exception as e:
        return {"error": str(e), "db_id": db_identifier}


@tool
async def rds_start_instance(db_identifier: str, region: str = "us-east-1") -> dict:
    """Start a stopped RDS instance."""
    try:
        resp = await _run(_c("rds", region).start_db_instance, DBInstanceIdentifier=db_identifier)
        return {
            "success": True, "db_id": db_identifier,
            "status":  resp.get("DBInstance", {}).get("DBInstanceStatus"),
            "console_url": console_url("rds_instance", region=region, name=db_identifier),
        }
    except Exception as e:
        return {"error": str(e), "db_id": db_identifier}


@tool
async def glue_disable_trigger(trigger_name: str, region: str = "us-east-1") -> dict:
    """Disable (deactivate) a Glue trigger — its scheduled jobs stop running.
    Reversible: re-enable later. Config preserved.
    """
    try:
        await _run(_c("glue", region).stop_trigger, Name=trigger_name)
        return {
            "success": True, "trigger": trigger_name,
            "state":   "DEACTIVATED",
            "savings_note": "Scheduled jobs will no longer run. Trigger definition preserved. Re-enable with glue.start_trigger.",
        }
    except Exception as e:
        return {"error": str(e), "trigger": trigger_name}


@tool
async def cloudwatch_disable_alarm(alarm_name: str, region: str = "us-east-1") -> dict:
    """Disable a CloudWatch alarm (suppress notifications, keep config)."""
    try:
        await _run(_c("cloudwatch", region).disable_alarm_actions, AlarmNames=[alarm_name])
        return {"success": True, "alarm": alarm_name, "actions_enabled": False,
                "note": "Alarm still evaluates, just doesn't trigger SNS/auto-scaling actions."}
    except Exception as e:
        return {"error": str(e), "alarm": alarm_name}


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 2 — Low-risk waste removal
# ═══════════════════════════════════════════════════════════════════════════════

@tool
async def ec2_release_address(allocation_id: str, region: str = "us-east-1") -> dict:
    """Release an Elastic IP. Saves $3.60/month per unattached EIP.
    Cannot be undone — the IP returns to AWS pool.
    """
    try:
        await _run(_c("ec2", region).release_address, AllocationId=allocation_id)
        return {"success": True, "allocation_id": allocation_id,
                "saved_per_month_usd": 3.60,
                "note": "Released. A new EIP can be allocated for free (first 1 per running instance)."}
    except Exception as e:
        return {"error": str(e), "allocation_id": allocation_id}


@tool
async def ec2_delete_volume(volume_id: str, region: str = "us-east-1") -> dict:
    """Delete an EBS volume. MUST be in 'available' state (detached).
    Permanent — create a snapshot first if you might need the data.
    """
    try:
        # Safety check: refuse if volume is in-use
        info = await _run(_c("ec2", region).describe_volumes, VolumeIds=[volume_id])
        vol = info.get("Volumes", [{}])[0]
        if vol.get("State") != "available":
            return {"error": f"Volume {volume_id} is in state '{vol.get('State')}', not 'available'. Detach first."}
        size_gb = vol.get("Size", 0)
        vtype = vol.get("VolumeType", "gp3")
        rates = {"gp3": 0.08, "gp2": 0.10, "io2": 0.125, "io1": 0.125}
        monthly = size_gb * rates.get(vtype, 0.10)
        await _run(_c("ec2", region).delete_volume, VolumeId=volume_id)
        return {"success": True, "volume_id": volume_id, "size_gb": size_gb,
                "saved_per_month_usd": round(monthly, 2),
                "note": f"Volume deleted. Recoverable only if a snapshot exists."}
    except Exception as e:
        return {"error": str(e), "volume_id": volume_id}


@tool
async def ec2_delete_snapshot(snapshot_id: str, region: str = "us-east-1") -> dict:
    """Delete an EBS snapshot. Permanent — cannot be recovered."""
    try:
        info = await _run(_c("ec2", region).describe_snapshots, SnapshotIds=[snapshot_id])
        snap = info.get("Snapshots", [{}])[0]
        size = snap.get("VolumeSize", 0)
        await _run(_c("ec2", region).delete_snapshot, SnapshotId=snapshot_id)
        return {"success": True, "snapshot_id": snapshot_id, "size_gb": size,
                "saved_per_month_usd": round(size * 0.05, 2),
                "note": "Snapshot deleted. Cannot be recovered."}
    except Exception as e:
        return {"error": str(e), "snapshot_id": snapshot_id}


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 3 — Destructive (data loss risk)
# ═══════════════════════════════════════════════════════════════════════════════

@tool
async def ec2_terminate_instance(instance_id: str, region: str = "us-east-1") -> dict:
    """TERMINATE (permanently delete) an EC2 instance. Cannot be reversed.
    Instance store volumes are lost. EBS root volumes deleted unless DeleteOnTermination=false.
    """
    try:
        resp = await _run(_c("ec2", region).terminate_instances, InstanceIds=[instance_id])
        state = resp.get("TerminatingInstances", [{}])[0].get("CurrentState", {}).get("Name")
        return {"success": True, "instance_id": instance_id, "state": state,
                "note": "Terminated. Instance state PERMANENTLY gone. EBS root deleted unless DeleteOnTermination=false."}
    except Exception as e:
        return {"error": str(e), "instance_id": instance_id}


@tool
async def rds_delete_instance(
    db_identifier: str,
    skip_final_snapshot: bool = False,
    region: str = "us-east-1",
) -> dict:
    """Delete an RDS instance. If skip_final_snapshot=False (default), a final
    snapshot is taken before deletion (safer). With skip=True, data is lost permanently.
    """
    try:
        kwargs = {"DBInstanceIdentifier": db_identifier, "SkipFinalSnapshot": skip_final_snapshot}
        if not skip_final_snapshot:
            kwargs["FinalDBSnapshotIdentifier"] = f"{db_identifier}-final-{int(__import__('time').time())}"
            kwargs["DeleteAutomatedBackups"] = False
        else:
            kwargs["DeleteAutomatedBackups"] = True
        await _run(_c("rds", region).delete_db_instance, **kwargs)
        return {
            "success": True, "db_id": db_identifier,
            "final_snapshot_taken": not skip_final_snapshot,
            "note": ("Final snapshot taken — restorable via RDS console."
                     if not skip_final_snapshot else
                     "⚠ NO snapshot. Data LOST. Cannot recover."),
        }
    except Exception as e:
        return {"error": str(e), "db_id": db_identifier}


@tool
async def lambda_delete_function(function_name: str, region: str = "us-east-1") -> dict:
    """Delete a Lambda function. Permanent."""
    try:
        await _run(_c("lambda", region).delete_function, FunctionName=function_name)
        return {"success": True, "function": function_name, "note": "Function code + config deleted."}
    except Exception as e:
        return {"error": str(e), "function": function_name}


@tool
async def glue_delete_job(job_name: str, region: str = "us-east-1") -> dict:
    """Delete a Glue ETL job (script and config preserved in any S3 location used)."""
    try:
        await _run(_c("glue", region).delete_job, JobName=job_name)
        return {"success": True, "job": job_name,
                "note": "Job definition removed. Script in S3 remains if you uploaded one."}
    except Exception as e:
        return {"error": str(e), "job": job_name}


@tool
async def glue_delete_crawler(crawler_name: str, region: str = "us-east-1") -> dict:
    """Delete a Glue crawler. Catalog tables created by it remain."""
    try:
        await _run(_c("glue", region).delete_crawler, Name=crawler_name)
        return {"success": True, "crawler": crawler_name,
                "note": "Crawler removed. Catalog tables it created are preserved (use glue.delete_table to remove)."}
    except Exception as e:
        return {"error": str(e), "crawler": crawler_name}


@tool
async def glue_delete_trigger(trigger_name: str, region: str = "us-east-1") -> dict:
    """Delete a Glue trigger. Jobs themselves are not deleted, just the scheduling."""
    try:
        await _run(_c("glue", region).delete_trigger, Name=trigger_name)
        return {"success": True, "trigger": trigger_name,
                "note": "Trigger removed. Underlying jobs still exist but won't auto-run."}
    except Exception as e:
        return {"error": str(e), "trigger": trigger_name}


@tool
async def cloudformation_delete_stack(stack_name: str, region: str = "us-east-1") -> dict:
    """Delete an entire CloudFormation stack and ALL its resources (cascades).
    This is powerful — one call can remove a VPC + all subnets + NATs + etc.
    Resources with deletion protection are skipped.
    """
    try:
        await _run(_c("cloudformation", region).delete_stack, StackName=stack_name)
        return {
            "success": True, "stack": stack_name,
            "status": "DELETE_IN_PROGRESS",
            "console_url": f"https://{region}.console.aws.amazon.com/cloudformation/home?region={region}#/stacks",
            "note": ("Stack deletion started — may take 5-30 min. ALL resources in this stack will be removed. "
                     "Resources with deletion protection (RDS, S3, etc.) may block the delete."),
        }
    except Exception as e:
        return {"error": str(e), "stack": stack_name}


# ═══════════════════════════════════════════════════════════════════════════════
# Combined FinOps audit
# ═══════════════════════════════════════════════════════════════════════════════

@tool
async def cleanup_recommendations(region: str = "us-east-1") -> dict:
    """Comprehensive FinOps audit — combines EBS volumes, EIPs, snapshots, Glue
    triggers, idle RDS, idle EC2 into one ranked report by $$ saved per action.

    Returns a list of suggested actions with priority and savings estimate.
    The agent should walk through them with the user, one by one, for approval.
    """
    actions = []
    total_saved = 0.0

    # 1. EBS volumes detached
    try:
        ec2 = _c("ec2", region)
        vols = await _run(ec2.describe_volumes, Filters=[{"Name": "status", "Values": ["available"]}])
        rates = {"gp3": 0.08, "gp2": 0.10, "io2": 0.125, "io1": 0.125, "st1": 0.045, "sc1": 0.015}
        for v in vols.get("Volumes", []):
            size = v.get("Size", 0)
            rate = rates.get(v.get("VolumeType", "gp3"), 0.10)
            monthly = round(size * rate, 2)
            total_saved += monthly
            actions.append({
                "priority":         "T2-safe",
                "action":           "ec2_delete_volume",
                "target":           v.get("VolumeId"),
                "saved_monthly":    monthly,
                "saved_yearly":     round(monthly * 12, 2),
                "reason":           f"EBS {v.get('VolumeType')} {size}GB detached — billed but unused",
            })
    except Exception as e:
        actions.append({"error": f"EBS scan failed: {e}"})

    # 2. Elastic IPs unattached
    try:
        addrs = await _run(ec2.describe_addresses)
        for a in addrs.get("Addresses", []):
            if not a.get("AssociationId"):
                total_saved += 3.60
                actions.append({
                    "priority":      "T2-safe",
                    "action":        "ec2_release_address",
                    "target":        a.get("AllocationId"),
                    "saved_monthly": 3.60,
                    "saved_yearly":  43.20,
                    "reason":        f"Elastic IP {a.get('PublicIp')} unattached",
                })
    except Exception as e:
        actions.append({"error": f"EIP scan failed: {e}"})

    # 3. Glue triggers active (potential overshoot if not used)
    try:
        glue = _c("glue", region)
        trigs = await _run(glue.get_triggers)
        active = [t for t in trigs.get("Triggers", []) if t.get("State") == "ACTIVATED" and t.get("Type") == "SCHEDULED"]
        for t in active:
            actions.append({
                "priority":     "T1-reversible",
                "action":       "glue_disable_trigger",
                "target":       t.get("Name"),
                "saved_monthly": "Variable — depends on job DPU consumption",
                "reason":       f"Scheduled trigger '{t.get('Name')}' running {t.get('Schedule')} — verify still needed",
            })
    except Exception as e:
        actions.append({"error": f"Glue triggers scan failed: {e}"})

    # 4. Old EBS snapshots (>180 days)
    try:
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=180)
        snaps = await _run(ec2.describe_snapshots, OwnerIds=["self"])
        for s in snaps.get("Snapshots", []):
            start = s.get("StartTime")
            if start and start < cutoff:
                size = s.get("VolumeSize", 0)
                monthly = round(size * 0.05 * 0.4, 2)  # ~40% of provisioned (actual usually less)
                total_saved += monthly
                actions.append({
                    "priority":      "T2-safe",
                    "action":        "ec2_delete_snapshot",
                    "target":        s.get("SnapshotId"),
                    "saved_monthly": monthly,
                    "reason":        f"Snapshot {size}GB older than 180 days ({start.date().isoformat()})",
                })
    except Exception as e:
        actions.append({"error": f"Snapshot scan failed: {e}"})

    # Sort actions: T1-reversible first (safest), then T2-safe, ranked by savings within tier
    def _rank(a):
        tier = {"T1-reversible": 0, "T2-safe": 1, "T3-destructive": 2}.get(a.get("priority", ""), 3)
        savings = a.get("saved_monthly", 0)
        if not isinstance(savings, (int, float)):
            savings = 0
        return (tier, -savings)
    actions = [a for a in actions if "error" not in a]
    actions.sort(key=_rank)

    return {
        "region":               region,
        "total_actions":        len(actions),
        "estimated_savings_monthly": round(total_saved, 2),
        "estimated_savings_yearly":  round(total_saved * 12, 2),
        "actions":              actions,
        "recommendation": (
            f"Found {len(actions)} actionable items totaling ~${round(total_saved, 2)}/month "
            "in waste. Start with T1-reversible (Glue triggers, RDS stop), then T2-safe "
            "(EIPs, detached volumes, old snapshots). Each action will require your approval."
        ),
        "next_step_command": (
            "To process one by one, ask: 'Walk me through the cleanup_recommendations actions one "
            "at a time, asking me to confirm each before executing.'"
        ),
    }



# ═══════════════════════════════════════════════════════════════════════════════
# DEEP AUDIT — slower (uses CloudWatch metrics) but catches more
# ═══════════════════════════════════════════════════════════════════════════════

@tool
async def cleanup_recommendations_deep(region: str = "us-east-1") -> dict:
    """Extended FinOps audit using CloudWatch metrics. Slower (5-15s) but catches:
      - Idle NAT Gateways (low data processed)
      - Idle RDS (low CPU + connections)
      - Lambda never-invoked in 90+ days
      - Large CloudWatch log groups with infinite retention
      - Stale AMIs not used by launch templates
      - In addition to everything cleanup_recommendations finds.

    Use this when the user asks for "deep audit" or "complete FinOps review".
    For a quick scan, use cleanup_recommendations instead.
    """
    # Start with the quick audit
    quick = await cleanup_recommendations.ainvoke({"region": region})
    actions = quick.get("actions", [])
    total_saved = quick.get("estimated_savings_monthly", 0)

    # 1. NAT Gateways — flag those with low bytes processed
    try:
        from datetime import datetime, timedelta, timezone
        ec2 = _c("ec2", region)
        cw  = _c("cloudwatch", region)
        nats = await _run(ec2.describe_nat_gateways)
        end = datetime.utcnow()
        start = end - timedelta(days=7)
        for nat in nats.get("NatGateways", []):
            if nat.get("State") != "available": continue
            nat_id = nat.get("NatGatewayId")
            try:
                stats = await _run(
                    cw.get_metric_statistics,
                    Namespace="AWS/NATGateway",
                    MetricName="BytesOutToDestination",
                    Dimensions=[{"Name": "NatGatewayId", "Value": nat_id}],
                    StartTime=start, EndTime=end,
                    Period=86400, Statistics=["Sum"],
                )
                total_bytes = sum(d.get("Sum", 0) for d in stats.get("Datapoints", []))
                if total_bytes < 1_000_000 * 7:  # < 1 MB/day average over 7 days
                    actions.append({
                        "priority":      "T3-destructive",
                        "action":        "manual_delete_nat",
                        "target":        nat_id,
                        "saved_monthly": 32.85,
                        "saved_yearly":  394.20,
                        "reason":        f"NAT GW idle ({total_bytes/1024:.1f} KB processed in 7 days) — costing $32.85/mo",
                    })
                    total_saved += 32.85
            except Exception:
                continue
    except Exception as e:
        actions.append({"warning": f"NAT scan failed: {e}"})

    # 2. RDS idle — CPU < 5% AND connections = 0 over 14 days
    try:
        rds = _c("rds", region)
        end = datetime.utcnow()
        start = end - timedelta(days=14)
        instances = await _run(rds.describe_db_instances)
        for inst in instances.get("DBInstances", []):
            if inst.get("DBInstanceStatus") != "available": continue
            db_id = inst.get("DBInstanceIdentifier")
            try:
                cpu_stats = await _run(
                    cw.get_metric_statistics,
                    Namespace="AWS/RDS",
                    MetricName="CPUUtilization",
                    Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
                    StartTime=start, EndTime=end,
                    Period=86400, Statistics=["Average"],
                )
                conn_stats = await _run(
                    cw.get_metric_statistics,
                    Namespace="AWS/RDS",
                    MetricName="DatabaseConnections",
                    Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
                    StartTime=start, EndTime=end,
                    Period=86400, Statistics=["Maximum"],
                )
                avg_cpu  = sum(d.get("Average", 0) for d in cpu_stats.get("Datapoints", [])) / max(1, len(cpu_stats.get("Datapoints", [])))
                max_conn = max((d.get("Maximum", 0) for d in conn_stats.get("Datapoints", [])), default=0)
                if avg_cpu < 5 and max_conn == 0:
                    instance_class = inst.get("DBInstanceClass", "db.t3.micro")
                    # Rough monthly estimate based on common rates
                    monthly_estimate = {"db.t3.micro": 12, "db.t3.small": 24, "db.t3.medium": 48,
                                        "db.m5.large": 130, "db.m5.xlarge": 260, "db.r5.large": 165}.get(instance_class, 50)
                    total_saved += monthly_estimate
                    actions.append({
                        "priority":      "T1-reversible",
                        "action":        "rds_stop_instance",
                        "target":        db_id,
                        "saved_monthly": monthly_estimate,
                        "reason":        f"RDS idle 14 days (avg CPU {avg_cpu:.1f}%, 0 connections). Class {instance_class}",
                    })
            except Exception:
                continue
    except Exception as e:
        actions.append({"warning": f"RDS idle scan failed: {e}"})

    # 3. Lambda never-invoked or stale
    try:
        lam = _c("lambda", region)
        end = datetime.utcnow()
        start = end - timedelta(days=90)
        paginator = lam.get_paginator("list_functions")
        functions = []
        async def _gather_pages():
            for page in paginator.paginate(): functions.extend(page.get("Functions", []))
        await _run(_gather_pages)
        for f in functions:
            fname = f.get("FunctionName")
            try:
                stats = await _run(
                    cw.get_metric_statistics,
                    Namespace="AWS/Lambda",
                    MetricName="Invocations",
                    Dimensions=[{"Name": "FunctionName", "Value": fname}],
                    StartTime=start, EndTime=end,
                    Period=86400 * 7, Statistics=["Sum"],
                )
                total_inv = sum(d.get("Sum", 0) for d in stats.get("Datapoints", []))
                if total_inv == 0:
                    actions.append({
                        "priority":      "T2-safe",
                        "action":        "lambda_delete_function",
                        "target":        fname,
                        "saved_monthly": 0.01,  # tiny (just code storage)
                        "reason":        f"Lambda never invoked in 90 days — can likely be deleted",
                    })
            except Exception:
                continue
    except Exception as e:
        actions.append({"warning": f"Lambda scan failed: {e}"})

    # 4. CloudWatch log groups large + infinite retention
    try:
        logs = _c("logs", region)
        paginator = logs.get_paginator("describe_log_groups")
        groups = []
        async def _gather_logs():
            for page in paginator.paginate(): groups.extend(page.get("logGroups", []))
        await _run(_gather_logs)
        for g in groups:
            stored = g.get("storedBytes", 0)
            retention = g.get("retentionInDays")
            if retention is None and stored > 1_000_000_000:  # >1 GB and no retention
                gb = stored / 1024**3
                monthly = round(gb * 0.03, 2)  # $0.03/GB-month CW Logs
                total_saved += monthly
                actions.append({
                    "priority":      "T2-safe",
                    "action":        "logs_put_retention_policy",
                    "target":        g.get("logGroupName"),
                    "saved_monthly": monthly,
                    "reason":        f"Log group {gb:.1f} GB with no retention. Set retention to 30/90 days to bound growth.",
                })
    except Exception as e:
        actions.append({"warning": f"Logs scan failed: {e}"})

    # Re-sort actions
    def _rank(a):
        tier = {"T1-reversible": 0, "T2-safe": 1, "T3-destructive": 2}.get(a.get("priority", ""), 3)
        s = a.get("saved_monthly", 0)
        if not isinstance(s, (int, float)): s = 0
        return (tier, -s)
    valid_actions = [a for a in actions if "error" not in a and "warning" not in a]
    valid_actions.sort(key=_rank)
    warnings = [a for a in actions if "warning" in a]

    return {
        "region":               region,
        "audit_type":           "DEEP (CloudWatch metrics queried)",
        "total_actions":        len(valid_actions),
        "estimated_savings_monthly": round(total_saved, 2),
        "estimated_savings_yearly":  round(total_saved * 12, 2),
        "actions":              valid_actions,
        "warnings":             warnings,
        "recommendation": (
            f"Deep audit found {len(valid_actions)} actionable items totaling "
            f"~${round(total_saved, 2)}/month. T1 (reversible) → T2 (safe) → T3 (destructive)."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# v23 — Delete counterparts for each v13 provisioning tool
# All destructive → require human_review approval at runtime.
# ═══════════════════════════════════════════════════════════════════════════════

@tool
async def dynamodb_delete_table(table_name: str, region: str = "us-east-1",
                                 backup_first: bool = True) -> dict:
    """Delete a DynamoDB table.
    backup_first=True (default): creates an on-demand backup before deletion.
       Recoverable from the backup for 35 days.
    backup_first=False: deletes immediately, data lost permanently.
    """
    ddb = _c("dynamodb", region)
    try:
        result = {"table": table_name, "region": region}
        if backup_first:
            from datetime import datetime
            backup_name = f"{table_name}-final-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            try:
                backup = await _run(ddb.create_backup, TableName=table_name, BackupName=backup_name)
                result["backup_arn"]  = backup.get("BackupDetails", {}).get("BackupArn")
                result["backup_name"] = backup_name
            except Exception as e:
                return {"error": f"Backup failed before delete: {e}. Pass backup_first=False to skip."}
        resp = await _run(ddb.delete_table, TableName=table_name)
        result["success"] = True
        result["status"]  = resp.get("TableDescription", {}).get("TableStatus")
        result["note"]    = ("Final backup taken — restorable for 35 days."
                             if backup_first else "⚠ NO backup. Data permanently lost.")
        return result
    except Exception as e:
        return {"error": str(e), "table": table_name}


@tool
async def s3_delete_bucket(bucket_name: str, force_empty: bool = False,
                            region: str = "us-east-1") -> dict:
    """Delete an S3 bucket.
    force_empty=False (default): refuses if bucket has objects (safer).
    force_empty=True: deletes all objects + versions FIRST, then bucket.
                       PERMANENT — versioning history lost.
    """
    s3 = _c("s3", region)
    try:
        if force_empty:
            # Delete all objects + versions
            paginator = s3.get_paginator("list_object_versions")
            deleted_count = 0
            for page in paginator.paginate(Bucket=bucket_name):
                objects = []
                for v in page.get("Versions", []):
                    objects.append({"Key": v["Key"], "VersionId": v["VersionId"]})
                for m in page.get("DeleteMarkers", []):
                    objects.append({"Key": m["Key"], "VersionId": m["VersionId"]})
                if objects:
                    await _run(s3.delete_objects, Bucket=bucket_name,
                               Delete={"Objects": objects, "Quiet": True})
                    deleted_count += len(objects)
        await _run(s3.delete_bucket, Bucket=bucket_name)
        return {"success": True, "bucket": bucket_name,
                "objects_purged": deleted_count if force_empty else 0,
                "note": ("Bucket + ALL contents permanently deleted." if force_empty
                         else "Empty bucket deleted.")}
    except Exception as e:
        msg = str(e)
        hint = "Bucket not empty — pass force_empty=True to purge contents first" \
               if "BucketNotEmpty" in msg else None
        return {"error": msg, "hint": hint, "bucket": bucket_name}


@tool
async def iam_delete_user(username: str) -> dict:
    """Delete an IAM user. Removes all attached policies, access keys, login profile
    automatically. If user is in groups, removes them first. Permanent."""
    iam = _c("iam")
    try:
        # Remove from groups
        groups = await _run(iam.list_groups_for_user, UserName=username)
        for g in groups.get("Groups", []):
            await _run(iam.remove_user_from_group, GroupName=g["GroupName"], UserName=username)
        # Delete access keys
        keys = await _run(iam.list_access_keys, UserName=username)
        for k in keys.get("AccessKeyMetadata", []):
            await _run(iam.delete_access_key, UserName=username, AccessKeyId=k["AccessKeyId"])
        # Delete login profile (if exists)
        try: await _run(iam.delete_login_profile, UserName=username)
        except: pass
        # Detach policies
        policies = await _run(iam.list_attached_user_policies, UserName=username)
        for p in policies.get("AttachedPolicies", []):
            await _run(iam.detach_user_policy, UserName=username, PolicyArn=p["PolicyArn"])
        # Delete inline policies
        inline = await _run(iam.list_user_policies, UserName=username)
        for pn in inline.get("PolicyNames", []):
            await _run(iam.delete_user_policy, UserName=username, PolicyName=pn)
        # Now delete the user
        await _run(iam.delete_user, UserName=username)
        return {"success": True, "user": username,
                "note": "User + all attached resources deleted. Permanent."}
    except Exception as e:
        return {"error": str(e), "user": username}


@tool
async def sqs_delete_queue(queue_url: str, region: str = "us-east-1") -> dict:
    """Delete an SQS queue. Messages in flight are lost. Permanent."""
    try:
        await _run(_c("sqs", region).delete_queue, QueueUrl=queue_url)
        return {"success": True, "queue_url": queue_url,
                "note": "Queue deleted. Takes up to 60s to fully remove."}
    except Exception as e:
        return {"error": str(e), "queue_url": queue_url}


@tool
async def sns_delete_topic(topic_arn: str, region: str = "us-east-1") -> dict:
    """Delete an SNS topic. All subscriptions removed automatically."""
    try:
        await _run(_c("sns", region).delete_topic, TopicArn=topic_arn)
        return {"success": True, "topic_arn": topic_arn,
                "note": "Topic + all subscriptions deleted."}
    except Exception as e:
        return {"error": str(e), "topic_arn": topic_arn}


@tool
async def route53_delete_hosted_zone(hosted_zone_id: str) -> dict:
    """Delete a Route 53 hosted zone.
    Zone must have ONLY the default NS + SOA records (no custom records).
    """
    try:
        await _run(_c("route53").delete_hosted_zone, Id=hosted_zone_id)
        return {"success": True, "hosted_zone_id": hosted_zone_id,
                "note": "Zone deleted. Update domain registrar if it pointed here."}
    except Exception as e:
        msg = str(e)
        hint = ("Zone has custom records — delete them first via route53.change_resource_record_sets, "
                "then retry.") if "HostedZoneNotEmpty" in msg else None
        return {"error": msg, "hint": hint, "hosted_zone_id": hosted_zone_id}


@tool
async def elasticache_delete_cluster(cluster_id: str, region: str = "us-east-1",
                                       final_snapshot: bool = True) -> dict:
    """Delete an ElastiCache cluster.
    final_snapshot=True (Redis only): saves a final snapshot before delete.
    """
    ec = _c("elasticache", region)
    try:
        kwargs = {"CacheClusterId": cluster_id}
        if final_snapshot:
            from datetime import datetime
            kwargs["FinalSnapshotIdentifier"] = f"{cluster_id}-final-{datetime.now().strftime('%Y%m%d')}"
        await _run(ec.delete_cache_cluster, **kwargs)
        return {"success": True, "cluster_id": cluster_id,
                "final_snapshot": kwargs.get("FinalSnapshotIdentifier"),
                "note": "Cluster deletion started. Takes 5-10 min."}
    except Exception as e:
        return {"error": str(e), "cluster_id": cluster_id}


@tool
async def kms_schedule_key_deletion(key_id: str, pending_window_days: int = 30,
                                      region: str = "us-east-1") -> dict:
    """Schedule a KMS key for deletion (7-30 day pending window).
    During the pending window, you can CANCEL with kms.cancel_key_deletion.
    Deletion CANNOT be undone after the window expires.
    Encrypted data using this key becomes permanently unreadable.
    """
    if not 7 <= pending_window_days <= 30:
        return {"error": "pending_window_days must be 7-30 (AWS limit)"}
    try:
        resp = await _run(_c("kms", region).schedule_key_deletion,
                          KeyId=key_id, PendingWindowInDays=pending_window_days)
        return {"success": True, "key_id": key_id,
                "deletion_date": resp.get("DeletionDate").isoformat() if resp.get("DeletionDate") else None,
                "pending_window_days": pending_window_days,
                "note": (f"Key scheduled for deletion in {pending_window_days} days. "
                         "Cancel anytime before then with kms.cancel_key_deletion. "
                         "⚠ After deletion, data encrypted with this key is UNRECOVERABLE.")}
    except Exception as e:
        return {"error": str(e), "key_id": key_id}


@tool
async def secretsmanager_delete_secret(secret_id: str, recovery_window_days: int = 30,
                                          force_delete: bool = False,
                                          region: str = "us-east-1") -> dict:
    """Delete a Secrets Manager secret.
    recovery_window_days: 7-30 (default 30) — soft delete, restorable in window.
    force_delete=True: skip recovery window, immediate deletion. PERMANENT.
    """
    sm = _c("secretsmanager", region)
    try:
        kwargs = {"SecretId": secret_id}
        if force_delete:
            kwargs["ForceDeleteWithoutRecovery"] = True
        else:
            if not 7 <= recovery_window_days <= 30:
                return {"error": "recovery_window_days must be 7-30"}
            kwargs["RecoveryWindowInDays"] = recovery_window_days
        resp = await _run(sm.delete_secret, **kwargs)
        return {"success": True, "secret_id": secret_id,
                "deletion_date": resp.get("DeletionDate").isoformat() if resp.get("DeletionDate") else None,
                "recovery_window_days": None if force_delete else recovery_window_days,
                "note": ("⚠ Force-deleted — NOT recoverable." if force_delete else
                         f"Soft-deleted. Recoverable for {recovery_window_days} days via "
                         "secretsmanager.restore_secret.")}
    except Exception as e:
        return {"error": str(e), "secret_id": secret_id}


@tool
async def cognito_delete_user_pool(user_pool_id: str, region: str = "us-east-1") -> dict:
    """Delete a Cognito user pool. ALL users in the pool are deleted.
    App clients and identity providers tied to this pool are also removed.
    Permanent — no recovery.
    """
    try:
        await _run(_c("cognito-idp", region).delete_user_pool, UserPoolId=user_pool_id)
        return {"success": True, "pool_id": user_pool_id,
                "note": "Pool + all users + app clients deleted. Permanent."}
    except Exception as e:
        msg = str(e)
        hint = ("Pool has a custom domain — delete it first with "
                "cognito-idp.delete_user_pool_domain") if "domain" in msg.lower() else None
        return {"error": msg, "hint": hint, "pool_id": user_pool_id}


@tool
async def ec2_delete_security_group(group_id: str, region: str = "us-east-1") -> dict:
    """Delete an EC2 security group. Group must not be in use by any instance
    or referenced by another SG."""
    try:
        await _run(_c("ec2", region).delete_security_group, GroupId=group_id)
        return {"success": True, "group_id": group_id, "note": "Security group deleted."}
    except Exception as e:
        msg = str(e)
        hint = ("Security group is in use. Either detach it from all ENIs or "
                "remove references from other SGs first.") if "DependencyViolation" in msg else None
        return {"error": msg, "hint": hint, "group_id": group_id}



@tool
async def dynamodb_delete_backup(backup_arn: str, region: str = "us-east-1") -> dict:
    """Delete a DynamoDB backup permanently.

    backup_arn format: arn:aws:dynamodb:REGION:ACCOUNT:table/TABLE/backup/BACKUP_ID

    Use this AFTER dynamodb_delete_table to remove the final backup it took.
    Permanent — cannot be undone. After this, the data is unrecoverable.
    """
    try:
        resp = await _run(_c("dynamodb", region).delete_backup, BackupArn=backup_arn)
        return {"success": True,
                "backup_arn": backup_arn,
                "deletion_time": resp.get("BackupDescription", {})
                                     .get("BackupDetails", {})
                                     .get("BackupCreationDateTime", "").__str__(),
                "note": "Backup permanently deleted. Table data is now unrecoverable."}
    except Exception as e:
        return {"error": str(e), "backup_arn": backup_arn}


@tool
async def dynamodb_list_backups(table_name: str = None, region: str = "us-east-1") -> dict:
    """List DynamoDB backups in a region, optionally filtered by table name.
    Use to find a backup ARN before deletion."""
    try:
        kwargs = {}
        if table_name:
            kwargs["TableName"] = table_name
        resp = await _run(_c("dynamodb", region).list_backups, **kwargs)
        backups = []
        for b in resp.get("BackupSummaries", []):
            backups.append({
                "backup_name":  b.get("BackupName"),
                "backup_arn":   b.get("BackupArn"),
                "table_name":   b.get("TableName"),
                "created":      b.get("BackupCreationDateTime").isoformat() if b.get("BackupCreationDateTime") else None,
                "size_bytes":   b.get("BackupSizeBytes", 0),
                "status":       b.get("BackupStatus"),
                "type":         b.get("BackupType"),
            })
        return {"region": region, "table_filter": table_name,
                "total": len(backups), "backups": backups}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# v26 — Comprehensive delete coverage (22 additional tools)
# Orphan snapshot cleaners + missing service deletes
# ═══════════════════════════════════════════════════════════════════════════════

# ── Orphan snapshot cleaners (artifacts left by safety-default deletes) ────────

@tool
async def rds_delete_db_snapshot(snapshot_id: str, region: str = "us-east-1") -> dict:
    """Delete an RDS DB snapshot. Permanent. Use after rds_delete_instance to
    remove the final snapshot it took."""
    try:
        await _run(_c("rds", region).delete_db_snapshot, DBSnapshotIdentifier=snapshot_id)
        return {"success": True, "snapshot_id": snapshot_id,
                "note": "RDS snapshot permanently deleted. Data unrecoverable."}
    except Exception as e:
        return {"error": str(e), "snapshot_id": snapshot_id}


@tool
async def elasticache_delete_snapshot(snapshot_name: str, region: str = "us-east-1") -> dict:
    """Delete an ElastiCache snapshot. Permanent."""
    try:
        await _run(_c("elasticache", region).delete_snapshot, SnapshotName=snapshot_name)
        return {"success": True, "snapshot": snapshot_name,
                "note": "Redis snapshot permanently deleted."}
    except Exception as e:
        return {"error": str(e), "snapshot": snapshot_name}


@tool
async def backup_delete_recovery_point(backup_vault: str, recovery_point_arn: str,
                                         region: str = "us-east-1") -> dict:
    """Delete a recovery point from AWS Backup vault. Permanent."""
    try:
        await _run(_c("backup", region).delete_recovery_point,
                   BackupVaultName=backup_vault, RecoveryPointArn=recovery_point_arn)
        return {"success": True, "recovery_point": recovery_point_arn,
                "note": "Recovery point deleted from vault."}
    except Exception as e:
        return {"error": str(e), "recovery_point": recovery_point_arn}


# ── Storage / file systems ─────────────────────────────────────────────────────

@tool
async def efs_delete_file_system(file_system_id: str, region: str = "us-east-1") -> dict:
    """Delete an EFS file system. All mount targets must be deleted first.
    Refuses if any mount targets remain. Permanent — all files lost."""
    try:
        # Check for mount targets first
        mt = await _run(_c("efs", region).describe_mount_targets, FileSystemId=file_system_id)
        if mt.get("MountTargets"):
            return {"error": f"File system has {len(mt['MountTargets'])} mount target(s). Delete them first.",
                    "hint": "Use efs.delete_mount_target on each before retrying.",
                    "file_system_id": file_system_id}
        await _run(_c("efs", region).delete_file_system, FileSystemId=file_system_id)
        return {"success": True, "file_system_id": file_system_id,
                "note": "EFS file system deleted. All data permanently lost."}
    except Exception as e:
        return {"error": str(e), "file_system_id": file_system_id}


# ── Data warehousing ───────────────────────────────────────────────────────────

@tool
async def redshift_delete_cluster(cluster_id: str, skip_final_snapshot: bool = False,
                                    region: str = "us-east-1") -> dict:
    """Delete a Redshift cluster. Default: takes a final snapshot for restore.
    skip_final_snapshot=True deletes immediately — data permanently lost."""
    try:
        kwargs = {"ClusterIdentifier": cluster_id, "SkipFinalClusterSnapshot": skip_final_snapshot}
        if not skip_final_snapshot:
            from datetime import datetime
            kwargs["FinalClusterSnapshotIdentifier"] = f"{cluster_id}-final-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        await _run(_c("redshift", region).delete_cluster, **kwargs)
        return {"success": True, "cluster_id": cluster_id,
                "final_snapshot_taken": not skip_final_snapshot,
                "note": ("Final snapshot taken." if not skip_final_snapshot else "⚠ No snapshot. Data LOST.")}
    except Exception as e:
        return {"error": str(e), "cluster_id": cluster_id}


@tool
async def redshift_delete_snapshot(snapshot_id: str, region: str = "us-east-1") -> dict:
    """Delete a Redshift snapshot. Permanent."""
    try:
        await _run(_c("redshift", region).delete_cluster_snapshot, SnapshotIdentifier=snapshot_id)
        return {"success": True, "snapshot_id": snapshot_id, "note": "Redshift snapshot deleted."}
    except Exception as e:
        return {"error": str(e), "snapshot_id": snapshot_id}


@tool
async def athena_delete_workgroup(workgroup_name: str, recursive_delete: bool = False,
                                    region: str = "us-east-1") -> dict:
    """Delete an Athena workgroup. recursive_delete=True also removes named queries
    and query history. The 'primary' workgroup cannot be deleted."""
    try:
        await _run(_c("athena", region).delete_work_group,
                   WorkGroup=workgroup_name, RecursiveDeleteOption=recursive_delete)
        return {"success": True, "workgroup": workgroup_name,
                "recursive": recursive_delete,
                "note": "Workgroup deleted. Query history " +
                        ("also removed." if recursive_delete else "preserved (in account logs).")}
    except Exception as e:
        return {"error": str(e), "workgroup": workgroup_name}


# ── Compute / container orchestration ──────────────────────────────────────────

@tool
async def eks_delete_cluster(cluster_name: str, region: str = "us-east-1") -> dict:
    """Delete an EKS cluster. All node groups + Fargate profiles must be deleted first.
    Permanent — all workloads lost."""
    try:
        # Check node groups
        ngs = await _run(_c("eks", region).list_nodegroups, clusterName=cluster_name)
        if ngs.get("nodegroups"):
            return {"error": f"Cluster has {len(ngs['nodegroups'])} node group(s).",
                    "hint": "Use eks_delete_nodegroup on each first.",
                    "cluster": cluster_name, "remaining": ngs["nodegroups"]}
        await _run(_c("eks", region).delete_cluster, name=cluster_name)
        return {"success": True, "cluster": cluster_name,
                "note": "EKS cluster deletion started (5-15 min). Permanent."}
    except Exception as e:
        return {"error": str(e), "cluster": cluster_name}


@tool
async def eks_delete_nodegroup(cluster_name: str, nodegroup_name: str,
                                 region: str = "us-east-1") -> dict:
    """Delete an EKS managed node group. EC2 instances terminated, EBS volumes deleted."""
    try:
        await _run(_c("eks", region).delete_nodegroup,
                   clusterName=cluster_name, nodegroupName=nodegroup_name)
        return {"success": True, "cluster": cluster_name, "nodegroup": nodegroup_name,
                "note": "Node group deletion started. Underlying EC2 instances will terminate."}
    except Exception as e:
        return {"error": str(e), "nodegroup": nodegroup_name}


@tool
async def ecs_delete_service(cluster: str, service: str, force: bool = False,
                               region: str = "us-east-1") -> dict:
    """Delete an ECS service. Default: requires desired_count=0 first.
    force=True scales tasks to 0 + deletes in one call."""
    try:
        await _run(_c("ecs", region).delete_service,
                   cluster=cluster, service=service, force=force)
        return {"success": True, "cluster": cluster, "service": service,
                "note": "Service deletion started. Running tasks " +
                        ("force-stopped." if force else "must drain first.")}
    except Exception as e:
        return {"error": str(e), "service": service}


@tool
async def ecs_delete_cluster(cluster_name: str, region: str = "us-east-1") -> dict:
    """Delete an ECS cluster. All services must be deleted first."""
    try:
        await _run(_c("ecs", region).delete_cluster, cluster=cluster_name)
        return {"success": True, "cluster": cluster_name,
                "note": "ECS cluster deleted. Container instances + Fargate tasks no longer managed."}
    except Exception as e:
        msg = str(e)
        hint = "Delete all services first with ecs_delete_service" if "services" in msg.lower() else None
        return {"error": msg, "hint": hint, "cluster": cluster_name}


@tool
async def autoscaling_delete_group(asg_name: str, force_delete: bool = False,
                                     region: str = "us-east-1") -> dict:
    """Delete an Auto Scaling group. force_delete=True terminates instances + deletes.
    Default refuses if instances are running."""
    try:
        await _run(_c("autoscaling", region).delete_auto_scaling_group,
                   AutoScalingGroupName=asg_name, ForceDelete=force_delete)
        return {"success": True, "asg": asg_name, "force": force_delete,
                "note": "ASG deleted. " + ("Instances force-terminated." if force_delete
                                            else "All instances were already terminated.")}
    except Exception as e:
        return {"error": str(e), "asg": asg_name}


# ── Network ────────────────────────────────────────────────────────────────────

@tool
async def ec2_delete_nat_gateway(nat_gateway_id: str, region: str = "us-east-1") -> dict:
    """Delete a NAT gateway. Saves ~$32/month per NAT.
    Allocated Elastic IP is NOT released — use ec2_release_address separately."""
    try:
        await _run(_c("ec2", region).delete_nat_gateway, NatGatewayId=nat_gateway_id)
        return {"success": True, "nat_gateway_id": nat_gateway_id,
                "saved_monthly_usd": 32.85,
                "note": "NAT gateway deletion started (5 min). EIP not released — call ec2_release_address."}
    except Exception as e:
        return {"error": str(e), "nat_gateway_id": nat_gateway_id}


@tool
async def ec2_delete_internet_gateway(igw_id: str, vpc_id: str = None,
                                        region: str = "us-east-1") -> dict:
    """Delete an Internet Gateway. Must be detached from VPC first.
    If vpc_id provided, detaches automatically before delete."""
    try:
        ec2 = _c("ec2", region)
        if vpc_id:
            await _run(ec2.detach_internet_gateway, InternetGatewayId=igw_id, VpcId=vpc_id)
        await _run(ec2.delete_internet_gateway, InternetGatewayId=igw_id)
        return {"success": True, "igw_id": igw_id,
                "note": "IGW " + ("detached and " if vpc_id else "") + "deleted."}
    except Exception as e:
        return {"error": str(e), "igw_id": igw_id}


@tool
async def ec2_delete_subnet(subnet_id: str, region: str = "us-east-1") -> dict:
    """Delete a subnet. Refuses if ENIs / instances / NAT gateways are still in it."""
    try:
        await _run(_c("ec2", region).delete_subnet, SubnetId=subnet_id)
        return {"success": True, "subnet_id": subnet_id, "note": "Subnet deleted."}
    except Exception as e:
        return {"error": str(e), "subnet_id": subnet_id,
                "hint": "Remove all ENIs, instances, NAT GWs from the subnet first."}


@tool
async def ec2_delete_vpc(vpc_id: str, region: str = "us-east-1") -> dict:
    """Delete a VPC. ALL dependencies must be removed first: subnets, route tables
    (non-main), NAT gateways, IGWs, ENIs, peering connections, endpoints.
    Prefer cloudformation_delete_stack for VPCs created via CFN."""
    try:
        await _run(_c("ec2", region).delete_vpc, VpcId=vpc_id)
        return {"success": True, "vpc_id": vpc_id, "note": "VPC deleted."}
    except Exception as e:
        return {"error": str(e), "vpc_id": vpc_id,
                "hint": "VPC has dependencies. Use cloudformation_delete_stack for cascade delete, "
                        "or manually remove: subnets, route tables, NAT GWs, IGW, ENIs, endpoints."}


# ── Streaming / messaging ──────────────────────────────────────────────────────

@tool
async def kinesis_delete_stream(stream_name: str, enforce_consumer_deletion: bool = False,
                                 region: str = "us-east-1") -> dict:
    """Delete a Kinesis Data Stream. Permanent.
    enforce_consumer_deletion=True force-deletes registered consumers too."""
    try:
        await _run(_c("kinesis", region).delete_stream,
                   StreamName=stream_name, EnforceConsumerDeletion=enforce_consumer_deletion)
        return {"success": True, "stream": stream_name,
                "note": "Stream deletion started. Records lost permanently."}
    except Exception as e:
        return {"error": str(e), "stream": stream_name}


@tool
async def firehose_delete_delivery_stream(delivery_stream_name: str,
                                            region: str = "us-east-1") -> dict:
    """Delete a Kinesis Data Firehose delivery stream."""
    try:
        await _run(_c("firehose", region).delete_delivery_stream,
                   DeliveryStreamName=delivery_stream_name, AllowForceDelete=True)
        return {"success": True, "delivery_stream": delivery_stream_name,
                "note": "Firehose deleted. Buffered records may be lost."}
    except Exception as e:
        return {"error": str(e), "delivery_stream": delivery_stream_name}


@tool
async def msk_delete_cluster(cluster_arn: str, region: str = "us-east-1") -> dict:
    """Delete an MSK (Managed Kafka) cluster. Permanent.
    Takes 10-30 min. All topics and data lost."""
    try:
        await _run(_c("kafka", region).delete_cluster, ClusterArn=cluster_arn)
        return {"success": True, "cluster_arn": cluster_arn,
                "note": "MSK cluster deletion started (10-30 min). All data permanently lost."}
    except Exception as e:
        return {"error": str(e), "cluster_arn": cluster_arn}


@tool
async def events_delete_rule(rule_name: str, event_bus_name: str = "default",
                              force: bool = False, region: str = "us-east-1") -> dict:
    """Delete an EventBridge rule. force=True removes all targets first."""
    try:
        eb = _c("events", region)
        if force:
            # Remove all targets first
            targets = await _run(eb.list_targets_by_rule, Rule=rule_name, EventBusName=event_bus_name)
            ids = [t["Id"] for t in targets.get("Targets", [])]
            if ids:
                await _run(eb.remove_targets, Rule=rule_name, EventBusName=event_bus_name, Ids=ids)
        await _run(eb.delete_rule, Name=rule_name, EventBusName=event_bus_name, Force=force)
        return {"success": True, "rule": rule_name, "event_bus": event_bus_name,
                "note": "Rule deleted."}
    except Exception as e:
        return {"error": str(e), "rule": rule_name}


# ── Search & ML ────────────────────────────────────────────────────────────────

@tool
async def opensearch_delete_domain(domain_name: str, region: str = "us-east-1") -> dict:
    """Delete an OpenSearch (or Elasticsearch) domain. Permanent. Takes 15-30 min."""
    try:
        await _run(_c("opensearch", region).delete_domain, DomainName=domain_name)
        return {"success": True, "domain": domain_name,
                "note": "OpenSearch domain deletion started (15-30 min). All indices lost."}
    except Exception as e:
        return {"error": str(e), "domain": domain_name}


@tool
async def sagemaker_delete_endpoint(endpoint_name: str, region: str = "us-east-1") -> dict:
    """Delete a SageMaker endpoint. Stops billing immediately.
    The endpoint config and model artifacts in S3 are preserved."""
    try:
        await _run(_c("sagemaker", region).delete_endpoint, EndpointName=endpoint_name)
        return {"success": True, "endpoint": endpoint_name,
                "note": "Endpoint deleted. Billing stops. Model artifacts in S3 preserved."}
    except Exception as e:
        return {"error": str(e), "endpoint": endpoint_name}


# ── Misc service deletes ───────────────────────────────────────────────────────

@tool
async def stepfunctions_delete_state_machine(state_machine_arn: str,
                                                region: str = "us-east-1") -> dict:
    """Delete a Step Functions state machine. Running executions complete normally."""
    try:
        await _run(_c("stepfunctions", region).delete_state_machine, stateMachineArn=state_machine_arn)
        return {"success": True, "state_machine_arn": state_machine_arn,
                "note": "Deletion scheduled. Running executions complete first."}
    except Exception as e:
        return {"error": str(e), "state_machine_arn": state_machine_arn}


@tool
async def apigateway_delete_rest_api(api_id: str, region: str = "us-east-1") -> dict:
    """Delete an API Gateway REST API. All resources, methods, and stages lost."""
    try:
        await _run(_c("apigateway", region).delete_rest_api, restApiId=api_id)
        return {"success": True, "api_id": api_id,
                "note": "REST API + all stages deleted permanently."}
    except Exception as e:
        return {"error": str(e), "api_id": api_id}


@tool
async def cloudfront_delete_distribution(distribution_id: str, if_match: str = None) -> dict:
    """Delete a CloudFront distribution. Must be DISABLED first.
    if_match: ETag from get_distribution (required by API)."""
    try:
        cf = _c("cloudfront")
        if not if_match:
            info = await _run(cf.get_distribution, Id=distribution_id)
            if_match = info.get("ETag")
        await _run(cf.delete_distribution, Id=distribution_id, IfMatch=if_match)
        return {"success": True, "distribution_id": distribution_id,
                "note": "Distribution deletion started (15-90 min for global edge cleanup)."}
    except Exception as e:
        return {"error": str(e), "distribution_id": distribution_id,
                "hint": "Distribution must be disabled first (update_distribution with Enabled=False)."}
