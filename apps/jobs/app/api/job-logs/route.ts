import { getPersistentViewerLogsPage } from "../../../lib/convex";
import { getDirectCloudWatchLogsPage } from "../../../lib/aws";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const jobId = new URL(request.url).searchParams.get("jobId");
  if (!jobId) {
    return Response.json({ error: "jobId is required" }, { status: 400 });
  }
  const searchParams = new URL(request.url).searchParams;
  const cursor = searchParams.get("cursor");
  const requestedLimit = Number(searchParams.get("limit") || "1000");
  const pageSize = Number.isFinite(requestedLimit) ? requestedLimit : 1_000;
  if (cursor?.startsWith("cloudwatch:")) {
    try {
      const payload = await getDirectCloudWatchLogsPage(jobId, cursor, pageSize);
      return Response.json(payload, {
        headers: {
          "Cache-Control": "no-store",
          "X-Diana-Log-Source": "cloudwatch-fallback",
        },
      });
    } catch (cloudWatchError) {
      console.error(cloudWatchError);
      return Response.json(
        { error: "Unable to continue reading logs from CloudWatch." },
        { status: 502, headers: { "Cache-Control": "no-store" } },
      );
    }
  }
  try {
    const payload = await getPersistentViewerLogsPage(
      jobId,
      cursor,
      pageSize,
    );
    return Response.json(payload, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (archiveError) {
    console.warn("[logs] persistent archive unavailable; reading CloudWatch", {
      jobId,
      error:
        archiveError instanceof Error ? archiveError.message : String(archiveError),
    });
    try {
      const payload = await getDirectCloudWatchLogsPage(jobId, cursor, pageSize);
      return Response.json(payload, {
        headers: {
          "Cache-Control": "no-store",
          "X-Diana-Log-Source": "cloudwatch-fallback",
        },
      });
    } catch (cloudWatchError) {
      console.error(cloudWatchError);
      return Response.json(
        { error: "Unable to read logs from the persistent archive or CloudWatch." },
        { status: 502, headers: { "Cache-Control": "no-store" } },
      );
    }
  }
}
