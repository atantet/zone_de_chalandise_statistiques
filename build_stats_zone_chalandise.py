"""
build_stats_zone_chalandise.py

Pipeline reproductible de génération des statistiques de zone de chalandise
pour l'étude de marché DJA — EARL La Petite Claye des Champs.

Données source : INSEE Filosofi 2021, carreaux 200 m
  https://www.insee.fr/fr/statistiques/8735162?sommaire=8735243

Le pipeline est organisé en deux étapes indépendantes, contrôlées par les
drapeaux RUN_ETAPE_1 / RUN_ETAPE_2 en bas du fichier. Le xlsx produit à
l'étape 1 est sauvegardé sur disque ; l'étape 2 le relit. On peut donc
relancer l'étape 2 seule pour régénérer les plots après modification du
script de plot, sans refaire l'agrégation des carreaux.

  Étape 1 — Statistiques agrégées (output : un .csv à plat)
    1.1 Téléchargement (cache local) du GeoPackage INSEE Filosofi 2021
    1.2 Lecture des 4 GeoPackages d'isochrones exportés depuis QGIS
    1.3 Intersection carreaux × polygones, agrégation des indicateurs
    1.4 Calcul de la référence France métropolitaine
    1.5 Écriture d'un CSV à plat (1 ligne par couple centre/durée + 1 ligne
        France métropolitaine)

  Étape 2 — Plots des indicateurs (output : 7 fichiers PNG dans images/)
    Lit le CSV et génère un bar-chart par indicateur, avec une barre par
    zone d'isochrone et une ligne de référence métropolitaine quand
    pertinent. Les plots sont écrits dans `images/` avec le millésime des
    données dans leur nom (par exemple `ind_somme_filosofi2021.png`).

Le millésime des données INSEE figure dans le nom du CSV produit
(`zone_de_chalandise_statistiques_filosofi2021.csv`) et dans le nom des
plots, pour distinguer explicitement les fichiers d'un millésime
antérieur.

Usage :
    conda activate zone-chalandise
    python build_stats_zone_chalandise.py
"""

from __future__ import annotations

import sys
import warnings
import zipfile
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import requests
from tqdm import tqdm


# ============================================================================
# CONFIGURATION
# ============================================================================

# Répertoire du script — sert de racine pour les sous-dossiers d'entrée
# et de sortie.
PROJET_DIR = Path(__file__).parent

# Sous-dossier des fichiers d'entrée (exports QGIS)
ENTREE_DIR = "entree"

# Sous-dossier des fichiers de sortie (CSV de résultats)
SORTIE_DIR = "sortie"

# Sous-dossier des plots (créé automatiquement si nécessaire)
PLOTS_DIR = "images"

# Cache pour le téléchargement INSEE — téléchargé une seule fois (~290 Mo)
CACHE_DIR = Path.home() / ".cache" / "insee_filosofi_2021"

# URL officielle INSEE — Filosofi 2021 carreaux 200 m, format GeoPackage
URL_INSEE_FILOSOFI = (
    "https://www.insee.fr/fr/statistiques/fichier/8735162/"
    "Filosofi2021_carreaux_200m_gpkg.zip"
)

# CRS du fichier INSEE Filosofi 2021 carreaux 200 m (Lambert 93).
# Source : documentation INSEE.
CRS_INSEE = "EPSG:2154"

# 4 fichiers d'isochrones à exporter depuis QGIS, un par centre.
# Chaque fichier contient 3 polygones, un par durée d'isochrone.
EXPORTS_QGIS = {
    "vente_a_la_ferme": "isochrones_vente_a_la_ferme.gpkg",
    "marche_bio_dol": "isochrones_marche_bio_de_dol.gpkg",
    "marche_pontorson": "isochrones_marche_de_pontorson.gpkg",
    "marche_rocabey": "isochrones_marche_de_rocabey.gpkg",
}

# Noms d'affichage des centres (utilisés dans les feuilles xlsx et les plots)
NOMS_AFFICHAGE = {
    "vente_a_la_ferme": "vente à la ferme",
    "marche_bio_dol": "marché bio de Dol",
    "marche_pontorson": "marché de Pontorson",
    "marche_rocabey": "marché de Rocabey",
}

# Ordre des centres dans les plots (du plus rural au plus urbain)
ORDRE_CENTRES = [
    "vente_a_la_ferme",
    "marche_bio_dol",
    "marche_pontorson",
    "marche_rocabey",
]

# Durées d'isochrones pour chaque centre (ordre croissant = zone restreinte
# en premier). Doivent correspondre à l'ordre des polygones dans les
# fichiers GeoPackage exportés depuis QGIS.
DUREES_PAR_CENTRE = {
    "vente_a_la_ferme": ["5 min", "8 min", "10 min"],
    "marche_bio_dol": ["10 min", "15 min", "20 min"],
    "marche_pontorson": ["10 min", "15 min", "20 min"],
    "marche_rocabey": ["10 min", "20 min", "30 min"],
}

# Nom du fichier CSV produit (millésime explicite dans le nom)
CSV_OUTPUT = "zone_de_chalandise_statistiques_filosofi2021.csv"

# Suffixe ajouté aux fichiers PNG des plots pour identifier le millésime
PLOTS_MILLESIME_SUFFIX = "_filosofi2021"

# Indicateurs à calculer et exporter (ordre = ordre des colonnes du CSV).
# Doit être cohérent avec le script de plot et le pipeline en aval.
INDICATEURS_OUTPUT = [
    "ind_somme",
    "men_somme",
    "ind_0_24_part",
    "ind_25_64_part",
    "ind_65p_part",
    "ind_snv_moy",
    "ind_par_men",
]

# Valeur spéciale dans la colonne `centre` pour la ligne France métropolitaine
CENTRE_METROPOLE = "metropole"

# Étiquettes des indicateurs pour les plots (étape 2)
ETIQUETTES_INDICATEURS = {
    "ind_somme": "Nombre d'individus",
    "men_somme": "Nombre de ménages",
    "ind_0_24_part": "Part des 0-24 ans (%)",
    "ind_25_64_part": "Part des 25-64 ans (%)",
    "ind_65p_part": "Part des 65 ans et + (%)",
    "ind_snv_moy": "Niveau de vie moyen par individu (€/an)",
    "ind_par_men": "Nombre d'individus par ménage",
}

# Indicateurs où il est pertinent d'afficher la ligne France métropolitaine.
# Les sommes (ind_somme, men_somme) ne se comparent pas à la métropole.
INDICATEURS_AVEC_METRO = {
    "ind_somme": False,
    "men_somme": False,
    "ind_0_24_part": True,
    "ind_25_64_part": True,
    "ind_65p_part": True,
    "ind_snv_moy": True,
    "ind_par_men": True,
}

# Indicateurs exprimés en pourcentage (multiplier par 100 pour l'affichage)
INDICATEURS_EN_POURCENT = {
    "ind_somme": 1,
    "men_somme": 1,
    "ind_0_24_part": 100,
    "ind_25_64_part": 100,
    "ind_65p_part": 100,
    "ind_snv_moy": 1,
    "ind_par_men": 1,
}

# Limites verticales pour les indicateurs en pourcentage (0-100)
INDICATEURS_YLIM = {
    "ind_somme": None,
    "men_somme": None,
    "ind_0_24_part": (0, 100),
    "ind_25_64_part": (0, 100),
    "ind_65p_part": (0, 100),
    "ind_snv_moy": None,
    "ind_par_men": None,
}

# Largeur d'une barre dans les plots (en unité d'axe x)
BAR_WIDTH = 0.25

# Résolution des plots produits
DPI_PLOTS = 300


# ============================================================================
# ÉTAPE 1 — STATISTIQUES AGRÉGÉES
# ============================================================================


def telecharger_gpkg_insee(url: str, cache_dir: Path) -> Path:
    """
    Télécharge et décompresse le GeoPackage INSEE Filosofi 2021 si nécessaire.

    Cache local : le fichier est téléchargé une seule fois. Le script vérifie
    sa présence avant de retélécharger.

    Returns:
        Chemin vers le fichier .gpkg décompressé.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "Filosofi2021_carreaux_200m_gpkg.zip"
    gpkg_path = cache_dir / "carreaux_200m_met.gpkg"

    if gpkg_path.exists():
        print(f"[1.1] GeoPackage INSEE déjà en cache : {gpkg_path}")
        return gpkg_path

    print(f"[1.1] Téléchargement du GeoPackage INSEE")
    print(f"      Depuis : {url}")
    print(f"      Vers   : {zip_path}")
    print(f"      (~294 Mo, à faire une seule fois)")

    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()
    total_size = int(response.headers.get("content-length", 0))

    with open(zip_path, "wb") as f, tqdm(
        total=total_size, unit="B", unit_scale=True, desc="      Téléchargement"
    ) as pbar:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                pbar.update(len(chunk))

    print(f"[1.1] Décompression vers : {cache_dir}")
    with zipfile.ZipFile(zip_path) as z:
        # On extrait le fichier .gpkg « met » (métropole) ; les autres sont DOM
        target_member = None
        for name in z.namelist():
            base = Path(name).name.lower()
            if base.endswith(".gpkg") and "met" in base:
                target_member = name
                break
        if target_member is None:
            raise RuntimeError(
                f"Impossible de trouver le GeoPackage métropole dans le zip. "
                f"Contenu : {z.namelist()}"
            )
        z.extract(target_member, cache_dir)
        extracted = cache_dir / target_member
        # On renomme vers un chemin stable
        extracted.rename(gpkg_path)

    # Suppression du zip pour libérer l'espace disque
    zip_path.unlink()
    print(f"[1.1] GeoPackage prêt : {gpkg_path}")
    return gpkg_path


def lire_isochrones_qgis(projet_dir: Path) -> dict[str, gpd.GeoDataFrame]:
    """
    Lit les 4 fichiers d'isochrones exportés depuis QGIS, situés dans le
    sous-dossier `entree/` du projet, et les reprojette en Lambert 93 (CRS
    du fichier INSEE).

    L'ordre des polygones dans chaque fichier doit être : zone la plus
    restreinte en premier. Le script trie par surface croissante pour
    forcer cet ordre, indépendamment de l'ordre de stockage QGIS.

    Returns:
        Dict {centre: GeoDataFrame à 3 polygones} en CRS Lambert 93.
    """
    entree_dir = projet_dir / ENTREE_DIR
    isochrones = {}
    for centre, filename in EXPORTS_QGIS.items():
        path = entree_dir / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Fichier isochrone introuvable : {path}\n"
                f"Tu dois exporter la couche QGIS "
                f"'Isochrones {NOMS_AFFICHAGE[centre]}' "
                f"en GeoPackage sous ce nom dans le sous-dossier `entree/`."
            )
        gdf = gpd.read_file(path)
        # Reprojeter en Lambert 93 pour intersection avec les carreaux INSEE
        gdf = gdf.to_crs(CRS_INSEE)
        # Trier par surface croissante (zone restreinte en premier)
        gdf = gdf.assign(_area=gdf.geometry.area)
        gdf = gdf.sort_values("_area").reset_index(drop=True)
        gdf = gdf.drop(columns="_area")
        isochrones[centre] = gdf
        print(
            f"[1.2] Lu {ENTREE_DIR}/{filename} : {len(gdf)} polygones, "
            f"reprojeté en {CRS_INSEE}"
        )
    return isochrones


def calculer_bbox_globale(
    isochrones: dict[str, gpd.GeoDataFrame], buffer_m: float = 1000
) -> tuple[float, float, float, float]:
    """
    Calcule la bounding box englobante de tous les polygones d'isochrones,
    avec un buffer de sécurité (par défaut 1 km).

    Returns:
        Tuple (minx, miny, maxx, maxy) en Lambert 93.
    """
    minx, miny = float("inf"), float("inf")
    maxx, maxy = float("-inf"), float("-inf")
    for gdf in isochrones.values():
        b = gdf.total_bounds
        minx = min(minx, b[0])
        miny = min(miny, b[1])
        maxx = max(maxx, b[2])
        maxy = max(maxy, b[3])
    return (minx - buffer_m, miny - buffer_m, maxx + buffer_m, maxy + buffer_m)


def lire_carreaux_filosofi(
    gpkg_path: Path,
    bbox: tuple[float, float, float, float] | None = None,
) -> gpd.GeoDataFrame:
    """
    Lit le GeoPackage INSEE Filosofi.

    Si une bounding box est fournie, ne charge que les carreaux intersectant
    la bbox (filtrage spatial à la lecture par geopandas). Cela évite de
    charger les 2,3 millions de carreaux de la métropole en mémoire.

    Returns:
        GeoDataFrame avec les carreaux et leurs 34 indicateurs INSEE.
    """
    if bbox is not None:
        print(f"[1.3] Lecture des carreaux Filosofi (bbox : {bbox})")
        carreaux = gpd.read_file(gpkg_path, bbox=bbox)
    else:
        print(f"[1.3] Lecture complète des carreaux Filosofi (métropole)")
        carreaux = gpd.read_file(gpkg_path)
    print(f"[1.3] {len(carreaux):,} carreaux chargés".replace(",", " "))
    return carreaux


def calculer_indicateurs(carreaux: gpd.GeoDataFrame) -> dict[str, float]:
    """
    Calcule les 7 indicateurs agrégés à partir d'un ensemble de carreaux.

    Les variables d'âge fournies par INSEE Filosofi 2021 sont en classes fines
    (ind_0_3, ind_4_5, ind_6_10, …, ind_80p). On les recompose en 3 classes
    larges pour rester compatible avec le format historique (0-24 / 25-64 / 65+).

    Le niveau de vie moyen est calculé en sommant les niveaux de vie totaux
    (ind_snv) puis en divisant par le total d'individus — c'est une moyenne
    pondérée correcte sur l'ensemble de la zone, pas une moyenne des moyennes.

    Returns:
        Dict {nom_indicateur: valeur} avec les 7 indicateurs de sortie.
    """
    if len(carreaux) == 0:
        return {ind: float("nan") for ind in INDICATEURS_OUTPUT}

    # Sommes pour les variables additives
    ind_somme = carreaux["ind"].sum()
    men_somme = carreaux["men"].sum()
    ind_snv_somme = carreaux["ind_snv"].sum()

    # Recomposition des tranches d'âge larges
    ind_0_24 = sum(
        carreaux[c].sum()
        for c in ["ind_0_3", "ind_4_5", "ind_6_10", "ind_11_17", "ind_18_24"]
    )
    ind_25_64 = sum(
        carreaux[c].sum() for c in ["ind_25_39", "ind_40_54", "ind_55_64"]
    )
    ind_65p = sum(carreaux[c].sum() for c in ["ind_65_79", "ind_80p"])

    if ind_somme == 0:
        return {ind: float("nan") for ind in INDICATEURS_OUTPUT}

    return {
        "ind_somme": float(ind_somme),
        "men_somme": float(men_somme),
        "ind_0_24_part": float(ind_0_24 / ind_somme),
        "ind_25_64_part": float(ind_25_64 / ind_somme),
        "ind_65p_part": float(ind_65p / ind_somme),
        "ind_snv_moy": float(ind_snv_somme / ind_somme),
        "ind_par_men": float(ind_somme / men_somme) if men_somme > 0 else float("nan"),
    }


def agreger_par_zone(
    carreaux: gpd.GeoDataFrame,
    isochrones: dict[str, gpd.GeoDataFrame],
) -> dict[tuple[str, str], dict[str, float]]:
    """
    Pour chaque (centre, durée), intersecte les carreaux avec le polygone
    d'isochrone et calcule les indicateurs agrégés.

    Convention d'intersection : un carreau appartient à une zone si son
    centroïde est dans le polygone. Cette convention est cohérente avec la
    pratique QGIS et l'usage statistique INSEE.

    Returns:
        Dict {(centre, duree_str): dict d'indicateurs}.
    """
    # Centroïdes calculés une fois pour toutes les zones
    centroides = carreaux.geometry.centroid

    resultats = {}
    for centre, gdf_iso in isochrones.items():
        durees = DUREES_PAR_CENTRE[centre]
        if len(durees) != len(gdf_iso):
            warnings.warn(
                f"Centre {centre} : {len(gdf_iso)} polygones dans le "
                f"GeoPackage mais {len(durees)} durées attendues "
                f"({durees}). Vérifier l'export QGIS."
            )

        for idx, poly_row in gdf_iso.iterrows():
            duree_str = durees[idx] if idx < len(durees) else f"zone {idx}"
            poly = poly_row.geometry

            # Sélection des carreaux dont le centroïde est dans le polygone
            mask = centroides.within(poly)
            carreaux_zone = carreaux[mask]

            indicateurs = calculer_indicateurs(carreaux_zone)
            resultats[(centre, duree_str)] = indicateurs

            print(
                f"      {NOMS_AFFICHAGE[centre]:<25} {duree_str:>7} : "
                f"{len(carreaux_zone):>5,} carreaux, ".replace(",", " ")
                + f"{indicateurs['ind_somme']:>8,.0f} indiv.".replace(",", " ")
            )

    return resultats


def _duree_to_min(duree_str: str) -> int:
    """
    Extrait le nombre de minutes d'une chaîne du type "5 min", "10 min", etc.

    Returns:
        Entier (5, 8, 10, 15, 20, 30…).
    """
    return int(duree_str.split()[0])


def ecrire_csv(
    resultats_zones: dict[tuple[str, str], dict[str, float]],
    indicateurs_metro: dict[str, float],
    csv_path: Path,
) -> None:
    """
    Écrit un CSV à plat avec :
      - Une ligne par couple (centre, durée) — total 12 lignes
      - Une ligne supplémentaire pour la France métropolitaine

    Format :
        centre, duree_min, ind_somme, men_somme, ind_0_24_part, ...

    `centre` est un slug interne (vente_a_la_ferme, marche_bio_dol, ...)
    `duree_min` est un entier en minutes ; vide pour la ligne metropole.

    Lisible directement par `pd.read_csv(path)`.
    """
    print(f"[1.5] Écriture du CSV : {csv_path}")

    lignes = []
    for centre in ORDRE_CENTRES:
        for duree in DUREES_PAR_CENTRE[centre]:
            key = (centre, duree)
            if key not in resultats_zones:
                continue
            indicateurs = resultats_zones[key]
            ligne = {
                "centre": centre,
                "duree_min": _duree_to_min(duree),
            }
            for ind in INDICATEURS_OUTPUT:
                ligne[ind] = indicateurs[ind]
            lignes.append(ligne)

    # Ligne France métropolitaine (duree_min vide)
    ligne_metro = {
        "centre": CENTRE_METROPOLE,
        "duree_min": pd.NA,
    }
    for ind in INDICATEURS_OUTPUT:
        ligne_metro[ind] = indicateurs_metro[ind]
    lignes.append(ligne_metro)

    df = pd.DataFrame(lignes)
    df.to_csv(csv_path, index=False, encoding="utf-8")

    print(f"[1.5] CSV écrit : {len(df)} lignes "
          f"({len(df) - 1} zones + 1 métropole)")


def etape_1_statistiques_agregees() -> Path:
    """
    Exécute l'étape 1 du pipeline et renvoie le chemin du xlsx produit.
    """
    print()
    print("=" * 70)
    print("ÉTAPE 1 — STATISTIQUES AGRÉGÉES")
    print("=" * 70)

    # 1.1 Téléchargement INSEE (cache local)
    gpkg_path = telecharger_gpkg_insee(URL_INSEE_FILOSOFI, CACHE_DIR)

    # 1.2 Lecture des isochrones QGIS
    print()
    print("[1.2] Lecture des 4 GeoPackages d'isochrones exportés depuis QGIS")
    isochrones = lire_isochrones_qgis(PROJET_DIR)

    # 1.3 Calcul de la bounding box englobante (avec buffer 1 km)
    bbox = calculer_bbox_globale(isochrones, buffer_m=1000)
    print(f"[1.2] Bbox globale (Lambert 93) : {bbox}")

    # 1.3 Lecture des carreaux INSEE dans la bbox
    print()
    print("[1.3] Agrégation des indicateurs par zone")
    carreaux_zone = lire_carreaux_filosofi(gpkg_path, bbox=bbox)
    resultats_zones = agreger_par_zone(carreaux_zone, isochrones)
    del carreaux_zone  # Libère la RAM avant chargement métropole

    # 1.4 Calcul de la référence France métropolitaine
    # On recharge le fichier complet (sans bbox) pour obtenir les totaux métro.
    # Coût mémoire : 2,3 M de carreaux mais on ne garde que les colonnes utiles.
    print()
    print("[1.4] Calcul de la référence France métropolitaine")
    print("      Lecture complète du GeoPackage INSEE (~2,3 M carreaux)")
    print("      Peut prendre 1-2 minutes selon votre machine.")
    carreaux_metro = lire_carreaux_filosofi(gpkg_path, bbox=None)
    indicateurs_metro = calculer_indicateurs(carreaux_metro)
    print(
        f"[1.4] France métropolitaine : "
        f"{indicateurs_metro['ind_somme']:,.0f} individus, ".replace(",", " ")
        + f"niveau de vie moyen {indicateurs_metro['ind_snv_moy']:,.0f} €".replace(",", " ")
    )
    del carreaux_metro

    # 1.5 Écriture du CSV dans le sous-dossier sortie/
    print()
    sortie_dir = PROJET_DIR / SORTIE_DIR
    sortie_dir.mkdir(parents=True, exist_ok=True)
    csv_path = sortie_dir / CSV_OUTPUT
    ecrire_csv(resultats_zones, indicateurs_metro, csv_path)

    return csv_path


# ============================================================================
# ÉTAPE 2 — PLOTS DES INDICATEURS
# ============================================================================


def _min_to_duree_str(duree_min: int) -> str:
    """Inverse de _duree_to_min : 5 → '5 min'."""
    return f"{duree_min} min"


def lire_csv(csv_path: Path) -> tuple[
    dict[tuple[str, str], dict[str, float]], dict[str, float]
]:
    """
    Lit le CSV produit à l'étape 1.

    Returns:
        (resultats_zones, indicateurs_metro), avec :
        - resultats_zones : dict {(centre_slug, duree_str): {indicateurs}}
        - indicateurs_metro : dict {indicateur: valeur}
    """
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Le CSV attendu n'existe pas : {csv_path}\n"
            f"Lance d'abord l'étape 1 (RUN_ETAPE_1 = True)."
        )

    df = pd.read_csv(csv_path, encoding="utf-8")

    resultats_zones = {}
    indicateurs_metro = {}

    for _, row in df.iterrows():
        centre = row["centre"]
        if centre == CENTRE_METROPOLE:
            indicateurs_metro = {
                ind: float(row[ind]) for ind in INDICATEURS_OUTPUT
            }
        else:
            duree = _min_to_duree_str(int(row["duree_min"]))
            resultats_zones[(centre, duree)] = {
                ind: float(row[ind]) for ind in INDICATEURS_OUTPUT
            }

    return resultats_zones, indicateurs_metro


def plot_indicateur(
    indicateur: str,
    resultats_zones: dict[tuple[str, str], dict[str, float]],
    indicateurs_metro: dict[str, float],
    output_path: Path,
) -> None:
    """
    Produit un bar-chart pour un indicateur donné.

    Une "grappe" de barres par centre, une barre par durée d'isochrone à
    l'intérieur de la grappe, ligne pointillée pour la moyenne France
    métropolitaine quand pertinent.
    """
    fig, ax = plt.subplots(figsize=(9, 5), layout="constrained")

    facteur = INDICATEURS_EN_POURCENT[indicateur]
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    # Position des barres
    n_durees = 3  # toujours 3 zones par centre
    market_width = BAR_WIDTH * (n_durees + 1)
    xticks = []
    xticklabels = []

    for i_centre, centre in enumerate(ORDRE_CENTRES):
        x_centre = i_centre * market_width + BAR_WIDTH * (n_durees - 1) / 2
        xticks.append(x_centre)
        durees = DUREES_PAR_CENTRE[centre]
        xticklabels.append(
            f"{NOMS_AFFICHAGE[centre].capitalize()}\n{', '.join(durees)}"
        )

        for i_duree, duree in enumerate(durees):
            key = (centre, duree)
            if key not in resultats_zones:
                continue
            val = resultats_zones[key][indicateur] * facteur
            x = i_centre * market_width + i_duree * BAR_WIDTH
            ax.bar(x, val, BAR_WIDTH, color=colors[i_duree], edgecolor="white")

    # Mise en forme
    ax.set_xticks(xticks)
    ax.set_xticklabels(xticklabels, rotation=20, ha="right")
    ax.set_ylabel(ETIQUETTES_INDICATEURS[indicateur])
    ax.grid(True, axis="y", alpha=0.4)
    ax.set_axisbelow(True)

    # Ligne France métropolitaine (si pertinent)
    if INDICATEURS_AVEC_METRO[indicateur] and indicateurs_metro:
        val_metro = indicateurs_metro[indicateur] * facteur
        xlim = ax.get_xlim()
        ax.hlines(
            [val_metro], *xlim,
            color="k", linestyle="--", linewidth=1,
            label=f"France métropolitaine ({val_metro:.1f})"
        )
        ax.set_xlim(xlim)
        ax.legend(loc="best", fontsize=9)

    # Limites verticales
    ylim = INDICATEURS_YLIM[indicateur]
    if ylim is not None:
        ax.set_ylim(ylim)

    plt.savefig(output_path, dpi=DPI_PLOTS)
    plt.close(fig)


def etape_2_plots(csv_path: Path) -> list[Path]:
    """
    Exécute l'étape 2 du pipeline : génère un plot par indicateur.

    Les plots sont écrits dans le sous-dossier `images/` (créé si nécessaire),
    avec un suffixe de millésime dans le nom (`<indicateur>_filosofi2021.png`).

    Returns:
        Liste des chemins des fichiers PNG produits.
    """
    print()
    print("=" * 70)
    print("ÉTAPE 2 — PLOTS DES INDICATEURS")
    print("=" * 70)
    print(f"[2.1] Lecture du CSV : {csv_path}")

    resultats_zones, indicateurs_metro = lire_csv(csv_path)
    print(f"[2.1] {len(resultats_zones)} zones chargées, "
          f"métropole : {'oui' if indicateurs_metro else 'absente'}")

    # Préparer le sous-dossier de sortie
    plots_dir = PROJET_DIR / PLOTS_DIR
    plots_dir.mkdir(parents=True, exist_ok=True)
    print(f"[2.2] Dossier de sortie des plots : {plots_dir}")

    plots_produits = []
    for indicateur in INDICATEURS_OUTPUT:
        filename = f"{indicateur}{PLOTS_MILLESIME_SUFFIX}.png"
        output_path = plots_dir / filename
        plot_indicateur(
            indicateur, resultats_zones, indicateurs_metro, output_path
        )
        plots_produits.append(output_path)
        print(f"[2.2] Plot produit : {output_path.relative_to(PROJET_DIR)}")

    return plots_produits


# ============================================================================
# ORCHESTRATION
# ============================================================================

# Drapeaux pour activer ou désactiver chaque étape.
# Utile quand on a déjà le xlsx et qu'on veut juste re-générer les plots
# après modification du script de plot.
RUN_ETAPE_1 = True
RUN_ETAPE_2 = True


def main() -> int:
    csv_path = PROJET_DIR / SORTIE_DIR / CSV_OUTPUT

    if RUN_ETAPE_1:
        csv_path = etape_1_statistiques_agregees()
    else:
        print(f"[Étape 1 désactivée — on suppose que {csv_path} existe]")

    if RUN_ETAPE_2:
        plots = etape_2_plots(csv_path)
        print()
        print(f"=== {len(plots)} plots produits ===")
    else:
        print(f"[Étape 2 désactivée]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
