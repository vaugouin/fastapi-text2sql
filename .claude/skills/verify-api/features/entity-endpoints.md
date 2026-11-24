# Entity detail endpoints and MCP

## Sub-features
- `GET /movies/{id}`, `/series/{id}`, `/seasons/{id_serie}/{season_number}`, `/persons/{id}`, `/companies/{id}`, `/networks/{id}`, `/collections/{id}`, `/topics/{id}`, `/lists/{id}`, `/movements/{id}`, `/technicals/{id}`, `/genres/{id}`, `/groups/{id}`, `/deaths/{id}`, `/awards/{id}`, `/nominations/{id}`, `/locations/{id}`, `/sourceworks/{id}`. Ids are the TMDb ones for movies, series and persons (15 Citizen Kane, 2636 Alfred Hitchcock).
- Hand-written SQL, no LLM, no cost. Related lists, localized `_FR` fields, `wikipedia_page`, `data_freshness`.
- The MCP server (`/mcp`, GitHub login) exposes the same JSON through `get_*` tools.

## How to get to it
Clicking an entity in a front; MCP tools in Claude or ChatGPT.

## Driving it
- `verify_api.py entity movies 15`, `verify_api.py entity seasons 1399 1`.
- From a Claude session with the text2sql MCP connector: the `get_*` tools return the same payload, which checks both surfaces at once.

## Gotchas
- `data/text_to_sql.md` (generated SQL) and these endpoints are two SQL surfaces over the same data: a discrepancy between a search answer and an entity page is worth reporting, not patching silently.
- Use these endpoints to check a search answer against the base (a film's runtime, a person's credits) rather than general knowledge.
