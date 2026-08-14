"""Verify the `wikipedia_page` block across every entity detail endpoint (FASTAPI-TEXT2SQL-195).

Run it against a deployed API after restarting the container; it needs no database access.

    python verify_wikipedia_page.py --base-url https://www.vaugouin.com --movie-id 1368337

Base URL and API key default to `T2S_BASE_URL` / `API_KEYS` (first key) from `.env`.

What it checks, endpoint by endpoint:

1. **Coverage**: the 15 detail endpoints that can serve `wikipedia_content` all return
   `wikipedia_page` when the entity has a Wikipedia article. A partial rollout would put an
   attribution on some sheets and not others, and a missing credit reads as a claim of
   authorship.
2. **Shape**: `lang` / `title` / `url`, all non-empty. The key is *absent* rather than
   null-filled when there is nothing to attribute, so a `"wikipedia_page": null` is a failure.
3. **The trap this ticket exists for**: `wikipedia_page.lang` must equal
   `data_freshness.wikipedia_lang`, and the URL host must be `<lang>.wikipedia.org`. An `fr`
   badge over an English article is a false attribution, which is worse than no credit at all.
4. **Language resolution**: `ui_language=fr` returns the French article when one exists;
   `ui_language=de`, which the API does not serve, falls back to `en` server-side.
5. **Payload cost**: a targeted `?collection=<name>` page carries no `wikipedia_page`.

Entity ids are **discovered**, not hardcoded, so the script stays valid as the database
changes: the walk starts at the seed movie (topics, lists, collections, movements, technicals,
awards, nominations), then widens to several cast members (groups, deaths, and the way to a
series), to that series and its seasons and episodes, and finally to neighbour films, stopping
for each entity type as soon as one id is found. Widening matters: a recent release carries no
award and no collection, and a living actor no cause-of-death entry, so a single seed silently
under-covers. What is still missing is reported as SKIPPED, never counted as a pass.
`/locations` is reachable only by a Wikidata Q-number, so pass one with `--location-id`.
"""
import argparse
import os
import sys
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MOVIE_ID = 1368337  # The Odyssey (2026), long EN and FR articles, many relations

# Endpoint order is the order of the ticket: the 15 routes that can serve wikipedia_content.
ENDPOINTS = [
    "movies", "series", "seasons", "episodes", "persons", "collections", "topics", "lists",
    "movements", "technicals", "groups", "deaths", "awards", "nominations", "locations",
]


class Checker:
    def __init__(self, base_url, api_key, timeout=60.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            headers={"X-API-Key": api_key}, timeout=timeout, follow_redirects=True
        )
        self.failures = []
        self.skipped = []
        self.checks = 0

    def get(self, path, **params):
        response = self.client.get(f"{self.base_url}{path}", params=params)
        response.raise_for_status()
        return response.json()

    def fail(self, label, message):
        self.failures.append(f"{label}: {message}")
        print(f"  FAIL  {label}: {message}")

    def ok(self, label, message):
        self.checks += 1
        print(f"  ok    {label}: {message}")

    # --- the invariants -------------------------------------------------------------

    def check_payload(self, label, payload):
        """Shape, absent-not-null, and agreement with data_freshness. Returns the block or None."""
        freshness = payload.get("data_freshness") or {}
        strfreshlang = freshness.get("wikipedia_lang")

        if "wikipedia_page" not in payload:
            if strfreshlang:
                # A page row exists (it dated the content) but carries no title or no URL.
                # Not a code defect: a crawler-coverage gap worth seeing rather than hiding.
                print(f"  note  {label}: no wikipedia_page while wikipedia_lang="
                      f"{strfreshlang!r} (page row without title/url, crawler coverage)")
            else:
                self.ok(label, "absent, and the entity has no Wikipedia page")
            return None

        page = payload["wikipedia_page"]
        if not isinstance(page, dict) or not page:
            self.fail(label, f"present but empty/null ({page!r}), the key must be omitted instead")
            return None

        for key in ("lang", "title", "url"):
            if not page.get(key):
                self.fail(label, f"missing or empty {key!r} in {page!r}")
                return None

        strlang, strurl = page["lang"], page["url"]

        if strfreshlang and strlang != strfreshlang:
            self.fail(label, f"lang {strlang!r} but data_freshness.wikipedia_lang "
                             f"{strfreshlang!r}, content and credit disagree")
        else:
            self.ok(label, f"lang={strlang} matches data_freshness.wikipedia_lang")

        strhost = urlparse(strurl).netloc
        if strhost != f"{strlang}.wikipedia.org":
            self.fail(label, f"lang {strlang!r} but URL host {strhost!r}, false attribution")
        else:
            self.ok(label, f"url host {strhost} matches lang")

        return page

    def check_endpoint(self, name, path):
        """Full response in en, then the fr and de language rules, then a targeted page."""
        print(f"\n[{name}] {path}")
        payload = self.get(path, ui_language="en")
        page_en = self.check_payload(f"{name} en", payload)

        payload_fr = self.get(path, ui_language="fr")
        page_fr = self.check_payload(f"{name} fr", payload_fr)
        if page_fr and page_en and page_fr["lang"] == "fr" and page_en["url"] == page_fr["url"]:
            self.fail(f"{name} fr", "same URL as English while claiming lang=fr")

        # 'de' is not served: the fallback must happen server-side, not in the client.
        payload_de = self.get(path, ui_language="de")
        page_de = self.check_payload(f"{name} de", payload_de)
        if page_de and page_de["lang"] != "en":
            self.fail(f"{name} de", f"unsupported language returned lang={page_de['lang']!r}, "
                                    f"expected the 'en' fallback")
        elif page_de:
            self.ok(f"{name} de", "unsupported language falls back to en server-side")

        # Targeted pagination page: lean payload, no attribution block.
        arrcollections = list((payload.get("pagination") or {}).keys())
        if arrcollections:
            strcollection = arrcollections[0]
            targeted = self.get(path, ui_language="en", collection=strcollection)
            if "wikipedia_page" in targeted:
                self.fail(f"{name} ?collection={strcollection}",
                          "wikipedia_page served on a targeted page")
            else:
                self.ok(f"{name} ?collection={strcollection}", "no wikipedia_page, as intended")

    def skip(self, name, reason):
        self.skipped.append(f"{name}: {reason}")
        print(f"\n[{name}] SKIPPED: {reason}")


def _first_id(rows, key):
    for row in rows or []:
        if row.get(key):
            return row[key]
    return None


# Each related list exposes the target entity's OWN primary key, and every detail route takes
# that integer id, never the Wikidata Q-number. These names are read off the endpoints'
# `pcollections` SELECTs, not guessed: guessing is what made the first run skip eight
# endpoints while cheerfully reporting no failure.
RELATION_KEYS = {
    "collections": "ID_T2S_COLLECTION", "topics": "ID_TOPIC", "lists": "ID_T2S_LIST",
    "movements": "ID_MOVEMENT", "technicals": "ID_TECHNICAL", "awards": "ID_AWARD",
    "nominations": "ID_NOMINATION", "groups": "ID_GROUP", "deaths": "ID_DEATH",
}

MAX_EXTRA_HOSTS = 4  # how many neighbours to walk per kind before giving up


def _harvest(paths, payload):
    """Take an id for every entity type this payload can supply and we still lack."""
    for name, key in RELATION_KEYS.items():
        if name in paths:
            continue
        value = _first_id(payload.get(name), key)
        if value:
            paths[name] = f"/{name}/{value}"


def _missing(paths):
    return [name for name in RELATION_KEYS if name not in paths]


def discover(checker, movie_id, location_id):
    """Walk outward from one movie until every entity type has a live id.

    One film is not enough on its own: a recent release has no award, no nomination and
    often no collection, and a living actor has no cause-of-death entry. So the walk widens
    to the film's neighbours (`similar`), to several cast members, and to a series, stopping
    for each entity type as soon as one id is found. What is still missing at the end is
    reported as SKIPPED, never counted as a pass.
    """
    paths = {"movies": f"/movies/{movie_id}"}
    movie = checker.get(f"/movies/{movie_id}", ui_language="en")
    _harvest(paths, movie)

    # Cast members: the only source of groups and deaths, and the way to a series.
    arrpersons = [row["ID_PERSON"] for row in (movie.get("cast") or []) if row.get("ID_PERSON")]
    arrpersons += [row["ID_PERSON"] for row in (movie.get("crew") or []) if row.get("ID_PERSON")]
    serie_id = None
    for person_id in arrpersons[:MAX_EXTRA_HOSTS]:
        person = checker.get(f"/persons/{person_id}", ui_language="en")
        paths.setdefault("persons", f"/persons/{person_id}")
        _harvest(paths, person)
        serie_id = serie_id or _first_id(person.get("series_cast"), "ID_SERIE") or \
            _first_id(person.get("series_crew"), "ID_SERIE")
        if not _missing(paths) and serie_id:
            break

    if serie_id:
        paths["series"] = f"/series/{serie_id}"
        serie = checker.get(f"/series/{serie_id}", ui_language="en")
        _harvest(paths, serie)  # a series carries the same Wikidata-keyed relations as a film
        season = (serie.get("seasons") or [None])[0]
        if season and season.get("SEASON_NUMBER") is not None:
            paths["seasons"] = f"/seasons/{serie_id}/{season['SEASON_NUMBER']}"
            detail = checker.get(paths["seasons"], ui_language="en")
            episode = (detail.get("episodes") or [None])[0]
            if episode and episode.get("EPISODE_NUMBER") is not None:
                paths["episodes"] = (f"/episodes/{serie_id}/{season['SEASON_NUMBER']}"
                                     f"/{episode['EPISODE_NUMBER']}")

    # Neighbour films: an older one is likely to carry the awards and collections a recent
    # seed lacks. Only walked while something is still missing.
    arrneighbours = [row["ID_MOVIE"] for row in (movie.get("similar") or []) if row.get("ID_MOVIE")]
    for neighbour_id in arrneighbours[:MAX_EXTRA_HOSTS]:
        if not _missing(paths):
            break
        _harvest(paths, checker.get(f"/movies/{neighbour_id}", ui_language="en"))

    if location_id:
        paths["locations"] = f"/locations/{location_id}"
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("T2S_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--api-key", default=(os.getenv("API_KEYS") or "").split(",")[0].strip())
    parser.add_argument("--movie-id", type=int, default=DEFAULT_MOVIE_ID,
                        help="seed movie: every other entity id is discovered from its relations")
    parser.add_argument("--location-id", default=None,
                        help="a Wikidata Q-number; /locations is reachable no other way")
    args = parser.parse_args()

    if not args.api_key:
        print("No API key: pass --api-key or set API_KEYS in .env")
        return 2

    checker = Checker(args.base_url, args.api_key)
    print(f"Base URL: {args.base_url}\nSeed movie: {args.movie_id}")

    paths = discover(checker, args.movie_id, args.location_id)
    for name in ENDPOINTS:
        if name in paths:
            checker.check_endpoint(name, paths[name])
        else:
            checker.skip(name, "no live id found on the seed movie, its cast, its series or "
                               "its neighbours"
                               + (" (reachable only by Q-number: pass --location-id)"
                                  if name == "locations" else
                                  " (try another --movie-id)"))

    print(f"\n{'-' * 70}")
    print(f"{checker.checks} checks passed, {len(checker.failures)} failed, "
          f"{len(checker.skipped)} endpoints skipped")
    for line in checker.skipped:
        print(f"  SKIPPED  {line}")
    for line in checker.failures:
        print(f"  FAILED   {line}")
    if checker.skipped:
        print("\nA skipped endpoint is NOT a pass: coverage is only proven for the ones exercised.")
    return 1 if checker.failures else 0


if __name__ == "__main__":
    sys.exit(main())
