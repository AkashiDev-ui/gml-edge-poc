# GML Edge Engine – POC Tablette Télématique (GreenMove Logistics)

Moteur autonome embarqué (Edge Computing), 100 % hors-ligne :

- **Module 1 – ZFE (Geo)** : détection d'entrée en Zone à Faibles Émissions par Bounding Box + Ray Casting.
- **Module 2 – Safety (Physics)** : détection des freinages violents dans un flux accéléromètre bruité et production d'un `daily_score.json`.

## Prérequis

- Python **3.8 ou plus**.
- **Aucune dépendance externe** : bibliothèque standard uniquement. Ce choix est volontaire, car le code doit tourner sur une tablette Zebra ET40 avec 150 Mo de RAM.

## Installation

```bash
git clone <URL_DU_DEPOT>
cd gml-edge-poc
```

## Lancer la démonstration

```bash
python3 main.py                      # les deux modules
python3 main.py --module geo         # ZFE seul
python3 main.py --module safety      # Safety seul
python3 main.py --module geo --realtime   # rejoue la trace GPS à 1 point/s (démo vidéo)
```

Le résultat est écrit dans `output/daily_score.json`.

## Prouver la robustesse (gestion des exceptions)

```bash
python3 main.py --gps data/truck_gps_corrupted.json --csv data/accelerometer_corrupted.csv
python3 main.py --csv fichier_inexistant.csv     # erreur propre, pas de crash
```

Les lignes invalides sont journalisées puis ignorées, et le traitement continue. Les cas couverts sont :

- texte au lieu d'un nombre ;
- colonnes manquantes ;
- `NaN` ;
- valeurs physiquement impossibles ;
- latitude hors bornes ;
- fichier absent.

## Tests unitaires

```bash
python3 -m unittest tests/test_engines.py -v
```

10 tests couvrent :

- le rejet par Bounding Box ;
- le Ray Casting ;
- l'alerte unique par entrée ;
- les données corrompues ;
- le lissage à 100 Hz ;
- le regroupement d'événements.

## Arborescence

```
data/      jeux de données de l'énoncé + jeux corrompus
src/       geo_engine.py, safety_engine.py
tests/     tests unitaires
output/    daily_score.json généré
main.py    point d'entrée CLI
```

## Point d'attention sur les données

Le point GPS n°3 (45.7850, 4.8050) est annoté « IN (Bordure) » dans l'énoncé.

- Il est bien **dans la Bounding Box**.
- Le Ray Casting montre en revanche qu'il est **au nord de l'arête** (45.7800, 4.8000) → (45.7900, 4.8600). À la longitude 4.8050, cette arête passe à la latitude 45.7808. Le point est donc **hors du polygone**.

C'est précisément le cas qui justifie de ne pas s'arrêter à la Bounding Box. L'alerte se déclenche ainsi au point n°4.
