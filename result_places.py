"""The coordinates behind the map of places (phase 3 lot D, 2026-11-14).

"Show on a map where Lawrence of Arabia was filmed", "Map the filming locations of Christopher
Nolan's films": the SQL already returns the right place rows (T_WC_T2S_LOCATION, ID_LOCATION
first), but never their position. Decision 3 of 2026-11-12: the coordinates come from a
preprocessing step, LATITUDE and LONGITUDE on T_WC_T2S_LOCATION (tmdb-movie-preprocess, process
72 step 4d, from Wikidata P625; migration-075 run on 2026-11-14), and the API stays out of the
Wikidata schema. The SQL model is not asked to project them: this module reads them by
ID_LOCATION after the query, as result_chain reads the lineage, so a model that forgets a column
or aliases it still gets a map. The rows of the first query are left as they are.

Two drawing rules from the data (study, section 1):
- a place of type country or region is not a point (Japan sits at 35.0, 136.0): it is marked as
  an area, drawn apart from the pins, never counted as a pin for the default;
- a fictional place, or one Wikidata gives no coordinate, is listed under the map, never pinned.

Three parts, so the step is tested offline (checks/test-result-places.py):
- plan(): the gate. The place ids of the rows, in row order, or None. Pure.
- DbPlaces: the database read. One SELECT, parameterized, capped server side.
- build(): summary_facts.places from the rows and the coordinates. Pure.
result_shape.apply_places() then offers or picks `map`.

Read-only: one SELECT, every id bound as a parameter, capped with SET STATEMENT
max_statement_time. A base without the two columns (migration not run) answers error 1054, which
DbPlaces turns into "no coordinates": the result stays as classify_result made it.
"""

# The place types the preprocessing writes (tmdb-movie-preprocess, process 72). An area is shaded
# or listed, never pinned; a fictional place has no coordinate (5 of 579 have one, and those are
# real places that a fiction borrowed: they are listed with the fiction all the same).
AREA_TYPES = ("country", "region")
FICTION_TYPES = ("fiction",)
# One page of rows at most (rows_per_page tops out at 50 in both fronts); a SQL of 500 rows still
# gets one statement.
MAX_IDS = 200
STATEMENT_SECONDS = 2
# The default (decision 4 of 2026-11-12): the map is the default over the card grid of place
# photos from two pins on. With one pin, or areas only, it is offered.
MIN_DEFAULT_PINS = 2

_MARIADB_BAD_FIELD = 1054
_ID_COLUMN = "ID_LOCATION"
_NAME_COLUMNS = ("LOCATION_NAME", "LOCATION_NAME_FR")


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_data(row):
    """A result row as the dict of its columns: the API's {"data": {...}} or a bare dict."""
    if isinstance(row, dict) and isinstance(row.get("data"), dict):
        return row["data"]
    return row if isinstance(row, dict) else {}


def plan(rows, result_entity=""):
    """The distinct ID_LOCATION values of the rows, in row order, or None.

    Only rows that are places: the column ID_LOCATION is projected, and the rows are not films,
    series or persons that merely name a place beside them ("films shot in Rome, with the place"
    has an ID_MOVIE: the map would pin the places and hide the films the question asked for).
    """
    if not rows:
        return None
    first = _row_data(rows[0])
    if _ID_COLUMN not in first:
        return None
    if result_entity not in ("", None, "location") and any(
            c in first for c in ("ID_MOVIE", "ID_SERIE", "ID_PERSON")):
        return None
    ids, seen = [], set()
    for row in rows:
        pid = _int_or_none(_row_data(row).get(_ID_COLUMN))
        if pid is None or pid in seen:
            continue
        seen.add(pid)
        ids.append(pid)
        if len(ids) >= MAX_IDS:
            break
    return ids or None


def places_sql(ids):
    """(sql, params): name, type and coordinates of the given places."""
    marks = ", ".join(["%s"] * len(ids))
    return (f"SELECT ID_LOCATION, LOCATION_NAME, LOCATION_NAME_FR, LOCATION_TYPE, LATITUDE, LONGITUDE "
            f"FROM T_WC_T2S_LOCATION WHERE ID_LOCATION IN ({marks})", list(ids))


class DbPlaces:
    """The coordinates read from MariaDB through a DictCursor. `statements` counts what ran."""

    def __init__(self, cursor, statement_seconds=STATEMENT_SECONDS):
        self.cursor = cursor
        self.statement_seconds = statement_seconds
        self.statements = 0
        self.missing_columns = False

    def fetch(self, ids):
        """{ID_LOCATION: row}; {} when the columns do not exist yet (migration-075 not run)."""
        if not ids:
            return {}
        sql, params = places_sql(ids)
        if self.statement_seconds and self.statement_seconds > 0:
            sql = f"SET STATEMENT max_statement_time={self.statement_seconds:g} FOR {sql}"
        try:
            self.cursor.execute(sql, params)
        except Exception as exc:  # pymysql.err.OperationalError / InternalError
            if exc.args and exc.args[0] == _MARIADB_BAD_FIELD:
                self.missing_columns = True
                return {}
            raise
        self.statements += 1
        return {int(r["ID_LOCATION"]): r for r in (self.cursor.fetchall() or []) if r.get("ID_LOCATION") is not None}


def _coordinate(value, bound):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 6) if -bound <= number <= bound else None


def _label(row_data, info, language):
    """The place's name in the UI language: the lookup's, else the row's."""
    order = ("LOCATION_NAME_FR", "LOCATION_NAME") if language == "fr" else _NAME_COLUMNS
    for source in (info or {}, row_data):
        for col in order:
            value = source.get(col)
            if value not in (None, ""):
                return str(value)
    return None


def build(rows, coordinates, language="en"):
    """summary_facts.places, or None when no place of the rows has a position.

    count       distinct places in the rows (ID_LOCATION)
    located     places with a position (pins and areas)
    pins        [{index, id, label, type, lat, lon}] a point place with a position, in row order;
                index is the first row of that place (a place comes back once per ancestor in a
                grouped answer: Giverny three times)
    areas       the same for a country or a region: a position, but not a point
    unlocated   [{index, id, label, type, reason}] reason "fiction" or "no-coordinates"
    bounds      {lat_min, lat_max, lon_min, lon_max} over pins and areas: the fronts frame the
                map on it
    """
    if not rows or not coordinates:
        return None
    pins, areas, unlocated, seen = [], [], [], set()
    for index, row in enumerate(rows):
        data = _row_data(row)
        pid = _int_or_none(data.get(_ID_COLUMN))
        if pid is None or pid in seen:
            continue
        seen.add(pid)
        info = coordinates.get(pid) or {}
        ptype = str(info.get("LOCATION_TYPE") or data.get("LOCATION_TYPE") or "").strip().lower() or None
        entry = {"index": index, "id": pid, "label": _label(data, info, language), "type": ptype}
        lat, lon = _coordinate(info.get("LATITUDE"), 90), _coordinate(info.get("LONGITUDE"), 180)
        if ptype in FICTION_TYPES:
            unlocated.append({**entry, "reason": "fiction"})
        elif lat is None or lon is None:
            unlocated.append({**entry, "reason": "no-coordinates"})
        else:
            (areas if ptype in AREA_TYPES else pins).append({**entry, "lat": lat, "lon": lon})
    located = pins + areas
    if not located:
        return None
    return {
        "count": len(seen),
        "located": len(located),
        "pins": pins,
        "areas": areas,
        "unlocated": unlocated,
        "bounds": {"lat_min": min(p["lat"] for p in located), "lat_max": max(p["lat"] for p in located),
                   "lon_min": min(p["lon"] for p in located), "lon_max": max(p["lon"] for p in located)},
    }


def is_default(places, requested_view=""):
    """For result_shape.apply_places: "asked" when the question asks for a map (the map wins over
    any form), True from two pins on (the map wins over the card grid of place photos), else
    False (offered only)."""
    if not places:
        return False
    if requested_view == "map":
        return "asked"
    return len(places.get("pins") or []) >= MIN_DEFAULT_PINS
