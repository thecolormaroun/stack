#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

failures=0

ignored_path() {
  case "$1" in
    .git/*|node_modules/*|scripts/security/scan-sensitive-content.sh|.gitleaks.toml)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

binary_or_unreadable() {
  [[ ! -f "$1" ]] && return 0
  grep -Iq . "$1" 2>/dev/null
}

report() {
  local file="$1"
  local line="$2"
  local rule="$3"

  printf '%s:%s: sensitive-content: %s\n' "$file" "$line" "$rule" >&2
  failures=$((failures + 1))
}

scan_path_name() {
  local file="$1"

  case "$file" in
    *.pem|*.p12|*.pfx|*.key|*.asc|*.kdbx|*.mobileconfig)
      report "$file" 0 "private key, certificate, or credential-like file extension"
      ;;
    .env|.env.*|*/.env|*/.env.*|*.env)
      case "$file" in
        *.example|*.sample|*.template)
          ;;
        *)
          report "$file" 0 "environment file should not be committed"
          ;;
      esac
      ;;
    */settings.local.json|settings.local.json|*.local.json|*.secrets.*|*secret*.json|*credentials*.json)
      report "$file" 0 "local settings or credential-like file name"
      ;;
  esac
}

scan_line() {
  local file="$1"
  local findings
  local count

  findings="$(
    awk -v file="$file" '
      function placeholder(line) {
        line = tolower(line)
        return line ~ /\$\{\{[^}]*secrets\.[^}]*}}/ ||
          line ~ /<your_|<example|example_|changeme|replace_me|not-a-real|redacted|placeholder/
      }

      function finding(rule) {
        print file ":" NR ": sensitive-content: " rule
      }

      {
        lower = tolower($0)

        if ($0 ~ /-----BEGIN[[:space:]][A-Z0-9[:space:]]*PRIVATE[[:space:]]KEY-----/) {
          finding("private key material")
        }

        if ($0 ~ /https?:\/\/[^[:space:]\/:@]+:[^[:space:]@]+@/) {
          finding("URL contains embedded credentials")
        }

        if ($0 ~ /\/Users\/maroun\//) {
          finding("local Maroun machine path")
        }

        if ($0 ~ /\.codex\/(sessions|archived_sessions|memories)/ ||
          $0 ~ /rollout-[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9-]+-[0-9a-f-]+\.jsonl/) {
          finding("private Codex session or memory artifact")
        }

        if (lower ~ /(finance\/amazon|amazon-collette|account_snapshots|monarch|copilot[[:space:]_-]*account)/) {
          finding("personal finance or household account lane")
        }

        if (!placeholder($0) &&
          $0 ~ /(sk-ant-api03-[A-Za-z0-9_-]{20,}|sk-proj-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{32,}|gh[pousr]_[A-Za-z0-9_]{32,}|github_pat_[A-Za-z0-9_]{32,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{20,})/) {
          finding("provider token pattern")
        }

        if (!placeholder($0) &&
          lower ~ /(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|private[_-]?key)[[:space:]]*[:=][[:space:]]*["'\''"]?[a-z0-9_.\/+=-]{16,}/) {
          finding("secret-looking config assignment")
        }
      }
    ' "$file"
  )"

  if [[ -n "$findings" ]]; then
    printf '%s\n' "$findings" >&2
    count="$(printf '%s\n' "$findings" | wc -l | tr -d ' ')"
    failures=$((failures + count))
  fi
}

scan_file() {
  local file="$1"

  ignored_path "$file" && return 0
  binary_or_unreadable "$file" || return 0

  scan_path_name "$file"
  scan_line "$file"
}

while IFS= read -r -d '' file; do
  scan_file "$file"
done < <(git ls-files -co --exclude-standard -z)

if (( failures > 0 )); then
  printf '\nStack sensitive content scan failed with %s finding(s).\n' "$failures" >&2
  printf 'Review the flagged lines without pasting secret values into chat or PR comments.\n' >&2
  exit 1
fi

printf 'Stack sensitive content scan passed.\n'
