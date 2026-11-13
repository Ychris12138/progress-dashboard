# Progress dashboard: local-first work

- This is an independent personal progress project. Phases one through three implement local data, front-end interactions and guarded Git transactions. Phase three permits synthetic-only tests against disposable local bare remotes. Phase four authorizes creating the owner-verified public GitHub repository and deploying only empty business data through Pages. Real progress publication remains disabled; do not remove the empty-data gate without explicit user authorization.
- Read README.md and docs/CONTRACTS.md before changing formats. All five schemas are independent. Update semantic validators, schemas and tests together.
- Source/private state lives in a sibling local directory, outside every Git worktree. Never move real chat content, IDs, paths, approvals or caches into this repository or fixtures.
- Formal public data starts empty. Synthetic examples belong only in tests/fixtures. Never approve or publish real records on the user's behalf without explicit approval of that batch digest.
- Public records are constructed using a positive allowlist. Never copy a source/draft object and strip a few private fields.
- Dates are uncertain whole days, not known midnight times. Overlapping conflicting snapshots require clarification. Do not fabricate status, percentages, efficiency or scientific conclusions.
- Do not modify source chats, inspect global Codex logs, scan the disk or send prompts to other chats. Desktop reads are scoped to user-selected sources and time windows. Tool/list summaries are not progress evidence.
- Current-work recording: read the draft schema; use a stable draft_id; include private evidence and verified public text; omit record_id and recorded_at; import locally and present the resulting preview for review.
- Desktop repeat reads must reuse source unit mappings, reread the recent five completed turns, preserve unfinished scan boundaries, and compare IDs plus content hashes. A changed source becomes a local review candidate.
- Use Python 3.12+, standard library runtime, and `python3.12 -m unittest discover -s tests -v`. CI includes 3.12 and 3.14; do not claim the latter passed without a run.
- The browser runtime has no third-party dependencies or CDN assets. Node 24.15+ and pinned jsdom are development-only DOM tests (`npm ci --ignore-scripts`, `npm test`). DOM checks are not evidence of real browser layout or device testing.
- Use `build.py --synthetic --output` outside the repository to preview fixtures. Preserve empty formal public data. Draft form inputs stay in memory; never persist them in browser storage, URLs or analytics.
- For browser checks use supported CUA with a connected browser. Never launch the installed system Chrome from a restricted shell or fall back to it through Playwright/Puppeteer. Report unavailable visual checks.
- Keep temporary evidence until the user has reviewed it. Do not reset commits, delete original chats, or remove failed capture evidence to make tests appear clean.
- Read docs/GIT_WORKFLOW.md before initialization or publication. Ordinary publish requires a frozen approved batch and an initialization receipt. Only scripts/demo_git.py automatically approves its fixed synthetic inputs; never reuse that approval shortcut for real records.
- Before a commit, rollback only verified batch-owned changes; external edits stop recovery. After a commit, retain it and query the remote before retrying. Never force-push, stash, rebase or reset automatically.
