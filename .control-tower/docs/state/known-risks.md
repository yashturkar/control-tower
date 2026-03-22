# Known Risks

- Tower role leakage into direct implementation if delegation discipline is not maintained.
- Memory drift if imported sessions are not curated into docs and working summaries.
- Session ambiguity if Tower sessions are not resumed through `tower resume`.
- The local working tree still contains untracked transient `.control-tower` artifacts after the rollout commit.
- Git-master and Builder conventions are recommended in state, but not yet codified in their prompts or policy files.
