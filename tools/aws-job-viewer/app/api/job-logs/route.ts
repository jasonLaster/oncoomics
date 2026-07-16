import { getPersistentViewerLogsPage } from "../../../lib/convex";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const jobId = new URL(request.url).searchParams.get("jobId");
  if (!jobId) {
    return Response.json({ error: "jobId is required" }, { status: 400 });
  }
  try {
    const searchParams = new URL(request.url).searchParams;
    const cursor = searchParams.get("cursor");
    const requestedLimit = Number(searchParams.get("limit") || "1000");
    const payload = await getPersistentViewerLogsPage(
      jobId,
      cursor,
      Number.isFinite(requestedLimit) ? requestedLimit : 1_000,
    );
    return Response.json(payload, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    console.error(error);
    return Response.json(
      { error: "Unable to read this job's persistent log archive." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
