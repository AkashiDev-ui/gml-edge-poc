"""
Module 1 - Moteur ZFE (Geo)
Détection d'entrée en Zone à Faibles Émissions 100 % hors-ligne.

Algorithme :
  1. Pré-filtre Bounding Box (4 comparaisons, O(1)) : élimine instantanément
     tous les points manifestement hors zone.
  2. Ray Casting (Point in Polygon, règle pair/impair, O(n) avec n = sommets) :
     uniquement pour les points situés dans la Bounding Box.
  3. Machine à états OUT -> IN : l'alerte [ALERT ZFE] n'est émise qu'au
     franchissement, pas à chaque point (pas de spam pour le chauffeur).

Complexité par point GPS : O(1) dans le cas courant, O(n) au pire.
Aucune boucle imbriquée sur les données -> pas de O(N^2) (cf. Annexe 2, Zebra ET40).
"""
import json
import logging
import math

log = logging.getLogger("GEO")


class GeoDataError(Exception):
    """Erreur sur les données géographiques (fichier absent, format invalide...)."""


def _valid_coord(lat, lon):
    return (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            and not isinstance(lat, bool) and not isinstance(lon, bool)
            and math.isfinite(lat) and math.isfinite(lon)
            and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise GeoDataError(f"Fichier introuvable : {path}")
    except json.JSONDecodeError as e:
        raise GeoDataError(f"JSON invalide dans {path} : {e}")


class Zone:
    """Polygone ZFE pré-calculé (bounding box calculée UNE seule fois au chargement)."""

    def __init__(self, vertices, name="ZFE"):
        pts = [(v["lat"], v["lon"]) for v in vertices
               if isinstance(v, dict) and _valid_coord(v.get("lat"), v.get("lon"))]
        # Le fichier ferme la boucle (dernier = premier) : on retire le doublon,
        # l'algorithme ferme lui-même le polygone via l'indice j = i - 1.
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 3:
            raise GeoDataError("Un polygone doit contenir au moins 3 sommets valides.")
        self.name = name
        self.vertices = pts
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        self.bbox = (min(lats), max(lats), min(lons), max(lons))

    @classmethod
    def from_file(cls, path, name="ZFE Lyon"):
        data = load_json(path)
        if not isinstance(data, list):
            raise GeoDataError("Le polygone doit être une liste de points {lat, lon}.")
        return cls(data, name)

    def in_bbox(self, lat, lon):
        min_lat, max_lat, min_lon, max_lon = self.bbox
        return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon

    def ray_casting(self, lat, lon):
        """Rayon horizontal lancé vers l'Est : on compte les arêtes traversées.
        Nombre impair -> dedans, pair -> dehors."""
        inside = False
        pts = self.vertices
        j = len(pts) - 1
        for i in range(len(pts)):          # une seule boucle sur les sommets
            lat_i, lon_i = pts[i]
            lat_j, lon_j = pts[j]
            # l'arête [j,i] chevauche-t-elle la latitude du point ?
            if (lat_i > lat) != (lat_j > lat):
                # longitude de l'intersection entre l'arête et le rayon
                lon_cross = lon_j + (lat - lat_j) * (lon_i - lon_j) / (lat_i - lat_j)
                if lon < lon_cross:
                    inside = not inside
            j = i
        return inside

    def contains(self, lat, lon):
        """Retourne (dedans: bool, méthode: str)."""
        if not self.in_bbox(lat, lon):
            return False, "bbox"           # rejet rapide, aucun calcul trigonométrique
        return self.ray_casting(lat, lon), "ray_casting"


class ZfeMonitor:
    """Machine à états : émet une alerte uniquement au passage OUT -> IN."""

    def __init__(self, zone):
        self.zone = zone
        self.state = "OUT"
        self.alerts = []
        self.stats = {"points": 0, "rejected": 0, "bbox_rejects": 0, "ray_casts": 0}

    def process(self, point):
        self.stats["points"] += 1
        try:
            pid = point.get("id", "?")
            ts = point.get("timestamp", "?")
            lat, lon = point.get("lat"), point.get("lon")
            if not _valid_coord(lat, lon):
                self.stats["rejected"] += 1
                log.warning("[GPS INVALIDE] point %s @%s ignoré (lat=%r, lon=%r) - "
                            "on conserve le dernier état connu : %s", pid, ts, lat, lon, self.state)
                return None
        except AttributeError:
            self.stats["rejected"] += 1
            log.warning("[GPS INVALIDE] entrée non exploitable ignorée : %r", point)
            return None

        inside, method = self.zone.contains(lat, lon)
        self.stats["bbox_rejects" if method == "bbox" else "ray_casts"] += 1
        new_state = "IN" if inside else "OUT"
        expected = point.get("expected")
        exp_txt = f" | attendu énoncé : {expected}" if expected else ""
        log.info("Point %s @%s (%.4f, %.4f) -> %s [%s]%s",
                 pid, ts, lat, lon, new_state, method, exp_txt)

        event = None
        if new_state == "IN" and self.state == "OUT":
            event = {"type": "ZFE_ENTRY", "zone": self.zone.name, "id": pid,
                     "timestamp": ts, "lat": lat, "lon": lon}
            self.alerts.append(event)
            log.critical("[ALERT ZFE] Entrée dans la %s - point %s à %s (%.4f, %.4f)",
                         self.zone.name, pid, ts, lat, lon)
        elif new_state == "OUT" and self.state == "IN":
            log.info("[INFO ZFE] Sortie de la %s - point %s à %s", self.zone.name, pid, ts)
        self.state = new_state
        return event
