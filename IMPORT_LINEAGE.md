# Import lineage

The original local protocol was committed before implementation and software tests. `history/original-local.bundle` preserves that complete original history. SHA values in retained software-verification records refer to the original local commits and are resolvable from the bundle. They are not claimed to be GitHub REST import commit SHAs.

GitHub repositories were created privately on 13 October 2026. The connected GitHub API recreates reviewable import commits after the browser-created initial README. Original research protocols are imported without edits. No research experiments had occurred at import time; the Mac benchmark followed on 17 October 2026. Raw software checks are prior local observations, not hosted-CI outcomes.

To inspect original history without overwriting current branches, run:

```bash
git fetch ./history/original-local.bundle 'refs/heads/*:refs/remotes/local-evidence/*'
git log --all --oneline
```

The current source matches the tested Python hashes. Changes during import concern repository links, status and lineage documentation only.
