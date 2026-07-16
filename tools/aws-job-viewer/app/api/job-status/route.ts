import { getViewerJob, REGION } from "../../../lib/aws";

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
    return Response.json(
      { generatedAt: new Date().toISOString(), region: REGION, job },
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
