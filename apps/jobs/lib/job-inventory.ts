import type { listViewerJobs } from "./aws";

type ViewerPayload = Awaited<ReturnType<typeof listViewerJobs>>;
type ViewerJob = ViewerPayload["jobs"][number];
type ViewerProgress = NonNullable<ViewerJob["progress"]>;

export type DurableViewerJob = {
  jobId: string;
  name: string | null;
  status: string;
  statusReason: string | null;
  queue: string | null;
  createdAt: number | null;
  startedAt: number | null;
  stoppedAt: number | null;
  runId: string;
  stage: string;
};

export type JobAggregate = ViewerProgress & { jobId: string };

export function mergeViewerJobs(
  liveJobs: ViewerJob[],
  durableJobs: DurableViewerJob[],
  aggregates: JobAggregate[],
): ViewerJob[] {
  const liveById = new Map(
    liveJobs
      .filter((job): job is ViewerJob & { id: string } => Boolean(job.id))
      .map((job) => [job.id, job]),
  );
  const progressById = new Map(
    aggregates.map(({ jobId, ...progress }) => [jobId, progress]),
  );
  const merged = durableJobs.map((durableJob): ViewerJob => {
    const liveJob = liveById.get(durableJob.jobId);
    liveById.delete(durableJob.jobId);
    if (liveJob) {
      return {
        ...liveJob,
        progress: progressById.get(durableJob.jobId) || liveJob.progress,
      };
    }
    return {
      id: durableJob.jobId,
      name: durableJob.name || durableJob.jobId,
      status: durableJob.status as ViewerJob["status"],
      statusReason: durableJob.statusReason,
      queue: durableJob.queue || "Unknown queue",
      createdAt: durableJob.createdAt,
      startedAt: durableJob.startedAt,
      stoppedAt: durableJob.stoppedAt,
      timeoutSeconds: null,
      attempts: 0,
      runId: durableJob.runId,
      stage: durableJob.stage,
      logStreamName: null,
      dependsOn: [],
      array: null,
      progress: progressById.get(durableJob.jobId) || null,
    };
  });
  for (const liveJob of liveById.values()) {
    merged.push({
      ...liveJob,
      progress:
        (liveJob.id ? progressById.get(liveJob.id) : null) || liveJob.progress,
    });
  }
  return merged.sort(
    (left, right) => (right.createdAt || 0) - (left.createdAt || 0),
  );
}
