# Languages

## Sub-features
- `ui_language` `en` or `fr`: titles and descriptions come back in that language (`_FR` columns), the cache is keyed by it, the answer and summary facts follow it.
- Entity resolution guesses the script family of each name (Latin, Cyrillic...) to pick the search columns.

## How to get to it
t2s-front `/fr/` and voice-agent in French send `ui_language: "fr"`.

## Driving it
- `verify_api.py ask "<question française>" --lang fr`. The smoke probe asks the Hitchcock question in French and expects French titles ("Sueurs froides").

## Gotchas
- Compare the English and French twins of a question: the same SQL shape should return the same entities, only the labels change.
