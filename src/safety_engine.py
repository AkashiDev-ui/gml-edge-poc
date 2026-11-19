"""
Module 2 - Moteur Safety (Physics)
Détection du freinage violent (Harsh Braking) dans un flux accéléromètre bruité.

Pipeline (chaque échantillon est traité une seule fois -> O(N), mémoire O(fenêtre)) :
  1. Nettoyage   : lignes illisibles, NaN, valeurs physiquement impossibles rejetées.
  2. Filtrage    : moyenne glissante sur ~0,2 s (fenêtre calculée selon la fréquence
                   d'échantillonnage) pour gommer les vibrations (route, moteur).
                   À 100 Hz -> 20 échantillons. À 1 Hz (fichier de l'énoncé) -> 1 :
                   chaque ligne est déjà un agrégat, lisser davantage effacerait l'événement.
  3. Seuil       : acc_y < -2,5 m/s² (axe longitudinal, valeur négative = décélération).
  4. Regroupement: échantillons consécutifs sous le seuil = UN seul événement
                   (on garde le pic), pour ne pas compter 20 freinages à 100 Hz.
  5. Score       : 100 - pénalités, export daily_score.json.
"""
import csv
import json
import logging
import math
from collections import deque
from datetime import datetime, timezone

log = logging.getLogger("SAFETY")

HARSH_BRAKING_THRESHOLD = -2.5     # m/s² (Annexe 3)
MAX_PLAUSIBLE_ACC = 50.0           # m/s² (~5 g) : au-delà = capteur défaillant / choc
SMOOTHING_SECONDS = 0.2
PENALTY = {"MODERATE": 5, "SEVERE": 10}   # SEVERE si < -4,0 m/s²
SEVERE_THRESHOLD = -4.0


class SafetyDataError(Exception):
    pass


def _to_float(value):
    f = float(value)                # lève ValueError / TypeError si illisible
    if not math.isfinite(f):
        raise ValueError("valeur non finie")
    return f


def read_samples(path, stats, quiet=False):
    """Générateur : lit le CSV ligne par ligne (streaming, faible empreinte RAM)."""
    try:
        f = open(path, newline="", encoding="utf-8")
    except FileNotFoundError:
        raise SafetyDataError(f"Fichier introuvable : {path}")
    with f:
        reader = csv.DictReader(f)
        required = {"timestamp", "acc_x", "acc_y", "acc_z"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise SafetyDataError(f"En-tête invalide, colonnes attendues : {sorted(required)}")
        for line_no, row in enumerate(reader, start=2):
            stats["lines"] += 1
            try:
                ts = _to_float(row["timestamp"])
                x, y, z = (_to_float(row[k]) for k in ("acc_x", "acc_y", "acc_z"))
                if max(abs(x), abs(y), abs(z)) > MAX_PLAUSIBLE_ACC:
                    raise ValueError("valeur physiquement impossible")
            except (ValueError, TypeError, KeyError) as e:
                stats["rejected"] += 1
                if not quiet:
                    log.warning("[DONNÉE INVALIDE] ligne %d ignorée (%s) : %s", line_no, e, row)
                continue
            yield ts, x, y, z


def estimate_window(path, default_hz=1.0):
    """Estime la fréquence d'échantillonnage sur les premières lignes valides."""
    stats = {"lines": 0, "rejected": 0}
    ts = []
    try:
        for s in read_samples(path, stats, quiet=True):
            ts.append(s[0])
            if len(ts) >= 50:
                break
    except SafetyDataError:
        return 1, default_hz
    deltas = sorted(b - a for a, b in zip(ts, ts[1:]) if b > a)
    hz = 1.0 / deltas[len(deltas) // 2] if deltas else default_hz   # médiane : robuste aux trous
    return max(1, round(hz * SMOOTHING_SECONDS)), hz


def analyse(path, vehicle_id="GML-TRUCK-001", threshold=HARSH_BRAKING_THRESHOLD):
    window, hz = estimate_window(path)
    log.info("Fréquence estimée : %.1f Hz -> fenêtre de lissage : %d échantillon(s)", hz, window)

    stats = {"lines": 0, "rejected": 0}
    buf = deque(maxlen=window)       # mémoire bornée, quelle que soit la taille du fichier
    running_sum = 0.0
    events, current = [], None
    first_ts = last_ts = None

    for ts, x, y, z in read_samples(path, stats):
        first_ts = ts if first_ts is None else first_ts
        last_ts = ts
        if len(buf) == buf.maxlen:
            running_sum -= buf[0]
        buf.append(y)
        running_sum += y
        y_f = running_sum / len(buf)  # moyenne glissante O(1) par échantillon

        if y_f < threshold:
            if current is None:
                current = {"start": ts, "end": ts, "peak_acc_y": y_f}
            else:
                current["end"] = ts
                current["peak_acc_y"] = min(current["peak_acc_y"], y_f)
        elif current is not None:
            events.append(current)
            current = None
    if current is not None:
        events.append(current)

    detailed = []
    for ev in events:
        sev = "SEVERE" if ev["peak_acc_y"] < SEVERE_THRESHOLD else "MODERATE"
        detailed.append({
            "type": "HARSH_BRAKING",
            "severity": sev,
            "timestamp": int(ev["start"]) if float(ev["start"]).is_integer() else ev["start"],
            "datetime_utc": datetime.fromtimestamp(ev["start"], timezone.utc).isoformat(),
            "duration_s": round(ev["end"] - ev["start"] + 1 / hz, 2),
            "peak_acc_y_ms2": round(ev["peak_acc_y"], 2),
            "peak_g": round(abs(ev["peak_acc_y"]) / 9.81, 3),
            "penalty": PENALTY[sev],
        })
        log.critical("[ALERT SAFETY] Freinage violent (%s) à %s : %.2f m/s² (%.2f g)",
                     sev, ev["start"], ev["peak_acc_y"], abs(ev["peak_acc_y"]) / 9.81)

    valid = stats["lines"] - stats["rejected"]
    score = max(0, 100 - sum(e["penalty"] for e in detailed))
    return {
        "schema_version": "1.0",
        "vehicle_id": vehicle_id,
        "date": datetime.fromtimestamp(first_ts, timezone.utc).date().isoformat() if first_ts else None,
        "period": {"start_ts": first_ts, "end_ts": last_ts},
        "processing": {
            "algorithm": "moving_average + threshold + event_grouping",
            "sampling_hz": round(hz, 2),
            "smoothing_window": window,
            "threshold_ms2": threshold,
            "lines_read": stats["lines"],
            "lines_valid": valid,
            "lines_rejected": stats["rejected"],
            "data_quality_pct": round(100 * valid / stats["lines"], 1) if stats["lines"] else 0,
        },
        "events": detailed,
        "summary": {
            "harsh_braking_count": len(detailed),
            "safety_score": score,
            "rating": "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 50 else "D",
        },
    }


def write_score(report, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
