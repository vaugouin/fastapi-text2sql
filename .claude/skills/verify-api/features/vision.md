# Image questions (vision pre-stage)

## Sub-features
- `POST /uploads/vision` takes the raw image bytes (JPEG, PNG, WEBP; HEIC refused; 25 MB ceiling) and returns `image_ref`, a bare file name; images are kept 30 days in the shared `uploads/` folder.
- `POST /search/text2sql` with `image_ref` (and optionally a question): the vision model identifies the work or person, the question is composed in code from what was identified, then the normal pipeline runs. `vision_evidence` and `vision_model_used` in the response. A recognition cache keyed by the image.

## How to get to it
voice-agent and t2s-front photo search; MCP clients pass an `image_ref` deposited first.

## Driving it
- `verify_api.py upload <file.jpg>` then `verify_api.py ask "what is this film?" --extra '{"image_ref": "<ref>"}'`.

## Gotchas
- **Only upload images that may sit on the production server for 30 days**: a poster or a film still, never a personal photo.
- The vision call is OpenAI only, by design.
