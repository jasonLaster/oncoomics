import { ConvexHttpClient } from "convex/browser";
import { getVercelOidcToken } from "@vercel/oidc";
import { api } from "../convex/_generated/api";
import type { listViewerJobs } from "./aws";

type ViewerPayload = Awaited<ReturnType<typeof listViewerJobs>>;

function convexUrl() {
  return process.env.CONVEX_URL || process.env.NEXT_PUBLIC_CONVEX_URL;
}

function normalizedSnapshot(payload: ViewerPayload) {
  const generatedAt = Date.parse(payload.generatedAt);
  return {
    generatedAt,
    region: payload.region,
    queues: payload.queues,
    jobs: payload.jobs
      .filter((job) => Boolean(job.id))
      .map((job) => ({
        jobId: job.id!,
        name: job.name || null,
        status: job.status || "UNKNOWN",
        statusReason: job.statusReason,
        queue: job.queue || null,
        createdAt: job.createdAt,
        startedAt: job.startedAt,
        stoppedAt: job.stoppedAt,
        runId: job.runId,
        stage: job.stage,
      })),
    progressEvents: payload.jobs.flatMap((job) =>
      job.id && job.progress
        ? job.progress.chromosomes.map((chromosome) => ({
            eventKey: `${job.id}:${chromosome.name}:${chromosome.position}`,
            jobId: job.id!,
            chromosome: chromosome.name,
            position: chromosome.position,
            length: chromosome.length,
            observedAt: generatedAt,
            active: chromosome.active,
          }))
        : [],
    ),
  };
}

export async function persistAndMergeViewerSnapshot(
  payload: ViewerPayload,
): Promise<ViewerPayload> {
  const url = convexUrl();
  if (!url) return payload;

  try {
    const token = await getVercelOidcToken();
    const client = new ConvexHttpClient(url, { auth: token, logger: false });
    const snapshot = normalizedSnapshot(payload);
    await client.mutation(api.jobProgress.ingestSnapshot, snapshot);
    const aggregates = await client.query(api.jobProgress.getAggregates, {
      jobIds: snapshot.jobs.map((job) => job.jobId),
    });
    const byJobId = new Map(
      aggregates.map((aggregate) => [aggregate.jobId, aggregate]),
    );

    return {
      ...payload,
      jobs: payload.jobs.map((job) => ({
        ...job,
        progress: job.id ? byJobId.get(job.id) || job.progress : job.progress,
      })),
    };
  } catch (error) {
    console.warn("[convex] snapshot persistence unavailable", {
      error: error instanceof Error ? error.message : String(error),
    });
    return payload;
  }
}
