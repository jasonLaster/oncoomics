import { mkdirSync, readFileSync } from "node:fs";
import { dirname } from "node:path";

export const ROOT = new URL("..", import.meta.url).pathname.replace(/\/$/, "");

export function pathFromRoot(relativePath: string) {
  return `${ROOT}/${relativePath}`.replaceAll("//", "/");
}

export function ensureDir(path: string) {
  mkdirSync(path, { recursive: true });
}

export function ensureParent(path: string) {
  ensureDir(dirname(path));
}

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(`${init?.method ?? "GET"} ${url} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchText(url: string, init?: RequestInit): Promise<string> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(`${init?.method ?? "GET"} ${url} returned ${response.status}`);
  }
  return response.text();
}

export async function postJson<T>(url: string, body: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

export async function writeJson(path: string, value: unknown) {
  ensureParent(path);
  await Bun.write(path, `${JSON.stringify(value, null, 2)}\n`);
}

export async function writeText(path: string, value: string) {
  ensureParent(path);
  await Bun.write(path, value.endsWith("\n") ? value : `${value}\n`);
}

export function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

export function readText(path: string) {
  return readFileSync(path, "utf8");
}

function csvValue(value: unknown) {
  if (value === null || value === undefined) {
    return "";
  }
  const text = String(value);
  if (/[",\n\r]/.test(text)) {
    return `"${text.replaceAll('"', '""')}"`;
  }
  return text;
}

export async function writeCsv(path: string, rows: Record<string, unknown>[], columns?: string[]) {
  const resolvedColumns = columns ?? Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const lines = [
    resolvedColumns.map(csvValue).join(","),
    ...rows.map((row) => resolvedColumns.map((column) => csvValue(row[column])).join(","))
  ];
  await writeText(path, lines.join("\n"));
}

export function parseDelimited(text: string, delimiter = "\t") {
  const lines = text.trimEnd().split(/\r?\n/);
  const headers = lines.shift()?.split(delimiter) ?? [];
  return lines.filter(Boolean).map((line) => {
    const values = line.split(delimiter);
    const row: Record<string, string> = {};
    headers.forEach((header, index) => {
      row[header] = values[index] ?? "";
    });
    return row;
  });
}

export function parseCsv(text: string) {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (quoted) {
      if (char === '"' && next === '"') {
        cell += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }

  if (cell.length > 0 || row.length > 0) {
    row.push(cell.replace(/\r$/, ""));
    rows.push(row);
  }

  const headers = rows.shift() ?? [];
  return rows.filter((values) => values.some((value) => value !== "")).map((values) => {
    const object: Record<string, string> = {};
    headers.forEach((header, index) => {
      object[header] = values[index] ?? "";
    });
    return object;
  });
}

export function pivotClinical(
  records: Array<{ sampleId?: string; patientId?: string; clinicalAttributeId: string; value: string }>,
  idField: "sampleId" | "patientId"
) {
  const byId = new Map<string, Record<string, string>>();
  for (const record of records) {
    const id = record[idField];
    if (!id) {
      continue;
    }
    const row = byId.get(id) ?? { [idField]: id };
    row[record.clinicalAttributeId] = record.value;
    byId.set(id, row);
  }
  return Array.from(byId.values()).sort((a, b) => String(a[idField]).localeCompare(String(b[idField])));
}

export function groupBy<T>(rows: T[], getKey: (row: T) => string) {
  const map = new Map<string, T[]>();
  for (const row of rows) {
    const key = getKey(row);
    const group = map.get(key) ?? [];
    group.push(row);
    map.set(key, group);
  }
  return map;
}

export function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function mean(values: Array<number | null | undefined>) {
  const clean = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (clean.length === 0) {
    return null;
  }
  return clean.reduce((sum, value) => sum + value, 0) / clean.length;
}

export function standardDeviation(values: Array<number | null | undefined>) {
  const clean = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (clean.length < 2) {
    return null;
  }
  const avg = mean(clean) ?? 0;
  const variance = clean.reduce((sum, value) => sum + (value - avg) ** 2, 0) / (clean.length - 1);
  return Math.sqrt(variance);
}

export function quantile(values: number[], q: number) {
  const clean = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (clean.length === 0) {
    return null;
  }
  const pos = (clean.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  const next = clean[base + 1];
  if (next === undefined) {
    return clean[base];
  }
  return clean[base] + rest * (next - clean[base]);
}

export function round(value: number | null | undefined, digits = 4) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "";
  }
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export function unique<T>(values: T[]) {
  return Array.from(new Set(values));
}

