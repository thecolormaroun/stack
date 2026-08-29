#!/usr/bin/env bun
/** Config-bound, source-scoped GBrain operations for Stack's weekly loop. */

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { assertSafeEnvironment } from "./gbrain-pinned-environment.mjs";

type Request =
  | { schema_version: 1; source: "x-bookmarks"; operation: "version" }
  | { schema_version: 1; source: "x-bookmarks"; operation: "sources_status" }
  | {
      schema_version: 1;
      source: "x-bookmarks";
      operation: "keyword";
      query: string;
      limit: number;
    }
  | {
      schema_version: 1;
      source: "x-bookmarks";
      operation: "import";
      directory: string;
    };

const VERSION = "0.42.67.0";

function fail(): never {
  throw new Error("pinned operation failed closed");
}

function assertLocalBackend(config: Record<string, unknown>): void {
  if (config.engine === "postgres") {
    if (typeof config.database_url !== "string") fail();
    const databaseUrl = new URL(config.database_url);
    const database = decodeURIComponent(databaseUrl.pathname.replace(/^\//, ""));
    if (
      !["postgres:", "postgresql:"].includes(databaseUrl.protocol) ||
      !["127.0.0.1", "::1", "localhost"].includes(databaseUrl.hostname) ||
      databaseUrl.port !== "5432" ||
      database !== "gbrain_mookie" ||
      databaseUrl.search !== "" ||
      databaseUrl.hash !== ""
    ) fail();
    return;
  }
  if (
    config.engine !== "pglite" ||
    config.database_url !== undefined ||
    typeof config.database_path !== "string" ||
    !isAbsolute(config.database_path)
  ) fail();
  const lexical = resolve(config.database_path);
  const localRoot = resolve(homedir(), ".gbrain");
  const resolved = realpathSync(lexical);
  const details = lstatSync(resolved);
  if (
    resolved !== lexical ||
    !(resolved === localRoot || resolved.startsWith(`${localRoot}/`)) ||
    details.isSymbolicLink() ||
    details.uid !== process.getuid?.() ||
    (details.mode & 0o022) !== 0
  ) fail();
}

function boundConfigBytes(): Buffer {
  const expectedDigest = process.env.GBRAIN_CONFIG_SHA256;
  if (!expectedDigest || !/^[a-f0-9]{64}$/.test(expectedDigest)) fail();
  const lexical = resolve(homedir(), ".gbrain", "config.json");
  const resolved = realpathSync(lexical);
  const details = lstatSync(resolved);
  const payload = readFileSync(resolved);
  if (
    resolved !== lexical ||
    details.isSymbolicLink() ||
    details.uid !== process.getuid?.() ||
    (details.mode & 0o777) !== 0o600 ||
    createHash("sha256").update(payload).digest("hex") !== expectedDigest
  ) fail();
  return payload;
}

function moduleRoot(): string {
  const cliPath = process.env.GBRAIN_CLI_PATH;
  if (!cliPath) fail();
  const expectedCli = realpathSync(join(homedir(), ".bun", "bin", "gbrain"));
  const resolvedCli = realpathSync(cliPath);
  if (resolvedCli !== expectedCli || !resolvedCli.endsWith("/gbrain/src/cli.ts")) fail();
  const root = dirname(dirname(resolvedCli));
  const packageDocument = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
  if (packageDocument?.name !== "gbrain" || packageDocument?.version !== VERSION) fail();
  return root;
}

function validateRequest(value: unknown): Request {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail();
  const request = value as Partial<Request>;
  if (request.schema_version !== 1 || request.source !== "x-bookmarks") fail();
  if (!["version", "sources_status", "keyword", "import"].includes(String(request.operation))) fail();
  if (request.operation === "import") {
    if (typeof request.directory !== "string" || !isAbsolute(request.directory)) fail();
    const lexical = resolve(request.directory);
    const resolved = realpathSync(lexical);
    const details = lstatSync(resolved);
    if (
      resolved !== lexical ||
      details.isSymbolicLink() ||
      !details.isDirectory() ||
      details.uid !== process.getuid?.() ||
      (details.mode & 0o002) !== 0
    ) fail();
  } else if (request.operation === "keyword") {
    if (
      typeof request.query !== "string" ||
      request.query.length === 0 ||
      request.query.length > 4096 ||
      !Number.isSafeInteger(request.limit) ||
      (request.limit as number) < 1 ||
      (request.limit as number) > 140
    ) fail();
  } else if ("directory" in request || "query" in request || "limit" in request) {
    fail();
  }
  return request as Request;
}

function localCloneAttested(status: Record<string, unknown>): boolean {
  if (status.remote_url !== null || typeof status.local_path !== "string" || typeof status.last_commit !== "string") {
    return false;
  }
  const lexical = resolve(status.local_path);
  const localRoot = resolve(homedir(), ".gbrain");
  try {
    const resolved = realpathSync(lexical);
    const sourceDetails = lstatSync(resolved);
    const gitDirectory = join(resolved, ".git");
    const gitDetails = lstatSync(gitDirectory);
    if (
      resolved !== lexical ||
      !resolved.startsWith(`${localRoot}/`) ||
      !sourceDetails.isDirectory() ||
      !gitDetails.isDirectory() ||
      sourceDetails.uid !== process.getuid?.() ||
      gitDetails.uid !== process.getuid?.() ||
      (sourceDetails.mode & 0o022) !== 0 ||
      (gitDetails.mode & 0o022) !== 0
    ) return false;
    const git = (args: string[]) => execFileSync("/usr/bin/git", ["-C", resolved, ...args], {
      encoding: "utf8",
      env: { HOME: homedir(), PATH: "/usr/bin:/bin:/usr/sbin:/sbin", TMPDIR: "/private/tmp" },
      timeout: 30_000,
    }).trim();
    return (
      git(["remote"]) === "" &&
      git(["rev-parse", "--is-inside-work-tree"]) === "true" &&
      git(["rev-parse", "HEAD"]) === status.last_commit &&
      git(["status", "--porcelain"]) === "" &&
      git(["fsck", "--no-progress"]) === ""
    );
  } catch {
    return false;
  }
}

async function main(): Promise<void> {
  if (realpathSync(process.execPath) !== realpathSync("/opt/homebrew/bin/bun")) fail();
  assertSafeEnvironment(process.env);
  const root = moduleRoot();
  const raw = await Bun.stdin.text();
  if (raw.length === 0 || raw.length > 8192) fail();
  const request = validateRequest(JSON.parse(raw));
  if (request.operation === "version") {
    process.stdout.write(`gbrain ${VERSION}`);
    return;
  }

  const configBytes = boundConfigBytes();
  const snapshotRoot = mkdtempSync(join(homedir(), ".gbrain", ".stack-config-"));
  const snapshotDirectory = join(snapshotRoot, ".gbrain");
  const snapshotConfig = join(snapshotDirectory, "config.json");
  try {
    chmodSync(snapshotRoot, 0o700);
    mkdirSync(snapshotDirectory, { mode: 0o700 });
    writeFileSync(snapshotConfig, configBytes, { mode: 0o600 });
    chmodSync(snapshotConfig, 0o600);
    process.env.GBRAIN_HOME = snapshotRoot;

    const configModule = await import(pathToFileURL(join(root, "src/core/config.ts")).href);
    const factoryModule = await import(pathToFileURL(join(root, "src/core/engine-factory.ts")).href);
    const expectedDigest = process.env.GBRAIN_CONFIG_SHA256 as string;
    const assertSnapshot = () => {
      const payload = readFileSync(snapshotConfig);
      if (createHash("sha256").update(payload).digest("hex") !== expectedDigest) fail();
    };
    assertSnapshot();
    const config = configModule.loadConfig();
    assertSnapshot();
    if (!config) fail();
    assertLocalBackend(config);
    const engineConfig = configModule.toEngineConfig(config);
    const engine = await factoryModule.createEngine(engineConfig);
    try {
      await engine.connect(engineConfig);
      if (request.operation === "sources_status") {
        const sourceModule = await import(pathToFileURL(join(root, "src/core/sources-ops.ts")).href);
        const status = await sourceModule.getSourceStatus(engine, request.source);
        assertSnapshot();
        const cloneState = status.clone_state === "corrupted" && localCloneAttested(status)
          ? "local-attested"
          : status.clone_state;
        process.stdout.write(JSON.stringify({
          id: status.id,
          page_count: status.page_count,
          last_sync_at: status.last_sync_at,
          last_commit: status.last_commit,
          archived: status.archived,
          clone_state: cloneState,
        }));
        return;
      }
      if (request.operation === "keyword") {
        const results = await engine.searchKeyword(request.query, {
          limit: request.limit,
          sourceId: request.source,
          orFallback: true,
        });
        const pageIds = [...new Set(results
          .map((row: { page_id?: number }) => row.page_id)
          .filter((value: number | undefined): value is number => Number.isSafeInteger(value)))];
        const unverified = pageIds.length > 0
          ? await engine.getUnverifiedExtractionPageIds(pageIds)
          : new Set<number>();
        for (const row of results) {
          if (unverified.has(row.page_id)) row.unverified = true;
        }
        assertSnapshot();
        process.stdout.write(JSON.stringify(results));
        return;
      }
      const importModule = await import(pathToFileURL(join(root, "src/commands/import.ts")).href);
      const result = await importModule.runImport(
        engine,
        [request.directory, "--source-id", request.source, "--no-embed", "--json"],
        { sourceId: request.source },
      );
      assertSnapshot();
      process.stdout.write(JSON.stringify({
        status: "success",
        imported: result.imported,
        skipped: result.skipped,
        errors: result.errors,
        chunks: result.chunksCreated,
        total_files: result.imported + result.skipped + result.errors,
      }));
    } finally {
      await engine.disconnect();
    }
  } finally {
    delete process.env.GBRAIN_HOME;
    rmSync(snapshotRoot, { recursive: true, force: true });
  }
}

main().catch(() => {
  process.stderr.write("pinned operation failed closed\n");
  process.exit(1);
});
