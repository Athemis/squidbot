# Dashboard CI Checks Mapping

## Ownership

- Accountable owners: repository maintainers (GitHub role: Maintain).
- Scope: dashboard CI job names, branch-protection required checks, and installed-artifact smoke gate.

## Required Branch-Protection Checks

- `dashboard-frontend`
- `dashboard-package-smoke`

## Update Policy

- If any dashboard CI job name changes in `.github/workflows/ci.yml`, this file must be
  updated in the same PR.
- PRs that change this file require maintainer review.
