"""
Glue extended tools — crawlers, triggers, job runs (with DPU consumption).

Complements the existing glue_list_databases / glue_list_jobs which only
cover databases and ETL job definitions.
"""
from __future__ import annotations
import asyncio
import functools
from datetime import datetime, timedelta, timezone
from langchain_core.tools import tool


def _run(fn, *a, **kw):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, functools.partial(fn, *a, **kw))


def _client(region: str = "us-east-1"):
    from core.session import get_client
    return get_client("glue", region)


def _cw(region: str = "us-east-1"):
    from core.session import get_client
    return get_client("cloudwatch", region)


@tool
async def glue_list_crawlers(region: str = "us-east-1") -> dict:
    """List ALL Glue crawlers with their schedule, state, last run, and target.
    Schedule format: AWS cron (e.g. 'cron(0 8 * * ? *)' = daily 8am UTC).
    """
    g = _client(region)
    try:
        resp = await _run(g.get_crawlers)
        crawlers = []
        for c in resp.get("Crawlers", []):
            sched = c.get("Schedule", {})
            last_crawl = c.get("LastCrawl", {})
            crawlers.append({
                "name":         c.get("Name"),
                "state":        c.get("State"),  # READY | RUNNING | STOPPING
                "schedule":     sched.get("ScheduleExpression"),
                "schedule_state": sched.get("State"),  # SCHEDULED | NOT_SCHEDULED | TRANSITIONING
                "database":     c.get("DatabaseName"),
                "targets":      _summarize_targets(c.get("Targets", {})),
                "last_run":     last_crawl.get("StartTime").isoformat() if last_crawl.get("StartTime") else None,
                "last_status":  last_crawl.get("Status"),
                "tables_created": c.get("LastCrawl", {}).get("MessagePrefix"),
            })
        scheduled = [c for c in crawlers if c.get("schedule_state") == "SCHEDULED"]
        return {
            "region":          region,
            "total_crawlers":  len(crawlers),
            "scheduled_count": len(scheduled),
            "crawlers":        crawlers,
            "note": (
                f"{len(scheduled)}/{len(crawlers)} crawlers actively scheduled."
                if crawlers else "No crawlers found in this region."
            ),
        }
    except Exception as e:
        return {"error": str(e), "region": region}


def _summarize_targets(tgts: dict) -> str:
    parts = []
    if tgts.get("S3Targets"):       parts.append(f"{len(tgts['S3Targets'])} S3 path(s)")
    if tgts.get("JdbcTargets"):     parts.append(f"{len(tgts['JdbcTargets'])} JDBC")
    if tgts.get("DynamoDBTargets"): parts.append(f"{len(tgts['DynamoDBTargets'])} DDB table(s)")
    if tgts.get("CatalogTargets"):  parts.append(f"{len(tgts['CatalogTargets'])} catalog")
    return ", ".join(parts) if parts else "no targets"


@tool
async def glue_list_triggers(region: str = "us-east-1") -> dict:
    """List Glue triggers (the scheduling mechanism for jobs).
    Trigger types: SCHEDULED (cron), CONDITIONAL (job dependency), ON_DEMAND.
    """
    g = _client(region)
    try:
        resp = await _run(g.get_triggers)
        triggers = []
        for t in resp.get("Triggers", []):
            triggers.append({
                "name":        t.get("Name"),
                "type":        t.get("Type"),
                "state":       t.get("State"),  # CREATED | ACTIVATED | DEACTIVATED
                "schedule":    t.get("Schedule"),
                "actions":     [a.get("JobName") for a in t.get("Actions", [])],
                "description": t.get("Description"),
            })
        active_sched = [t for t in triggers if t["type"] == "SCHEDULED" and t["state"] == "ACTIVATED"]
        return {
            "region":           region,
            "total_triggers":   len(triggers),
            "active_scheduled": len(active_sched),
            "triggers":         triggers,
        }
    except Exception as e:
        return {"error": str(e), "region": region}


@tool
async def glue_get_job_runs(job_name: str, days_back: int = 30, region: str = "us-east-1") -> dict:
    """Recent job runs for a Glue ETL job, including DPU-seconds consumed.
    Each run's billed duration × DPU count = DPU-hours billed at $0.44/DPU-hour.
    """
    g = _client(region)
    try:
        resp = await _run(g.get_job_runs, JobName=job_name, MaxResults=200)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        runs = []
        total_dpu_sec = 0
        for r in resp.get("JobRuns", []):
            started = r.get("StartedOn")
            if started and started.replace(tzinfo=timezone.utc) < cutoff if started.tzinfo is None else started < cutoff:
                continue
            exec_time   = r.get("ExecutionTime", 0)         # seconds
            dpu_seconds = r.get("DPUSeconds", 0) or 0
            total_dpu_sec += dpu_seconds
            runs.append({
                "id":             r.get("Id"),
                "started":        started.isoformat() if started else None,
                "duration_sec":   exec_time,
                "status":         r.get("JobRunState"),
                "dpu_seconds":    dpu_seconds,
                "dpu_hours":      round(dpu_seconds / 3600, 3) if dpu_seconds else None,
                "estimated_cost_usd": round((dpu_seconds / 3600) * 0.44, 2) if dpu_seconds else None,
                "max_capacity":   r.get("MaxCapacity"),
                "worker_type":    r.get("WorkerType"),
                "error":          r.get("ErrorMessage"),
            })
        total_dpu_h = total_dpu_sec / 3600
        return {
            "job_name":        job_name,
            "region":          region,
            "period_days":     days_back,
            "run_count":       len(runs),
            "total_dpu_hours": round(total_dpu_h, 2),
            "total_cost_usd":  round(total_dpu_h * 0.44, 2),
            "runs":            runs[:50],   # cap output
        }
    except Exception as e:
        return {"error": str(e), "job_name": job_name, "region": region}


@tool
async def glue_total_dpu_usage(days_back: int = 30, region: str = "us-east-1") -> dict:
    """Total Glue DPU-hours consumed across ALL jobs in a region for the given period.

    Calls glue_get_job_runs for every job and sums DPU-seconds. Use this to answer
    'how many DPU-hours did my Glue jobs consume this month?'.
    """
    g = _client(region)
    try:
        jobs_resp = await _run(g.get_jobs)
        all_jobs = jobs_resp.get("Jobs", [])
        per_job = []
        grand_total_dpu_sec = 0
        for job in all_jobs:
            job_name = job.get("Name")
            runs_resp = await _run(g.get_job_runs, JobName=job_name, MaxResults=200)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
            job_dpu_sec = 0
            run_count = 0
            for r in runs_resp.get("JobRuns", []):
                started = r.get("StartedOn")
                if not started: continue
                if started.tzinfo is None: started = started.replace(tzinfo=timezone.utc)
                if started < cutoff: continue
                run_count += 1
                job_dpu_sec += r.get("DPUSeconds", 0) or 0
            grand_total_dpu_sec += job_dpu_sec
            per_job.append({
                "job":         job_name,
                "runs":        run_count,
                "dpu_hours":   round(job_dpu_sec / 3600, 2),
                "cost_usd":    round((job_dpu_sec / 3600) * 0.44, 2),
            })
        per_job.sort(key=lambda x: -x["dpu_hours"])
        grand_total_h = grand_total_dpu_sec / 3600
        return {
            "region":            region,
            "period_days":       days_back,
            "total_jobs":        len(all_jobs),
            "total_dpu_hours":   round(grand_total_h, 2),
            "total_cost_usd":    round(grand_total_h * 0.44, 2),
            "rate_per_dpu_hour": 0.44,
            "by_job":            per_job[:20],
        }
    except Exception as e:
        return {"error": str(e), "region": region}



@tool
async def glue_inspect_job_pipeline(job_name: str, region: str = "us-east-1") -> dict:
    """Trace a Glue ETL job's full pipeline: script location, data sources,
    target catalog tables, and last run history.

    Use this to answer 'which datasets does job X process?' before disabling
    its trigger. Helps the user identify which jobs are tied to data they no
    longer use.
    """
    g = _client(region)
    try:
        job = await _run(g.get_job, JobName=job_name)
        j = job.get("Job", {})
        command = j.get("Command", {})
        script_location = command.get("ScriptLocation")
        default_args = j.get("DefaultArguments", {})

        # Pull recent runs to see what data sources are accessed
        runs_resp = await _run(g.get_job_runs, JobName=job_name, MaxResults=5)
        recent_runs = []
        for r in runs_resp.get("JobRuns", []):
            recent_runs.append({
                "started":    r.get("StartedOn").isoformat() if r.get("StartedOn") else None,
                "duration":   r.get("ExecutionTime"),
                "status":     r.get("JobRunState"),
                "dpu_hours":  round((r.get("DPUSeconds", 0) or 0) / 3600, 2),
            })

        # Detect input/output S3 paths from args (common patterns: --input_path, --output_path, --S3_*)
        s3_inputs = []
        s3_outputs = []
        for arg_name, arg_val in default_args.items():
            if not isinstance(arg_val, str): continue
            if arg_val.startswith("s3://"):
                ln = arg_name.lower()
                if any(w in ln for w in ["input", "source", "raw"]):
                    s3_inputs.append({"arg": arg_name, "path": arg_val})
                elif any(w in ln for w in ["output", "target", "dest", "sink"]):
                    s3_outputs.append({"arg": arg_name, "path": arg_val})
                else:
                    s3_inputs.append({"arg": arg_name, "path": arg_val})

        # Find triggers that fire this job
        triggers_resp = await _run(g.get_triggers)
        firing_triggers = []
        for t in triggers_resp.get("Triggers", []):
            actions = t.get("Actions", [])
            if any(a.get("JobName") == job_name for a in actions):
                firing_triggers.append({
                    "name":     t.get("Name"),
                    "type":     t.get("Type"),
                    "state":    t.get("State"),
                    "schedule": t.get("Schedule"),
                })

        return {
            "job_name":          job_name,
            "region":            region,
            "script_location":   script_location,
            "command_type":      command.get("Name"),  # glueetl | pythonshell | gluestreaming
            "glue_version":      j.get("GlueVersion"),
            "worker_type":       j.get("WorkerType"),
            "number_of_workers": j.get("NumberOfWorkers"),
            "max_capacity":      j.get("MaxCapacity"),
            "timeout_minutes":   j.get("Timeout"),
            "s3_inputs":         s3_inputs,
            "s3_outputs":        s3_outputs,
            "default_arguments": default_args,
            "firing_triggers":   firing_triggers,
            "recent_runs":       recent_runs,
            "summary": (
                f"Job '{job_name}' is a {command.get('Name')} script at {script_location}. "
                f"Inputs: {len(s3_inputs)} S3 path(s). Outputs: {len(s3_outputs)} S3 path(s). "
                f"Fired by {len(firing_triggers)} trigger(s)."
            ),
        }
    except Exception as e:
        return {"error": str(e), "job_name": job_name, "region": region}
