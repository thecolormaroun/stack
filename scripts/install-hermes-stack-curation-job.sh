#!/usr/bin/env bash
# Print the reviewed Hermes cron operations; scheduling is opt-in only.
set -euo pipefail

stack_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

enable=false
install_wrappers=false
approval_token=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-wrappers) install_wrappers=true ;;
    --enable) enable=true ;;
    --approval-token) approval_token="${2:-}"; shift ;;
    *) echo "usage: $0 [--install-wrappers] [--enable --approval-token I_APPROVE_HERMES_STACK_CURATION]" >&2; exit 2 ;;
  esac
  shift
done

scripts_dir="${HOME}/.hermes/scripts"
collection_wrapper="$scripts_dir/stack-bookmark-collection.sh"
curation_wrapper="$scripts_dir/stack-bookmark-curation.sh"
collection_script="$(basename "$collection_wrapper")"
curation_script="$(basename "$curation_wrapper")"
verification_dir="${STACK_HERMES_VERIFICATION_DIR:-${HOME}/.local/state/stack/receipts}"
max_receipt_age="${STACK_HERMES_RECEIPT_MAX_AGE_SECONDS:-86400}"
collection_command=(hermes cron create '17 1 * * *' --name stack-bookmark-collection --script "$collection_script" --no-agent)
curation_command=(hermes cron create '23 9 * * 1' --name stack-bookmark-curation --script "$curation_script" --no-agent)
printf 'Dry-run only. Exact Hermes commands:\n'
printf 'hermes cron create %q --name %q --script %q --no-agent\n' '17 1 * * *' stack-bookmark-collection "$collection_script"
printf 'hermes cron create %q --name %q --script %q --no-agent\n' '23 9 * * 1' stack-bookmark-curation "$curation_script"
if [[ "$install_wrappers" == true ]]; then
  mkdir -p "$scripts_dir"
  umask 077
  printf '#!/usr/bin/env bash\nexport STACK_HERMES_LINK_INBOX_DB="${STACK_HERMES_LINK_INBOX_DB:-${MOOKIE_LINK_INBOX_DB:-${HERMES_HOME:-${HOME}/hermes}/link-inbox.db}}"\ncase "${1:-}" in\n  --dry-run) exec %q/scripts/run-stack-bookmark-curation.sh collection --manual ;;\n  --manual) exec %q/scripts/run-stack-bookmark-curation.sh collection --manual --apply ;;\nesac\nexec %q/scripts/run-stack-bookmark-curation.sh collection --apply\n' "$stack_root" "$stack_root" "$stack_root" > "$collection_wrapper"
  printf '#!/usr/bin/env bash\nexport HERMES_LINK_INBOX_SCRIPT="${HERMES_LINK_INBOX_SCRIPT:-${HERMES_HOME:-${HOME}/hermes}/scripts/mookie_link_inbox.py}"\ncase "${1:-}" in\n  --dry-run) exec %q/scripts/run-stack-bookmark-curation.sh curation --manual ;;\n  --manual) exec %q/scripts/run-stack-bookmark-curation.sh curation --manual --apply ;;\nesac\nexec %q/scripts/run-stack-bookmark-curation.sh curation --apply\n' "$stack_root" "$stack_root" "$stack_root" > "$curation_wrapper"
  chmod 700 "$collection_wrapper" "$curation_wrapper"
  echo "Installed wrappers only; no cron jobs were created. Run both manually and inspect their receipts before enablement."
fi
if [[ "$enable" != true ]]; then
  echo "Not enabling: pass --enable with the explicit approval token only after run-now verification."
  exit 0
fi
if [[ "$approval_token" != "I_APPROVE_HERMES_STACK_CURATION" ]]; then
  echo "Refusing enablement: explicit approval token is required." >&2
  exit 2
fi
if [[ ! -x "$collection_wrapper" || ! -x "$curation_wrapper" ]]; then
  echo "Refusing enablement: install and manually verify both wrappers first." >&2
  exit 4
fi
if [[ ! -d "$verification_dir" ]]; then
  echo "Refusing enablement: owner-only manual verification receipt directory is missing." >&2
  exit 5
fi
if ! python3 - "$verification_dir" <<'PY'
import os, stat, sys
details = os.stat(sys.argv[1])
if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700:
    raise SystemExit(1)
PY
then
  echo "Refusing enablement: verification receipt directory must be current-owner mode 0700." >&2
  exit 5
fi
if ! python3 - "$verification_dir" "$max_receipt_age" <<'PY'
import json, os, stat, sys, time
root, max_age = sys.argv[1], int(sys.argv[2])
now = time.time()
for phase in ("collection", "curation"):
    found = False
    for name in os.listdir(root):
        if not name.startswith(phase + "-") or not name.endswith(".json"):
            continue
        path = os.path.join(root, name)
        st = os.stat(path)
        if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600 or now - st.st_mtime > max_age:
            continue
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("receipt_type") == phase and data.get("phase") == phase and data.get("complete") is True and data.get("manual_run") is True and data.get("mode") == "apply":
            found = True
            break
    if not found:
        raise SystemExit(f"missing recent successful manual {phase} receipt")
PY
then
  echo "Refusing enablement: missing, stale, partial, or non-manual collection/curation receipts." >&2
  exit 5
fi
if ! python3 - "$stack_root" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
for relative in ("config/bookmark-sources.json", "config/bookmark-fetch-policy.json", "registry/capabilities.json"):
    path = root / relative
    if not path.is_file():
        raise SystemExit(f"missing curation configuration: {relative}")
    json.loads(path.read_text(encoding="utf-8"))
if not (root / "scripts/run-stack-bookmark-curation.sh").is_file():
    raise SystemExit("missing curation runner")
PY
then
  echo "Refusing enablement: Stack curation configuration is not ready." >&2
  exit 6
fi
gateway_status="$(hermes cron status 2>&1 || true)"
if [[ "$gateway_status" != *"Gateway is running"* || "$gateway_status" == *"not running"* ]]; then
  echo "Refusing enablement: Hermes gateway is not running." >&2
  exit 3
fi
existing_jobs="$(hermes cron list --all 2>&1 || true)"
if [[ "$existing_jobs" == *"stack-bookmark-collection"* || "$existing_jobs" == *"stack-bookmark-curation"* ]]; then
  echo "Refusing enablement: a Stack bookmark cron name already exists." >&2
  exit 7
fi
if ! collection_output="$("${collection_command[@]}" 2>&1)"; then
  printf '%s\n' "$collection_output" >&2
  exit 8
fi
printf '%s\n' "$collection_output"
collection_id="$(printf '%s\n' "$collection_output" | sed -n 's/^.*Created job: \([^[:space:]]\{1,\}\).*$/\1/p' | tail -1)"
if [[ -z "$collection_id" ]]; then
  echo "Collection job was created but its ID could not be verified; inspect Hermes cron state before retrying." >&2
  exit 8
fi
if ! curation_output="$("${curation_command[@]}" 2>&1)"; then
  printf '%s\n' "$curation_output" >&2
  if ! hermes cron remove "$collection_id"; then
    echo "Failed to compensate the collection job; manual Hermes cron cleanup is required." >&2
  fi
  exit 8
fi
printf '%s\n' "$curation_output"
curation_id="$(printf '%s\n' "$curation_output" | sed -n 's/^.*Created job: \([^[:space:]]\{1,\}\).*$/\1/p' | tail -1)"
if [[ -z "$curation_id" ]]; then
  echo "Curation job was created but its ID could not be verified; rolling back both jobs." >&2
  hermes cron remove "$collection_id" || true
  exit 8
fi
