import { getViewerJob, REGION } from "../../../lib/aws";
import { persistAndMergeViewerSnapshot } from "../../../lib/convex";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const jobId = new URL(request.url).searchParams.get("jobId");
  if (!jobId) {
    return Response.json(
      { error: "jobId is required" },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const job = await getViewerJob(jobId);
    if (!job) {
      return Response.json(
        { error: "Job not found" },
        { status: 404, headers: { "Cache-Control": "no-store" } },
      );
    }
    const generatedAt = new Date().toISOString();
    const payload = await persistAndMergeViewerSnapshot({
      generatedAt,
      region: REGION,
      queues: job.queue ? [job.queue] : [],
      jobs: [job],
    });
    return Response.json(
      { generatedAt, region: REGION, job: payload.jobs[0] || job },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    console.error("[job-status] unable to refresh selected job", {
      jobId,
      error: error instanceof Error ? error.message : String(error),
    });
    return Response.json(
      { error: "Unable to refresh the selected AWS Batch job." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
