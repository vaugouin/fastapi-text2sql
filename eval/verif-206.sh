#!/bin/sh
# Verifie la mesure de correspondance d'entites (FASTAPI-TEXT2SQL-206) et, au passage,
# l'anomalie de reprise complexe (FASTAPI-TEXT2SQL-208).
#
# TROIS QUESTIONS, TROIS REGIONS DE LA DISTRIBUTION
#   Bogart    le temoin : un nom correctement ecrit, resolu en rapidfuzz, ratio proche de 100.
#             Aucun score ici alors que l'entite resout = le processus sert l'ancien code.
#   Wagonlit  le faux positif : une collection inexistante qui resout quand meme, mesuree le
#             2026-08-24 vers "Life Collection". Son score est le premier point de la
#             distribution qu'un seuil devra couper.
#   Zorglub   le vrai rejet, seul type dote d'un seuil (min_fuzz_ratio 72), et accessoirement le
#             cas de -208 : repli brut a 1, zero ligne, et pourtant aucune reprise ce matin.
#
# NI CURL NI BASH, C'EST VOULU
# L'image du conteneur est python:3.12-slim-bookworm, qui n'embarque pas curl. Tout passe donc
# par python3 et sa bibliotheque standard, et le shebang est /bin/sh sans bashisme, pour que le
# script tourne aussi bien dans le conteneur que sur le poste.
#
# CLE ET HOTE
# La cle est prise dans le premier .env qui en porte une, cherche a trois endroits dans cet
# ordre : la racine du depot (la disposition <depot>/eval/ habituelle), puis a cote du script
# lui-meme, ou il atterrit quand eval/ est recopie a plat comme ~/docker/text2sql-eval sur le
# VPS, puis le repertoire courant. Dans un fichier donne, API_KEYS l'emporte sur API_KEY, qui
# l'emporte sur TEXT2SQL_API_KEY, le nom que l'evaluateur donne a la meme valeur X-API-Key.
# Une variable d'environnement KEY deja posee l'emporte sur tout, ce qui permet de tester une
# autre cle sans toucher au fichier. L'hote par defaut est www.vaugouin.com:8186, l'instance Blue ; depuis
# un conteneur sur le VPS, BASE_URL=http://172.17.0.1:8186 evite l'aller-retour par le DNS
# public, comme le fait deja le reverseproxy.
#
# Usage :
#   sh eval/verif-206.sh
#   BASE_URL=http://172.17.0.1:8186 sh eval/verif-206.sh
#   KEY=<autre cle> sh eval/verif-206.sh
#   docker exec -w /app <conteneur> sh eval/verif-206.sh

set -e

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(dirname -- "$SCRIPT_DIR")

BASE_URL="${BASE_URL:-http://www.vaugouin.com:8186}"
export BASE_URL REPO_DIR SCRIPT_DIR
export KEY="${KEY:-}"

# python3 dans le conteneur, python ailleurs. On verifie que l'interpreteur REPOND, et pas
# seulement qu'il figure dans le PATH : Windows y place un raccourci `python` qui renvoie vers le
# Microsoft Store et echoue, ce qu'un simple `command -v` ne distingue pas.
PY_BIN=""
for candidate in "${PYTHON:-}" python3 python; do
    [ -n "$candidate" ] || continue
    if "$candidate" -c "import sys" >/dev/null 2>&1; then
        PY_BIN="$candidate"
        break
    fi
done
if [ -z "$PY_BIN" ]; then
    echo "Aucun interpreteur Python utilisable. Poser PYTHON=<chemin> au besoin." >&2
    exit 1
fi

"$PY_BIN" - <<'PYTHON'
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE_URL = os.environ["BASE_URL"].rstrip("/")
REPO_DIR = os.environ["REPO_DIR"]
SCRIPT_DIR = os.environ.get("SCRIPT_DIR") or REPO_DIR

NOMS_DE_CLE = ("API_KEYS", "API_KEY", "TEXT2SQL_API_KEY")


def dossiers_env():
    """Les dossiers susceptibles de porter le .env, du plus autoritaire au moins.

    REPO_DIR est la racine du depot quand ce script est dans son dossier eval/, la seule
    disposition ou le fichier est a coup sur celui de l'API. SCRIPT_DIR est ce meme dossier
    quand eval/ a ete recopie a plat, ce qu'est ~/docker/text2sql-eval sur le VPS. Le
    repertoire courant vient en dernier. Les doublons sont retires pour qu'un lancement normal
    ne rapporte qu'un seul chemin.
    """
    ordre = []
    for chemin in (REPO_DIR, SCRIPT_DIR, os.getcwd()):
        if chemin and chemin not in ordre:
            ordre.append(chemin)
    return ordre


def read_key():
    """KEY de l'environnement, sinon le premier nom de cle trouve dans le premier .env qui en a.

    Le .env est parse a la main plutot qu'avec python-dotenv : ce script doit tourner dans
    n'importe quel conteneur, y compris un qui n'aurait pas la dependance. TEXT2SQL_API_KEY est
    accepte parce que le .env de l'evaluateur nomme ainsi la meme valeur, et que son dossier est
    un endroit d'ou ce script tourne legitimement.
    """
    key = (os.environ.get("KEY") or "").strip()
    if key:
        return key, "variable d'environnement KEY"
    essayes = []
    for dossier in dossiers_env():
        env_path = os.path.join(dossier, ".env")
        essayes.append(env_path)
        if not os.path.isfile(env_path):
            continue
        found = {}
        with open(env_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                name = name.strip()
                if name in NOMS_DE_CLE:
                    found[name] = value.strip().strip('"').strip("'")
        for name in NOMS_DE_CLE:
            if found.get(name):
                # API_KEYS peut en contenir plusieurs, separees par une virgule ; la premiere suffit.
                return found[name].split(",")[0].strip(), f"{name} de {env_path}"
    return "", "aucun .env portant " + ", ".join(NOMS_DE_CLE) + " dans : " + ", ".join(essayes)


def call(question, key):
    payload = json.dumps({
        "question": question,
        "complex_question_processing": True,
        "retrieve_from_cache": False,
        "store_to_cache": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + "/search/text2sql",
        data=payload,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=180) as response:
        body = response.read().decode("utf-8", "replace")
    return json.loads(body), time.perf_counter() - started


def show(label, question, key):
    print("=" * 78)
    print("  " + label)
    print("  " + question)
    print("=" * 78)
    try:
        data, elapsed = call(question, key)
    except urllib.error.HTTPError as http_error:
        detail = http_error.read().decode("utf-8", "replace")[:200]
        print("  HTTP %s : %s" % (http_error.code, detail))
        return
    except Exception as call_error:
        print("  appel impossible : %s" % call_error)
        return

    scores = data.get("entity_match_scores") or []
    print("  lignes rendues        %s" % len(data.get("result") or []))
    print("  pire distance         %s" % data.get("entity_match_worst_distance"))
    print("  pire ratio            %s" % data.get("entity_match_worst_fuzz_ratio"))
    if scores:
        for score in scores:
            print("    %-18s %-11s %-24s -> %-24s d=%-8s r=%-5s %s" % (
                score.get("placeholder"), score.get("search_mode"),
                str(score.get("sought"))[:24], str(score.get("candidate"))[:24],
                score.get("distance"), score.get("fuzz_ratio"),
                "REJETE" if score.get("rejected") else ""))
    elif "entity_match_scores" not in data:
        print("    CHAMP ABSENT : l'instance sert du code anterieur a -206")
    else:
        print("    (liste vide : aucune entite passee par un resolveur score)")

    print("  --- portes de la reprise complexe ---")
    print("  (a) ambigu            %s" % data.get("ambiguous_question_for_text2sql"))
    print("  (b) repli brut        %s" % data.get("entity_raw_fallback_count"))
    print("  (c) rien extrait      %s" % data.get("no_entity_extracted"))
    print("  complexe declenche    %s" % data.get("complex_model_used"))
    print("  cout simplification   %s" % data.get("complex_question_processing_time"))
    print("  total annonce         %.2f s" % (data.get("total_processing_time") or 0.0))
    print("  mesure au client      %.2f s" % elapsed)
    print()


def main():
    key, origin = read_key()
    print("Cible : %s" % BASE_URL)
    print("Cle   : %s" % (("%s... (%s)" % (key[:6], origin)) if key else "MANQUANTE (%s)" % origin))
    print()
    if not key:
        print("Sans cle, l'API repondra 401. Renseigner API_KEYS ou API_KEY dans le .env,")
        print("ou passer KEY=<valeur> en variable d'environnement.")
        return 1

    try:
        request = urllib.request.Request(BASE_URL + "/", headers={"X-API-Key": key})
        with urllib.request.urlopen(request, timeout=30) as response:
            root = json.loads(response.read().decode("utf-8", "replace"))
        print("Instance : version %s, bk-trees prets : %s"
              % (root.get("api_version"), root.get("bktrees_ready")))
        if root.get("bktrees_ready") is False:
            print("ATTENTION : les BK-trees se construisent encore. Les resolveurs rapidfuzz")
            print("(Person_name, premiere strategie de Collection_name) se comportent autrement")
            print("pendant ce temps, et les scores releves maintenant ne veulent rien dire.")
        print()
    except Exception as probe_error:
        print("Sonde de racine indisponible (%s), on continue.\n" % probe_error)

    for label, question in QUESTIONS:
        show(label, question, key)
    return 0


sys.exit(main())
PYTHON
