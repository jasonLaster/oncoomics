from __future__ import annotations

import contextlib
import json
import os
import random
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping, Optional

from .paths import path_from_root


def unix_nano() -> int:
    return time.time_ns()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def random_hex(bytes_count: int) -> str:
    return random.randbytes(bytes_count).hex() if hasattr(random, "randbytes") else os.urandom(bytes_count).hex()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def process_tree_pids(root_pid: int) -> list[int]:
    pending = [root_pid]
    seen = {root_pid}
    while pending:
        pid = pending.pop()
        try:
            result = subprocess.run(["pgrep", "-P", str(pid)], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
        except FileNotFoundError:
            break
        for line in result.stdout.splitlines():
            try:
                child_pid = int(line.strip())
            except ValueError:
                continue
            if child_pid not in seen:
                seen.add(child_pid)
                pending.append(child_pid)
    return sorted(seen)


def process_metrics(root_pid: Optional[int]) -> dict[str, Any]:
    if not root_pid:
        return {"processCount": 0, "processes": []}
    pids = process_tree_pids(root_pid)
    if not pids:
        return {"processCount": 0, "processes": []}
    try:
        result = subprocess.run(
            ["ps", "-o", "pid=,ppid=,%cpu=,%mem=,rss=,command=", "-p", ",".join(str(pid) for pid in pids)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        return {"processCount": len(pids), "processes": [{"pid": pid} for pid in pids]}

    processes: list[dict[str, Any]] = []
    total_cpu = 0.0
    total_rss_kb = 0
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 5)
        if len(fields) < 5:
            continue
        try:
            pid = int(fields[0])
            ppid = int(fields[1])
            cpu = float(fields[2])
            mem = float(fields[3])
            rss_kb = int(fields[4])
        except ValueError:
            continue
        command = fields[5] if len(fields) > 5 else ""
        total_cpu += cpu
        total_rss_kb += rss_kb
        processes.append({"pid": pid, "ppid": ppid, "cpuPercent": cpu, "memPercent": mem, "rssKb": rss_kb, "command": command})
    return {
        "processCount": len(processes),
        "totalCpuPercent": round(total_cpu, 2),
        "totalRssKb": total_rss_kb,
        "processes": processes,
    }


def system_metrics(base_path: Optional[Path] = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    try:
        load1, load5, load15 = os.getloadavg()
        payload["loadAverage"] = {"1m": load1, "5m": load5, "15m": load15}
    except OSError:
        pass
    try:
        usage = shutil.disk_usage(base_path or path_from_root(""))
        payload["disk"] = {"totalBytes": usage.total, "usedBytes": usage.used, "freeBytes": usage.free}
    except OSError:
        pass
    return payload


class TelemetrySpan:
    def __init__(
        self,
        telemetry: RunTelemetry,
        name: str,
        attributes: Optional[Mapping[str, Any]] = None,
        parent_span_id: Optional[str] = None,
    ) -> None:
        self.telemetry = telemetry
        self.name = name
        self.attributes: dict[str, Any] = dict(attributes or {})
        self.span_id = random_hex(8)
        self.parent_span_id: Optional[str] = parent_span_id if parent_span_id is not None else telemetry.current_span_id()
        self.start_time_unix_nano = unix_nano()
        self.end_time_unix_nano = 0
        self.status = "unset"

    def __enter__(self) -> TelemetrySpan:
        self.telemetry.push_span(self.span_id)
        self.telemetry.event(
            "span.start",
            {
                "spanId": self.span_id,
                "parentSpanId": self.parent_span_id,
                "name": self.name,
                "attributes": self.attributes,
            },
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        self.end_time_unix_nano = unix_nano()
        duration_ms = round((self.end_time_unix_nano - self.start_time_unix_nano) / 1_000_000, 3)
        self.status = "error" if exc_type else "ok"
        if exc_type:
            self.attributes["exception.type"] = getattr(exc_type, "__name__", str(exc_type))
            self.attributes["exception.message"] = str(exc)
        self.telemetry.write_span(
            {
                "traceId": self.telemetry.trace_id,
                "spanId": self.span_id,
                "parentSpanId": self.parent_span_id or "",
                "name": self.name,
                "kind": "internal",
                "startTimeUnixNano": self.start_time_unix_nano,
                "endTimeUnixNano": self.end_time_unix_nano,
                "durationMs": duration_ms,
                "status": self.status,
                "attributes": self.attributes,
            }
        )
        self.telemetry.event(
            "span.end",
            {
                "spanId": self.span_id,
                "name": self.name,
                "durationMs": duration_ms,
                "status": self.status,
            },
        )
        self.telemetry.pop_span(self.span_id)
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def progress(self, **values: Any) -> None:
        self.telemetry.heartbeat(self.name, values)


class RunTelemetry:
    def __init__(
        self,
        workflow: str,
        results_dir: str,
        attributes: Optional[Mapping[str, Any]] = None,
        upload_uri: Optional[str] = None,
    ) -> None:
        self.workflow = workflow
        self.enabled = os.environ.get("DIANA_OMICS_TELEMETRY", "1") != "0"
        self.run_id = os.environ.get("DIANA_OMICS_RUN_ID") or f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}"
        self.trace_id = random_hex(16)
        self.upload_uri = upload_uri if upload_uri is not None else os.environ.get("DIANA_OMICS_LOG_UPLOAD_URI", "")
        self.base_dir = path_from_root(f"{results_dir}/logs/telemetry")
        self.run_dir = self.base_dir / self.run_id
        self.events_path = self.run_dir / "events.jsonl"
        self.spans_path = self.run_dir / "otel_spans.jsonl"
        self.resources_path = self.run_dir / "resource_samples.jsonl"
        self.heartbeat_path = self.run_dir / "heartbeat.json"
        self.manifest_path = self.run_dir / "run_manifest.json"
        self._lock = threading.Lock()
        self._local = threading.local()
        self.started_at = utc_now()
        self.started_monotonic = time.monotonic()
        self.attributes = dict(attributes or {})
        if self.enabled:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self.events_path.touch()
            self.spans_path.touch()
            self.resources_path.touch()
            write_json(
                self.base_dir / "latest_run.json",
                {
                    "workflow": self.workflow,
                    "runId": self.run_id,
                    "traceId": self.trace_id,
                    "runDir": str(self.run_dir),
                    "startedAt": self.started_at,
                },
            )
            write_json(
                self.manifest_path,
                {
                    "workflow": self.workflow,
                    "runId": self.run_id,
                    "traceId": self.trace_id,
                    "startedAt": self.started_at,
                    "status": "running",
                    "attributes": self.attributes,
                    "files": {
                        "events": str(self.events_path),
                        "spans": str(self.spans_path),
                        "resources": str(self.resources_path),
                        "heartbeat": str(self.heartbeat_path),
                    },
                },
            )
            self.event("run.start", {"attributes": self.attributes})

    def _stack(self) -> list[str]:
        stack = getattr(self._local, "span_stack", None)
        if stack is None:
            stack = []
            self._local.span_stack = stack
        return stack

    def current_span_id(self) -> Optional[str]:
        stack = self._stack()
        return stack[-1] if stack else None

    def push_span(self, span_id: str) -> None:
        self._stack().append(span_id)

    def pop_span(self, span_id: str) -> None:
        stack = self._stack()
        if stack and stack[-1] == span_id:
            stack.pop()
        elif span_id in stack:
            stack.remove(span_id)

    @contextlib.contextmanager
    def span(
        self,
        name: str,
        attributes: Optional[Mapping[str, Any]] = None,
        parent_span_id: Optional[str] = None,
    ) -> Iterator[TelemetrySpan]:
        if not self.enabled:
            yield TelemetrySpan(self, name, attributes, parent_span_id)
            return
        span = TelemetrySpan(self, name, attributes, parent_span_id)
        with span:
            yield span

    def event(self, name: str, attributes: Optional[Mapping[str, Any]] = None) -> None:
        if not self.enabled:
            return
        payload = {
            "timestamp": utc_now(),
            "traceId": self.trace_id,
            "runId": self.run_id,
            "workflow": self.workflow,
            "spanId": self.current_span_id() or "",
            "name": name,
            "attributes": dict(attributes or {}),
        }
        with self._lock:
            append_jsonl(self.events_path, payload)

    def write_span(self, payload: Mapping[str, Any]) -> None:
        if not self.enabled:
            return
        span_payload = {"resource": {"service.name": "diana-omics", "workflow": self.workflow, "run.id": self.run_id}, **dict(payload)}
        with self._lock:
            append_jsonl(self.spans_path, span_payload)

    def heartbeat(self, stage: str, progress: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        if not self.enabled:
            return {}
        snapshot = {
            "timestamp": utc_now(),
            "workflow": self.workflow,
            "runId": self.run_id,
            "traceId": self.trace_id,
            "stage": stage,
            "activeSpanId": self.current_span_id() or "",
            "progress": dict(progress or {}),
            "system": system_metrics(path_from_root("")),
        }
        with self._lock:
            write_json(self.heartbeat_path, snapshot)
            append_jsonl(self.events_path, {"name": "heartbeat", **snapshot})
        return snapshot

    def sample_resources(
        self,
        label: str,
        command_pid: Optional[int] = None,
        attributes: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {}
        snapshot = {
            "timestamp": utc_now(),
            "workflow": self.workflow,
            "runId": self.run_id,
            "traceId": self.trace_id,
            "spanId": self.current_span_id() or "",
            "label": label,
            "attributes": dict(attributes or {}),
            "system": system_metrics(path_from_root("")),
            "processTree": process_metrics(command_pid),
        }
        with self._lock:
            append_jsonl(self.resources_path, snapshot)
        return snapshot

    def _upload_destination(self) -> str:
        return self.upload_uri.rstrip("/") + f"/{self.workflow}/{self.run_id}" if self.upload_uri else ""

    def _manifest_payload(
        self,
        status: str,
        finished_at: str,
        attributes: Optional[Mapping[str, Any]],
        upload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "workflow": self.workflow,
            "runId": self.run_id,
            "traceId": self.trace_id,
            "startedAt": self.started_at,
            "finishedAt": finished_at,
            "durationSeconds": round(time.monotonic() - self.started_monotonic, 3),
            "status": status,
            "attributes": {**self.attributes, **dict(attributes or {})},
            "upload": dict(upload),
            "uploadUri": upload.get("uri", ""),
            "uploadStatus": upload.get("status", ""),
            "files": {
                "events": str(self.events_path),
                "spans": str(self.spans_path),
                "resources": str(self.resources_path),
                "heartbeat": str(self.heartbeat_path),
            },
        }

    def finalize(self, status: str, attributes: Optional[Mapping[str, Any]] = None) -> None:
        if not self.enabled:
            return
        finished_at = utc_now()
        self.event("run.end", {"status": status, "attributes": attributes or {}})
        upload: dict[str, Any] = {
            "status": "not_configured",
            "uri": "",
            "mode": "",
            "attemptedAt": "",
            "completedAt": "",
            "error": "",
        }
        if self.upload_uri:
            upload.update({"status": "pending", "uri": self._upload_destination(), "attemptedAt": utc_now()})
        write_json(self.manifest_path, self._manifest_payload(status, finished_at, attributes, upload))
        if self.upload_uri:
            try:
                upload.update(self.upload())
                self.event("logs.uploaded", upload)
            except Exception as error:
                upload.update({"status": "failed", "completedAt": utc_now(), "error": str(error)})
                self.event("logs.upload_failed", upload)
            write_json(self.manifest_path, self._manifest_payload(status, finished_at, attributes, upload))
            if upload.get("status") == "uploaded":
                try:
                    self.upload()
                except Exception as error:
                    self.event("logs.upload_refresh_failed", {"uri": upload.get("uri", ""), "error": str(error)})

    def upload(self) -> dict[str, Any]:
        if not self.upload_uri:
            return {"status": "not_configured", "uri": "", "mode": "", "completedAt": "", "error": ""}
        destination = self._upload_destination()
        if destination.startswith("s3://"):
            subprocess.run(["aws", "s3", "sync", str(self.run_dir), destination], check=True)
            return {"status": "uploaded", "uri": destination, "mode": "s3", "completedAt": utc_now(), "error": ""}
        destination_path = Path(destination)
        if destination_path.exists():
            shutil.rmtree(destination_path)
        shutil.copytree(self.run_dir, destination_path)
        return {"status": "uploaded", "uri": str(destination_path), "mode": "local", "completedAt": utc_now(), "error": ""}


def run_traced_command(
    command: str,
    log_path: Optional[str],
    telemetry: Optional[RunTelemetry],
    span_name: str,
    attributes: Optional[Mapping[str, Any]] = None,
    parent_span_id: Optional[str] = None,
    max_buffer: Optional[int] = None,
) -> str:
    heartbeat_seconds = int(
        os.environ.get("DIANA_OMICS_TRACE_HEARTBEAT_SECONDS", os.environ.get("DIANA_OMICS_COMMAND_HEARTBEAT_SECONDS", "30"))
    )
    span_attributes = {"command": command, "logPath": log_path or "", **dict(attributes or {})}
    span_context = telemetry.span(span_name, span_attributes, parent_span_id=parent_span_id) if telemetry else contextlib.nullcontext()
    with span_context as span:
        started_monotonic = time.monotonic()
        started_at = utc_now()
        next_heartbeat = started_monotonic + max(1, heartbeat_seconds)
        with tempfile.TemporaryDirectory(prefix="diana-omics-command-") as tmpdir:
            stdout_path = Path(tmpdir) / "stdout.txt"
            stderr_path = Path(tmpdir) / "stderr.txt"
            with stdout_path.open("w+", encoding="utf-8") as stdout_handle, stderr_path.open("w+", encoding="utf-8") as stderr_handle:
                process = subprocess.Popen(
                    ["bash", "-lc", command],
                    cwd=path_from_root(""),
                    text=True,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    start_new_session=True,
                )
                if telemetry:
                    telemetry.event("command.start", {"span": span_name, "pid": process.pid, "logPath": log_path or ""})
                while True:
                    exit_status = process.poll()
                    if exit_status is not None:
                        break
                    now = time.monotonic()
                    if heartbeat_seconds > 0 and now >= next_heartbeat:
                        elapsed = round(now - started_monotonic, 3)
                        sample = telemetry.sample_resources(span_name, process.pid, {"elapsedSeconds": elapsed}) if telemetry else {}
                        process_tree = sample.get("processTree", {}) if sample else {}
                        if telemetry:
                            telemetry.heartbeat(
                                span_name,
                                {
                                    "elapsedSeconds": elapsed,
                                    "commandPid": process.pid,
                                    "logPath": log_path or "",
                                    "processCount": process_tree.get("processCount", 0),
                                    "totalCpuPercent": process_tree.get("totalCpuPercent", ""),
                                    "totalRssKb": process_tree.get("totalRssKb", ""),
                                },
                            )
                        cpu = process_tree.get("totalCpuPercent", "")
                        rss = process_tree.get("totalRssKb", "")
                        print(
                            f"[heartbeat] span={span_name} elapsed={int(elapsed)}s pid={process.pid} cpu={cpu} rssKb={rss} log={log_path or ''}",
                            flush=True,
                        )
                        next_heartbeat = now + heartbeat_seconds
                    time.sleep(1)
                stdout_handle.seek(0)
                stderr_handle.seek(0)
                stdout = stdout_handle.read()
                stderr = stderr_handle.read()
        finished_at = utc_now()
        duration_seconds = round(time.monotonic() - started_monotonic, 3)
        if max_buffer is not None and max_buffer > 0:
            stdout = stdout[-max_buffer:]
            stderr = stderr[-max_buffer:]
        if log_path:
            resolved_log = path_from_root(log_path)
            ensure_parent(resolved_log)
            resolved_log.write_text(
                "\n".join(
                    [
                        f"$ {command}",
                        "",
                        "## telemetry",
                        json.dumps(
                            {
                                "span": span_name,
                                "startedAt": started_at,
                                "finishedAt": finished_at,
                                "durationSeconds": duration_seconds,
                                "exitStatus": exit_status,
                                "runId": telemetry.run_id if telemetry else "",
                                "traceId": telemetry.trace_id if telemetry else "",
                            },
                            sort_keys=True,
                        ),
                        "",
                        "## stdout",
                        stdout or "",
                        "",
                        "## stderr",
                        stderr or "",
                        "",
                        f"exit_status={exit_status}",
                    ]
                ),
                encoding="utf-8",
            )
        if telemetry:
            telemetry.sample_resources(span_name, None, {"durationSeconds": duration_seconds, "exitStatus": exit_status})
            telemetry.event(
                "command.end",
                {
                    "span": span_name,
                    "durationSeconds": duration_seconds,
                    "exitStatus": exit_status,
                    "logPath": log_path or "",
                },
            )
        if isinstance(span, TelemetrySpan):
            span.set_attribute("command.duration_seconds", duration_seconds)
            span.set_attribute("command.exit_status", exit_status)
        if exit_status != 0:
            suffix = f". See {log_path}." if log_path else f"\n{stderr}"
            raise RuntimeError(f"Command failed ({exit_status}): {command}{suffix}")
        return stdout
