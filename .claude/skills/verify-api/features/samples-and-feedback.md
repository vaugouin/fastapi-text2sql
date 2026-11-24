# Samples and feedback

## Sub-features
- `GET /samples?ui_language=en|fr&set=sample`: the tree of suggested questions (evaluation categories, sample questions with their parsed assertion). What the fronts show in their samples panel.
- `POST /feedback`: a user's 👍 or 👎 on an answer, with `request_id` (every search response carries one) and a comment; stored in `T_WC_T2S_FEEDBACK`; a 👎 turns the cache off for that question.

## How to get to it
Samples: the panel of every front. Feedback: the thumbs under an answer.

## Driving it
- `verify_api.py smoke --free` includes `GET /samples?ui_language=fr`.
- Feedback: **not driven by this CLI**. It writes to a production table read by the `analyse-feedback` workflow; a test rating would pollute it. If a check is needed, ask Philippe, then mark the row as a test in its comment.

## Gotchas
- The `request_id` of the response you verified is the key to find its log on the server and its feedback row.
