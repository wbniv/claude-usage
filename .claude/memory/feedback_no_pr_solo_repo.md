---
name: feedback_no_pr_solo_repo
description: "Don't open PRs on this solo repo — pushing the branch (or merging to main) is enough"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7a2bdaad-d4f5-4652-ad79-a240be78798e
---

For claude-usage (github.com/wbniv/claude-usage), do NOT open pull requests. When asked to "push", push the branch (or merge to main) and stop.

**Why:** It's a solo repo with no review flow; a PR is pure ceremony/overhead. User reacted with "no PR needed, duh" after I opened one unprompted.

**How to apply:** On "push" → `git push` the branch. Only open a PR if the user explicitly says "open a PR" / "PR". See [[feedback_commit_scope.md]] for the same minimal-scope spirit.
