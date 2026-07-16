import assert from "node:assert/strict";
import test from "node:test";

import {
  adaptLogMessage,
  adaptLogMessages,
} from "../app/log-adapters.ts";

test("extracts GATK chromosome progress without changing the raw line", () => {
  const raw = "12:15:02.014 INFO ProgressMeter - chr17:43044295  12.3  43125482  42.5%";
  const event = adaptLogMessage(raw);

  assert.equal(event.raw, raw);
  assert.equal(event.category, "progress");
  assert.equal(event.severity, "info");
  assert.equal(event.source, "gatk");
  assert.equal(event.type, "log-progress");
  assert.deepEqual(event.metadata, {
    chromosome: "chr17",
    position: 43_044_295,
    process: "GATK",
    percent: 42.5,
  });
  assert.match(event.detail, /chr17 · 43,044,295 bp · 42.5%/);
  assert.match(event.searchText, /chromosome chr17/);
});

test("adapts compact GATK progress without inventing a position", () => {
  const event = adaptLogMessage(
    "INFO ProgressMeter - chr17 67.5% complete at 42.1 Mb/min",
  );

  assert.equal(event.category, "progress");
  assert.equal(event.metadata.chromosome, "chr17");
  assert.equal(event.metadata.percent, 67.5);
  assert.equal(event.metadata.position, undefined);
});

test("formats Diana commands and cache artifacts", () => {
  const [step, cache] = adaptLogMessages([
    "==> /usr/bin/python3 -m diana_omics validate:phase3-wgs",
    "[cache-reuse] label=tumor.alignment path=results/phase3_wgs_smoke/tumor.bam",
  ]);

  assert.equal(step.category, "process");
  assert.equal(step.source, "diana");
  assert.equal(step.title, "Validate phase3 wgs");
  assert.equal(step.metadata.process, "validate:phase3-wgs");

  assert.equal(cache.category, "artifact");
  assert.equal(cache.severity, "success");
  assert.equal(cache.title, "Artifact reused");
  assert.equal(cache.metadata.label, "tumor.alignment");
  assert.equal(
    cache.metadata.path,
    "results/phase3_wgs_smoke/tumor.bam",
  );
});

test("formats timestamped Diana runtime stages and AWS transfers", () => {
  const stage = adaptLogMessage(
    "[2026-07-16T08:01:50.888229+00:00] stage=gather run_id=diana-wgs-hrd-20260716T033101Z work=/work/diana-hrd",
  );
  const transfer = adaptLogMessage(
    "[2026-07-16T09:04:57.425077+00:00] RUN /opt/diana-aws/bin/aws s3 cp /work/tumor.bam s3://diana-results/run/tumor.bam --only-show-errors",
  );

  assert.equal(stage.category, "process");
  assert.equal(stage.source, "diana");
  assert.equal(stage.title, "Gather stage");
  assert.equal(stage.metadata.process, "gather");
  assert.equal(transfer.category, "artifact");
  assert.equal(transfer.source, "aws");
  assert.equal(transfer.title, "S3 transfer");
  assert.equal(transfer.metadata.path, "s3://diana-results/run/tumor.bam");
});

test("compresses routine shard heartbeats into structured progress", () => {
  const event = adaptLogMessage(
    "INFO Evidence shard chr21 heartbeat received",
  );

  assert.equal(event.category, "progress");
  assert.equal(event.source, "diana");
  assert.equal(event.title, "Shard heartbeat");
  assert.equal(event.detail, "chr21 received");
  assert.equal(event.metadata.chromosome, "chr21");
  assert.match(event.searchText, /heartbeat received/);
});

test("recognizes Nextflow process submission and progress", () => {
  const submitted = adaptLogMessage(
    "[ab/12cd34] Submitted process > PHASE3_ALIGN (tumor)",
  );
  const running = adaptLogMessage(
    "[31/1c1aaa] process > PHASE3_ALIGN (normal) [ 43%] 3 of 7",
  );
  const complete = adaptLogMessage(
    "[31/1c1aaa] process > PHASE3_ALIGN (normal) [100%] 7 of 7 ✔",
  );

  assert.equal(submitted.category, "process");
  assert.equal(submitted.metadata.process, "PHASE3_ALIGN (tumor)");
  assert.equal(running.category, "progress");
  assert.equal(running.metadata.percent, 43);
  assert.equal(running.metadata.process, "PHASE3_ALIGN (normal)");
  assert.equal(complete.category, "success");
  assert.equal(complete.severity, "success");
});

test("separates warnings, errors, success, commands, and artifacts", () => {
  assert.equal(adaptLogMessage("warning: low disk space").category, "warning");
  assert.equal(adaptLogMessage("error: checksum mismatch").category, "error");
  assert.equal(adaptLogMessage("Plan verification passed.").category, "success");
  assert.equal(adaptLogMessage("$ samtools quickcheck tumor.bam").category, "process");

  const artifact = adaptLogMessage(
    "Uploaded artifact to s3://diana-results/runs/run-12/summary.json",
  );
  assert.equal(artifact.category, "artifact");
  assert.equal(artifact.source, "aws");
  assert.equal(
    artifact.metadata.path,
    "s3://diana-results/runs/run-12/summary.json",
  );
});

test("preserves useful JSON telemetry metadata", () => {
  const event = adaptLogMessage(
    JSON.stringify({
      name: "stage.progress",
      status: "running",
      attributes: {
        stage: "mutect2",
        contig: "chr13",
        position: 32_315_086,
        progressPercent: 61.25,
        outputPath: "results/evidence/chr13.vcf.gz",
        records: 412,
      },
    }),
  );

  assert.equal(event.category, "progress");
  assert.equal(event.source, "json");
  assert.equal(event.metadata.chromosome, "chr13");
  assert.equal(event.metadata.position, 32_315_086);
  assert.equal(event.metadata.percent, 61.25);
  assert.equal(event.metadata.process, "mutect2");
  assert.equal(event.metadata.path, "results/evidence/chr13.vcf.gz");
  assert.equal(event.metadata.records, 412);
});

test("uses event names to format JSON artifact telemetry", () => {
  const event = adaptLogMessage(
    JSON.stringify({
      level: "info",
      category: "delivery",
      event: "artifact_uploaded",
      message: "Encrypted reviewer packet uploaded",
    }),
  );

  assert.equal(event.category, "artifact");
  assert.equal(event.title, "Artifact uploaded");
  assert.equal(event.detail, "Encrypted reviewer packet uploaded");
});

test("does not throw on malformed JSON and keeps ANSI-decorated raw text", () => {
  const malformed = '{"name":"stage.progress","attributes":';
  assert.doesNotThrow(() => adaptLogMessage(malformed));
  assert.equal(adaptLogMessage(malformed).category, "info");

  const raw = "\u001b[33mwarning: retrying download\u001b[0m";
  const event = adaptLogMessage(raw);
  assert.equal(event.raw, raw);
  assert.equal(event.category, "warning");
  assert.doesNotMatch(event.detail, /\u001b/);
});
