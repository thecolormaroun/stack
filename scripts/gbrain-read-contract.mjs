/** Audited read compatibility; never broadens mutation support. */
export const READ_VERSIONS = new Set(["0.42.67.0", "0.48.2.0"]);
export const IMPORT_VERSION = "0.42.67.0";

export function operationVersionAllowed(version, operation) {
  if (operation === "import") return version === IMPORT_VERSION;
  return ["version", "sources_status", "keyword"].includes(operation)
    && READ_VERSIONS.has(version);
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
