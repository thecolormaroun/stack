/** Environment fence shared by the pinned GBrain runtime and portable tests. */

const ALLOWED_GBRAIN_KEYS = new Set([
  "GBRAIN_SOURCE",
  "GBRAIN_CLI_PATH",
  "GBRAIN_CONFIG_SHA256",
]);

const BLOCKED_PROVIDER_PREFIXES = [
  "OPENAI_",
  "ANTHROPIC_",
  "ZEROENTROPY_",
  "OPENROUTER_",
  "VOYAGE_",
  "AZURE_OPENAI_",
  "GEMINI_",
  "GOOGLE_",
];

function isDangerousKey(key) {
  return (
    (key.startsWith("GBRAIN_") && !ALLOWED_GBRAIN_KEYS.has(key)) ||
    key === "DATABASE_URL" ||
    key.endsWith("_API_KEY") ||
    key.endsWith("_TOKEN") ||
    key.endsWith("_SECRET") ||
    BLOCKED_PROVIDER_PREFIXES.some((prefix) => key.startsWith(prefix))
  );
}

export function assertSafeEnvironment(environment = process.env) {
  if (Object.keys(environment).some(isDangerousKey)) {
    throw new Error("pinned environment rejected");
  }
}
