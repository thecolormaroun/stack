# Capability Change Review

- Change: `{{CHANGE_ID}}`
- State: `{{STATE}}`
- Target: `{{TARGET_CAPABILITY}}`
- Base commit: `{{BASE_COMMIT}}`
- Patch digest: `{{PATCH_DIGEST}}`
- Evidence: {{EVIDENCE_IDS}}

## Expected behavior

{{EXPECTED_BEHAVIOR}}

## Scope and overlap

{{SCOPE_SUMMARY}}

{{OVERLAP_ANALYSIS}}

## Evaluation

- Profile: `{{EVALUATION_PROFILE}}`
- Development manifest: `{{DEVELOPMENT_DIGEST}}`
- Holdout manifest: `{{HOLDOUT_DIGEST}}`
- Rotating canary manifest: `{{CANARY_DIGEST}}`
- Result: `{{EVALUATION_STATUS}}`

## Safety boundary

This artifact is an owner-local quarantined patch. It does not authorize a
branch, pull request, merge, install, runtime publication, active-evidence
pointer update, provider spend, or source mutation.

## Rollback

Restore the declared paths from base commit `{{BASE_COMMIT}}`. Publication must
retain separate merge, compile, install, discovery, and rollback receipts.
