# doc/ : reference documentation

Long-form references that would drown [../AGENTS.md](../AGENTS.md) and [../README.md](../README.md)
if they lived there. `AGENTS.md` and `CLAUDE.md` stay at the repository root on purpose: the first
is the canonical source of agent instructions for the repo, the second is only a pointer to it, and
moving either would break that convention.

## The index

| document | read it when |
|---|---|
| [entity-resolution-thresholds.md](entity-resolution-thresholds.md) | **you are about to change a `min_fuzz_ratio`, or to add a new entity that needs one.** Method, data, traps and the exact bench commands |
| [MCP.md](MCP.md) | working on the MCP server: tool code, resource reference, client setup, bearer token, end-to-end flow |
| [RAPIDFUZZ.md](RAPIDFUZZ.md) | touching the RapidFuzz path: setup, and the `*_NORM` / `*_KEY` generated columns and FULLTEXT indexes it requires |
| [SEASONS_AND_EPISODES.md](SEASONS_AND_EPISODES.md) | working on the seasons or episodes endpoints, their source tables, and the read-model swap still pending |
| [EXTEND_T2S_TECHNICAL.md](EXTEND_T2S_TECHNICAL.md) | extending `Technical_format`: schema, prompt and resolver changes, and the retired `Aspect_ratio` history |
| [closed-vocab-entity-plan.md](closed-vocab-entity-plan.md) | adding a closed-vocabulary entity, the rollout pattern and its checklist |
| [sql/](sql/) | reference DDL for the canonical tables. **Read-only** unless a task explicitly says otherwise |

## Adding a new entity: the threshold is not optional

A resolver without a rejection threshold does not fail. It returns its nearest neighbour however
far it sits, and produces a confidently wrong answer that nothing signals. That was the state of
thirteen resolvers out of fourteen until 2026-08-25, and it is why invented names resolved to real
people.

So when a new entity ships, its threshold ships with it, and it is **measured, never chosen**:
[entity-resolution-thresholds.md](entity-resolution-thresholds.md) carries the method, the bench
and the commands. Section 10 of that document is the one to read first if a value looks wrong,
because on this work the instrument was at fault four times before the resolver ever was.

Two traps from that document bite a new entity in particular. If its ChromaDB documents concatenate
a description, declare `document_name_separator` or the ratio will grade a perfect match near zero.
If its values carry a generic descriptor word, declare `score_stopwords` or that shared word will
inflate the similarity of anything unrelated.

## Keeping this folder honest

Every document here is dated and says what was measured rather than what was intended. When one of
them stops matching the code, fix the document in the same commit as the code, and say so in the
message. A reference that lies is worse than an absent one, because it is believed.
