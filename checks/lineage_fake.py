"""An in-memory lineage source for result_chain.walk (phase 3 lot E), used by the offline checks.

Same five methods as result_chain.DbLineage, over rows in the walk's own column layout: `links`
(CHILD_TYPE, CHILD_ID, DISPLAY_ORDER and the source-work columns), `movies`, `series`, `works`.
checks/data/p3e-lineage-graph-20261112.json holds such rows as the live base returned them
(text2sql-eval/check-phase3-lot-e-lineage-20261112.txt, voie 1, 2026-11-12).
"""
import json


class FakeLineage:
    def __init__(self, links, movies=(), series=(), works=()):
        self.links = [dict(x) for x in links]
        self.movie_rows = {m["ID_MOVIE"]: dict(m) for m in movies}
        self.serie_rows = {s["ID_SERIE"]: dict(s) for s in series}
        self.work_rows = {w["ID_SOURCE_WORK"]: dict(w) for w in works}
        for link in self.links:
            self.work_rows.setdefault(link["ID_SOURCE_WORK"], {k: link.get(k) for k in (
                "ID_SOURCE_WORK", "SOURCE_WORK_TYPE", "SOURCE_WORK_FORM", "ID_MOVIE", "ID_SERIE", "SOURCE_WORK_NAME",
                "SOURCE_WORK_NAME_FR", "SOURCE_WORK_YEAR", "POSTER_PATH", "WIKIPEDIA_IMAGE_PATH")})
        self.statements = 0

    @classmethod
    def from_json(cls, path):
        d = json.load(open(path, encoding="utf-8"))
        return cls(d["links"], d.get("movies") or (), d.get("series") or (), d.get("works") or ())

    def parents(self, movie_ids, serie_ids):
        self.statements += 1
        m, s = set(movie_ids), set(serie_ids)
        return [dict(x) for x in self.links if (x["CHILD_TYPE"] == "movie" and x["CHILD_ID"] in m)
                or (x["CHILD_TYPE"] == "serie" and x["CHILD_ID"] in s)]

    def children(self, movie_ids, serie_ids, work_ids):
        self.statements += 1
        m, s, w = set(movie_ids), set(serie_ids), set(work_ids)
        return [dict(x) for x in self.links if x.get("ID_MOVIE") in m or x.get("ID_SERIE") in s
                or x["ID_SOURCE_WORK"] in w]

    def movies(self, ids):
        self.statements += 1
        return [dict(self.movie_rows[i]) for i in ids if i in self.movie_rows]

    def series(self, ids):
        self.statements += 1
        return [dict(self.serie_rows[i]) for i in ids if i in self.serie_rows]

    def works(self, ids):
        self.statements += 1
        return [dict(self.work_rows[i]) for i in ids if i in self.work_rows]
