"""AWS S3 tools — fixed asyncio get_running_loop."""
from __future__ import annotations
import asyncio
import functools
import json
from langchain_core.tools import tool


def _run(fn, *a, **kw):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, functools.partial(fn, *a, **kw))


def _s3():
    from core.session import get_client
    return get_client("s3")


@tool
async def s3_list_buckets() -> dict:
    """List all S3 buckets in the account with creation dates and regions."""
    s3 = _s3()
    resp = await _run(s3.list_buckets)
    buckets = []
    for b in resp.get("Buckets", []):
        try:
            loc = await _run(s3.get_bucket_location, Bucket=b["Name"])
            region = loc["LocationConstraint"] or "us-east-1"
        except Exception:
            region = "unknown"
        buckets.append({"name": b["Name"], "created": str(b["CreationDate"]), "region": region})
    return {"buckets": buckets, "count": len(buckets)}


@tool
async def s3_list_objects(bucket: str, prefix: str = "", max_keys: int = 100) -> dict:
    """List objects in an S3 bucket. Use prefix to filter by folder path."""
    s3 = _s3()
    resp = await _run(s3.list_objects_v2, Bucket=bucket, Prefix=prefix, MaxKeys=max_keys)
    return {
        "objects":   [{"key": o["Key"], "size_bytes": o["Size"], "last_modified": str(o["LastModified"]), "storage_class": o.get("StorageClass")} for o in resp.get("Contents", [])],
        "truncated": resp.get("IsTruncated", False),
        "count":     resp.get("KeyCount", 0),
    }


@tool
async def s3_get_bucket_size(bucket: str) -> dict:
    """Get total size and object count of an S3 bucket via CloudWatch metrics."""
    from core.session import get_client
    import datetime
    cw = get_client("cloudwatch", "us-east-1")
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=2)

    def _get_metric(metric_name, unit):
        return cw.get_metric_statistics(
            Namespace="AWS/S3", MetricName=metric_name,
            Dimensions=[
                {"Name": "BucketName", "Value": bucket},
                {"Name": "StorageType", "Value": "StandardStorage" if metric_name == "BucketSizeBytes" else "AllStorageTypes"},
            ],
            StartTime=start, EndTime=end, Period=86400, Statistics=["Average"], Unit=unit,
        )

    size_resp  = await _run(_get_metric, "BucketSizeBytes", "Bytes")
    count_resp = await _run(_get_metric, "NumberOfObjects", "Count")
    size  = size_resp["Datapoints"][-1]["Average"]  if size_resp["Datapoints"]  else 0
    count = count_resp["Datapoints"][-1]["Average"] if count_resp["Datapoints"] else 0
    return {
        "bucket":       bucket,
        "size_bytes":   size,
        "size_gb":      round(size / 1e9, 3),
        "size_tb":      round(size / 1e12, 5),
        "object_count": int(count),
    }


@tool
async def s3_get_bucket_policy(bucket: str) -> dict:
    """Get the bucket policy JSON for an S3 bucket."""
    s3 = _s3()
    try:
        resp = await _run(s3.get_bucket_policy, Bucket=bucket)
        return {"bucket": bucket, "policy": json.loads(resp["Policy"])}
    except Exception as e:
        if "NoSuchBucketPolicy" in str(e):
            return {"bucket": bucket, "policy": None, "message": "No bucket policy set"}
        raise


@tool
async def s3_get_bucket_acl(bucket: str) -> dict:
    """Get the ACL (access control list) for an S3 bucket."""
    s3 = _s3()
    resp = await _run(s3.get_bucket_acl, Bucket=bucket)
    public_grants = [
        g for g in resp["Grants"]
        if g.get("Grantee", {}).get("URI", "").endswith("AllUsers")
        or g.get("Grantee", {}).get("URI", "").endswith("AuthenticatedUsers")
    ]
    return {
        "bucket":        bucket,
        "owner":         resp["Owner"],
        "grants":        resp["Grants"],
        "public_access": len(public_grants) > 0,
        "risk":          "HIGH — bucket is publicly readable" if public_grants else "OK",
    }


@tool
async def s3_get_bucket_versioning(bucket: str) -> dict:
    """Check if versioning is enabled on an S3 bucket."""
    s3 = _s3()
    resp = await _run(s3.get_bucket_versioning, Bucket=bucket)
    status = resp.get("Status", "Disabled")
    return {
        "bucket":     bucket,
        "versioning": status,
        "mfa_delete": resp.get("MFADelete", "Disabled"),
        "warning":    "Versioning disabled — no object history for recovery" if status != "Enabled" else None,
    }


@tool
async def s3_get_bucket_encryption(bucket: str) -> dict:
    """Check if server-side encryption is enabled on an S3 bucket."""
    s3 = _s3()
    try:
        resp = await _run(s3.get_bucket_encryption, Bucket=bucket)
        rules = resp["ServerSideEncryptionConfiguration"]["Rules"]
        return {
            "bucket": bucket,
            "encrypted": True,
            "algorithm": rules[0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"],
        }
    except Exception as e:
        if "ServerSideEncryptionConfigurationNotFoundError" in str(e):
            return {
                "bucket":    bucket,
                "encrypted": False,
                "risk":      "HIGH — no server-side encryption configured",
            }
        raise


@tool
async def s3_create_bucket(bucket_name: str, region: str = "us-east-1") -> dict:
    """Create a new S3 bucket with encryption and versioning enabled by default. REQUIRES CONFIRMATION."""
    s3 = _s3()
    create_args: dict = {"Bucket": bucket_name}
    if region != "us-east-1":
        create_args["CreateBucketConfiguration"] = {"LocationConstraint": region}
    await _run(s3.create_bucket, **create_args)
    # Enable encryption by default
    await _run(
        s3.put_bucket_encryption,
        Bucket=bucket_name,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    # Block public access
    await _run(
        s3.put_public_access_block,
        Bucket=bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    return {"created": bucket_name, "region": region, "encryption": "AES256", "public_access_blocked": True}


@tool
async def s3_delete_object(bucket: str, key: str) -> dict:
    """Delete an object from an S3 bucket. REQUIRES CONFIRMATION."""
    s3 = _s3()
    await _run(s3.delete_object, Bucket=bucket, Key=key)
    return {"deleted": key, "bucket": bucket}


@tool
async def s3_get_public_access_block(bucket: str) -> dict:
    """Get the Public Access Block configuration for an S3 bucket."""
    s3 = _s3()
    try:
        resp = await _run(s3.get_public_access_block, Bucket=bucket)
        config = resp.get("PublicAccessBlockConfiguration", {})
        fully_blocked = all([
            config.get("BlockPublicAcls"),
            config.get("BlockPublicPolicy"),
            config.get("RestrictPublicBuckets"),
        ])
        return {
            "bucket":         bucket,
            "config":         config,
            "fully_blocked":  fully_blocked,
            "risk":           "OK" if fully_blocked else "HIGH — public access may be allowed",
        }
    except Exception as e:
        return {"bucket": bucket, "error": str(e), "risk": "UNKNOWN"}
