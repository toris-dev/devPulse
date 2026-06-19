from dagster import Definitions, OpExecutionContext, job, op

from pipeline.runner import run_collect, run_pipeline


@op
def collect_geeknews(context: OpExecutionContext) -> dict:
    limit = context.op_config.get("limit", 20)
    feeds = context.op_config.get("feeds", ["all", "ask", "show", "new", "top"])
    result = run_collect(feed_types=feeds, limit=limit)
    context.log.info("Collected %s posts", result["collected"])
    return result


@op
def process_pipeline(context: OpExecutionContext) -> dict:
    limit = context.op_config.get("limit", 3)
    feeds = context.op_config.get("feeds", ["all", "ask", "show"])
    result = run_pipeline(limit=limit, feed_types=feeds)
    context.log.info("Processed %s posts", result["count"])
    return result


@job
def geeknews_mvp_job():
    collect_geeknews()
    process_pipeline()


defs = Definitions(jobs=[geeknews_mvp_job])
