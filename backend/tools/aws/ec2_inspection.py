"""
EC2 inspection tools — EBS volumes, snapshots, Elastic IPs.

These are commonly billed under "EC2-Other" in Cost Explorer and are
classic FinOps quick wins (unattached volumes, idle EIPs, etc.).
"""
from __future__ import annotations
import asyncio
import functools
from langchain_core.tools import tool


def _run(fn, *a, **kw):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, functools.partial(fn, *a, **kw))


def _ec2(region: str = "us-east-1"):
    from core.session import get_client
    return get_client("ec2", region)


@tool
async def ec2_list_volumes(state_filter: str = "all", region: str = "us-east-1") -> dict:
    """List EBS volumes.
    state_filter: 'all' | 'available' (detached, billed but unused) | 'in-use'
    Returns each volume's size, type, attachment state, and monthly cost estimate.
    """
    rates = {"gp3": 0.08, "gp2": 0.10, "io2": 0.125, "io1": 0.125,
             "st1": 0.045, "sc1": 0.015, "standard": 0.05}
    ec2 = _ec2(region)
    filters = []
    if state_filter == "available":
        filters.append({"Name": "status", "Values": ["available"]})
    elif state_filter == "in-use":
        filters.append({"Name": "status", "Values": ["in-use"]})
    try:
        resp = await _run(ec2.describe_volumes, Filters=filters) if filters else \
               await _run(ec2.describe_volumes)
        volumes = []
        wasted_monthly = 0.0
        for v in resp.get("Volumes", []):
            size_gb = v.get("Size", 0)
            vtype = v.get("VolumeType", "gp3")
            rate = rates.get(vtype, 0.10)
            monthly = round(size_gb * rate, 2)
            state = v.get("State")
            attached_to = [a.get("InstanceId") for a in v.get("Attachments", []) if a.get("InstanceId")]
            entry = {
                "volume_id":    v.get("VolumeId"),
                "size_gb":      size_gb,
                "type":         vtype,
                "state":        state,
                "encrypted":    v.get("Encrypted"),
                "attached_to":  attached_to,
                "created":      v.get("CreateTime").isoformat() if v.get("CreateTime") else None,
                "monthly_cost_usd": monthly,
                "tags":         {t["Key"]: t["Value"] for t in v.get("Tags", [])},
            }
            volumes.append(entry)
            if state == "available":  # detached but billed
                wasted_monthly += monthly
        volumes.sort(key=lambda x: -x["monthly_cost_usd"])
        return {
            "region":             region,
            "total_volumes":      len(volumes),
            "available_count":    sum(1 for v in volumes if v["state"] == "available"),
            "wasted_monthly_usd": round(wasted_monthly, 2),
            "volumes":            volumes[:50],
            "note": (
                f"⚠ {round(wasted_monthly, 2)} USD/month wasted on detached volumes — delete or attach them."
                if wasted_monthly > 0 else "All volumes are attached and serving workloads."
            ),
        }
    except Exception as e:
        return {"error": str(e), "region": region}


@tool
async def ec2_list_addresses(region: str = "us-east-1") -> dict:
    """List Elastic IPs.
    Unattached EIPs cost $3.60/month each ($0.005/hour × 730 hours).
    """
    ec2 = _ec2(region)
    try:
        resp = await _run(ec2.describe_addresses)
        addresses = []
        unattached_count = 0
        for a in resp.get("Addresses", []):
            attached = bool(a.get("AssociationId"))
            if not attached: unattached_count += 1
            addresses.append({
                "public_ip":      a.get("PublicIp"),
                "allocation_id":  a.get("AllocationId"),
                "attached":       attached,
                "instance_id":    a.get("InstanceId"),
                "network_interface": a.get("NetworkInterfaceId"),
                "domain":         a.get("Domain"),  # vpc | standard
                "monthly_cost_usd": 0 if attached else 3.60,
            })
        return {
            "region":             region,
            "total":              len(addresses),
            "unattached":         unattached_count,
            "wasted_monthly_usd": round(unattached_count * 3.60, 2),
            "addresses":          addresses,
            "note": (
                f"⚠ {unattached_count} unattached EIP(s) costing ${unattached_count * 3.60:.2f}/month — release them."
                if unattached_count > 0 else "All EIPs attached, no waste."
            ),
        }
    except Exception as e:
        return {"error": str(e), "region": region}


@tool
async def ec2_list_snapshots(owner: str = "self", region: str = "us-east-1") -> dict:
    """List EBS snapshots owned by the account.
    Each snapshot bills $0.05/GB-month for incremental data.
    """
    ec2 = _ec2(region)
    try:
        resp = await _run(ec2.describe_snapshots, OwnerIds=[owner])
        snaps = []
        total_gb = 0
        for s in resp.get("Snapshots", []):
            size = s.get("VolumeSize", 0)
            total_gb += size
            snaps.append({
                "snapshot_id":   s.get("SnapshotId"),
                "volume_id":     s.get("VolumeId"),
                "size_gb":       size,
                "started":       s.get("StartTime").isoformat() if s.get("StartTime") else None,
                "state":         s.get("State"),
                "encrypted":     s.get("Encrypted"),
                "description":   s.get("Description", "")[:80],
                "monthly_cost_estimate_usd": round(size * 0.05, 2),
            })
        snaps.sort(key=lambda x: x["started"] or "")
        return {
            "region":              region,
            "total_snapshots":     len(snaps),
            "total_provisioned_gb": total_gb,
            "max_monthly_cost":    round(total_gb * 0.05, 2),
            "note": (
                "Note: actual snapshot cost is based on changed-block storage, not "
                "provisioned size. Real bill is often 30-60% of this max estimate. "
                "Check Cost Explorer for actual."
            ),
            "snapshots":           snaps[:50],
        }
    except Exception as e:
        return {"error": str(e), "region": region}
