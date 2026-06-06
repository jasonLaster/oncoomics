import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

type AtlasSource = {
  id: string;
  title: string;
  kind: string;
  priority: string;
  primary_use: string;
  access: string;
  urls: string[];
  expected_artifacts: string[];
  verifier: string;
};

type AtlasManifest = {
  schema_version: string;
  generated_from: string;
  sources: AtlasSource[];
};

const root = new URL("..", import.meta.url).pathname.replace(/\/$/, "");
const wikiRoot = "/Users/jasonlaster/src/projects/diana-tnbc/obsidian/wiki/omics";

const errors: string[] = [];
const warnings: string[] = [];

function requireFile(path: string) {
  if (!existsSync(path)) {
    errors.push(`Missing required file: ${path}`);
  }
}

function readProjectFile(relativePath: string) {
  const fullPath = join(root, relativePath);
  requireFile(fullPath);
  return existsSync(fullPath) ? readFileSync(fullPath, "utf8") : "";
}

function commandVersion(command: string, args: string[]) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  if (result.status !== 0) {
    return null;
  }
  return `${result.stdout}${result.stderr}`.trim().split("\n")[0] ?? "";
}

const requiredProjectFiles = [
  "README.md",
  "docs/PROJECT_PLAN.md",
  "docs/SOURCE_MAP.md",
  "docs/WIKI_SOURCE_SUMMARY.md",
  "manifests/validation_atlases.json"
];

for (const file of requiredProjectFiles) {
  requireFile(join(root, file));
}

const requiredWikiFiles = [
  "index.md",
  "findings-overview.md",
  "derived-findings.md",
  "analysis-workflows.md",
  "validation-atlases.md",
  "partner-questions.md"
];

for (const file of requiredWikiFiles) {
  requireFile(join(wikiRoot, file));
}

const plan = readProjectFile("docs/PROJECT_PLAN.md");
for (let i = 0; i <= 7; i += 1) {
  if (!plan.includes(`Milestone ${i}`)) {
    errors.push(`PROJECT_PLAN.md is missing Milestone ${i}.`);
  }
}

for (const required of ["Verifier", "HRD", "Bun", "Python", "TCGA-BRCA", "CHORD", "scarHRD"]) {
  if (!plan.includes(required)) {
    errors.push(`PROJECT_PLAN.md is missing required term: ${required}`);
  }
}

const sourceMap = readProjectFile("docs/SOURCE_MAP.md");
for (const requiredUrl of [
  "https://gdc.cancer.gov/about-data/publications/brca_2012",
  "https://docs.cbioportal.org/downloads/",
  "https://xena.ucsc.edu/",
  "https://www.nature.com/articles/nm.4292",
  "https://github.com/UMCUGenetics/CHORD"
]) {
  if (!sourceMap.includes(requiredUrl)) {
    errors.push(`SOURCE_MAP.md is missing required URL: ${requiredUrl}`);
  }
}

let manifest: AtlasManifest | null = null;
try {
  manifest = JSON.parse(readProjectFile("manifests/validation_atlases.json")) as AtlasManifest;
} catch (error) {
  errors.push(`validation_atlases.json is not valid JSON: ${String(error)}`);
}

if (manifest) {
  if (!manifest.schema_version) {
    errors.push("Manifest is missing schema_version.");
  }
  if (!Array.isArray(manifest.sources) || manifest.sources.length < 10) {
    errors.push("Manifest should include at least 10 researched sources/tools.");
  }

  const ids = new Set<string>();
  let hasPhase1 = false;
  let hasTool = false;
  let hasDataset = false;

  for (const source of manifest.sources) {
    if (ids.has(source.id)) {
      errors.push(`Duplicate manifest source id: ${source.id}`);
    }
    ids.add(source.id);

    for (const field of ["id", "title", "kind", "priority", "primary_use", "access", "verifier"] as const) {
      if (!source[field]) {
        errors.push(`Manifest source ${source.id || "(missing id)"} is missing ${field}.`);
      }
    }

    if (!Array.isArray(source.urls) || source.urls.length === 0) {
      errors.push(`Manifest source ${source.id} must include at least one URL.`);
    }

    if (!Array.isArray(source.expected_artifacts) || source.expected_artifacts.length === 0) {
      errors.push(`Manifest source ${source.id} must include expected artifacts.`);
    }

    hasPhase1 ||= source.priority.includes("phase-1");
    hasTool ||= source.kind === "tool";
    hasDataset ||= source.kind === "dataset";
  }

  if (!hasPhase1) {
    errors.push("Manifest has no phase-1 source.");
  }
  if (!hasTool) {
    errors.push("Manifest has no tool sources.");
  }
  if (!hasDataset) {
    errors.push("Manifest has no dataset sources.");
  }
}

const pythonVersion = commandVersion("python3", ["--version"]);
if (!pythonVersion) {
  errors.push("python3 is not available.");
}

const rVersion = commandVersion("R", ["--version"]);
if (!rVersion) {
  warnings.push("R is not available locally; R-native tools should use a container or later R setup.");
}

if (!process.versions.bun) {
  errors.push("This verifier should be run with Bun.");
}

async function checkUrls() {
  if (!manifest || process.env.CHECK_URLS !== "1") {
    return;
  }

  for (const source of manifest.sources) {
    for (const url of source.urls) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        let response = await fetch(url, { method: "HEAD", signal: controller.signal });
        if (response.status === 405 || response.status === 403) {
          response = await fetch(url, { method: "GET", signal: controller.signal });
        }
        if (response.status >= 400) {
          warnings.push(`URL returned ${response.status}: ${url}`);
        }
      } catch (error) {
        warnings.push(`URL check failed for ${url}: ${String(error)}`);
      } finally {
        clearTimeout(timeout);
      }
    }
  }
}

await checkUrls();

for (const warning of warnings) {
  console.warn(`warning: ${warning}`);
}

if (errors.length > 0) {
  for (const error of errors) {
    console.error(`error: ${error}`);
  }
  process.exit(1);
}

console.log("Plan verification passed.");
if (pythonVersion) {
  console.log(`Python: ${pythonVersion}`);
}
console.log(`Bun: ${process.versions.bun}`);

