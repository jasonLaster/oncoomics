import { getViewerLogs } from "../../../lib/aws";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const jobId = new URL(request.url).searchParams.get("jobId");
  if (!jobId) {
    return Response.json({ error: "jobId is required" }, { status: 400 });
  }
  try {
    const payload = await getViewerLogs(jobId);
    return Response.json(payload, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    console.error(error);
    return Response.json(
      { error: "Unable to read this job's CloudWatch log stream." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
