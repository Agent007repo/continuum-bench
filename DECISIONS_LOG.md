# Decisions log

2026-10-13: We prioritise TrustTrace and build a tested vertical slice before expanding the catalogue. Current artefacts are a foundation, not release v0.1.0.

2026-10-13: Connected GitHub tools verify account Agent007repo but cannot create repositories. Repository-name lookups returned 404, which means absent or inaccessible. We prepare local git history and a private-creation script. No existing repositories are modified.

2026-10-13: Package names are working repository names. Global PyPI name availability is UNVERIFIED. Neither package will be published to PyPI in this milestone.

2026-10-13: Legal texts and EUR-Lex reuse terms are blocked by retrieval. We use original synthetic design concerns, not copied excerpts or binding article mappings. We retain an explicit verification backlog.

2026-10-13: We cannot truthfully state that Samarth reviewed the code or ran annotations yet. The AI disclosure distinguishes completed assistant work from pending human review.

2026-10-13: CI uses ubuntu-24.04 and mocks. Private-runner sizing is based on the opened GitHub documentation, not a claim that CI has run. Pages deployment and releases remain disabled pending explicit approval.

2026-10-13: Both initial hosted verification jobs passed. The gitleaks Action wrapper failed on its PR-metadata API call because the workflow token has contents-read permission only. We replace the wrapper with gitleaks CLI 8.30.1 and pin the Linux archive SHA-256 verified from the official release. It scans full checked-out git history and keeps the existing token permissions. Hosted secret-check validation is rerun before accepting the milestone.
