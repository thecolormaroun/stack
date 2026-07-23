# Private overlays

Private reference packs are local-only inputs. Stack's public catalog may name an optional overlay with an opaque `private-overlay:*` identifier and a `private-policy:*` policy identifier, but it must never contain a private path, URL, title, excerpt, or payload.

## Local contract

Create the local overlay outside this repository from [`registry/private-overlay.schema.json`](../registry/private-overlay.schema.json). Its directory, payload directory, and target-manifest directory must be mode `0700`; the overlay, payload, and target-manifest files must be mode `0600` and owned by the current user. The overlay binds each named runtime target to an opaque `local-target:*` identity. Its `target_authorization` points to a separate owner-local manifest whose owner identity and target identity must match before a private join is allowed. A target name supplied on the command line is therefore not authorization by itself.

Validate and compile it into an owner-only local output directory:

```sh
python3 scripts/validate-private-overlay.py \
  --overlay /owner-only/overlay.json \
  --target codex-local \
  --output /owner-only/compiled-private
```

For a target not listed by `authorized_runtime_targets`, the command returns an `excluded` result and creates no private output. For a listed target whose owner-local target manifest has been removed, changed, permissioned incorrectly, or whose identity no longer matches, it fails closed. For an authorized target, it stages then atomically replaces a separate private runtime manifest and private receipt with a digest. The command-line result and receipt contain only status, opaque identifiers, named target, and digest; they never include payload paths or contents. These files are local deployment state and must not be copied into generated Stack runtimes, logs, candidate packets, or public receipts.

Overlay directories, payloads, and their contents must not contain symlinks. If
authorization is removed, a trusted target identity no longer matches, a payload is missing, ownership or permissions are invalid, or validation fails, the
compiler revokes any existing private output for that target before returning.
This prevents a previously authorized payload from remaining reachable.

## Runtime compiler integration

`scripts/compile-runtime.py` must call `scan_public_artifact` on each public catalog, runtime manifest, receipt, and log payload before publishing it. It may call `compile_overlay` only after the public compilation succeeds and only when the declared runtime target is explicitly authorized. A missing, unreadable, removed, or incorrectly permissioned overlay payload fails that private compilation; the compiler must leave the public runtime intact and either fail closed or report the optional overlay as excluded. It must never fall back to copying a private payload into public output.

The scanner rejects URLs, common local filesystem paths, and fixture-only private sentinels. Production callers should treat any scanner failure as a publication failure, not as a redaction request.

The live synthetic contract proof is recorded in
[`artifacts/private-overlay-verification/2026-07-18.json`](../artifacts/private-overlay-verification/2026-07-18.json).
It records only the opaque overlay identifier, target names, modes, status, and
private-manifest digest. The source path and payload remain owner-local and are
never copied into this repository.
