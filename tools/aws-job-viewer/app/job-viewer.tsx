"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

const REFRESH_SECONDS = 60;
const ACTIVE_STATUSES = new Set([
  "SUBMITTED",
  "PENDING",
  "RUNNABLE",
  "STARTING",
  "RUNNING",
]);

type Chromosome = {
  name: string;
  position: number;
  length: number;
  percent: number;
  active: boolean;
};

type Progress = {
  chromosomes: Chromosome[];
  started: number;
  active: number;
  completed: number;
  queued: number;
  genomePercent: number;
  rateMbPerMinute: number;
  etaSeconds: number | null;
};

type ViewerJob = {
  id: string;
  name: string;
  status: string;
  statusReason: string | null;
  queue: string;
  createdAt: number | null;
  startedAt: number | null;
  stoppedAt: number | null;
  timeoutSeconds: number | null;
  attempts: number;
  runId: string;
  stage: string;
  logStreamName: string | null;
  dependsOn: string[];
  progress: Progress | null;
};

type JobsPayload = {
  generatedAt: string;
  region: string;
  queues: string[];
  jobs: ViewerJob[];
};

type LogEvent = { timestamp: number | null; message: string };
type LogsPayload = {
  jobId: string;
  jobName: string;
  logStreamName: string | null;
  events: LogEvent[];
};

const WORKFLOW = [
  { id: "integrity", label: "Intake integrity", detail: "AWS-side SHA-256 verification" },
  { id: "alignment", label: "Alignment", detail: "Lane alignment and BAM gather" },
  { id: "evidence", label: "Variant evidence", detail: "Chromosome-level Mutect2 calling" },
  { id: "gather", label: "Evidence gather", detail: "VCFs, stats, and F1R2 archives" },
  { id: "filter", label: "Filter and annotate", detail: "Contamination, PASS, BRCA, SBS96, and SV" },
  { id: "delivery", label: "Readiness and delivery", detail: "Encrypted upload and final validation" },
];

function clamp(value: number) {
  return Math.max(0, Math.min(100, value));
}

function formatDate(value: number | string | null) {
  if (!value) return "—";
  const date = typeof value === "number" ? new Date(value) : new Date(value);
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function formatElapsed(startedAt: number | null, stoppedAt: number | null) {
  if (!startedAt) return "Not started";
  const seconds = Math.max(0, Math.floor(((stoppedAt || Date.now()) - startedAt) / 1_000));
  const hours = Math.floor(seconds / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function formatEta(seconds: number | null) {
  if (!seconds || !Number.isFinite(seconds)) return "Calculating";
  const hours = Math.floor(seconds / 3_600);
  const minutes = Math.max(1, Math.round((seconds % 3_600) / 60));
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function formatBases(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)} Mb`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)} kb`;
  return `${value} bp`;
}

function statusLabel(status: string) {
  return status.toLowerCase().replaceAll("_", " ");
}

function stageState(stage: string, selectedStage: string, selectedStatus: string) {
  const selectedIndex = WORKFLOW.findIndex((item) => item.id === selectedStage);
  const index = WORKFLOW.findIndex((item) => item.id === stage);
  if (selectedStatus === "SUCCEEDED") return "complete";
  if (selectedStatus === "FAILED" && index === Math.max(0, selectedIndex)) return "failed";
  if (index < Math.max(0, selectedIndex)) return "complete";
  if (index === Math.max(0, selectedIndex)) return "active";
  return "queued";
}

export function JobViewer() {
  const [payload, setPayload] = useState<JobsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<"overview" | "logs">("overview");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [countdown, setCountdown] = useState(REFRESH_SECONDS);
  const [logs, setLogs] = useState<LogsPayload | null>(null);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [logsLoading, setLogsLoading] = useState(false);

  const fetchJobs = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const response = await fetch("/api/jobs", { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Unable to load jobs.");
      setPayload(body);
      setError(null);
      setSelectedId((current) => {
        if (current && body.jobs.some((job: ViewerJob) => job.id === current)) return current;
        return body.jobs.find((job: ViewerJob) => ACTIVE_STATUSES.has(job.status))?.id || body.jobs[0]?.id || null;
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load jobs.");
    } finally {
      setIsRefreshing(false);
      setCountdown(REFRESH_SECONDS);
    }
  }, []);

  const fetchLogs = useCallback(async (jobId: string) => {
    setLogsLoading(true);
    setLogs((current) => (current?.jobId === jobId ? current : null));
    try {
      const response = await fetch(`/api/job-logs?jobId=${encodeURIComponent(jobId)}`, {
        cache: "no-store",
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Unable to load logs.");
      setLogs(body);
      setLogsError(null);
    } catch (cause) {
      setLogsError(cause instanceof Error ? cause.message : "Unable to load logs.");
    } finally {
      setLogsLoading(false);
    }
  }, []);

  useEffect(() => {
    const initialTimer = window.setTimeout(() => void fetchJobs(), 0);
    const refreshTimer = window.setInterval(() => void fetchJobs(), REFRESH_SECONDS * 1_000);
    const countdownTimer = window.setInterval(
      () => setCountdown((value) => (value > 1 ? value - 1 : REFRESH_SECONDS)),
      1_000,
    );
    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(refreshTimer);
      window.clearInterval(countdownTimer);
    };
  }, [fetchJobs]);

  useEffect(() => {
    if (tab !== "logs" || !selectedId) return;
    const initialTimer = window.setTimeout(() => void fetchLogs(selectedId), 0);
    const timer = window.setInterval(() => void fetchLogs(selectedId), REFRESH_SECONDS * 1_000);
    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(timer);
    };
  }, [fetchLogs, selectedId, tab]);

  const jobs = payload?.jobs || [];
  const activeJobs = jobs.filter((job) => ACTIVE_STATUSES.has(job.status));
  const recentJobs = jobs.filter((job) => !ACTIVE_STATUSES.has(job.status));
  const selected = jobs.find((job) => job.id === selectedId) || null;
  const runJobs = selected ? jobs.filter((job) => job.runId === selected.runId) : [];
  const progress = selected?.progress || runJobs.find((job) => job.progress)?.progress || null;
  const selectedStage = selected?.stage === "batch" ? "evidence" : selected?.stage || "integrity";

  const logLines = useMemo(
    () =>
      (logs?.events || []).map((event) => {
        const timestamp = event.timestamp
          ? new Date(event.timestamp).toISOString().replace("T", " ").replace("Z", " UTC")
          : "";
        return `${timestamp}  ${event.message}`.trimEnd();
      }),
    [logs],
  );

  return (
    <main className="viewer-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">D</span>
          <div>
            <p className="eyebrow">Diana Compute</p>
            <h1>Run monitor</h1>
          </div>
        </div>
        <div className="topbar-meta">
          <div className="connection-state">
            <span className={`live-dot ${error ? "is-error" : ""}`} aria-hidden="true" />
            <span>{error ? "Connection issue" : "Live from AWS"}</span>
          </div>
          <span className="meta-divider" aria-hidden="true" />
          <span>{payload?.region || "us-east-1"}</span>
          <span className="meta-divider" aria-hidden="true" />
          <span>Refresh in {countdown}s</span>
          <button className="refresh-button" onClick={() => void fetchJobs()} disabled={isRefreshing}>
            {isRefreshing ? "Refreshing…" : "Refresh now"}
          </button>
        </div>
      </header>

      <div className="workspace">
        <aside className="job-rail" aria-label="AWS Batch jobs">
          <div className="rail-heading">
            <div>
              <p className="eyebrow">Queues</p>
              <h2>Jobs</h2>
            </div>
            <span className="count-badge">{activeJobs.length} active</span>
          </div>

          {error && (
            <div className="rail-error" role="alert">
              <strong>Unable to reach AWS</strong>
              <span>{error}</span>
            </div>
          )}

          {!payload && !error && <p className="rail-empty">Discovering Batch queues…</p>}
          {payload && jobs.length === 0 && (
            <p className="rail-empty">No active or recently completed jobs were found.</p>
          )}

          {activeJobs.length > 0 && (
            <JobGroup title="Running now" jobs={activeJobs} selectedId={selectedId} onSelect={setSelectedId} />
          )}
          {recentJobs.length > 0 && (
            <JobGroup title="Last 24 hours" jobs={recentJobs} selectedId={selectedId} onSelect={setSelectedId} />
          )}

          <div className="rail-footer">
            <span>Last sync</span>
            <time>{payload ? formatDate(payload.generatedAt) : "Waiting…"}</time>
          </div>
        </aside>

        <section className="main-panel">
          {!selected ? (
            <div className="empty-state">
              <span className="empty-glyph" aria-hidden="true">⌁</span>
              <h2>{error ? "Viewer is offline" : "No job selected"}</h2>
              <p>{error ? "Add read-only AWS credentials to the server and refresh." : "Running and recent jobs will appear here automatically."}</p>
            </div>
          ) : (
            <>
              <div className="job-heading">
                <div>
                  <div className="job-heading-line">
                    <span className={`status-pill status-${selected.status.toLowerCase()}`}>
                      <span aria-hidden="true" />
                      {statusLabel(selected.status)}
                    </span>
                    <span className="stage-label">{selected.stage}</span>
                  </div>
                  <h2>{selected.name}</h2>
                  <p className="run-id">{selected.runId}</p>
                </div>
                <dl className="heading-facts">
                  <div><dt>Queue</dt><dd>{selected.queue || "—"}</dd></div>
                  <div><dt>Elapsed</dt><dd>{formatElapsed(selected.startedAt, selected.stoppedAt)}</dd></div>
                  <div><dt>Attempts</dt><dd>{selected.attempts || 1}</dd></div>
                </dl>
              </div>

              <div className="tabs" role="tablist" aria-label="Job details">
                <button role="tab" aria-selected={tab === "overview"} onClick={() => setTab("overview")}>Overview</button>
                <button role="tab" aria-selected={tab === "logs"} onClick={() => setTab("logs")}>
                  Raw logs
                  {selected.logStreamName && <span className="tab-live-dot" aria-hidden="true" />}
                </button>
              </div>

              {tab === "overview" ? (
                <div className="overview-content">
                  {selected.statusReason && <div className="status-note">{selected.statusReason}</div>}

                  <section className="metrics-grid" aria-label="Run metrics">
                    <Metric label="Genome traversed" value={progress ? `${progress.genomePercent.toFixed(1)}%` : "—"} detail={progress ? `${progress.started} of 23 chromosomes started` : "Waiting for progress logs"} accent />
                    <Metric label="Active shards" value={progress ? String(progress.active) : selected.status === "RUNNING" ? "1" : "0"} detail={progress ? `${progress.queued} chromosomes queued` : "Batch job containers"} />
                    <Metric label="Throughput" value={progress?.rateMbPerMinute ? `${progress.rateMbPerMinute.toFixed(1)} Mb/min` : "—"} detail="Observed from CloudWatch logs" />
                    <Metric label="Compute ETA" value={progress ? formatEta(progress.etaSeconds) : "Calculating"} detail="Mutect2 evidence stage only" />
                  </section>

                  <div className="content-grid">
                    <section className="card workflow-card">
                      <div className="section-heading">
                        <div><p className="eyebrow">Dependency chain</p><h3>Run progress</h3></div>
                        <span>{runJobs.length} Batch {runJobs.length === 1 ? "job" : "jobs"}</span>
                      </div>
                      <ol className="workflow-list">
                        {WORKFLOW.map((step) => {
                          const state = stageState(step.id, selectedStage, selected.status);
                          return (
                            <li key={step.id} className={`workflow-step is-${state}`}>
                              <span className="step-marker" aria-hidden="true">{state === "complete" ? "✓" : state === "failed" ? "!" : ""}</span>
                              <div><strong>{step.label}</strong><span>{step.detail}</span></div>
                              <span className="step-state">{state}</span>
                            </li>
                          );
                        })}
                      </ol>
                    </section>

                    <section className="card detail-card">
                      <div className="section-heading"><div><p className="eyebrow">Execution</p><h3>Job details</h3></div></div>
                      <dl className="detail-list">
                        <div><dt>Created</dt><dd>{formatDate(selected.createdAt)}</dd></div>
                        <div><dt>Started</dt><dd>{formatDate(selected.startedAt)}</dd></div>
                        <div><dt>Stopped</dt><dd>{formatDate(selected.stoppedAt)}</dd></div>
                        <div><dt>Stage</dt><dd>{selected.stage}</dd></div>
                        <div><dt>Dependencies</dt><dd>{selected.dependsOn.length || "None"}</dd></div>
                        <div><dt>Log stream</dt><dd className="truncate" title={selected.logStreamName || ""}>{selected.logStreamName || "Pending"}</dd></div>
                      </dl>
                      <div className="interpretation-note">
                        <strong>Output boundary</strong>
                        <p>This run produces exploratory evidence for HRD review. It does not produce a clinically validated scalar HRD call.</p>
                      </div>
                    </section>
                  </div>

                  <section className="card chromosome-card">
                    <div className="section-heading chromosome-heading">
                      <div><p className="eyebrow">Mutect2 shards</p><h3>Chromosome progress</h3></div>
                      {progress && <span>{progress.completed} complete · {progress.active} active · {progress.queued} queued</span>}
                    </div>
                    {progress?.chromosomes.length ? (
                      <div className="chromosome-grid">
                        {Array.from({ length: 23 }, (_, index) => {
                          const name = index === 22 ? "chrX" : `chr${index + 1}`;
                          const chromosome = progress.chromosomes.find((item) => item.name === name);
                          return <ChromosomeBar key={name} name={name} chromosome={chromosome} />;
                        })}
                      </div>
                    ) : (
                      <p className="card-empty">Chromosome-level progress will appear when GATK progress events reach CloudWatch.</p>
                    )}
                  </section>
                </div>
              ) : (
                <section className="logs-panel">
                  <div className="logs-toolbar">
                    <div>
                      <p className="eyebrow">CloudWatch tail</p>
                      <h3>{logs?.jobName || selected.name}</h3>
                      <span title={logs?.logStreamName || selected.logStreamName || ""}>{logs?.logStreamName || selected.logStreamName || "Log stream pending"}</span>
                    </div>
                    <div className="logs-toolbar-actions">
                      <span>{logLines.length ? `${logLines.length} latest events` : "No events"}</span>
                      <button onClick={() => void fetchLogs(selected.id)} disabled={logsLoading}>{logsLoading ? "Loading…" : "Refresh logs"}</button>
                    </div>
                  </div>
                  {logsError ? (
                    <div className="logs-empty" role="alert"><strong>Logs unavailable</strong><span>{logsError}</span></div>
                  ) : !selected.logStreamName ? (
                    <div className="logs-empty"><strong>Log stream not created yet</strong><span>CloudWatch logs become available after the Batch container starts.</span></div>
                  ) : logsLoading && !logs ? (
                    <div className="logs-empty"><strong>Reading CloudWatch…</strong><span>Loading the latest 1,000 events.</span></div>
                  ) : logLines.length ? (
                    <pre className="raw-log" aria-label="Raw CloudWatch logs">{logLines.join("\n")}</pre>
                  ) : (
                    <div className="logs-empty"><strong>No log events yet</strong><span>This view will retry automatically on the next one-minute refresh.</span></div>
                  )}
                </section>
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function JobGroup({ title, jobs, selectedId, onSelect }: { title: string; jobs: ViewerJob[]; selectedId: string | null; onSelect: (id: string) => void }) {
  return (
    <section className="job-group">
      <h3>{title}</h3>
      <div className="job-list">
        {jobs.map((job) => (
          <button key={job.id} className={`job-row ${job.id === selectedId ? "is-selected" : ""}`} onClick={() => onSelect(job.id)}>
            <span className={`job-status-dot status-${job.status.toLowerCase()}`} aria-hidden="true" />
            <span className="job-row-copy"><strong>{job.name}</strong><span>{job.stage} · {formatElapsed(job.startedAt, job.stoppedAt)}</span></span>
            {job.progress && <span className="job-percent">{job.progress.genomePercent.toFixed(0)}%</span>}
          </button>
        ))}
      </div>
    </section>
  );
}

function Metric({ label, value, detail, accent = false }: { label: string; value: string; detail: string; accent?: boolean }) {
  return (
    <div className={`metric ${accent ? "is-accent" : ""}`}>
      <span>{label}</span><strong>{value}</strong><small>{detail}</small>
    </div>
  );
}

function ChromosomeBar({ name, chromosome }: { name: string; chromosome?: Chromosome }) {
  const percent = clamp(chromosome?.percent || 0);
  const state = !chromosome ? "queued" : percent >= 99.9 ? "complete" : chromosome.active ? "active" : "waiting";
  return (
    <div className={`chromosome-row is-${state}`}>
      <div><strong>{name.replace("chr", "")}</strong><span>{chromosome ? formatBases(chromosome.position) : "queued"}</span></div>
      <div className="progress-track" aria-label={`${name} ${percent.toFixed(1)} percent`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(percent)}>
        <span style={{ width: `${percent}%` }} />
      </div>
      <span>{chromosome ? `${percent.toFixed(0)}%` : "—"}</span>
    </div>
  );
}
