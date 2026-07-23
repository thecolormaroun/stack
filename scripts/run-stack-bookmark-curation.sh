#!/usr/bin/env bash
# Run one Stack collection or curation phase.  This script never publishes.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-}"
if [[ "$mode" != "collection" && "$mode" != "curation" ]]; then
  echo "usage: $0 collection|curation [--manual] [--apply]" >&2
  exit 2
fi
shift
manual_run=false
if [[ "${1:-}" == "--manual" ]]; then
  manual_run=true
  shift
fi
requested_mode="dry-run"
if [[ "${1:-}" == "--apply" ]]; then
  requested_mode="apply"
fi

state_root="${STACK_BOOKMARK_STATE_ROOT:-${HOME}/.local/state/stack}"
umask 077
mkdir -p "$state_root/receipts"
chmod 700 "$state_root" "$state_root/receipts"
lock="$state_root/${mode}.lock"
if ! mkdir "$lock" 2>/dev/null; then
  printf '{"receipt_type":"scheduler","outcome":"lock_busy","phase":"%s"}\n' "$mode"
  exit 75
fi
trap 'rmdir "$lock"' EXIT

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
receipt="$state_root/receipts/${mode}-${stamp}.json"
annotate_receipt() {
  python3 - "$receipt" "$mode" "$manual_run" "$requested_mode" <<'PY'
import json, sys
path, phase, manual, requested_mode = sys.argv[1:]
data = json.loads(open(path, encoding="utf-8").read())
data["receipt_type"] = "partial" if data.get("complete") is False else phase
data["phase"] = phase
data["complete"] = data.get("complete") is not False
data["manual_run"] = manual == "true"
data.setdefault("mode", requested_mode)
open(path, "w", encoding="utf-8").write(json.dumps(data, indent=2, sort_keys=True) + "\n")
PY
  chmod 600 "$receipt"
}
annotate_failed_receipt() {
  python3 - "$receipt" "$mode" "$manual_run" "$requested_mode" <<'PY'
import json, sys
path, phase, manual, requested_mode = sys.argv[1:]
data = json.loads(open(path, encoding="utf-8").read())
data.update({"receipt_type": "partial", "phase": phase, "complete": False,
             "manual_run": manual == "true", "mode": requested_mode})
open(path, "w", encoding="utf-8").write(json.dumps(data, indent=2, sort_keys=True) + "\n")
PY
  chmod 600 "$receipt"
}
if [[ "$mode" == "collection" ]]; then
  python3 "$root/scripts/collect-bookmark-candidates.py" \
    --sources "${STACK_BOOKMARK_SOURCES:-$root/config/bookmark-sources.json}" \
    --policy "${STACK_BOOKMARK_FETCH_POLICY:-$root/config/bookmark-fetch-policy.json}" \
    --ledger "${STACK_BOOKMARK_LEDGER:-$state_root/bookmark-intake.sqlite}" \
    --out "$receipt" "$@"
  annotate_receipt
  exit 0
fi

# Curation is intentionally review-only.  Candidates are materialized from the
# owner-only ledger; no external candidate export is required.
apply=0
if [[ "${1:-}" == "--apply" ]]; then
  apply=1
  shift
fi
if [[ "$#" -ne 0 ]]; then
  echo "usage: $0 curation [--manual] [--apply]" >&2
  exit 2
fi
ledger="${STACK_BOOKMARK_LEDGER:-$state_root/bookmark-intake.sqlite}"
curation_policy="${STACK_CAPABILITY_ACTIVATION_POLICY:-$root/config/capability-activation-policy.json}"
candidate_file="$state_root/.curation-candidates-$stamp.json"
trap 'rm -f "$candidate_file"; rmdir "$lock"' EXIT
python3 "$root/scripts/materialize-bookmark-candidates.py" \
  --ledger "$ledger" --policy "$curation_policy" --out "$candidate_file"
python3 "$root/scripts/triage-bookmark-candidates.py" \
  --candidates "$candidate_file" \
  --catalog "${STACK_CAPABILITY_CATALOG:-$root/registry/capabilities.json}" \
  --policy "$curation_policy" \
  --out "$receipt"
if [[ "$apply" -eq 1 ]]; then
  if [[ -n "${HERMES_LINK_INBOX_SCRIPT:-}" ]]; then
    if ! python3 - "$receipt" "$HERMES_LINK_INBOX_SCRIPT" "$root/scripts/triage-bookmark-candidates.py" <<'PY'
import importlib.util, json, subprocess, sys
packet, script, module_path = sys.argv[1:]
spec = importlib.util.spec_from_file_location("stack_triage", module_path)
triage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(triage)
for record in triage.hermes_callback_records(json.load(open(packet, encoding="utf-8"))):
    subprocess.run([sys.executable, *triage.hermes_callback_argv(script, record)], check=True)
PY
    then
      annotate_failed_receipt
      exit 1
    fi
  fi
  # Mark only the bounded presented candidates, and only after every configured
  # callback succeeds. Deferred candidates remain eligible for a later packet.
  if ! python3 "$root/scripts/materialize-bookmark-candidates.py" \
    --ledger "$ledger" --policy "$curation_policy" --apply --packet "$receipt" >/dev/null; then
    annotate_failed_receipt
    exit 1
  fi
fi
annotate_receipt
