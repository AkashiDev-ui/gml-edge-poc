#!/usr/bin/env python3
"""GML Edge Engine - POC autonome (Python 3.8+, bibliothèque standard uniquement)."""
import argparse
import logging
import sys
import time
from pathlib import Path

from src.geo_engine import GeoDataError, ZfeMonitor, Zone, load_json
from src.safety_engine import SafetyDataError, analyse, write_score

BASE = Path(__file__).parent


def setup_logging():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s [%(name)s] %(levelname)-8s %(message)s",
                        datefmt="%H:%M:%S")


def run_geo(polygon, gps, realtime):
    log = logging.getLogger("GEO")
    try:
        zone = Zone.from_file(polygon)
        track = load_json(gps)
        if not isinstance(track, list):
            raise GeoDataError("La trace GPS doit être une liste de points.")
    except GeoDataError as e:
        log.error("Module ZFE non démarré : %s", e)
        return False
    log.info("Zone chargée : %d sommets, bbox lat[%.4f;%.4f] lon[%.4f;%.4f]",
             len(zone.vertices), *zone.bbox)
    monitor = ZfeMonitor(zone)
    for p in track:
        t0 = time.perf_counter()
        monitor.process(p)
        log.debug("calcul : %.3f ms", (time.perf_counter() - t0) * 1000)
        if realtime:
            time.sleep(1)
    log.info("Bilan ZFE : %s | alertes : %d", monitor.stats, len(monitor.alerts))
    return True


def run_safety(csv_path, out_path):
    log = logging.getLogger("SAFETY")
    try:
        report = analyse(csv_path)
        write_score(report, out_path)
    except (SafetyDataError, OSError) as e:
        log.error("Module Safety non exécuté : %s", e)
        return False
    s = report["summary"]
    log.info("Score du jour : %d/100 (%s) - %d freinage(s) violent(s) -> %s",
             s["safety_score"], s["rating"], s["harsh_braking_count"], out_path)
    return True


def main():
    ap = argparse.ArgumentParser(description="POC GreenMove Logistics - moteur Edge")
    ap.add_argument("--module", choices=["geo", "safety", "all"], default="all")
    ap.add_argument("--polygon", default=BASE / "data/lyon_polygon.json")
    ap.add_argument("--gps", default=BASE / "data/truck_gps.json")
    ap.add_argument("--csv", default=BASE / "data/accelerometer_data.csv")
    ap.add_argument("--out", default=BASE / "output/daily_score.json")
    ap.add_argument("--realtime", action="store_true", help="rejoue la trace GPS à 1 point/s")
    args = ap.parse_args()
    setup_logging()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    ok = True
    try:
        if args.module in ("geo", "all"):
            print("=" * 70 + "\n MODULE 1 - MOTEUR ZFE (GEO)\n" + "=" * 70)
            ok &= run_geo(args.polygon, args.gps, args.realtime)
        if args.module in ("safety", "all"):
            print("=" * 70 + "\n MODULE 2 - MOTEUR SAFETY (PHYSICS)\n" + "=" * 70)
            ok &= run_safety(args.csv, args.out)
    except KeyboardInterrupt:
        logging.getLogger("MAIN").warning("Arrêt demandé par l'utilisateur.")
    except Exception:  # filet de sécurité : la tablette ne doit jamais crasher
        logging.getLogger("MAIN").exception("Erreur inattendue, moteur maintenu en vie.")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
