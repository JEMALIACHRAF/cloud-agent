"""
refresh_pricing.py — refresh pricing cache from AWS Pricing API.

Covers: EC2, RDS, Aurora, ElastiCache, Fargate (Linux x86 on-demand + 1yr No-Upfront RI).

Usage:
    python scripts/refresh_pricing.py                          # all services
    python scripts/refresh_pricing.py --service ec2
    python scripts/refresh_pricing.py --service rds --region eu-west-3
    python scripts/refresh_pricing.py --stats
    python scripts/refresh_pricing.py --clear

Needs AWS creds + pricing:GetProducts IAM perm.
"""
import argparse, asyncio, json, os, sys
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REGION_NAMES = {
    "us-east-1": "US East (N. Virginia)", "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)", "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)", "eu-west-2": "EU (London)", "eu-west-3": "EU (Paris)",
    "eu-central-1": "EU (Frankfurt)", "eu-north-1": "EU (Stockholm)",
    "ap-northeast-1": "Asia Pacific (Tokyo)", "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-southeast-1": "Asia Pacific (Singapore)", "ap-southeast-2": "Asia Pacific (Sydney)",
    "ca-central-1": "Canada (Central)", "sa-east-1": "South America (Sao Paulo)",
}


def _parse_ondemand(pl_json):
    pl = json.loads(pl_json)
    od = pl.get("terms", {}).get("OnDemand", {})
    sku = next(iter(od.keys()), None)
    if not sku: raise ValueError("No OnDemand")
    pd = next(iter(od[sku]["priceDimensions"].values()))
    return float(pd["pricePerUnit"]["USD"])


def _parse_ri_1yr_noupfront(pl_json):
    pl = json.loads(pl_json)
    for _, term in pl.get("terms", {}).get("Reserved", {}).items():
        a = term.get("termAttributes", {})
        if a.get("LeaseContractLength") == "1yr" and a.get("PurchaseOption") == "No Upfront" \
           and a.get("OfferingClass") == "standard":
            pd = next(iter(term["priceDimensions"].values()))
            return float(pd["pricePerUnit"]["USD"])
    return None


def _client():
    import boto3
    return boto3.client("pricing", region_name="us-east-1")


def _store(svc_key, region, params, hourly, source, meta):
    from tools.aws.pricing_cache import _set_cache, _cache_key
    _set_cache(_cache_key(svc_key, region, params), hourly, source, meta)


# ─── EC2 ───────────────────────────────────────────────────────────────────────
EC2_TYPES = ["t3.nano","t3.micro","t3.small","t3.medium","t3.large","t3.xlarge","t3.2xlarge",
             "t4g.micro","t4g.small","t4g.medium","t4g.large",
             "m5.large","m5.xlarge","m5.2xlarge","m5.4xlarge",
             "m6i.large","m6i.xlarge","m6i.2xlarge",
             "c5.large","c5.xlarge","c5.2xlarge","c5.4xlarge",
             "r5.large","r5.xlarge","r5.2xlarge",
             "r6g.large","r6g.xlarge"]

def fetch_ec2(it, region):
    r = _client().get_products(ServiceCode="AmazonEC2", Filters=[
        {"Type":"TERM_MATCH","Field":"instanceType","Value":it},
        {"Type":"TERM_MATCH","Field":"location","Value":REGION_NAMES[region]},
        {"Type":"TERM_MATCH","Field":"operatingSystem","Value":"Linux"},
        {"Type":"TERM_MATCH","Field":"tenancy","Value":"Shared"},
        {"Type":"TERM_MATCH","Field":"preInstalledSw","Value":"NA"},
        {"Type":"TERM_MATCH","Field":"capacitystatus","Value":"Used"},
    ], MaxResults=1)
    if not r.get("PriceList"): raise ValueError(f"No price")
    pl = r["PriceList"][0]
    return {"od": _parse_ondemand(pl), "ri": _parse_ri_1yr_noupfront(pl)}


async def refresh_ec2(region):
    print(f"\n▸ EC2 ({region})…")
    ok = fail = 0
    for it in EC2_TYPES:
        try:
            r = fetch_ec2(it, region)
            _store(f"ec2.{it}", region, {"instance_type":it}, r["od"], "live_api", {"sku":"OnDemand Linux"})
            if r["ri"]:
                _store(f"ec2.{it}.ri_1yr_nu", region, {"instance_type":it,"ri":"1yr_nu"},
                       r["ri"], "live_api", {"sku":"RI 1yr No Upfront"})
            print(f"  ✓ {it:<14} ${r['od']:.4f}/hr" + (f"  RI ${r['ri']:.4f}" if r['ri'] else ""))
            ok += 1
        except Exception as e:
            print(f"  ✗ {it:<14} {str(e)[:60]}"); fail += 1
    print(f"  EC2: {ok} OK, {fail} failed")


# ─── RDS ───────────────────────────────────────────────────────────────────────
RDS_TYPES = [("db.t3.micro","MySQL"),("db.t3.small","MySQL"),("db.t3.medium","MySQL"),
             ("db.t3.large","MySQL"),("db.t4g.micro","MySQL"),("db.t4g.small","MySQL"),
             ("db.t4g.medium","MySQL"),("db.m5.large","MySQL"),("db.m5.xlarge","MySQL"),
             ("db.r5.large","MySQL"),("db.r5.xlarge","MySQL"),
             ("db.t3.micro","PostgreSQL"),("db.t3.medium","PostgreSQL"),
             ("db.m5.large","PostgreSQL"),("db.r5.large","PostgreSQL")]

def fetch_rds(it, eng, region, multi_az=False):
    r = _client().get_products(ServiceCode="AmazonRDS", Filters=[
        {"Type":"TERM_MATCH","Field":"instanceType","Value":it},
        {"Type":"TERM_MATCH","Field":"databaseEngine","Value":eng},
        {"Type":"TERM_MATCH","Field":"location","Value":REGION_NAMES[region]},
        {"Type":"TERM_MATCH","Field":"deploymentOption","Value":"Multi-AZ" if multi_az else "Single-AZ"},
        {"Type":"TERM_MATCH","Field":"licenseModel","Value":"No license required"},
    ], MaxResults=1)
    if not r.get("PriceList"): raise ValueError("No price")
    pl = r["PriceList"][0]
    return {"od": _parse_ondemand(pl), "ri": _parse_ri_1yr_noupfront(pl)}


async def refresh_rds(region):
    print(f"\n▸ RDS ({region})…")
    ok = fail = 0
    for it, eng in RDS_TYPES:
        try:
            r = fetch_rds(it, eng, region)
            _store(f"rds.{it}.{eng.lower()}", region, {"instance_type":it,"engine":eng},
                   r["od"], "live_api", {"engine":eng,"deployment":"Single-AZ"})
            if r["ri"]:
                _store(f"rds.{it}.{eng.lower()}.ri_1yr_nu", region,
                       {"instance_type":it,"engine":eng,"ri":"1yr_nu"}, r["ri"], "live_api",
                       {"engine":eng})
            print(f"  ✓ {it:<14} {eng:<11} ${r['od']:.4f}/hr" + (f"  RI ${r['ri']:.4f}" if r['ri'] else ""))
            ok += 1
        except Exception as e:
            print(f"  ✗ {it:<14} {eng:<11} {str(e)[:50]}"); fail += 1
    print(f"  RDS: {ok} OK, {fail} failed")


# ─── Aurora ────────────────────────────────────────────────────────────────────
AURORA_TYPES = [("db.t3.medium","Aurora MySQL"),("db.r6g.large","Aurora MySQL"),
                ("db.r6g.xlarge","Aurora MySQL"),("db.r5.large","Aurora MySQL"),
                ("db.t3.medium","Aurora PostgreSQL"),("db.r6g.large","Aurora PostgreSQL"),
                ("db.r6g.xlarge","Aurora PostgreSQL")]

def fetch_aurora(it, eng, region):
    r = _client().get_products(ServiceCode="AmazonRDS", Filters=[
        {"Type":"TERM_MATCH","Field":"instanceType","Value":it},
        {"Type":"TERM_MATCH","Field":"databaseEngine","Value":eng},
        {"Type":"TERM_MATCH","Field":"location","Value":REGION_NAMES[region]},
    ], MaxResults=1)
    if not r.get("PriceList"): raise ValueError("No price")
    pl = r["PriceList"][0]
    return {"od": _parse_ondemand(pl), "ri": _parse_ri_1yr_noupfront(pl)}


async def refresh_aurora(region):
    print(f"\n▸ Aurora ({region})…")
    ok = fail = 0
    for it, eng in AURORA_TYPES:
        try:
            r = fetch_aurora(it, eng, region)
            eng_k = eng.lower().replace(" ","_")
            _store(f"aurora.{it}.{eng_k}", region, {"instance_type":it,"engine":eng},
                   r["od"], "live_api", {"engine":eng})
            if r["ri"]:
                _store(f"aurora.{it}.{eng_k}.ri_1yr_nu", region,
                       {"instance_type":it,"engine":eng,"ri":"1yr_nu"}, r["ri"], "live_api",
                       {"engine":eng})
            print(f"  ✓ {it:<14} {eng:<22} ${r['od']:.4f}/hr" + (f"  RI ${r['ri']:.4f}" if r['ri'] else ""))
            ok += 1
        except Exception as e:
            print(f"  ✗ {it:<14} {eng:<22} {str(e)[:50]}"); fail += 1
    print(f"  Aurora: {ok} OK, {fail} failed")


# ─── ElastiCache ───────────────────────────────────────────────────────────────
ELASTICACHE_TYPES = [("cache.t3.micro","Redis"),("cache.t3.small","Redis"),
                     ("cache.t3.medium","Redis"),("cache.t4g.micro","Redis"),
                     ("cache.t4g.small","Redis"),("cache.r6g.large","Redis"),
                     ("cache.r6g.xlarge","Redis"),("cache.m6g.large","Redis"),
                     ("cache.t3.micro","Memcached"),("cache.r6g.large","Memcached")]

def fetch_elasticache(nt, eng, region):
    r = _client().get_products(ServiceCode="AmazonElastiCache", Filters=[
        {"Type":"TERM_MATCH","Field":"instanceType","Value":nt},
        {"Type":"TERM_MATCH","Field":"cacheEngine","Value":eng},
        {"Type":"TERM_MATCH","Field":"location","Value":REGION_NAMES[region]},
    ], MaxResults=1)
    if not r.get("PriceList"): raise ValueError("No price")
    pl = r["PriceList"][0]
    return {"od": _parse_ondemand(pl), "ri": _parse_ri_1yr_noupfront(pl)}


async def refresh_elasticache(region):
    print(f"\n▸ ElastiCache ({region})…")
    ok = fail = 0
    for nt, eng in ELASTICACHE_TYPES:
        try:
            r = fetch_elasticache(nt, eng, region)
            _store(f"elasticache.{nt}.{eng.lower()}", region, {"node_type":nt,"engine":eng},
                   r["od"], "live_api", {"engine":eng})
            if r["ri"]:
                _store(f"elasticache.{nt}.{eng.lower()}.ri_1yr_nu", region,
                       {"node_type":nt,"engine":eng,"ri":"1yr_nu"}, r["ri"], "live_api",
                       {"engine":eng})
            print(f"  ✓ {nt:<18} {eng:<10} ${r['od']:.4f}/hr" + (f"  RI ${r['ri']:.4f}" if r['ri'] else ""))
            ok += 1
        except Exception as e:
            print(f"  ✗ {nt:<18} {eng:<10} {str(e)[:50]}"); fail += 1
    print(f"  ElastiCache: {ok} OK, {fail} failed")


# ─── Fargate ───────────────────────────────────────────────────────────────────

def fetch_fargate(region):
    cli = _client()
    # vCPU-hour
    r = cli.get_products(ServiceCode="AmazonECS", Filters=[
        {"Type":"TERM_MATCH","Field":"location","Value":REGION_NAMES[region]},
        {"Type":"TERM_MATCH","Field":"operatingSystem","Value":"Linux"},
        {"Type":"TERM_MATCH","Field":"cputype","Value":"perCPU"},
    ], MaxResults=10)
    vcpu = None
    for raw in r.get("PriceList", []):
        try:
            pl = json.loads(raw)
            ut = pl.get("product",{}).get("attributes",{}).get("usagetype","")
            if ut.endswith("Fargate-vCPU-Hours:perCPU"):
                vcpu = _parse_ondemand(raw); break
        except: continue
    # GB-hour
    r = cli.get_products(ServiceCode="AmazonECS", Filters=[
        {"Type":"TERM_MATCH","Field":"location","Value":REGION_NAMES[region]},
        {"Type":"TERM_MATCH","Field":"operatingSystem","Value":"Linux"},
        {"Type":"TERM_MATCH","Field":"memorytype","Value":"perGB"},
    ], MaxResults=10)
    gb = None
    for raw in r.get("PriceList", []):
        try:
            pl = json.loads(raw)
            ut = pl.get("product",{}).get("attributes",{}).get("usagetype","")
            if ut.endswith("Fargate-GB-Hours"):
                gb = _parse_ondemand(raw); break
        except: continue
    if vcpu is None or gb is None:
        raise ValueError("Fargate prices not found")
    return {"vcpu": vcpu, "gb": gb}


async def refresh_fargate(region):
    print(f"\n▸ Fargate ({region})…")
    try:
        r = fetch_fargate(region)
        _store("fargate.vcpu_hour", region, {"unit":"vcpu_hour"}, r["vcpu"], "live_api",
               {"sku":"Fargate-vCPU-Hours Linux x86"})
        _store("fargate.gb_hour", region, {"unit":"gb_hour"}, r["gb"], "live_api",
               {"sku":"Fargate-GB-Hours Linux x86"})
        print(f"  ✓ vCPU ${r['vcpu']:.5f}/hr   GB ${r['gb']:.5f}/hr")
    except Exception as e:
        print(f"  ✗ Fargate: {e}")


# ─── Main ──────────────────────────────────────────────────────────────────────

async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--service", choices=["all","ec2","rds","aurora","elasticache","fargate"],
                   default="all")
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--stats", action="store_true")
    p.add_argument("--clear", action="store_true")
    a = p.parse_args()

    from tools.aws.pricing_cache import cache_stats, clear_cache
    if a.stats:
        s = cache_stats()
        print("\nPricing cache stats:")
        for k, v in s.items(): print(f"  {k:<18} {v}")
        return
    if a.clear:
        clear_cache(); print("✓ Cache cleared"); return

    print(f"\n═══ Pricing Refresh — {datetime.now().isoformat()} — {a.region} ═══")
    runners = {"ec2":refresh_ec2,"rds":refresh_rds,"aurora":refresh_aurora,
               "elasticache":refresh_elasticache,"fargate":refresh_fargate}
    if a.service == "all":
        for fn in runners.values(): await fn(a.region)
    else:
        await runners[a.service](a.region)
    s = cache_stats()
    print(f"\n✓ Done. Cache: {s['fresh_entries']} fresh entries.")


if __name__ == "__main__":
    asyncio.run(main())
