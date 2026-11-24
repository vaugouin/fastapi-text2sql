# Feature map of the API

One file per feature, written from the client's point of view: what the feature is, how a client reaches it, how to drive it with `scripts/verify_api.py`, what to read in the response, and the traps. It is the agent's memory of the product surface: a vague report ("the French answer looks wrong", a screenshot of a front) maps to a feature here, then to a probe.

| Feature | File | Spends tokens |
| --- | --- | --- |
| Instances, readiness, identity | `health-and-instances.md` | no |
| Question to SQL, the core pipeline | `search.md` | yes |
| Bare identifiers (IMDb, Wikidata) | `fast-path.md` | no |
| Cache tiers and the feedback bypass | `cache.md` | yes, unless a hit |
| Stronger-model retry and rescues | `complex-retry.md` | yes, more |
| Result representations and intent | `representations.md` | yes |
| Languages (`ui_language`) | `languages.md` | yes |
| Pagination, homonyms, dropped clauses | `pagination-and-ambiguity.md` | yes |
| Image questions (vision pre-stage) | `vision.md` | yes |
| Entity detail endpoints and MCP | `entity-endpoints.md` | no |
| Samples and feedback | `samples-and-feedback.md` | no |

`smoke.json` holds the probes `verify_api.py smoke` runs, with their measured expectations.

Keep this map true: when an endpoint, a request field or a response field changes, update the matching file in the same commit, and add or adjust a probe in `smoke.json`.
