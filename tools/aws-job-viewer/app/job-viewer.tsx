"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  adaptLogMessage,
  type AdaptedLogEvent,
  type LogCategory,
  type LogSeverity,
} from "./log-adapters";

const REFRESH_SECONDS = 60;
const LOG_PAGE_SIZE = 250;
const LEFT_RAIL_KEY = "diana-viewer-v2:left-rail-collapsed";
const RIGHT_RAIL_KEY = "diana-viewer-v2:right-rail-collapsed";
const MOBILE_QUERY = "(max-width: 820px)";

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

type LogEvent = {
  eventKey: string;
  timestamp: number;
  ingestionTime: number | null;
  logStreamName: string;
  message: string;
};

type LogsPayload = {
  jobId: string;
  jobName: string | null;
  logStreamName: string | null;
  events: LogEvent[];
  totalEvents: number;
  backfillComplete: boolean;
  isDone: boolean;
  continueCursor: string | null;
};

type LogMergeMode = "replace" | "refresh" | "prepend";
type WorkflowState = "complete" | "active" | "queued" | "failed";
type LogLevelFilter = "all" | "info" | "warn" | "error" | "success";

const WORKFLOW = [
  {
    id: "integrity",
    aliases: ["integrity", "preflight"],
    index: "01",
    label: "Intake integrity",
    detail: "Manifest, checksum, and reference readiness",
  },
  {
    id: "alignment",
    aliases: ["alignment"],
    index: "02",
    label: "Alignment",
    detail: "Lane alignment and coordinate-sorted BAMs",
  },
  {
    id: "evidence",
    aliases: ["evidence"],
    index: "03",
    label: "Variant evidence",
    detail: "Parallel chromosome-level Mutect2 calling",
  },
  {
    id: "gather",
    aliases: ["gather"],
    index: "04",
    label: "Evidence gather",
    detail: "BAM, VCF, statistics, and F1R2 assembly",
  },
  {
    id: "filter",
    aliases: ["filter", "annotation"],
    index: "05",
    label: "Filter and annotate",
    detail: "Contamination, PASS, BRCA, SBS96, and SV",
  },
  {
    id: "delivery",
    aliases: ["delivery", "readiness"],
    index: "06",
    label: "Readiness and delivery",
    detail: "Encrypted outputs and final validation",
  },
] as const;

function clamp(value: number) {
  return Math.max(0, Math.min(100, value));
}

function formatDate(value: number | string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function formatClock(value: number) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function formatElapsed(startedAt: number | null, stoppedAt: number | null) {
  if (!startedAt) return "Not started";
  const seconds = Math.max(
    0,
    Math.floor(((stoppedAt || Date.now()) - startedAt) / 1_000),
  );
  const hours = Math.floor(seconds / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m`;
  return "<1m";
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

function titleCase(value: string) {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function normalizedStage(stage: string) {
  if (stage === "preflight") return "integrity";
  if (stage === "batch") return "evidence";
  return stage;
}

function statusIsActive(status: string) {
  return ACTIVE_STATUSES.has(status);
}

async function requestLogPage(jobId: string, cursor?: string | null) {
  const searchParams = new URLSearchParams({
    jobId,
    limit: String(LOG_PAGE_SIZE),
  });
  if (cursor) searchParams.set("cursor", cursor);
  const response = await fetch(`/api/job-logs?${searchParams.toString()}`, {
    cache: "no-store",
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Unable to load logs.");
  return body as LogsPayload;
}

function mergeLogPayload(
  current: LogsPayload | null,
  incoming: LogsPayload,
  mode: LogMergeMode,
) {
  if (!current || current.jobId !== incoming.jobId || mode === "replace") {
    return incoming;
  }
  const events = new Map<string, LogEvent>();
  for (const event of [...current.events, ...incoming.events]) {
    events.set(event.eventKey, event);
  }
  const mergedEvents = [...events.values()].sort(
    (left, right) =>
      left.timestamp - right.timestamp || left.eventKey.localeCompare(right.eventKey),
  );
  return {
    ...incoming,
    events: mergedEvents,
    continueCursor:
      mode === "prepend" ? incoming.continueCursor : current.continueCursor,
    isDone: mode === "prepend" ? incoming.isDone : current.isDone,
  };
}

function workflowState(
  stepId: string,
  selected: ViewerJob,
  runJobs: ViewerJob[],
): { state: WorkflowState; jobs: ViewerJob[] } {
  const selectedStage = normalizedStage(selected.stage);
  const selectedIndex = Math.max(
    0,
    WORKFLOW.findIndex((item) => item.id === selectedStage),
  );
  const stepIndex = WORKFLOW.findIndex((item) => item.id === stepId);
  const definition = WORKFLOW[stepIndex];
  const jobs = runJobs
    .filter((job) =>
      (definition.aliases as readonly string[]).includes(
        normalizedStage(job.stage),
      ),
    )
    .sort((left, right) => (right.createdAt || 0) - (left.createdAt || 0));

  let state: WorkflowState =
    stepIndex < selectedIndex
      ? "complete"
      : stepIndex === selectedIndex
        ? selected.status === "FAILED"
          ? "failed"
          : selected.status === "SUCCEEDED"
            ? "complete"
            : "active"
        : "queued";

  if (jobs.some((job) => statusIsActive(job.status))) state = "active";
  else if (jobs[0]?.status === "FAILED") state = "failed";
  else if (jobs.some((job) => job.status === "SUCCEEDED")) state = "complete";

  return { state, jobs };
}

function stateNarrative(state: WorkflowState, jobs: ViewerJob[]) {
  if (state === "active") {
    const count = jobs.filter((job) => statusIsActive(job.status)).length;
    return count > 1 ? `${count} jobs active` : "In progress now";
  }
  if (state === "failed") return "Attention required";
  if (state === "complete") {
    const recovered = jobs.some((job) => job.status === "FAILED");
    return recovered ? "Complete after retry" : "Complete";
  }
  return "Waiting on dependency";
}

function levelName(severity: LogSeverity): Exclude<LogLevelFilter, "all"> {
  return severity === "warning" ? "warn" : severity;
}

function levelLabel(level: Exclude<LogLevelFilter, "all">) {
  return level === "warn" ? "Warning" : titleCase(level);
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
  const [logsLoadingOlder, setLogsLoadingOlder] = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [jobSearch, setJobSearch] = useState("");
  const [logSearch, setLogSearch] = useState("");
  const [logLevel, setLogLevel] = useState<LogLevelFilter>("all");
  const [logCategory, setLogCategory] = useState<"all" | LogCategory>("all");
  const [selectedLogKey, setSelectedLogKey] = useState<string | null>(null);
  const mainPanelRef = useRef<HTMLElement>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const paginationRef = useRef<HTMLDivElement>(null);
  const eventInspectorBackRef = useRef<HTMLButtonElement>(null);
  const lastInspectButtonRef = useRef<HTMLButtonElement | null>(null);
  const rightRailBeforeInspectRef = useRef(false);
  const feedScrollBeforeInspectRef = useRef<number | null>(null);
  const preserveScrollHeightRef = useRef<number | null>(null);
  const scrollToNewestRef = useRef(false);

  const fetchJobs = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const response = await fetch("/api/jobs", { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Unable to load jobs.");
      setPayload(body);
      setError(null);
      setSelectedId((current) => {
        if (current && body.jobs.some((job: ViewerJob) => job.id === current)) {
          return current;
        }
        return (
          body.jobs.find((job: ViewerJob) => ACTIVE_STATUSES.has(job.status))?.id ||
          body.jobs[0]?.id ||
          null
        );
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load jobs.");
    } finally {
      setIsRefreshing(false);
      setCountdown(REFRESH_SECONDS);
    }
  }, []);

  const fetchLogs = useCallback(
    async (
      jobId: string,
      cursor?: string | null,
      mode: LogMergeMode = "refresh",
    ) => {
      setLogsLoading(true);
      if (mode === "replace") scrollToNewestRef.current = true;
      setLogs((current) => (current?.jobId === jobId ? current : null));
      try {
        const body = await requestLogPage(jobId, cursor);
        setLogs((current) => mergeLogPayload(current, body, mode));
        setLogsError(null);
      } catch (cause) {
        setLogsError(
          cause instanceof Error ? cause.message : "Unable to load logs.",
        );
      } finally {
        setLogsLoading(false);
      }
    },
    [],
  );

  const loadOlderLogs = useCallback(async () => {
    if (
      !selectedId ||
      !logs ||
      logs.jobId !== selectedId ||
      logs.isDone ||
      !logs.continueCursor ||
      logsLoadingOlder
    ) {
      return;
    }
    preserveScrollHeightRef.current = feedRef.current?.scrollHeight || null;
    setLogsLoadingOlder(true);
    try {
      const body = await requestLogPage(selectedId, logs.continueCursor);
      setLogs((current) => mergeLogPayload(current, body, "prepend"));
      setLogsError(null);
    } catch (cause) {
      setLogsError(
        cause instanceof Error ? cause.message : "Unable to load older logs.",
      );
    } finally {
      setLogsLoadingOlder(false);
    }
  }, [logs, logsLoadingOlder, selectedId]);

  useEffect(() => {
    const query = window.matchMedia(MOBILE_QUERY);
    const applyViewport = () => {
      const mobile = query.matches;
      setIsMobile(mobile);
      const savedLeft = window.localStorage.getItem(LEFT_RAIL_KEY);
      const savedRight = window.localStorage.getItem(RIGHT_RAIL_KEY);
      setLeftCollapsed(savedLeft === null ? mobile : savedLeft === "true");
      setRightCollapsed(savedRight === null ? mobile : savedRight === "true");
    };
    applyViewport();
    query.addEventListener("change", applyViewport);
    return () => query.removeEventListener("change", applyViewport);
  }, []);

  useEffect(() => {
    const initialTimer = window.setTimeout(() => void fetchJobs(), 0);
    const refreshTimer = window.setInterval(
      () => void fetchJobs(),
      REFRESH_SECONDS * 1_000,
    );
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
    const initialTimer = window.setTimeout(
      () => void fetchLogs(selectedId, null, "replace"),
      0,
    );
    const timer = window.setInterval(
      () => void fetchLogs(selectedId, null, "refresh"),
      REFRESH_SECONDS * 1_000,
    );
    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(timer);
    };
  }, [fetchLogs, selectedId, tab]);

  useLayoutEffect(() => {
    mainPanelRef.current?.scrollTo({ top: 0 });
  }, [selectedId, tab]);

  useLayoutEffect(() => {
    const feed = feedRef.current;
    if (!feed) return;
    if (scrollToNewestRef.current) {
      feed.scrollTop = feed.scrollHeight;
      scrollToNewestRef.current = false;
      return;
    }
    if (preserveScrollHeightRef.current !== null) {
      const previousHeight = preserveScrollHeightRef.current;
      feed.scrollTop += Math.max(0, feed.scrollHeight - previousHeight);
      preserveScrollHeightRef.current = null;
    }
  }, [logs?.events.length]);

  useEffect(() => {
    const sentinel = paginationRef.current;
    const feed = feedRef.current;
    if (
      tab !== "logs" ||
      !sentinel ||
      !feed ||
      !logs ||
      logs.isDone ||
      !logs.continueCursor ||
      selectedLogKey !== null
    ) {
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) void loadOlderLogs();
      },
      { root: feed, rootMargin: "180px 0px 0px", threshold: 0.01 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadOlderLogs, logs, selectedLogKey, tab]);

  const jobs = payload?.jobs || [];
  const selected = jobs.find((job) => job.id === selectedId) || null;
  const runJobs = selected
    ? jobs.filter((job) => job.runId === selected.runId)
    : [];
  const progress =
    selected?.progress || runJobs.find((job) => job.progress)?.progress || null;
  const workflow = selected
    ? WORKFLOW.map((step) => ({
        ...step,
        ...workflowState(step.id, selected, runJobs),
      }))
    : [];

  const normalizedJobSearch = jobSearch.trim().toLocaleLowerCase();
  const visibleJobs = normalizedJobSearch
    ? jobs.filter((job) =>
        [job.name, job.runId, job.stage, job.status, job.queue]
          .join(" ")
          .toLocaleLowerCase()
          .includes(normalizedJobSearch),
      )
    : jobs;
  const activeJobs = visibleJobs.filter((job) => ACTIVE_STATUSES.has(job.status));
  const recentJobs = visibleJobs.filter((job) => !ACTIVE_STATUSES.has(job.status));

  const displayedLogs = logs?.jobId === selectedId ? logs : null;
  const adaptedLogs = useMemo(
    () =>
      (displayedLogs?.events || []).map((event) => ({
        event,
        adapted: adaptLogMessage(event.message),
      })),
    [displayedLogs],
  );
  const categoryOptions = useMemo(
    () =>
      [...new Set(adaptedLogs.map(({ adapted }) => adapted.category))].sort(),
    [adaptedLogs],
  );
  const normalizedLogSearch = logSearch.trim().toLocaleLowerCase();
  const filteredLogs = useMemo(
    () =>
      adaptedLogs.filter(({ adapted }) => {
        const matchesSearch =
          !normalizedLogSearch || adapted.searchText.includes(normalizedLogSearch);
        const matchesLevel =
          logLevel === "all" || levelName(adapted.severity) === logLevel;
        const matchesCategory =
          logCategory === "all" || adapted.category === logCategory;
        return matchesSearch && matchesLevel && matchesCategory;
      }),
    [adaptedLogs, logCategory, logLevel, normalizedLogSearch],
  );
  const selectedLogEvent = selectedLogKey
    ? adaptedLogs.find(({ event }) => event.eventKey === selectedLogKey) || null
    : null;

  useEffect(() => {
    if (!selectedLogEvent || !isMobile || rightCollapsed) return;
    eventInspectorBackRef.current?.focus();
  }, [isMobile, rightCollapsed, selectedLogEvent]);

  const inspectLogEvent = (
    eventKey: string,
    trigger: HTMLButtonElement,
  ) => {
    lastInspectButtonRef.current = trigger;
    rightRailBeforeInspectRef.current = rightCollapsed;
    feedScrollBeforeInspectRef.current = feedRef.current?.scrollTop ?? null;
    setSelectedLogKey(eventKey);
    setRightCollapsed(false);
    if (isMobile) {
      setLeftCollapsed(true);
      window.localStorage.setItem(LEFT_RAIL_KEY, "true");
    }
  };

  const closeEventInspector = () => {
    setSelectedLogKey(null);
    if (rightRailBeforeInspectRef.current) setRightCollapsed(true);
    window.requestAnimationFrame(() => {
      if (lastInspectButtonRef.current?.isConnected) {
        lastInspectButtonRef.current.focus({ preventScroll: true });
      }
      if (feedRef.current && feedScrollBeforeInspectRef.current !== null) {
        feedRef.current.scrollTop = feedScrollBeforeInspectRef.current;
      }
    });
  };

  useEffect(() => {
    if (!selectedLogEvent) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeEventInspector();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  const toggleLeftRail = () => {
    const next = !leftCollapsed;
    setLeftCollapsed(next);
    window.localStorage.setItem(LEFT_RAIL_KEY, String(next));
    if (!next && isMobile) {
      setRightCollapsed(true);
      window.localStorage.setItem(RIGHT_RAIL_KEY, "true");
    }
  };

  const toggleRightRail = () => {
    const next = !rightCollapsed;
    setRightCollapsed(next);
    window.localStorage.setItem(RIGHT_RAIL_KEY, String(next));
    if (!next && isMobile) {
      setLeftCollapsed(true);
      window.localStorage.setItem(LEFT_RAIL_KEY, "true");
    }
  };

  const selectJob = (jobId: string) => {
    setSelectedLogKey(null);
    lastInspectButtonRef.current = null;
    setSelectedId(jobId);
  };

  const selectTab = (nextTab: "overview" | "logs") => {
    setSelectedLogKey(null);
    lastInspectButtonRef.current = null;
    setTab(nextTab);
  };

  const runHealth = {
    active: runJobs.filter((job) => statusIsActive(job.status)).length,
    succeeded: runJobs.filter((job) => job.status === "SUCCEEDED").length,
    failed: runJobs.filter((job) => job.status === "FAILED").length,
  };
  const workflowComplete = workflow.filter((step) => step.state === "complete").length;
  const currentStep =
    workflow.find((step) => step.state === "active") ||
    workflow.find((step) => step.state === "failed") ||
    workflow.find((step) => step.state === "queued") ||
    workflow.at(-1);

  return (
    <main className="viewer-shell">
      <header className="topbar">
        <div className="topbar-start">
          <button
            className="rail-toggle"
            data-testid="toggle-left-rail"
            aria-expanded={!leftCollapsed}
            aria-controls="job-navigation"
            aria-label={leftCollapsed ? "Open job rail" : "Collapse job rail"}
            onClick={toggleLeftRail}
          >
            <span className="panel-icon panel-icon-left" aria-hidden="true" />
          </button>
          <div className="brand-lockup">
            <span className="brand-mark" aria-hidden="true">D</span>
            <div>
              <p className="eyebrow">Diana Compute</p>
              <h1>Run monitor <span>v2</span></h1>
            </div>
          </div>
        </div>

        <div className="topbar-meta">
          <div className="connection-state">
            <span className={`live-dot ${error ? "is-error" : ""}`} aria-hidden="true" />
            <span>{error ? "Connection issue" : "Live"}</span>
          </div>
          <span className="region-label">{payload?.region || "us-east-1"}</span>
          <span className="refresh-label">Next sync {countdown}s</span>
          <button
            className="refresh-button"
            onClick={() => void fetchJobs()}
            disabled={isRefreshing}
          >
            <span aria-hidden="true">↻</span>
            {isRefreshing ? "Syncing" : "Sync now"}
          </button>
          <button
            className="rail-toggle"
            data-testid="toggle-right-rail"
            aria-expanded={!rightCollapsed}
            aria-controls="event-inspector"
            aria-label={rightCollapsed ? "Open context inspector" : "Collapse context inspector"}
            onClick={toggleRightRail}
          >
            <span className="panel-icon panel-icon-right" aria-hidden="true" />
          </button>
        </div>
      </header>

      <div
        className="workspace"
        data-left-collapsed={leftCollapsed}
        data-right-collapsed={rightCollapsed}
      >
        <aside
          id="job-navigation"
          className="workspace-rail job-rail"
          data-testid="left-rail"
          data-collapsed={leftCollapsed}
          aria-label="AWS Batch jobs"
        >
          <div className="rail-heading">
            <div>
              <p className="eyebrow">Workspace</p>
              <h2>Jobs</h2>
            </div>
            <span className="count-badge">{jobs.filter((job) => statusIsActive(job.status)).length} live</span>
          </div>

          <label className="rail-search">
            <span className="sr-only">Search jobs</span>
            <span aria-hidden="true">⌕</span>
            <input
              value={jobSearch}
              onChange={(event) => setJobSearch(event.target.value)}
              placeholder="Search run, stage, status…"
            />
            {jobSearch && (
              <button onClick={() => setJobSearch("")} aria-label="Clear job search">×</button>
            )}
          </label>

          {error && (
            <div className="rail-error" role="alert">
              <strong>Unable to reach AWS</strong>
              <span>{error}</span>
            </div>
          )}
          {!payload && !error && <JobRailSkeleton />}
          {payload && visibleJobs.length === 0 && (
            <p className="rail-empty">
              {jobSearch ? "No jobs match this search." : "No active or recent jobs found."}
            </p>
          )}
          {activeJobs.length > 0 && (
            <JobGroup
              title="Running now"
              jobs={activeJobs}
              selectedId={selectedId}
              onSelect={selectJob}
            />
          )}
          {recentJobs.length > 0 && (
            <JobGroup
              title="Last 24 hours"
              jobs={recentJobs}
              selectedId={selectedId}
              onSelect={selectJob}
            />
          )}

          <div className="rail-footer">
            <span>Last sync</span>
            <time>{payload ? formatDate(payload.generatedAt) : "Waiting…"}</time>
          </div>
        </aside>

        <section
          className="main-panel"
          data-active-tab={tab}
          inert={isMobile && Boolean(selectedLogEvent) && !rightCollapsed}
          ref={mainPanelRef}
        >
          {!selected ? (
            <div className="empty-state">
              <span className="empty-glyph" aria-hidden="true">⌁</span>
              <p className="eyebrow">Run workspace</p>
              <h2>{error ? "Viewer is offline" : "No job selected"}</h2>
              <p>
                {error
                  ? "Add read-only AWS credentials to the server and refresh."
                  : "Running and recent jobs will appear here automatically."}
              </p>
            </div>
          ) : (
            <>
              <div className="job-heading">
                <div className="job-heading-copy">
                  <div className="job-heading-line">
                    <span className={`status-pill status-${selected.status.toLowerCase()}`}>
                      <span aria-hidden="true" />
                      {statusLabel(selected.status)}
                    </span>
                    <span className="stage-label">{titleCase(selected.stage)}</span>
                    <span className="job-heading-separator" aria-hidden="true">/</span>
                    <span className="run-id-compact">{selected.runId}</span>
                  </div>
                  <h2>{selected.name}</h2>
                </div>
                <dl className="heading-facts">
                  <div><dt>Queue</dt><dd>{selected.queue || "—"}</dd></div>
                  <div><dt>Elapsed</dt><dd>{formatElapsed(selected.startedAt, selected.stoppedAt)}</dd></div>
                  <div><dt>Attempts</dt><dd>{selected.attempts || 1}</dd></div>
                </dl>
              </div>

              <div className="tabs" role="tablist" aria-label="Job details">
                <button
                  role="tab"
                  aria-selected={tab === "overview"}
                  onClick={() => selectTab("overview")}
                >
                  Overview
                </button>
                <button
                  role="tab"
                  aria-selected={tab === "logs"}
                  onClick={() => selectTab("logs")}
                >
                  Logs
                  {selected.logStreamName && <span className="tab-live-dot" aria-hidden="true" />}
                </button>
              </div>

              {tab === "overview" ? (
                <div className="overview-content">
                  {selected.statusReason && (
                    <div className={`status-note status-note-${selected.status.toLowerCase()}`}>
                      <span aria-hidden="true">{selected.status === "FAILED" ? "!" : "i"}</span>
                      <p>{selected.statusReason}</p>
                    </div>
                  )}

                  <section className="run-narrative" aria-label="Run summary">
                    <div className="run-narrative-copy">
                      <p className="eyebrow">Current run</p>
                      <h3>{currentStep?.label || "Preparing workflow"}</h3>
                      <p>{currentStep?.detail || "Waiting for the first observed stage."}</p>
                    </div>
                    <div className="run-progress-summary">
                      <div>
                        <strong>{progress ? `${progress.genomePercent.toFixed(1)}%` : `${Math.round((workflowComplete / WORKFLOW.length) * 100)}%`}</strong>
                        <span>{progress ? "genome traversed" : "workflow observed"}</span>
                      </div>
                      <div className="run-progress-track" role="progressbar" aria-label="Overall run progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress?.genomePercent || (workflowComplete / WORKFLOW.length) * 100)}>
                        <span style={{ width: `${clamp(progress?.genomePercent || (workflowComplete / WORKFLOW.length) * 100)}%` }} />
                      </div>
                    </div>
                  </section>

                  <section className="metrics-grid" aria-label="Run metrics">
                    <Metric
                      label="Genome traversed"
                      value={progress ? `${progress.genomePercent.toFixed(1)}%` : "—"}
                      detail={progress ? `${progress.started} of 23 chromosomes started` : "Waiting for progress events"}
                      accent
                    />
                    <Metric
                      label="Active shards"
                      value={progress ? String(progress.active) : selected.status === "RUNNING" ? "1" : "0"}
                      detail={progress ? `${progress.completed} complete · ${progress.queued} queued` : "Batch containers observed"}
                    />
                    <Metric
                      label="Throughput"
                      value={progress?.rateMbPerMinute ? `${progress.rateMbPerMinute.toFixed(1)} Mb/min` : "—"}
                      detail="Observed from GATK progress"
                    />
                    <Metric
                      label="Compute ETA"
                      value={progress ? formatEta(progress.etaSeconds) : "Calculating"}
                      detail="Evidence stage estimate"
                    />
                  </section>

                  <section className="workflow-board card" data-testid="workflow-progress">
                    <div className="section-heading">
                      <div>
                        <p className="eyebrow">Dependency map</p>
                        <h3>Run progress</h3>
                      </div>
                      <span>{runJobs.length} related Batch {runJobs.length === 1 ? "job" : "jobs"}</span>
                    </div>
                    <ol className="workflow-grid">
                      {workflow.map((step) => (
                        <li
                          key={step.id}
                          className={`workflow-step is-${step.state}`}
                          data-state={step.state}
                        >
                          <div className="step-topline">
                            <span className="step-index">{step.index}</span>
                            <span className="step-state-icon" aria-hidden="true">
                              {step.state === "complete" ? "✓" : step.state === "failed" ? "!" : step.state === "active" ? "●" : ""}
                            </span>
                          </div>
                          <div className="step-copy">
                            <strong>{step.label}</strong>
                            <span>{step.detail}</span>
                          </div>
                          <div className="step-footer">
                            <span className="step-state-label">{stateNarrative(step.state, step.jobs)}</span>
                            {step.jobs.length > 0 && <span>{step.jobs.length} {step.jobs.length === 1 ? "job" : "jobs"}</span>}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </section>

                  <section className="card chromosome-card">
                    <div className="section-heading chromosome-heading">
                      <div>
                        <p className="eyebrow">Mutect2 shards</p>
                        <h3>Chromosome progress</h3>
                      </div>
                      {progress && (
                        <div className="chromosome-legend">
                          <span><i className="legend-complete" />{progress.completed} complete</span>
                          <span><i className="legend-active" />{progress.active} active</span>
                          <span><i />{progress.queued} queued</span>
                        </div>
                      )}
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
                      <p className="card-empty">
                        Chromosome-level progress will appear when GATK progress events reach CloudWatch.
                      </p>
                    )}
                  </section>
                </div>
              ) : (
                <section className="logs-panel">
                  <div className="logs-heading">
                    <div>
                      <p className="eyebrow">Persistent CloudWatch archive</p>
                      <h3>Event stream</h3>
                      <span title={displayedLogs?.logStreamName || selected.logStreamName || ""}>
                        {displayedLogs?.logStreamName || selected.logStreamName || "Log stream pending"}
                      </span>
                    </div>
                    <div className="logs-heading-meta">
                      <strong>{displayedLogs ? displayedLogs.totalEvents.toLocaleString() : "—"}</strong>
                      <span>stored events</span>
                    </div>
                  </div>

                  <div className="logs-toolbar" aria-label="Log search and filters">
                    <label className="log-search-field">
                      <span aria-hidden="true">⌕</span>
                      <span className="sr-only">Search log events</span>
                      <input
                        data-testid="log-search"
                        value={logSearch}
                        onChange={(event) => setLogSearch(event.target.value)}
                        placeholder="Search messages, paths, chromosomes…"
                      />
                      <kbd>/</kbd>
                    </label>
                    <label className="filter-field">
                      <span>Level</span>
                      <select
                        data-testid="log-level-filter"
                        value={logLevel}
                        onChange={(event) => setLogLevel(event.target.value as LogLevelFilter)}
                      >
                        <option value="all">All levels</option>
                        <option value="info">Info</option>
                        <option value="success">Success</option>
                        <option value="warn">Warnings</option>
                        <option value="error">Errors</option>
                      </select>
                    </label>
                    <label className="filter-field">
                      <span>Type</span>
                      <select
                        data-testid="log-category-filter"
                        value={logCategory}
                        onChange={(event) => setLogCategory(event.target.value as "all" | LogCategory)}
                      >
                        <option value="all">All event types</option>
                        {categoryOptions.map((category) => (
                          <option key={category} value={category}>{titleCase(category)}</option>
                        ))}
                      </select>
                    </label>
                    <button
                      className="logs-refresh-button"
                      onClick={() => void fetchLogs(selected.id, null, "refresh")}
                      disabled={logsLoading}
                    >
                      <span aria-hidden="true">↻</span>
                      {logsLoading ? "Syncing" : "Refresh"}
                    </button>
                  </div>

                  <div className="logs-result-bar">
                    <span>
                      Showing <strong>{filteredLogs.length.toLocaleString()}</strong> of {displayedLogs?.events.length.toLocaleString() || 0} loaded
                    </span>
                    {(logSearch || logLevel !== "all" || logCategory !== "all") && (
                      <button onClick={() => { setLogSearch(""); setLogLevel("all"); setLogCategory("all"); }}>
                        Clear filters
                      </button>
                    )}
                    {displayedLogs?.backfillComplete && <span className="archive-state"><i />Archive complete</span>}
                  </div>

                  {logsError && !displayedLogs ? (
                    <LogsEmpty
                      title="Logs unavailable"
                      detail={logsError}
                      action={() => void fetchLogs(selected.id, null, "replace")}
                    />
                  ) : !selected.logStreamName ? (
                    <LogsEmpty
                      title="Log stream not created yet"
                      detail="CloudWatch logs become available after the Batch container starts."
                    />
                  ) : logsLoading && !displayedLogs ? (
                    <LogsEmpty
                      title="Reading the persistent archive…"
                      detail="Syncing CloudWatch into Convex and loading the newest page."
                    />
                  ) : (
                    <div className="log-feed" data-testid="log-feed" ref={feedRef}>
                      <div
                        className="log-pagination-sentinel"
                        data-testid="log-pagination-sentinel"
                        ref={paginationRef}
                      >
                        {displayedLogs && !displayedLogs.isDone ? (
                          <button onClick={() => void loadOlderLogs()} disabled={logsLoadingOlder}>
                            <span className={logsLoadingOlder ? "loading-spinner" : "history-glyph"} aria-hidden="true">{logsLoadingOlder ? "" : "↑"}</span>
                            {logsLoadingOlder ? "Loading earlier events…" : "Scroll for earlier events"}
                          </button>
                        ) : (
                          <span>Beginning of retained archive</span>
                        )}
                      </div>

                      {logsError && displayedLogs && (
                        <div className="inline-log-error" role="alert">
                          <span>{logsError}</span>
                          <button onClick={() => void loadOlderLogs()}>Retry</button>
                        </div>
                      )}

                      {filteredLogs.length > 0 ? (
                        <div className="log-event-list">
                          {filteredLogs.map(({ event, adapted }) => (
                            <LogEventRow
                              key={event.eventKey}
                              event={event}
                              adapted={adapted}
                              search={logSearch}
                              selected={event.eventKey === selectedLogKey}
                              onInspect={inspectLogEvent}
                            />
                          ))}
                        </div>
                      ) : displayedLogs?.events.length ? (
                        <div className="logs-no-match">
                          <strong>No matching events</strong>
                          <span>Try a broader search or clear one of the active filters.</span>
                        </div>
                      ) : (
                        <div className="logs-no-match">
                          <strong>No log events yet</strong>
                          <span>The archive will retry automatically on the next sync.</span>
                        </div>
                      )}
                    </div>
                  )}
                </section>
              )}
            </>
          )}
        </section>

        <aside
          id="event-inspector"
          className="workspace-rail inspector-rail"
          data-testid="right-rail"
          data-collapsed={rightCollapsed}
          data-mode={selectedLogEvent ? "event" : "run"}
          aria-label={selectedLogEvent ? "Event inspector" : "Run inspector"}
          aria-labelledby={selectedLogEvent ? "event-inspector-title" : undefined}
          aria-modal={selectedLogEvent && isMobile ? true : undefined}
          role={selectedLogEvent && isMobile ? "dialog" : undefined}
        >
          {selectedLogEvent ? (
            <EventInspector
              entry={selectedLogEvent}
              backRef={eventInspectorBackRef}
              onBack={closeEventInspector}
            />
          ) : selected ? (
            <>
              <div className="inspector-heading">
                <p className="eyebrow">Run inspector</p>
                <h2>Context</h2>
              </div>

              <section className="inspector-section health-section">
                <div className="inspector-section-title">
                  <h3>Run health</h3>
                  <span>{runJobs.length} jobs</span>
                </div>
                <div className="health-grid">
                  <div className="health-active"><strong>{runHealth.active}</strong><span>Active</span></div>
                  <div className="health-success"><strong>{runHealth.succeeded}</strong><span>Passed</span></div>
                  <div className="health-failed"><strong>{runHealth.failed}</strong><span>Failed</span></div>
                </div>
              </section>

              <section className="inspector-section">
                <div className="inspector-section-title"><h3>Execution</h3></div>
                <dl className="detail-list">
                  <div><dt>Created</dt><dd>{formatDate(selected.createdAt)}</dd></div>
                  <div><dt>Started</dt><dd>{formatDate(selected.startedAt)}</dd></div>
                  <div><dt>Stopped</dt><dd>{formatDate(selected.stoppedAt)}</dd></div>
                  <div><dt>Stage</dt><dd>{titleCase(selected.stage)}</dd></div>
                  <div><dt>Dependencies</dt><dd>{selected.dependsOn.length || "None"}</dd></div>
                  <div><dt>Attempts</dt><dd>{selected.attempts || 1}</dd></div>
                </dl>
              </section>

              <section className="inspector-section">
                <div className="inspector-section-title"><h3>Identifiers</h3></div>
                <dl className="identity-list">
                  <div><dt>Run ID</dt><dd title={selected.runId}>{selected.runId}</dd></div>
                  <div><dt>Job ID</dt><dd title={selected.id}>{selected.id}</dd></div>
                  <div><dt>Log stream</dt><dd title={selected.logStreamName || ""}>{selected.logStreamName || "Pending"}</dd></div>
                </dl>
              </section>

              <div className="interpretation-note">
                <div className="boundary-icon" aria-hidden="true">◇</div>
                <div>
                  <strong>Output boundary</strong>
                  <p>Exploratory HRD evidence only. This viewer does not produce a clinically validated scalar HRD call.</p>
                </div>
              </div>
            </>
          ) : (
            <p className="rail-empty">Select a job to inspect run context.</p>
          )}
        </aside>
      </div>
      {selectedLogEvent && isMobile && !rightCollapsed && (
        <button
          className="rail-backdrop"
          aria-label="Close event inspector"
          onClick={closeEventInspector}
        />
      )}
    </main>
  );
}

function JobGroup({
  title,
  jobs,
  selectedId,
  onSelect,
}: {
  title: string;
  jobs: ViewerJob[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="job-group">
      <h3>{title}<span>{jobs.length}</span></h3>
      <div className="job-list">
        {jobs.map((job) => (
          <button
            key={job.id}
            className={`job-row ${job.id === selectedId ? "is-selected" : ""}`}
            onClick={() => onSelect(job.id)}
            aria-pressed={job.id === selectedId}
          >
            <span className={`job-status-mark status-${job.status.toLowerCase()}`} aria-hidden="true">
              <i />
            </span>
            <span className="job-row-copy">
              <strong title={job.name}>{job.name}</strong>
              <span>{titleCase(job.stage)} · {formatElapsed(job.startedAt, job.stoppedAt)}</span>
            </span>
            {job.progress ? (
              <span className="job-percent">{job.progress.genomePercent.toFixed(0)}%</span>
            ) : (
              <span className="job-status-text">{statusLabel(job.status)}</span>
            )}
          </button>
        ))}
      </div>
    </section>
  );
}

function JobRailSkeleton() {
  return (
    <div className="job-skeleton" aria-label="Discovering Batch queues">
      {Array.from({ length: 5 }, (_, index) => <span key={index} />)}
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
  accent = false,
}: {
  label: string;
  value: string;
  detail: string;
  accent?: boolean;
}) {
  return (
    <div className={`metric ${accent ? "is-accent" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function ChromosomeBar({ name, chromosome }: { name: string; chromosome?: Chromosome }) {
  const percent = clamp(chromosome?.percent || 0);
  const state = !chromosome
    ? "queued"
    : percent >= 99.9
      ? "complete"
      : chromosome.active
        ? "active"
        : "waiting";
  return (
    <div className={`chromosome-row is-${state}`}>
      <div>
        <strong>{name.replace("chr", "")}</strong>
        <span>{chromosome ? formatBases(chromosome.position) : "queued"}</span>
      </div>
      <div
        className="progress-track"
        aria-label={`${name} ${percent.toFixed(1)} percent`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <span>{chromosome ? `${percent.toFixed(0)}%` : "—"}</span>
    </div>
  );
}

function LogEventRow({
  event,
  adapted,
  search,
  selected,
  onInspect,
}: {
  event: LogEvent;
  adapted: AdaptedLogEvent;
  search: string;
  selected: boolean;
  onInspect: (eventKey: string, trigger: HTMLButtonElement) => void;
}) {
  const level = levelName(adapted.severity);
  const metadata = Object.entries(adapted.metadata)
    .filter((entry): entry is [string, string | number | boolean] => entry[1] !== undefined)
    .filter(([key]) => !["level", "category", "event", "message"].includes(key))
    .slice(0, 5);
  return (
    <article
      className={`log-event ${adapted.type}`}
      data-testid="log-event"
      data-level={level}
      data-category={adapted.category}
      data-selected={selected}
      aria-label={`${levelLabel(level)} ${adapted.title}: ${adapted.detail}`}
    >
      <time dateTime={new Date(event.timestamp).toISOString()} title={formatDate(event.timestamp)}>
        {formatClock(event.timestamp)}
      </time>
      <span className={`log-level log-level-${level}`}>{levelLabel(level)}</span>
      <span className="log-event-glyph" aria-hidden="true">
        {adapted.category === "progress" ? "↗" : adapted.category === "artifact" ? "◇" : adapted.severity === "error" ? "!" : adapted.severity === "warning" ? "△" : adapted.severity === "success" ? "✓" : "·"}
      </span>
      <div className="log-event-body">
        <div className="log-event-titleline">
          <strong>{adapted.title}</strong>
          <span>{adapted.source}</span>
          <span>{titleCase(adapted.category)}</span>
        </div>
        <p><HighlightedText text={adapted.detail} search={search} /></p>
        {metadata.length > 0 && (
          <dl className="log-metadata">
            {metadata.map(([key, value]) => (
              <div key={key}><dt>{titleCase(key)}</dt><dd>{String(value)}</dd></div>
            ))}
          </dl>
        )}
      </div>
      <button
        className="event-inspect-button"
        data-testid="inspect-log-event"
        aria-controls="event-inspector"
        aria-expanded={selected}
        aria-label={`Inspect ${adapted.title} at ${formatClock(event.timestamp)}`}
        onClick={(clickEvent) => onInspect(event.eventKey, clickEvent.currentTarget)}
      >
        <span aria-hidden="true">↗</span>
        <span className="event-inspect-label">{selected ? "Selected" : "Inspect"}</span>
      </button>
    </article>
  );
}

function EventInspector({
  entry,
  backRef,
  onBack,
}: {
  entry: { event: LogEvent; adapted: AdaptedLogEvent };
  backRef: React.RefObject<HTMLButtonElement | null>;
  onBack: () => void;
}) {
  const { event, adapted } = entry;
  const level = levelName(adapted.severity);
  const metadata = Object.entries(adapted.metadata).filter(
    (item): item is [string, string | number | boolean] => item[1] !== undefined,
  );

  return (
    <div className="event-inspector-content" data-testid="event-inspector-content">
      <div className="event-inspector-heading">
        <p className="eyebrow">Event inspector</p>
        <button ref={backRef} onClick={onBack}>
          <span aria-hidden="true">←</span>
          Back to run
        </button>
      </div>

      <section className="event-inspector-summary">
        <span className="log-event-glyph" aria-hidden="true">
          {adapted.category === "progress" ? "↗" : adapted.category === "artifact" ? "◇" : adapted.severity === "error" ? "!" : adapted.severity === "warning" ? "△" : adapted.severity === "success" ? "✓" : "·"}
        </span>
        <div>
          <h2 id="event-inspector-title">{adapted.title}</h2>
          <div className="event-inspector-badges">
            <span data-level={level}>{levelLabel(level)}</span>
            <span>{titleCase(adapted.category)}</span>
            <span>{adapted.source}</span>
          </div>
        </div>
        <time dateTime={new Date(event.timestamp).toISOString()}>
          {formatDate(event.timestamp)}
        </time>
      </section>

      <section className="inspector-section event-message-section">
        <div className="inspector-section-title"><h3>Message</h3></div>
        <p>{adapted.detail}</p>
      </section>

      {metadata.length > 0 && (
        <section className="inspector-section">
          <div className="inspector-section-title"><h3>Parsed fields</h3></div>
          <dl className="event-field-list">
            {metadata.map(([key, value]) => (
              <div key={key}><dt>{titleCase(key)}</dt><dd>{String(value)}</dd></div>
            ))}
          </dl>
        </section>
      )}

      <section className="inspector-section">
        <div className="inspector-section-title"><h3>Provenance</h3></div>
        <dl className="event-field-list">
          <div><dt>Event key</dt><dd title={event.eventKey}>{event.eventKey}</dd></div>
          <div><dt>Ingested</dt><dd>{formatDate(event.ingestionTime)}</dd></div>
          <div><dt>Log stream</dt><dd title={event.logStreamName}>{event.logStreamName}</dd></div>
        </dl>
      </section>

      <section className="inspector-section event-raw-section">
        <div className="inspector-section-title"><h3>Raw payload</h3></div>
        <pre>{adapted.raw}</pre>
      </section>
    </div>
  );
}

function HighlightedText({ text, search }: { text: string; search: string }) {
  const query = search.trim();
  if (!query) return text;
  const parts = text.split(new RegExp(`(${escapeRegExp(query)})`, "ig"));
  return parts.map((part, index) =>
    part.toLocaleLowerCase() === query.toLocaleLowerCase() ? (
      <mark key={`${part}-${index}`}>{part}</mark>
    ) : (
      part
    ),
  );
}

function LogsEmpty({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: () => void;
}) {
  return (
    <div className="logs-empty" role={title.includes("unavailable") ? "alert" : undefined}>
      <span className="empty-log-glyph" aria-hidden="true">≋</span>
      <strong>{title}</strong>
      <span>{detail}</span>
      {action && <button onClick={action}>Try again</button>}
    </div>
  );
}
