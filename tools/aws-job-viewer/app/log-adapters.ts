export type LogCategory =
  | "progress"
  | "success"
  | "warning"
  | "error"
  | "process"
  | "artifact"
  | "info";

export type LogSeverity = "info" | "success" | "warning" | "error";

export type LogSource =
  | "diana"
  | "aws"
  | "nextflow"
  | "gatk"
  | "shell"
  | "json"
  | "generic";

export type LogTypeIdentifier = `log-${LogCategory}`;
export type LogMetadataValue = string | number | boolean;

export type LogMetadata = {
  chromosome?: string;
  position?: number;
  percent?: number;
  process?: string;
  path?: string;
  exitCode?: number;
  [key: string]: LogMetadataValue | undefined;
};

export type AdaptedLogEvent = {
  raw: string;
  category: LogCategory;
  severity: LogSeverity;
  type: LogTypeIdentifier;
  source: LogSource;
  title: string;
  detail: string;
  metadata: LogMetadata;
  searchText: string;
};

type EventFields = Omit<AdaptedLogEvent, "raw" | "type" | "searchText">;
type JsonRecord = Record<string, unknown>;

const ANSI_ESCAPE = /\u001b\[[0-?]*[ -/]*[@-~]/g;
const GATK_PROGRESS =
  /ProgressMeter\s+-\s+(chr(?:\d{1,2}|X|Y|M|MT))(?::(\d+))?/i;
const PERCENT = /(?:^|[\s[(])([0-9]+(?:\.[0-9]+)?)\s*%/;
const PATH = /(?:s3|https?):\/\/[^\s'"),;]+|(?:\.{0,2}\/|\b(?:data|results|workspace|nextflow-out)\/)[^\s'"),;]+/i;
const KEY_VALUE = /\b([A-Za-z][\w.-]*)=(?:"([^"]*)"|'([^']*)'|([^\s,]+))/g;

function stripAnsi(value: string) {
  return value.replace(ANSI_ESCAPE, "");
}

function normalizeForParsing(raw: string) {
  return stripAnsi(raw).replaceAll("\r", "").trim();
}

function compactWhitespace(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function humanize(value: string) {
  return value
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[._:-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^./, (letter) => letter.toUpperCase());
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || value.trim() === "") return undefined;
  const parsed = Number(value.replaceAll(",", ""));
  return Number.isFinite(parsed) ? parsed : undefined;
}

function metadataValue(value: string): LogMetadataValue {
  const normalized = value.replace(/[.;]$/, "");
  const numeric = numberValue(normalized);
  if (numeric !== undefined) return numeric;
  if (normalized === "true") return true;
  if (normalized === "false") return false;
  return normalized;
}

function metadataKey(value: string) {
  return value.replace(/[-_.]+([A-Za-z0-9])/g, (_, letter: string) =>
    letter.toUpperCase(),
  );
}

function inlineMetadata(text: string): LogMetadata {
  const metadata: LogMetadata = {};
  for (const match of text.matchAll(KEY_VALUE)) {
    metadata[metadataKey(match[1])] = metadataValue(
      match[2] ?? match[3] ?? match[4] ?? "",
    );
  }
  const path = text.match(PATH)?.[0];
  if (path) metadata.path = path;
  return metadata;
}

function metadataEntries(metadata: LogMetadata) {
  return Object.entries(metadata).filter(
    (entry): entry is [string, LogMetadataValue] => entry[1] !== undefined,
  );
}

function finish(raw: string, fields: EventFields): AdaptedLogEvent {
  const metadataText = metadataEntries(fields.metadata)
    .map(([key, value]) => `${key} ${String(value)}`)
    .join(" ");
  const searchText = compactWhitespace(
    [stripAnsi(raw), fields.title, fields.detail, fields.source, metadataText].join(
      " ",
    ),
  ).toLocaleLowerCase();
  return {
    raw,
    ...fields,
    type: `log-${fields.category}`,
    searchText,
  };
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function firstValue(record: JsonRecord, keys: string[]) {
  for (const key of keys) {
    const value = record[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return undefined;
}

function copyJsonMetadata(metadata: LogMetadata, record: JsonRecord) {
  for (const [key, value] of Object.entries(record)) {
    if (
      typeof value === "string" ||
      typeof value === "boolean" ||
      (typeof value === "number" && Number.isFinite(value))
    ) {
      metadata[metadataKey(key)] = value;
    }
  }
}

function normalizeKnownMetadata(metadata: LogMetadata) {
  const chromosome =
    metadata.chromosome ?? metadata.contig ?? metadata.chrom ?? metadata.sequence;
  if (typeof chromosome === "string") metadata.chromosome = chromosome;

  const position = numberValue(
    metadata.position ?? metadata.pos ?? metadata.locusPosition,
  );
  if (position !== undefined) metadata.position = position;

  const percent = numberValue(
    metadata.percent ?? metadata.progressPercent ?? metadata.completionPercent,
  );
  if (percent !== undefined && percent >= 0 && percent <= 100) {
    metadata.percent = percent;
  }

  const process =
    metadata.process ?? metadata.stage ?? metadata.step ?? metadata.tool;
  if (typeof process === "string") metadata.process = process;

  const path =
    metadata.path ??
    metadata.outputPath ??
    metadata.artifactPath ??
    metadata.uri ??
    metadata.url;
  if (typeof path === "string") metadata.path = path;

  const exitCode = numberValue(
    metadata.exitCode ?? metadata.returnCode ?? metadata.statusCode,
  );
  if (exitCode !== undefined) metadata.exitCode = exitCode;
}

function severityFromText(value: string): LogSeverity | undefined {
  const normalized = value.toLocaleLowerCase();
  if (/\b(error|fatal|failed|failure|exception)\b/.test(normalized)) return "error";
  if (/\b(warn|warning|retry|degraded)\b/.test(normalized)) return "warning";
  if (/\b(ok|passed|success|succeeded|complete|completed)\b/.test(normalized)) {
    return "success";
  }
  if (/\b(info|debug|trace|running|started|start)\b/.test(normalized)) return "info";
  return undefined;
}

function categoryFromJson(name: string, severity: LogSeverity): LogCategory {
  const normalized = name.toLocaleLowerCase();
  if (severity === "error") return "error";
  if (severity === "warning") return "warning";
  if (/progress|heartbeat|meter/.test(normalized)) return "progress";
  if (/artifact|output|upload|cache\.reuse|cache_hit/.test(normalized)) {
    return "artifact";
  }
  if (/command|process|task|span\.start|run\.start/.test(normalized)) {
    return "process";
  }
  if (severity === "success" || /span\.end|run\.end/.test(normalized)) {
    return "success";
  }
  return "info";
}

function jsonDetail(record: JsonRecord, attributes: JsonRecord, name: string) {
  const explicit = firstValue(record, ["message", "detail", "description", "error"]);
  if (typeof explicit === "string") return compactWhitespace(explicit);
  const useful = Object.entries(attributes)
    .filter(([, value]) =>
      ["string", "number", "boolean"].includes(typeof value),
    )
    .slice(0, 4)
    .map(([key, value]) => `${humanize(key)}: ${String(value)}`)
    .join(" · ");
  return useful || humanize(name) || "Structured telemetry event";
}

function adaptJson(raw: string, text: string): AdaptedLogEvent | null {
  if (!text.startsWith("{") || !text.endsWith("}")) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isRecord(parsed)) return null;

  const attributes = isRecord(parsed.attributes) ? parsed.attributes : {};
  const metadata: LogMetadata = {};
  copyJsonMetadata(metadata, parsed);
  copyJsonMetadata(metadata, attributes);
  delete metadata.message;
  delete metadata.detail;
  delete metadata.description;
  normalizeKnownMetadata(metadata);

  const nameValue = firstValue(parsed, [
    "name",
    "event",
    "type",
    "kind",
    "category",
  ]);
  const name = typeof nameValue === "string" ? nameValue : "telemetry";
  const statusValue = firstValue(parsed, ["severity", "level", "status"]);
  const attributeStatus = firstValue(attributes, ["severity", "level", "status"]);
  const severity =
    severityFromText(String(statusValue ?? attributeStatus ?? name)) ?? "info";
  const category = categoryFromJson(name, severity);
  return finish(raw, {
    category,
    severity,
    source: "json",
    title: humanize(name) || "Telemetry",
    detail: jsonDetail(parsed, attributes, name),
    metadata,
  });
}

function adaptGatk(raw: string, text: string): AdaptedLogEvent | null {
  const progress = text.match(GATK_PROGRESS);
  if (progress) {
    const chromosome = progress[1];
    const position = progress[2] === undefined ? undefined : Number(progress[2]);
    const percentValue = text.match(PERCENT)?.[1];
    const percent = percentValue === undefined ? undefined : Number(percentValue);
    const metadata: LogMetadata = {
      chromosome,
      process: "GATK",
      ...(position !== undefined ? { position } : {}),
      ...(percent !== undefined && percent <= 100 ? { percent } : {}),
    };
    const detail = [
      chromosome,
      position !== undefined ? `${position.toLocaleString("en-US")} bp` : "",
      percent !== undefined && percent <= 100 ? `${percent}%` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    return finish(raw, {
      category: percent !== undefined && percent >= 100 ? "success" : "progress",
      severity: percent !== undefined && percent >= 100 ? "success" : "info",
      source: "gatk",
      title: percent !== undefined && percent >= 100 ? "GATK complete" : "GATK progress",
      detail,
      metadata,
    });
  }

  const message = text.match(
    /(?:^|\s)(INFO|WARN|ERROR)\s+([A-Za-z][\w$.-]+)\s+-\s+(.+)$/,
  );
  if (!message) return null;
  const level = message[1];
  const category = level === "ERROR" ? "error" : level === "WARN" ? "warning" : "info";
  return finish(raw, {
    category,
    severity: category === "error" ? "error" : category === "warning" ? "warning" : "info",
    source: "gatk",
    title: humanize(message[2]),
    detail: message[3].trim(),
    metadata: { process: message[2], ...inlineMetadata(message[3]) },
  });
}

function adaptNextflow(raw: string, text: string): AdaptedLogEvent | null {
  if (/^ERROR\s*~/i.test(text)) {
    return finish(raw, {
      category: "error",
      severity: "error",
      source: "nextflow",
      title: "Nextflow error",
      detail: text.replace(/^ERROR\s*~\s*/i, ""),
      metadata: inlineMetadata(text),
    });
  }

  const submitted = text.match(/Submitted process\s*>\s*(.+)$/i);
  if (submitted) {
    const process = submitted[1].trim();
    return finish(raw, {
      category: "process",
      severity: "info",
      source: "nextflow",
      title: "Process submitted",
      detail: process,
      metadata: { process },
    });
  }

  const processRow = text.match(
    /^(?:\[[^\]]+\]\s*)?process\s*>\s*(.+)$/i,
  );
  if (processRow && /\[[ ]*\d+(?:\.\d+)?%\]/.test(text)) {
    const percent = Number(text.match(/\[\s*(\d+(?:\.\d+)?)%\]/)?.[1]);
    const process = processRow[1]
      .replace(/\[\s*\d+(?:\.\d+)?%\].*$/, "")
      .trim();
    const complete = percent >= 100 || /[✔✓]/.test(text);
    return finish(raw, {
      category: complete ? "success" : "progress",
      severity: complete ? "success" : "info",
      source: "nextflow",
      title: complete ? "Process complete" : "Process progress",
      detail: `${process} · ${percent}%`,
      metadata: { process, percent },
    });
  }

  const executor = text.match(/executor\s*>\s*(.+)$/i);
  if (executor) {
    return finish(raw, {
      category: "process",
      severity: "info",
      source: "nextflow",
      title: "Nextflow executor",
      detail: executor[1].trim(),
      metadata: { process: executor[1].trim() },
    });
  }

  if (/^(Launching|N E X T F L O W)/i.test(text)) {
    return finish(raw, {
      category: "process",
      severity: "info",
      source: "nextflow",
      title: "Nextflow",
      detail: compactWhitespace(text),
      metadata: inlineMetadata(text),
    });
  }
  return null;
}

function inferSource(text: string): LogSource {
  if (/\b(?:AWS|Batch|CloudWatch|ECS|EC2|S3)\b/i.test(text)) return "aws";
  if (/\b(?:GATK|Mutect2|FilterMutectCalls|ProgressMeter)\b/i.test(text)) return "gatk";
  if (/\b(?:Nextflow|process\s*>|executor\s*>|work dir:)\b/i.test(text)) return "nextflow";
  if (/\b(?:diana[_-]omics|phase3-wgs)|^\[(?:cache|phase3|sra)-/i.test(text)) return "diana";
  return "generic";
}

function adaptExplicitError(raw: string, text: string): AdaptedLogEvent | null {
  const error = text.match(
    /^(?:error\s*:|fatal\s*:|exception\s*:|traceback\b|caused by\s*:)|\b(?:job|command|process|task|validation|verification)\s+(?:has\s+)?failed\b/i,
  );
  if (!error) return null;
  return finish(raw, {
    category: "error",
    severity: "error",
    source: inferSource(text),
    title: /^caused by/i.test(text) ? "Failure cause" : "Error",
    detail: compactWhitespace(text.replace(/^(?:error|fatal|exception)\s*:\s*/i, "")),
    metadata: inlineMetadata(text),
  });
}

function adaptWarning(raw: string, text: string): AdaptedLogEvent | null {
  const warning = text.match(/^(?:warn(?:ing)?\s*:)|\bWARN(?:ING)?\b|^\[(?:retry|cache-skip)\]/i);
  if (!warning) return null;
  const retry = /retry/i.test(text);
  return finish(raw, {
    category: "warning",
    severity: "warning",
    source: inferSource(text),
    title: retry ? "Retry scheduled" : "Warning",
    detail: compactWhitespace(text.replace(/^(?:warn(?:ing)?)\s*:\s*/i, "")),
    metadata: inlineMetadata(text),
  });
}

function adaptDianaStep(raw: string, text: string): AdaptedLogEvent | null {
  if (!text.startsWith("==>")) return null;
  const detail = text.slice(3).trim();
  if (/\b(?:passed|succeeded|complete|completed|ready)\b/i.test(detail)) {
    return finish(raw, {
      category: "success",
      severity: "success",
      source: "diana",
      title: "Step complete",
      detail,
      metadata: inlineMetadata(detail),
    });
  }
  const command = detail.match(/-m\s+diana_omics\s+([^\s]+)/)?.[1];
  if (command) {
    return finish(raw, {
      category: "process",
      severity: "info",
      source: "diana",
      title: humanize(command),
      detail,
      metadata: { process: command, ...inlineMetadata(detail) },
    });
  }
  return finish(raw, {
    category: "info",
    severity: "info",
    source: "diana",
    title: "Diana",
    detail,
    metadata: inlineMetadata(detail),
  });
}

function adaptCommand(raw: string, text: string): AdaptedLogEvent | null {
  const command = text.match(/^Command executed:\s*(.*)$/i);
  const shell = text.match(/^[$+]\s+(.+)$/);
  const runtime = text.match(/^\[[^\]]+\]\s+RUN\s+(.+)$/i);
  const detail = command?.[1] || shell?.[1] || runtime?.[1];
  if (!detail) return null;
  const awsTransfer = /(?:^|\/)aws\s+s3\s+cp\s+/i.test(detail);
  if (awsTransfer) {
    const metadata = inlineMetadata(detail);
    const s3Path = detail.match(/s3:\/\/[^\s'"),;]+/i)?.[0];
    if (s3Path) metadata.path = s3Path;
    return finish(raw, {
      category: "artifact",
      severity: "info",
      source: "aws",
      title: "S3 transfer",
      detail,
      metadata: { ...metadata, process: "aws s3 cp" },
    });
  }
  return finish(raw, {
    category: "process",
    severity: "info",
    source: "shell",
    title: "Command",
    detail,
    metadata: { process: detail.split(/\s+/)[0], ...inlineMetadata(detail) },
  });
}

function adaptRuntimeStage(raw: string, text: string): AdaptedLogEvent | null {
  const lifecycle = text.match(/^\[[^\]]+\]\s+stage=([^\s]+)\s*(.*)$/i);
  if (!lifecycle) return null;
  const stage = lifecycle[1];
  return finish(raw, {
    category: "process",
    severity: "info",
    source: "diana",
    title: `${humanize(stage)} stage`,
    detail: lifecycle[2] || `Stage ${stage} started`,
    metadata: { process: stage, ...inlineMetadata(text) },
  });
}

function adaptShardHeartbeat(raw: string, text: string): AdaptedLogEvent | null {
  const heartbeat = text.match(
    /^(?:INFO\s+)?Evidence shard\s+(chr(?:\d{1,2}|X|Y|M|MT))\s+heartbeat received$/i,
  );
  if (!heartbeat) return null;
  const chromosome = heartbeat[1];
  return finish(raw, {
    category: "progress",
    severity: "info",
    source: "diana",
    title: "Shard heartbeat",
    detail: `${chromosome} received`,
    metadata: { chromosome, process: "evidence" },
  });
}

function adaptArtifact(raw: string, text: string): AdaptedLogEvent | null {
  if (
    !/(?:\b(?:artifact|output|report|packet)\b.*\b(?:written|wrote|saved|created|ready|uploaded|published)\b|\b(?:written|wrote|saved|uploaded|published)\b.*\b(?:to|at)\b|^\[(?:cache-hit|cache-reuse|cache-manifest|public-bam-cache)\])/i.test(
      text,
    )
  ) {
    return null;
  }
  const metadata = inlineMetadata(text);
  const path = metadata.path || text.match(PATH)?.[0];
  if (path) metadata.path = String(path);
  const reused = /cache-(?:hit|reuse)|reusing/i.test(text);
  const uploaded = /upload|publish/i.test(text);
  const written = /written|wrote|saved|created/i.test(text);
  return finish(raw, {
    category: "artifact",
    severity: reused || uploaded || written ? "success" : "info",
    source: inferSource(text),
    title: reused
      ? "Artifact reused"
      : uploaded
        ? "Artifact uploaded"
        : written
          ? "Artifact written"
          : "Output ready",
    detail: compactWhitespace(text),
    metadata,
  });
}

function adaptSuccess(raw: string, text: string): AdaptedLogEvent | null {
  if (!/\b(?:passed|succeeded|successfully|completed|verified|ready)\b|[✔✓]/i.test(text)) {
    return null;
  }
  return finish(raw, {
    category: "success",
    severity: "success",
    source: inferSource(text),
    title: "Complete",
    detail: compactWhitespace(text),
    metadata: inlineMetadata(text),
  });
}

/** Convert a raw CloudWatch line into deterministic, display-ready log data. */
export function adaptLogMessage(rawText: string): AdaptedLogEvent {
  const raw = String(rawText ?? "");
  const text = normalizeForParsing(raw);
  const adapted =
    adaptJson(raw, text) ??
    adaptGatk(raw, text) ??
    adaptNextflow(raw, text) ??
    adaptExplicitError(raw, text) ??
    adaptWarning(raw, text) ??
    adaptDianaStep(raw, text) ??
    adaptRuntimeStage(raw, text) ??
    adaptShardHeartbeat(raw, text) ??
    adaptCommand(raw, text) ??
    adaptArtifact(raw, text) ??
    adaptSuccess(raw, text);
  if (adapted) return adapted;

  return finish(raw, {
    category: "info",
    severity: "info",
    source: inferSource(text),
    title: "Info",
    detail: text,
    metadata: inlineMetadata(text),
  });
}

export function adaptLogMessages(rawMessages: readonly string[]) {
  return rawMessages.map(adaptLogMessage);
}
