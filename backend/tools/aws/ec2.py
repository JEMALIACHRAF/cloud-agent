"""AWS EC2 tools — fixed asyncio + retry config."""
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
async def ec2_list_instances(region: str = "us-east-1", state: str = "") -> dict:
    """List EC2 instances. Optionally filter by state: running|stopped|terminated."""
    ec2 = _ec2(region)
    filters = [{"Name": "instance-state-name", "Values": [state]}] if state else []
    resp = await _run(ec2.describe_instances, Filters=filters)
    instances = []
    for r in resp["Reservations"]:
        for i in r["Instances"]:
            instances.append({
                "id":          i["InstanceId"],
                "type":        i["InstanceType"],
                "state":       i["State"]["Name"],
                "public_ip":   i.get("PublicIpAddress"),
                "private_ip":  i.get("PrivateIpAddress"),
                "name":        next((t["Value"] for t in i.get("Tags", []) if t["Key"] == "Name"), ""),
                "launch_time": str(i.get("LaunchTime", "")),
                "az":          i.get("Placement", {}).get("AvailabilityZone", ""),
                "has_tags":    len(i.get("Tags", [])) > 0,
            })
    return {"instances": instances, "count": len(instances)}


@tool
async def ec2_start_instance(instance_id: str, region: str = "us-east-1") -> dict:
    """Start a stopped EC2 instance by instance ID."""
    ec2 = _ec2(region)
    resp = await _run(ec2.start_instances, InstanceIds=[instance_id])
    return {
        "started": instance_id,
        "previous_state": resp["StartingInstances"][0]["PreviousState"]["Name"],
    }


@tool
async def ec2_stop_instance(instance_id: str, region: str = "us-east-1") -> dict:
    """Stop a running EC2 instance by instance ID. REQUIRES CONFIRMATION."""
    ec2 = _ec2(region)
    resp = await _run(ec2.stop_instances, InstanceIds=[instance_id])
    return {
        "stopped": instance_id,
        "previous_state": resp["StoppingInstances"][0]["PreviousState"]["Name"],
    }


@tool
async def ec2_reboot_instance(instance_id: str, region: str = "us-east-1") -> dict:
    """Reboot an EC2 instance."""
    ec2 = _ec2(region)
    await _run(ec2.reboot_instances, InstanceIds=[instance_id])
    return {"rebooted": instance_id}


@tool
async def ec2_describe_instance(instance_id: str, region: str = "us-east-1") -> dict:
    """Get full details of a specific EC2 instance."""
    ec2 = _ec2(region)
    resp = await _run(ec2.describe_instances, InstanceIds=[instance_id])
    if not resp["Reservations"]:
        return {"error": f"Instance {instance_id} not found"}
    i = resp["Reservations"][0]["Instances"][0]
    return {
        "id":              i["InstanceId"],
        "type":            i["InstanceType"],
        "state":           i["State"]["Name"],
        "ami":             i.get("ImageId"),
        "key_pair":        i.get("KeyName"),
        "public_ip":       i.get("PublicIpAddress"),
        "private_ip":      i.get("PrivateIpAddress"),
        "vpc_id":          i.get("VpcId"),
        "subnet_id":       i.get("SubnetId"),
        "security_groups": [sg["GroupId"] for sg in i.get("SecurityGroups", [])],
        "iam_profile":     i.get("IamInstanceProfile", {}).get("Arn"),
        "tags":            {t["Key"]: t["Value"] for t in i.get("Tags", [])},
        "launch_time":     str(i.get("LaunchTime", "")),
        "az":              i.get("Placement", {}).get("AvailabilityZone", ""),
        "ebs_optimized":   i.get("EbsOptimized"),
        "monitoring":      i.get("Monitoring", {}).get("State"),
    }


@tool
async def ec2_list_amis(region: str = "us-east-1", owner: str = "self") -> dict:
    """List AMIs owned by the account."""
    ec2 = _ec2(region)
    resp = await _run(ec2.describe_images, Owners=[owner])
    amis = [
        {
            "id":           i["ImageId"],
            "name":         i.get("Name", ""),
            "state":        i["State"],
            "created":      i.get("CreationDate", ""),
            "architecture": i.get("Architecture"),
        }
        for i in resp["Images"]
    ]
    amis.sort(key=lambda x: x["created"], reverse=True)
    return {"amis": amis[:20], "count": len(resp["Images"])}


@tool
async def ec2_list_security_groups(region: str = "us-east-1") -> dict:
    """List security groups with their inbound/outbound rules."""
    ec2 = _ec2(region)
    resp = await _run(ec2.describe_security_groups)
    groups = []
    for sg in resp["SecurityGroups"]:
        open_ports = []
        for rule in sg.get("IpPermissions", []):
            for ip in rule.get("IpRanges", []):
                if ip.get("CidrIp") == "0.0.0.0/0":
                    port = rule.get("FromPort", "all")
                    open_ports.append(str(port))
        groups.append({
            "id":          sg["GroupId"],
            "name":        sg["GroupName"],
            "vpc_id":      sg.get("VpcId"),
            "description": sg.get("Description"),
            "open_to_world": open_ports,
            "risk": "HIGH" if open_ports else "OK",
        })
    return {"security_groups": groups, "high_risk_count": sum(1 for g in groups if g["risk"] == "HIGH")}


@tool
async def ec2_describe_security_group(group_id: str, region: str = "us-east-1") -> dict:
    """Get full details of a security group including all rules."""
    ec2 = _ec2(region)
    resp = await _run(ec2.describe_security_groups, GroupIds=[group_id])
    if not resp["SecurityGroups"]:
        return {"error": f"Security group {group_id} not found"}
    sg = resp["SecurityGroups"][0]
    return {
        "id":          sg["GroupId"],
        "name":        sg["GroupName"],
        "vpc_id":      sg.get("VpcId"),
        "inbound":     sg.get("IpPermissions", []),
        "outbound":    sg.get("IpPermissionsEgress", []),
    }


@tool
async def ec2_list_vpcs(region: str = "us-east-1") -> dict:
    """List all VPCs with their CIDR blocks and tags."""
    ec2 = _ec2(region)
    resp = await _run(ec2.describe_vpcs)
    return {
        "vpcs": [
            {
                "id":       v["VpcId"],
                "cidr":     v["CidrBlock"],
                "default":  v["IsDefault"],
                "state":    v["State"],
                "name":     next((t["Value"] for t in v.get("Tags", []) if t["Key"] == "Name"), ""),
            }
            for v in resp["Vpcs"]
        ]
    }


@tool
async def ec2_list_subnets(region: str = "us-east-1") -> dict:
    """List all subnets with their VPC, AZ, and CIDR."""
    ec2 = _ec2(region)
    resp = await _run(ec2.describe_subnets)
    return {
        "subnets": [
            {
                "id":         s["SubnetId"],
                "vpc_id":     s["VpcId"],
                "cidr":       s["CidrBlock"],
                "az":         s["AvailabilityZone"],
                "public":     s["MapPublicIpOnLaunch"],
                "available_ips": s["AvailableIpAddressCount"],
                "name":       next((t["Value"] for t in s.get("Tags", []) if t["Key"] == "Name"), ""),
            }
            for s in resp["Subnets"]
        ]
    }


@tool
async def ec2_list_key_pairs(region: str = "us-east-1") -> dict:
    """List all EC2 key pairs."""
    ec2 = _ec2(region)
    resp = await _run(ec2.describe_key_pairs)
    return {"key_pairs": [{"name": k["KeyName"], "fingerprint": k["KeyFingerprint"]} for k in resp["KeyPairs"]]}


@tool
async def ec2_list_elastic_ips(region: str = "us-east-1") -> dict:
    """List all Elastic IPs — unassociated ones cost money."""
    ec2 = _ec2(region)
    resp = await _run(ec2.describe_addresses)
    addresses = [
        {
            "public_ip":     a["PublicIp"],
            "allocation_id": a.get("AllocationId"),
            "associated":    "InstanceId" in a or "NetworkInterfaceId" in a,
            "instance_id":   a.get("InstanceId"),
        }
        for a in resp["Addresses"]
    ]
    unassociated = [a for a in addresses if not a["associated"]]
    return {
        "addresses": addresses,
        "unassociated_count": len(unassociated),
        "cost_warning": f"{len(unassociated)} unassociated EIPs — each costs ~$3.60/month" if unassociated else None,
    }
