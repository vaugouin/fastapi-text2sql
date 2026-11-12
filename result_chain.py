"""The lineage walk behind the `chain` representation (phase 3 lot E, 2026-11-12).

A question about remakes and adaptations ("Trace the chain of remakes behind A Star Is Born
(2018)", "Which films descend from Seven Samurai?") needs the links between works, and the SQL
rows never carry them: on 1.1.20 the model reached the right works in five different column
layouts (REMAKE_DEPTH, SOURCE_LEVEL, ADAPTATION_STEP...), walked the wrong way once (The
Departed) and dropped the middle film once (Last Man Standing, Yojimbo missing). Decision 5 of
2026-11-12: the chain comes from a second, deterministic query run by the API, not from a prompt
rule. The SQL keeps finding the work the question names; this module walks the source-work graph
from it and returns `summary_facts.chain`. The rows of the first query are left as they are.

The graph. A movie or a series is "based on" rows of T_WC_T2S_SOURCE_WORK through
T_WC_T2S_MOVIE_SOURCE_WORK / T_WC_T2S_SERIE_SOURCE_WORK; a source work whose ID_MOVIE or ID_SERIE
is set IS that movie or series (a remake), any other source work is a node of its own (a novel, a
play, a comic). Several parents per work (A Star Is Born 2018 cites 1976, 1954 and 1937) and some
cycles (Dog Day Afternoon, The Dog and Terrorism and Kebab cite each other): a DAG with cycles,
walked breadth first, cycle-guarded, bounded in depth, in nodes and in time.

Three parts, so the walk is tested offline on a fake graph (checks/test-result-chain.py):
- plan(): the gate. Whether to walk, from which works, in which direction. Pure.
- walk(): the breadth-first walk over a `source` object with five methods (parents, children,
  movies, series, works). DbLineage is the database one; tests pass an in-memory one.
- caption-free facts: nodes, edges, layers by generation, the anchor, the direction, truncation.
  Each front writes its own sentence from them (README "Result representations: the contract").

Read-only: SELECT statements only, every id bound as a parameter, each statement capped with
SET STATEMENT max_statement_time, the whole walk under a wall-clock budget.
"""
import re
import time

import result_intent

# Bounds (decision of 2026-11-12: "depth 4, 30 nodes"). A generation beyond the fourth is rare in
# the data (47 film-to-film paths at two hops, 10 at three, the rest cycles), and thirty cards is
# already more than a phone shows without scrolling.
MAX_DEPTH = 4
MAX_NODES = 30
# The anchors: the works the question names (resolved entities), else the rows themselves.
MAX_ANCHORS = 3
MAX_ROW_ANCHORS = 10
# Time: each statement is capped server side, the whole walk on the wall clock. A walk that runs
# out of time returns what it has, flagged truncated ("time").
STATEMENT_SECONDS = 2
BUDGET_SECONDS = 3.0
# A chain is offered from two edges on: one edge is "X is based on Y", which a card says.
MIN_EDGES = 2

_WORK_TABLES = {"T_WC_T2S_MOVIE": "movie", "T_WC_T2S_SERIE": "serie", "T_WC_T2S_SOURCE_WORK": "source_work"}
_WORK_ENTITIES = ("movie", "serie", "movie_serie", "source_work")
# The id in a match's candidate_id: "332562_MOVIE_TITLE" (lexicon), "movieid_76157_it" or
# "t2ssourceworkid_6848_en" (ChromaDB): the first run of digits between underscores.
_ID_RE = re.compile(r"(?:^|_)(\d+)(?=_|$)")


# --- The gate -------------------------------------------------------------------------------
def _resolved_anchors(entity_match_scores):
    """The works the question names, from the entity resolution: [(type, id)], in order."""
    out = []
    for score in entity_match_scores or []:
        if not isinstance(score, dict) or score.get("rejected"):
            continue
        kind = _WORK_TABLES.get(str(score.get("table") or "").upper())
        cid = str(score.get("candidate_id") or "")
        m = _ID_RE.search(cid)
        if not kind or not m:
            continue
        key = (kind, int(m.group(1)))
        if key not in out:
            out.append(key)
    return out[:MAX_ANCHORS]


def _row_anchors(rows):
    """The works the rows hold: [(type, id)] in row order. A source-work row that is itself a
    movie or a series (its ID_MOVIE / ID_SERIE set) counts as that movie or series."""
    out = []
    for item in rows or []:
        data = item.get("data") if isinstance(item, dict) and isinstance(item.get("data"), dict) else item
        if not isinstance(data, dict):
            continue
        key = None
        if data.get("ID_SOURCE_WORK") is not None:
            if data.get("ID_MOVIE") is not None:
                key = ("movie", data.get("ID_MOVIE"))
            elif data.get("ID_SERIE") is not None:
                key = ("serie", data.get("ID_SERIE"))
            else:
                key = ("source_work", data.get("ID_SOURCE_WORK"))
        elif data.get("ID_CONTENT") is not None and str(data.get("CONTENT_TYPE") or "").lower() in ("movie", "serie"):
            key = (str(data.get("CONTENT_TYPE")).lower(), data.get("ID_CONTENT"))
        elif data.get("ID_MOVIE") is not None:
            key = ("movie", data.get("ID_MOVIE"))
        elif data.get("ID_SERIE") is not None:
            key = ("serie", data.get("ID_SERIE"))
        if key is None:
            continue
        try:
            key = (key[0], int(key[1]))
        except (TypeError, ValueError):
            continue
        if key not in out:
            out.append(key)
    return out[:MAX_ROW_ANCHORS]


def plan(question, intent, entity_match_scores, rows, result_entity=""):
    """Whether to walk, from where and which way; None when the question asks no lineage.

    Walk when the question uses lineage words (result_intent.rules_lineage) or the task is
    `relate`, and there is a work to start from:
    - the works the question names (resolved movie, series or source work), always first;
    - else, for strong lineage words only, the works the rows hold, when the rows are works; the
      chain is then kept only if it joins every row work into one lineage (`rows_must_join`), so
      "list the remakes of 80s horror films" (unrelated rows) draws no chain.
    Weak words ("based on", "adapte de") and `relate` need a named work. The rows must be works
    (movie, serie, movie_serie, source_work) in every case.

    Returns {"anchors": [(type, id)], "direction": "up" | "down" | "both", "strength": "strong"
    | "weak" | "relate", "rows_must_join": bool}.
    """
    if not rows:
        return None
    # The rows must be works: a chain beside persons ("Who both directed and acted in Pulp
    # Fiction?", a relate task) answers another question.
    if str(result_entity or "").lower() not in _WORK_ENTITIES:
        return None
    lineage = result_intent.rules_lineage(question or "")
    task = (intent or {}).get("task") if isinstance(intent, dict) else None
    if lineage:
        strength, direction = lineage["strength"], lineage["direction"]
    elif task == "relate":
        strength, direction = "relate", "both"
    else:
        return None
    anchors = _resolved_anchors(entity_match_scores)
    rows_must_join = False
    if not anchors and strength == "strong":
        anchors = _row_anchors(rows)
        rows_must_join = len(anchors) > 1
    if not anchors:
        return None
    return {"anchors": anchors, "direction": direction, "strength": strength, "rows_must_join": rows_must_join}


# --- The database side ----------------------------------------------------------------------
_SW_COLUMNS = ("sw.ID_SOURCE_WORK, sw.SOURCE_WORK_TYPE, sw.SOURCE_WORK_FORM, sw.ID_MOVIE, sw.ID_SERIE, "
               "sw.SOURCE_WORK_NAME, sw.SOURCE_WORK_NAME_FR, sw.SOURCE_WORK_YEAR, sw.POSTER_PATH, "
               "sw.WIKIPEDIA_IMAGE_PATH")
_JUNCTIONS = (("movie", "T_WC_T2S_MOVIE_SOURCE_WORK", "ID_MOVIE"), ("serie", "T_WC_T2S_SERIE_SOURCE_WORK", "ID_SERIE"))


def _marks(values):
    return ", ".join(["%s"] * len(values))


def parents_sql(movie_ids, serie_ids):
    """(sql, params): the sources of the given movies and series, one row per link."""
    parts, params = [], []
    for kind, junction, col in _JUNCTIONS:
        ids = movie_ids if kind == "movie" else serie_ids
        if not ids:
            continue
        parts.append(
            f"SELECT '{kind}' AS CHILD_TYPE, j.{col} AS CHILD_ID, j.DISPLAY_ORDER, {_SW_COLUMNS} "
            f"FROM {junction} j JOIN T_WC_T2S_SOURCE_WORK sw ON sw.ID_SOURCE_WORK = j.ID_SOURCE_WORK "
            f"WHERE j.{col} IN ({_marks(ids)}) AND COALESCE(j.DELETED, 0) = 0 AND COALESCE(sw.DELETED, 0) = 0")
        params.extend(ids)
    return " UNION ALL ".join(parts), params


def children_sql(movie_ids, serie_ids, work_ids):
    """(sql, params): the movies and series based on the given movies, series or source works."""
    conds, cparams = [], []
    for col, ids in (("sw.ID_MOVIE", movie_ids), ("sw.ID_SERIE", serie_ids), ("sw.ID_SOURCE_WORK", work_ids)):
        if ids:
            conds.append(f"{col} IN ({_marks(ids)})")
            cparams.extend(ids)
    if not conds:
        return "", []
    where = "(" + " OR ".join(conds) + ")"
    parts, params = [], []
    for kind, junction, col in _JUNCTIONS:
        parts.append(
            f"SELECT '{kind}' AS CHILD_TYPE, j.{col} AS CHILD_ID, j.DISPLAY_ORDER, {_SW_COLUMNS} "
            f"FROM T_WC_T2S_SOURCE_WORK sw JOIN {junction} j ON j.ID_SOURCE_WORK = sw.ID_SOURCE_WORK "
            f"WHERE {where} AND COALESCE(j.DELETED, 0) = 0 AND COALESCE(sw.DELETED, 0) = 0")
        params.extend(cparams)
    return " UNION ALL ".join(parts), params


def movies_sql(ids):
    return (f"SELECT ID_MOVIE, MOVIE_TITLE, MOVIE_TITLE_FR, RELEASE_YEAR, POSTER_PATH FROM T_WC_T2S_MOVIE "
            f"WHERE ID_MOVIE IN ({_marks(ids)})", list(ids))


def series_sql(ids):
    return (f"SELECT ID_SERIE, SERIE_TITLE, SERIE_TITLE_FR, FIRST_AIR_YEAR, POSTER_PATH FROM T_WC_T2S_SERIE "
            f"WHERE ID_SERIE IN ({_marks(ids)})", list(ids))


def works_sql(ids):
    return (f"SELECT {_SW_COLUMNS} FROM T_WC_T2S_SOURCE_WORK sw "
            f"WHERE sw.ID_SOURCE_WORK IN ({_marks(ids)}) AND COALESCE(sw.DELETED, 0) = 0", list(ids))


class DbLineage:
    """The graph read from MariaDB through a DictCursor. Read-only, parameterized, each statement
    capped server side; `statements` counts what ran, for the response's message."""

    def __init__(self, cursor, statement_seconds=STATEMENT_SECONDS):
        self.cursor = cursor
        self.statement_seconds = statement_seconds
        self.statements = 0

    def _fetch(self, sql, params):
        if not sql:
            return []
        if self.statement_seconds and self.statement_seconds > 0:
            sql = f"SET STATEMENT max_statement_time={self.statement_seconds:g} FOR {sql}"
        self.cursor.execute(sql, params)
        self.statements += 1
        return list(self.cursor.fetchall() or [])

    def parents(self, movie_ids, serie_ids):
        return self._fetch(*parents_sql(movie_ids, serie_ids))

    def children(self, movie_ids, serie_ids, work_ids):
        return self._fetch(*children_sql(movie_ids, serie_ids, work_ids))

    def movies(self, ids):
        return self._fetch(*movies_sql(ids)) if ids else []

    def series(self, ids):
        return self._fetch(*series_sql(ids)) if ids else []

    def works(self, ids):
        return self._fetch(*works_sql(ids)) if ids else []


# --- The walk -------------------------------------------------------------------------------
def _source_key(row):
    """The node a source-work row stands for: the movie or series it is, else itself."""
    if row.get("ID_MOVIE") is not None:
        return ("movie", int(row["ID_MOVIE"]))
    if row.get("ID_SERIE") is not None:
        return ("serie", int(row["ID_SERIE"]))
    return ("source_work", int(row["ID_SOURCE_WORK"]))


def _edge_kind(child_type, parent_type, source_type):
    """remake: a movie from a movie, a series from a series. adaptation: across forms (a film from
    a novel, a play, a comic, a game, a tale, a series from a film). based_on: a source of the
    `other` type (a character, a franchise)."""
    if parent_type in ("movie", "serie"):
        return "remake" if parent_type == child_type else "adaptation"
    if str(source_type or "").lower() in ("", "other"):
        return "based_on"
    return "adaptation"


def _int_or_none(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def walk(source, anchors, direction, language="en", max_depth=MAX_DEPTH, max_nodes=MAX_NODES,
         budget_seconds=BUDGET_SECONDS, clock=time.monotonic):
    """Walk the lineage around `anchors` and return the chain facts, or None.

    `direction`: "up" (the sources, then their sources), "down" (the works based on the anchor,
    then on those), "both" (up and down from the anchor; no siblings: the other remakes of a
    source are not the anchor's lineage). Breadth first, one generation per round, each node
    expanded once (a node seen again adds its edge but is not walked twice, which is the cycle
    guard), at most `max_depth` generations each way and `max_nodes` works. A probe one
    generation further tells a real depth cut from a lineage that simply ends, and adds the links
    it finds between works already in the chain (a cycle closing at the last generation).
    """
    start = clock()
    nodes, info = {}, {}   # key -> insertion order; key -> facts read from the database
    edges = {}              # (parent key, child key) -> {"kind", "source_type"}
    truncated = None

    def out_of_time():
        return budget_seconds is not None and clock() - start > budget_seconds

    def add_node(key):
        nonlocal truncated
        if key in nodes:
            return True
        if len(nodes) >= max_nodes:
            truncated = truncated or "nodes"
            return False
        nodes[key] = len(nodes)
        return True

    def note_source(row):
        key = _source_key(row)
        if key[0] == "source_work":
            info.setdefault(key, {
                "title": row.get("SOURCE_WORK_NAME"), "title_fr": row.get("SOURCE_WORK_NAME_FR"),
                "year": _int_or_none(row.get("SOURCE_WORK_YEAR")), "source_type": row.get("SOURCE_WORK_TYPE"),
                "source_form": row.get("SOURCE_WORK_FORM"), "poster_path": row.get("POSTER_PATH"),
                "wikipedia_image_path": row.get("WIKIPEDIA_IMAGE_PATH")})
        return key

    # Anchors: a named source work that is itself a movie or a series becomes that movie or series.
    anchor_keys = []
    named_works = [i for t, i in anchors if t == "source_work"]
    by_work = {}
    if named_works:
        for row in source.works(named_works):
            by_work[int(row["ID_SOURCE_WORK"])] = row
    for kind, ident in anchors:
        if kind == "source_work":
            row = by_work.get(int(ident))
            if row is None:
                continue
            key = note_source(row)
        else:
            key = (kind, int(ident))
        if key not in anchor_keys:
            anchor_keys.append(key)
    if not anchor_keys:
        return None
    for key in anchor_keys:
        add_node(key)

    def link(parent, child, row):
        if parent == child:
            return
        edges.setdefault((parent, child), {
            "kind": _edge_kind(child[0], parent[0], row.get("SOURCE_WORK_TYPE")),
            "source_type": row.get("SOURCE_WORK_TYPE")})

    def ids(frontier, kind):
        return sorted({i for t, i in frontier if t == kind})

    def up_round(frontier, record=True):
        """One generation up; returns the new parent keys (only those added to the chain)."""
        rows = source.parents(ids(frontier, "movie"), ids(frontier, "serie"))
        rows.sort(key=lambda r: (r.get("CHILD_TYPE"), r.get("CHILD_ID"), r.get("DISPLAY_ORDER") or 0,
                                 r.get("ID_SOURCE_WORK")))
        fresh, found = [], False
        for row in rows:
            child = (row["CHILD_TYPE"], int(row["CHILD_ID"]))
            parent = note_source(row)
            if parent == child:
                continue
            if not record:
                if parent in nodes:
                    link(parent, child, row)
                else:
                    found = True
                continue
            new = parent not in nodes
            if not add_node(parent):
                continue
            link(parent, child, row)
            if new:
                fresh.append(parent)
        return found if not record else fresh

    def down_round(frontier, record=True):
        rows = source.children(ids(frontier, "movie"), ids(frontier, "serie"), ids(frontier, "source_work"))
        rows.sort(key=lambda r: (r.get("ID_SOURCE_WORK"), r.get("CHILD_TYPE"), r.get("CHILD_ID")))
        fresh, found = [], False
        frontier_set = set(frontier)
        for row in rows:
            parent = note_source(row)
            if parent not in frontier_set:
                continue
            child = (row["CHILD_TYPE"], int(row["CHILD_ID"]))
            if parent == child:
                continue
            if not record:
                if child in nodes:
                    link(parent, child, row)
                else:
                    found = True
                continue
            new = child not in nodes
            if not add_node(child):
                continue
            link(parent, child, row)
            if new:
                fresh.append(child)
        return found if not record else fresh

    depth_up = depth_down = 0
    for step, wanted in ((up_round, direction in ("up", "both")), (down_round, direction in ("down", "both"))):
        if not wanted:
            continue
        frontier, depth, reached = list(anchor_keys), 0, 0
        while frontier:
            if out_of_time():
                truncated = truncated or "time"
                break
            if depth >= max_depth:
                # One probe further: does the lineage go on past the cut?
                if step(frontier, record=False):
                    truncated = truncated or "depth"
                break
            fresh = step(frontier)
            depth += 1
            if fresh:
                reached = depth
            frontier = [k for k in fresh if not (step is up_round and k[0] == "source_work")]
        if step is up_round:
            depth_up = reached
        else:
            depth_down = reached

    # Facts of the movies and series met (title in the asked language, year, poster).
    movie_ids = sorted(i for t, i in nodes if t == "movie")
    serie_ids = sorted(i for t, i in nodes if t == "serie")
    if movie_ids:
        for row in source.movies(movie_ids):
            info[("movie", int(row["ID_MOVIE"]))] = {
                "title": row.get("MOVIE_TITLE"), "title_fr": row.get("MOVIE_TITLE_FR"),
                "year": _int_or_none(row.get("RELEASE_YEAR")), "poster_path": row.get("POSTER_PATH")}
    if serie_ids:
        for row in source.series(serie_ids):
            info[("serie", int(row["ID_SERIE"]))] = {
                "title": row.get("SERIE_TITLE"), "title_fr": row.get("SERIE_TITLE_FR"),
                "year": _int_or_none(row.get("FIRST_AIR_YEAR")), "poster_path": row.get("POSTER_PATH")}
    return _facts(nodes, info, edges, anchor_keys, direction, language, truncated, max_depth, max_nodes,
                  depth_up, depth_down)


def _cycle_edges(keys, edges):
    """The edges that close a cycle, found by a depth-first search from the oldest works in a
    fixed order; removing them leaves a DAG."""
    out = {}
    for pair in edges:
        out.setdefault(pair[0], []).append(pair[1])
    state, back = {}, set()
    for root in keys:
        if root in state:
            continue
        stack = [(root, iter(sorted(out.get(root, []), key=keys.index)))]
        state[root] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
                continue
            if state.get(nxt) == 1:
                back.add((node, nxt))
            elif nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(sorted(out.get(nxt, []), key=keys.index))))
    return back


def _facts(nodes, info, edges, anchor_keys, direction, language, truncated, max_depth, max_nodes,
           depth_up, depth_down):
    keys = list(nodes)
    if len(keys) < 2 or not edges:
        return None

    def year_of(k):
        y = (info.get(k) or {}).get("year")
        return y if isinstance(y, int) else 10 ** 6

    # Depth-first search from the oldest works, so the edge dropped from a cycle is the one that
    # points back in time.
    keys.sort(key=lambda k: (year_of(k), nodes[k]))
    back = _cycle_edges(keys, edges)
    # Generations: the longest path from a work with no source in the chain (cycle edges aside).
    incoming = {k: [] for k in keys}
    for (p, c) in edges:
        if (p, c) not in back:
            incoming[c].append(p)
    layer = {}

    def layer_of(k, seen=()):
        if k in layer:
            return layer[k]
        ps = [p for p in incoming[k] if p not in seen]
        value = 0 if not ps else 1 + max(layer_of(p, seen + (k,)) for p in ps)
        layer[k] = value
        return value

    for k in keys:
        layer_of(k)

    def title(k):
        i = info.get(k) or {}
        if language == "fr" and i.get("title_fr"):
            return i.get("title_fr")
        return i.get("title") or i.get("title_fr")

    order = sorted(keys, key=lambda k: (layer[k], year_of(k), str(title(k) or "").lower(), k))
    index = {k: n for n, k in enumerate(order)}
    out_nodes = []
    for k in order:
        i = info.get(k) or {}
        node = {
            "type": k[0], "id": k[1], "title": title(k), "year": i.get("year"),
            "layer": layer[k], "anchor": k in anchor_keys,
            "poster_path": i.get("poster_path") or None,
            "image": bool(i.get("poster_path") or i.get("wikipedia_image_path")),
        }
        if k[0] == "source_work":
            node["source_type"] = i.get("source_type")
            node["source_form"] = i.get("source_form")
            node["wikipedia_image_path"] = i.get("wikipedia_image_path") or None
        out_nodes.append(node)
    out_edges = sorted(
        ({"from": index[p], "to": index[c], "kind": e["kind"], "source_type": e["source_type"],
          "cycle": (p, c) in back} for (p, c), e in edges.items()),
        key=lambda e: (e["to"], e["from"]))
    layers = []
    for k in order:
        while len(layers) <= layer[k]:
            layers.append([])
        layers[layer[k]].append(index[k])
    dated = [n for n, k in enumerate(order) if isinstance((info.get(k) or {}).get("year"), int)]
    earliest = min(dated, key=lambda n: (out_nodes[n]["year"], n)) if dated else None
    latest = max(dated, key=lambda n: (out_nodes[n]["year"], -n)) if dated else None
    kinds = sorted({e["kind"] for e in out_edges})
    types = sorted({n["type"] for n in out_nodes})
    return {
        "anchor": [index[k] for k in anchor_keys if k in index],
        "direction": direction,
        "nodes": out_nodes,
        "edges": out_edges,
        "layers": layers,
        "count": len(out_nodes),
        "generations": len(layers),
        "depth": {"up": depth_up, "down": depth_down},
        "kinds": kinds,
        "types": types,
        "earliest": earliest,
        "latest": latest,
        "cycles": len(back),
        "truncated": bool(truncated),
        "truncated_by": truncated,
        "max_depth": max_depth,
        "max_nodes": max_nodes,
    }


def joins_rows(chain, row_anchors):
    """True when every row work sits in one connected lineage of the chain (rows_must_join)."""
    if not chain:
        return False
    keys = [(n["type"], n["id"]) for n in chain["nodes"]]
    wanted = [k for k in row_anchors if k in keys]
    if len(wanted) < len(row_anchors):
        return False
    parent = list(range(len(keys)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in chain["edges"]:
        parent[find(e["from"])] = find(e["to"])
    roots = {find(keys.index(k)) for k in wanted}
    return len(roots) == 1


def is_default(plan_, chain):
    """chain is the default over the shape's own form when the question asks for a lineage
    (strong words or a relate task), or when the walk found at least two generations of descent
    (A Fistful of Dollars, Yojimbo, Red Harvest under "What is it based on, and what is that based
    on?"). A fan of sources one generation deep under weak words ("Films based on Dracula") is
    only offered."""
    if not plan_ or not chain:
        return False
    return plan_.get("strength") in ("strong", "relate") or chain.get("generations", 0) >= 3


def build(source, plan_, language="en", **bounds):
    """walk() for a plan, with the row-join check; None when there is no chain to offer."""
    if not plan_:
        return None
    chain = walk(source, plan_["anchors"], plan_["direction"], language=language, **bounds)
    if not chain or len(chain["edges"]) < MIN_EDGES:
        return None
    if plan_.get("rows_must_join") and not joins_rows(chain, plan_["anchors"]):
        return None
    return chain
