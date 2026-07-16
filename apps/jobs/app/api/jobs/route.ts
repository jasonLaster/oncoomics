import { listViewerJobs } from "../../../lib/aws";
import { persistAndMergeViewerSnapshot } from "../../../lib/convex";

export const runtime = "nodejs";

export async function GET() {
  try {
    const livePayload = await listViewerJobs();
    const payload = await persistAndMergeViewerSnapshot(livePayload);
    return Response.json(payload, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    console.error(error);
    return Response.json(
      {
        error: "Unable to read AWS Batch. Check the server's read-only AWS credentials.",
      },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
