"""
Proactive Analysis Agent — background security/cost/hygiene scanner.
Runs periodically and injects alerts into new conversations.
"""
from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass, field
from typing import Literal
from datetime import datetime, timedelta

Severity = Literal["low", "medium", "high", "critical"]


@dataclass
class Alert:
    severity: Severity
    category: str          # security | cost | hygiene | availability
    title: str
    detail: str
    service: str
    region: str = "global"
    action: str = ""       # recommended action


@dataclass
class ScanResult:
    alerts: list[Alert] = field(default_factory=list)
    scanned_at: datetime = field(default_factory=datetime.utcnow)
    regions_scanned: list[str] = field(default_factory=list)

    def to_context_string(self) -> str:
        """Format alerts for injection into LLM system prompt."""
        if not self.alerts:
            return ""
        lines = ["\n## 🔍 Proactive Infrastructure Scan Results"]
        lines.append(f"*Scanned at {self.scanned_at.strftime('%Y-%m-%d %H:%M UTC')}*\n")
        by_severity = {"critical": [], "high": [], "medium": [], "low": []}
        for a in self.alerts:
            by_severity[a.severity].append(a)
        for sev in ["critical", "high", "medium", "low"]:
            alerts = by_severity[sev]
            if not alerts:
                continue
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}[sev]
            for a in alerts:
                lines.append(f"{icon} **[{sev.upper()}] {a.title}** ({a.service}, {a.region})")
                lines.append(f"  {a.detail}")
                if a.action:
                    lines.append(f"  → *Recommended: {a.action}*")
        lines.append("\n*Proactively mention these issues if relevant to the user's question.*")
        return "\n".join(lines)


class ProactiveScanner:
    """Runs background scans against the user's AWS account."""

    def __init__(self):
        self._last_result: ScanResult | None = None
        self._scanning = False

    async def scan(self, credentials: dict, region: str = "us-east-1") -> ScanResult:
        """Full scan — runs all checks concurrently."""
        if self._scanning:
            return self._last_result or ScanResult()
        self._scanning = True
        try:
            checks = await asyncio.gather(
                self._check_public_s3_buckets(credentials),
                self._check_stale_iam_keys(credentials),
                self._check_security_group_open_ssh(credentials, region),
                self._check_unencrypted_rds(credentials, region),
                self._check_stopped_instances(credentials, region),
                self._check_root_mfa(credentials),
                return_exceptions=True,
            )
            alerts: list[Alert] = []
            for result in checks:
                if isinstance(result, list):
                    alerts.extend(result)
                # Swallow exceptions from individual checks — don't fail entire scan
            self._last_result = ScanResult(
                alerts=alerts,
                regions_scanned=[region],
            )
        finally:
            self._scanning = False
        return self._last_result

    def get_cached_result(self) -> ScanResult | None:
        return self._last_result

    # ── Individual checks ──────────────────────────────────────────────────

    async def _check_public_s3_buckets(self, credentials: dict) -> list[Alert]:
        from core.session import set_session, get_client
        set_session(credentials)
        alerts = []
        try:
            loop = asyncio.get_running_loop()
            s3 = get_client("s3")
            resp = await loop.run_in_executor(None, s3.list_buckets)
            for bucket in resp.get("Buckets", [])[:20]:
                name = bucket["Name"]
                try:
                    pab = await loop.run_in_executor(
                        None, lambda n=name: s3.get_public_access_block(Bucket=n)
                    )
                    config = pab.get("PublicAccessBlockConfiguration", {})
                    if not all([
                        config.get("BlockPublicAcls"),
                        config.get("BlockPublicPolicy"),
                        config.get("RestrictPublicBuckets"),
                    ]):
                        alerts.append(Alert(
                            severity="high",
                            category="security",
                            title=f"S3 bucket '{name}' has public access enabled",
                            detail="Public Access Block is not fully enabled — data may be publicly accessible.",
                            service="S3",
                            action=f"Enable Block Public Access on bucket '{name}'",
                        ))
                except Exception:
                    pass
        except Exception:
            pass
        return alerts

    async def _check_stale_iam_keys(self, credentials: dict) -> list[Alert]:
        from core.session import set_session, get_client
        set_session(credentials)
        alerts = []
        try:
            loop = asyncio.get_running_loop()
            iam = get_client("iam")
            users_resp = await loop.run_in_executor(None, iam.list_users)
            for user in users_resp.get("Users", [])[:30]:
                username = user["UserName"]
                try:
                    keys_resp = await loop.run_in_executor(
                        None, lambda u=username: iam.list_access_keys(UserName=u)
                    )
                    for key in keys_resp.get("AccessKeyMetadata", []):
                        age_days = (datetime.utcnow() - key["CreateDate"].replace(tzinfo=None)).days
                        if age_days > 90 and key["Status"] == "Active":
                            alerts.append(Alert(
                                severity="medium" if age_days < 180 else "high",
                                category="security",
                                title=f"Stale IAM access key for user '{username}'",
                                detail=f"Key {key['AccessKeyId'][:8]}… is {age_days} days old (>90 days). Rotate it.",
                                service="IAM",
                                action=f"Rotate access key for IAM user '{username}'",
                            ))
                except Exception:
                    pass
        except Exception:
            pass
        return alerts

    async def _check_security_group_open_ssh(self, credentials: dict, region: str) -> list[Alert]:
        from core.session import set_session, get_client
        set_session(credentials)
        alerts = []
        try:
            loop = asyncio.get_running_loop()
            ec2 = get_client("ec2", region)
            resp = await loop.run_in_executor(None, ec2.describe_security_groups)
            for sg in resp.get("SecurityGroups", []):
                for rule in sg.get("IpPermissions", []):
                    if rule.get("FromPort") == 22 or rule.get("IpProtocol") == "-1":
                        for ip_range in rule.get("IpRanges", []):
                            if ip_range.get("CidrIp") == "0.0.0.0/0":
                                sg_name = sg.get("GroupName", sg["GroupId"])
                                alerts.append(Alert(
                                    severity="high",
                                    category="security",
                                    title=f"Security group '{sg_name}' allows SSH from 0.0.0.0/0",
                                    detail="Port 22 is open to the internet — brute force risk.",
                                    service="EC2",
                                    region=region,
                                    action=f"Restrict port 22 to your IP in security group '{sg_name}'",
                                ))
        except Exception:
            pass
        return alerts

    async def _check_unencrypted_rds(self, credentials: dict, region: str) -> list[Alert]:
        from core.session import set_session, get_client
        set_session(credentials)
        alerts = []
        try:
            loop = asyncio.get_running_loop()
            rds = get_client("rds", region)
            resp = await loop.run_in_executor(None, rds.describe_db_instances)
            for db in resp.get("DBInstances", []):
                if not db.get("StorageEncrypted"):
                    alerts.append(Alert(
                        severity="high",
                        category="security",
                        title=f"RDS instance '{db['DBInstanceIdentifier']}' is NOT encrypted",
                        detail="Storage encryption is disabled — data at rest is unprotected.",
                        service="RDS",
                        region=region,
                        action="Enable storage encryption (requires snapshot restore to new encrypted instance)",
                    ))
        except Exception:
            pass
        return alerts

    async def _check_stopped_instances(self, credentials: dict, region: str) -> list[Alert]:
        from core.session import set_session, get_client
        set_session(credentials)
        alerts = []
        try:
            loop = asyncio.get_running_loop()
            ec2 = get_client("ec2", region)
            resp = await loop.run_in_executor(
                None,
                lambda: ec2.describe_instances(Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]),
            )
            stopped = []
            for reservation in resp.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    name = next((t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), inst["InstanceId"])
                    stopped.append(name)
            if len(stopped) >= 3:
                alerts.append(Alert(
                    severity="low",
                    category="cost",
                    title=f"{len(stopped)} EC2 instances stopped but EBS volumes still billing",
                    detail=f"Stopped instances: {', '.join(stopped[:5])}{'…' if len(stopped) > 5 else ''}. EBS volumes still accrue costs.",
                    service="EC2",
                    region=region,
                    action="Review stopped instances — terminate if not needed to save EBS costs",
                ))
        except Exception:
            pass
        return alerts

    async def _check_root_mfa(self, credentials: dict) -> list[Alert]:
        from core.session import set_session, get_client
        set_session(credentials)
        alerts = []
        try:
            loop = asyncio.get_running_loop()
            iam = get_client("iam")
            summary = await loop.run_in_executor(None, iam.get_account_summary)
            s = summary.get("SummaryMap", {})
            if s.get("AccountMFAEnabled", 0) == 0:
                alerts.append(Alert(
                    severity="critical",
                    category="security",
                    title="Root account MFA is NOT enabled",
                    detail="AWS root account has no MFA — this is a critical security risk.",
                    service="IAM",
                    action="Enable MFA on the root account immediately via AWS Console",
                ))
        except Exception:
            pass
        return alerts


# Singleton scanner
_scanner = ProactiveScanner()


def get_scanner() -> ProactiveScanner:
    return _scanner
