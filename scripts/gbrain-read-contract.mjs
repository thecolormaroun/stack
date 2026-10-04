/** Audited read compatibility; never broadens mutation support. */
export const READ_VERSIONS = new Set(["0.42.67.0", "0.48.2.0", "0.59.0.0"]);
export const IMPORT_VERSION = "0.42.67.0";

export function operationVersionAllowed(version, operation) {
  if (operation === "import") return version === IMPORT_VERSION;
  return ["version", "sources_status", "keyword"].includes(operation)
    && READ_VERSIONS.has(version);
}

export function readEngineConfig(version, operation, config) {
  if (!operationVersionAllowed(version, operation)) throw new Error("unsupported operation");
  if (operation === "import" || operation === "version") return config;
  // 0.59 PGLite connect writes ownership locks and can repair WAL. Never
  // connect it for a read. Older versions retain their existing contracts.
  if (version === "0.59.0.0" && config.engine !== "postgres") {
    throw new Error("read backend rejected");
  }
  if (config.engine !== "postgres") return config;
  const url = new URL(config.database_url);
  if (url.search || url.hash) throw new Error("read connection override rejected");
  // postgres.js passes this as a startup GUC on every pooled connection,
  // including replacement connections. This never rewrites the owner config.
  url.searchParams.set("default_transaction_read_only", "on");
  return {...config, database_url: url.href};
}

export function assertReadOnlySession(rows) {
  if (!Array.isArray(rows) || rows.length !== 1 || rows[0]?.read_only !== "on") {
    throw new Error("read-only session not established");
  }
}

export function extractionIsUnverified(records, pageId) {
  // The old API returned only quarantined page IDs. The newer API also
  // returns ordinary status-bearing pages, with an explicit boolean flag.
  if (records instanceof Set) return records.has(pageId);
  if (!(records instanceof Map)) throw new Error("invalid extraction status contract");
  if (!records.has(pageId)) return false;
  const record = records.get(pageId);
  if (!record || typeof record.unverified !== "boolean") {
    throw new Error("invalid extraction status contract");
  }
  return record.unverified;
}
