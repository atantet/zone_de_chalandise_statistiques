# Pipeline de mise à jour des statistiques de zone de chalandise

Ce dossier contient un pipeline reproductible qui télécharge les données
INSEE Filosofi 2021 (carreaux 200 m), les croise avec les zones d'isochrones
de l'étude de marché (exportées depuis QGIS), et produit :

1. Un classeur xlsx avec les indicateurs agrégés par zone
   (`zone_de_chalandise_statistiques_filosofi2021.xlsx`)
2. Sept fichiers PNG (un par indicateur), pour intégration dans l'étude.

## Pré-requis

- Conda (Miniforge / Mambaforge / Anaconda) installé
- Une connexion internet pour le premier téléchargement des données INSEE
  (~ 294 Mo, fait une seule fois grâce au cache local)
- Environ 500 Mo d'espace disque libre dans `~/.cache/insee_filosofi_2021/`

## Préparation : exports QGIS (à faire une seule fois)

Dans QGIS, ouvre le projet `zone_de_chalandise_projet.qgz`. Pour chacune
des 4 couches « Isochrones [débouché] » :

1. Clic droit sur la couche dans le panneau **Couches**
2. **Exporter → Save Features As…**
3. **Format** : GeoPackage
4. **Nom du fichier** (à respecter exactement) :
   - `isochrones_vente_a_la_ferme.gpkg`
   - `isochrones_marche_bio_de_dol.gpkg`
   - `isochrones_marche_de_pontorson.gpkg`
   - `isochrones_marche_de_rocabey.gpkg`
5. **CRS** : laisser le CRS du projet QGIS (le script reprojette en
   Lambert 93 automatiquement)
6. **Save**

Place les 4 fichiers dans le sous-dossier `entree/` à côté du script
`build_stats_zone_chalandise.py`. Crée le dossier `entree/` s'il n'existe
pas encore.

Tu peux vérifier l'ordre des polygones dans chaque GeoPackage en ouvrant la
table d'attributs dans QGIS — le script trie automatiquement par surface
croissante (zone la plus restreinte en premier), donc l'ordre dans QGIS
n'a pas d'importance pour l'agrégation.

## Installation de l'environnement Conda

À faire une seule fois :

```bash
conda env create -f environment.yaml
```

Cela crée un environnement nommé `zone-chalandise` avec geopandas, pandas,
matplotlib, etc.

## Exécution

```bash
conda activate zone-chalandise
python build_stats_zone_chalandise.py
```

À la première exécution, le téléchargement INSEE dure quelques minutes
(294 Mo). Les exécutions suivantes utilisent le cache local et sont
nettement plus rapides.

## Arborescence du projet

```
zone_chalandise_pipeline/
├── build_stats_zone_chalandise.py   # Le script
├── environment.yaml                  # Environnement Conda
├── README.md                         # Ce fichier
├── .gitignore                        # Exclusions Git
├── entree/                           # Exports QGIS (à créer par l'utilisateur)
│   ├── isochrones_vente_a_la_ferme.gpkg
│   ├── isochrones_marche_bio_de_dol.gpkg
│   ├── isochrones_marche_de_pontorson.gpkg
│   └── isochrones_marche_de_rocabey.gpkg
├── sortie/                           # CSV agrégé (produit par le script)
│   └── zone_de_chalandise_statistiques_filosofi2021.csv
└── images/                           # Plots PNG (produits par le script)
    ├── ind_somme_filosofi2021.png
    ├── men_somme_filosofi2021.png
    ├── ind_0_24_part_filosofi2021.png
    ├── ind_25_64_part_filosofi2021.png
    ├── ind_65p_part_filosofi2021.png
    ├── ind_snv_moy_filosofi2021.png
    └── ind_par_men_filosofi2021.png
```

Les dossiers `sortie/` et `images/` sont créés automatiquement par le
script. Tu dois créer toi-même `entree/` et y placer les 4 exports QGIS.

## Sortie attendue

Le script produit un **CSV à plat** dans `sortie/` :

- `zone_de_chalandise_statistiques_filosofi2021.csv` — 13 lignes (12 zones
  + 1 ligne France métropolitaine) et 9 colonnes (`centre`, `duree_min`, et
  les 7 indicateurs). Lisible directement par `pandas.read_csv(...)`.

Et **sept plots PNG** dans `images/` :

- `ind_somme_filosofi2021.png` (nombre d'individus)
- `men_somme_filosofi2021.png` (nombre de ménages)
- `ind_0_24_part_filosofi2021.png` (part des 0-24 ans)
- `ind_25_64_part_filosofi2021.png` (part des 25-64 ans)
- `ind_65p_part_filosofi2021.png` (part des 65 ans et plus)
- `ind_snv_moy_filosofi2021.png` (niveau de vie moyen)
- `ind_par_men_filosofi2021.png` (individus par ménage)

## Régénérer seulement les plots (sans refaire l'agrégation)

Si tu modifies le script de plot et veux régénérer les figures sans
relancer l'agrégation des carreaux :

1. Édite `build_stats_zone_chalandise.py`
2. En bas du fichier, mets `RUN_ETAPE_1 = False`
3. Lance le script normalement
4. Une fois satisfait du résultat, remets `RUN_ETAPE_1 = True` pour la
   prochaine exécution complète

## Mettre à jour avec un futur millésime INSEE (Filosofi 2023, etc.)

Le jour où l'INSEE publie un nouveau millésime :

1. Mets à jour `URL_INSEE_FILOSOFI` en haut du script avec la nouvelle URL
2. Mets à jour `CSV_OUTPUT` et `PLOTS_MILLESIME_SUFFIX` avec le nouveau
   millésime (par exemple `zone_de_chalandise_statistiques_filosofi2023.csv`
   et `_filosofi2023`)
3. Vide ou renomme le cache si tu veux forcer un nouveau téléchargement :
   `rm -rf ~/.cache/insee_filosofi_2021/`
4. Lance le script

## Dépannage

**Erreur « Fichier isochrone introuvable »** : vérifie que tu as exporté
les 4 GeoPackages avec exactement les noms attendus, dans le sous-dossier
`entree/` à côté du script. Crée le dossier `entree/` s'il n'existe pas.

**Erreur de mémoire à l'étape 1.4 (référence métropolitaine)** : le
chargement complet du GeoPackage (2,3 M de carreaux) demande ~2 Go de RAM.
Si ta machine est limitée, tu peux remplacer le chargement complet par
une lecture en chunks (à coder manuellement) ou utiliser le fichier CSV
INSEE équivalent (87 Mo, plus léger en RAM).

**Téléchargement échoué** : relance le script, il reprend là où il s'est
arrêté grâce au cache. Si le zip est corrompu, supprime-le manuellement
(`rm ~/.cache/insee_filosofi_2021/Filosofi2021_carreaux_200m_gpkg.zip`)
et relance.
