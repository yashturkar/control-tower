# Known Risks

- Tower role leakage into direct implementation if delegation discipline is not maintained.
- Memory drift if imported sessions are not curated into docs and working summaries.
- Session ambiguity if Tower sessions are not resumed through `tower resume`.
- Specialist delegation is blocked until Codex authentication is restored after the observed `refresh_token_reused` failure.
