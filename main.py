#!/usr/bin/env python3
"""
Preventief Toekomstbestendig Onderhoud aan de Wegmarkeringen
==================================

  1. Filteren          — checkbox- en bereik-filters
  2. Tabel             — gesorteerd overzicht + exports (Excel, Pickle,
                          4 thematische QGIS-lagen)
  3. Grafieken         — matplotlib-kaarten, KDE plots, bocht × health
  4. Clustering        — PELT changepoint-detectie met instelbare gewichten
                          + cluster QGIS-export
  5. Diagnose          — stap-voor-stap door de PELT-pipeline voor 1 hectopunt
  6. Netwerk-validatie — controle dat clusters aaneengesloten zijn
  7. Theorie PELT      — wiskundige onderbouwing

Bestandsindeling
----------------
De code is opgedeeld in afgebakende secties met `# === BANNER ===`.

  1. CONFIGURATIE           — Settings: paden, kolommen, defaults
  2. DATA PREPARATION       — alles wat nodig is om van een ruwe pickle
                              naar de "prepared" dataset te komen.
                              Single entry point: `prepare_dataset(raw, key)`.
                              Dit hele blok is ontworpen om los getrokken te
                              kunnen worden (b.v. naar een prep-notebook).
  3. FILTERS                — sidebar widgets + `apply_filters`.  Filters
                              herstellen `_inspectie_scores` na strippen,
                              dus een klein stuk data-prep leeft hier
                              bewust (afhankelijk van filter-keuzes).
  4. PELT CLUSTERING        — algoritme + `attach_cluster_severity`
                              (post-clustering rang-prep).
  5. DIAGNOSE               — één hectopunt door de pipeline volgen.
  6. CHARTS                 — matplotlib charts + registry.
  7. QGIS EXPORTS           — thematische lagen + cluster-GPKG.
  8. TABEL                  — annotatie-merge + downloads (Excel/pickle).
  9. SIDEBAR PELT CONTROLS  — widgets voor clustering-parameters.
 10. OUTPUT GENERATIE       — "Genereer alles" bundel.
 11. ANNOTATIES             — persistente JSON met levensduur/onderhoud.
 12. TAB RENDERER           — render_map_tab (enige view; clustering +
                              diagnose draaien inline in de kaart).
 13. MAIN APP               — orchestratie + entrypoint.

Pipeline (in volgorde):
    raw pickle ─► prepare_dataset ─► apply_filters ─► kaart
                                                       │
                                  cluster ◄── PELT ────┤
                                  diagnose ◄───────────┘

Run:
    pip install streamlit pandas numpy scikit-learn matplotlib ruptures \\
                pyarrow shapely geopandas scipy contextily openpyxl
    streamlit run pipeline_dashboard.py
"""
from __future__ import annotations

import base64
import colorsys
import io
import json
import logging
import os
import re
import sqlite3
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from matplotlib.figure import Figure

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("pipeline_dashboard")

try:
    from scipy.stats import gaussian_kde
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False
    logger.warning("scipy niet beschikbaar — KDE plots uitgeschakeld")

try:
    import contextily as ctx
    _CTX_OK = True
except ImportError:
    _CTX_OK = False
    logger.warning("contextily niet beschikbaar — basemap uitgeschakeld")

try:
    import ruptures as rpt
    HAS_RUPTURES = True
except ImportError:
    HAS_RUPTURES = False


# ============================================================
# CONFIGURATIE
# ============================================================
class Settings:
    OUTPUT_DIR = Path(__file__).parent / "Output"
    LOGO_PATH  = Path(__file__).parent / "Input" / "logo.png"
    DEFAULT_DATASETS: List[str] = [
        "Data_Analyse-Dataset.pkl",
        "Data_Rekenmodel-Dataset_origineel.pkl",
        "Data_Analyse-Dataset_patched.pkl",
        "Data_Rekenmodel-Dataset.pkl",
    ]
    BASEMAP_CACHE = OUTPUT_DIR / "_nl_basemap.npz"

    CURVE_THRESHOLD = 400

    # Kleur palette (vrijwel identiek aan main.py voor herkenbaarheid)
    COLOR_GREEN_PRIMARY = "#1A6B3C"
    COLOR_BLUE_PRIMARY  = "#1F4E79"
    COLOR_GREY_PRIMARY  = "#5A6472"

    # ── Tabel kolommen (zelfde set als main.py) ────────────────
    # Volgorde = volgorde van weergave in de Tabel-tab én in de
    # "Alle attributen"-paneel onder de kaart. Houd hier ALLE
    # output-kolommen van de dataprep zichtbaar.
    # Labels = exact dataset-kolomnamen (snake_case). Computed kolommen
    # (zonder onderscheid prefix) krijgen hun interne naam zonder leading
    # underscore zodat de hele code dezelfde benaming hanteert.
    TREE_COLUMNS: List[Tuple[str, str]] = [
        ("wegnr_hmp",        "wegnr_hmp"),
        ("hectomtrng",       "hectomtrng"),
        ("hecto_lttr",       "hecto_lttr"),
        ("Zijde",            "Zijde"),
        ("distrnaam",        "distrnaam"),
        ("draaihoek",        "draaihoek"),
        ("boogstraal",       "boogstraal"),
        ("aantal_bochten",   "aantal_bochten"),
        ("strook",           "strook"),
        ("klein_voertuig",   "klein_voertuig"),
        ("middel_voertuig",  "middel_voertuig"),
        ("lang_voertuig",    "lang_voertuig"),
        ("totaal_voertuig",  "totaal_voertuig"),
        ("health_2023",      "kwaliteit 2023"),
        ("visibility_2023",  "zichtbaarheid 2023"),
        ("health_2025",      "kwaliteit 2025"),
        ("visibility_2025",  "zichtbaarheid 2025"),
        ("aantal_inspecties", "aantal_inspecties"),
        ("_leeftijd_str",    "leeftijd"),
        ("deklaagsoort",     "deklaagsoort"),
        ("aanlegdatum",      "aanlegdatum"),
        ("aantal_deklagen",  "aantal_deklagen"),
        ("info",             "info"),
        ("wegbehnaam",       "wegbehnaam"),
        ("beginkm",          "beginkm"),
        ("eindkm",           "eindkm"),
        ("snelwegnummer",    "snelwegnummer"),
        ("wegnummer",        "wegnummer"),
        ("wegnr_aw",         "wegnr_aw"),
        ("rijrichtng",       "rijrichtng"),
        ("oplopend",         "oplopend"),
        ("afstand",          "afstand"),
        ("gps_coordinaten",  "gps_coordinaten"),
        ("hectopunt_rd_coordinaten", "hectopunt_rd_coordinaten"),
        ("streetsmart_link", "streetsmart_link"),
        ("google_maps_link", "google_maps_link"),
        ("pdok_viewer_link", "pdok_viewer_link"),
        ("wvk_id",           "wvk_id"),
    ]

    EXPORT_COLUMNS: List[str] = [
        "wvk_id", "wegnr_hmp", "Zijde", "hectomtrng", "hecto_lttr",
        "draaihoek", "boogstraal", "aantal_bochten",
        "health_2023", "visibility_2023",
        "health_2025", "visibility_2025", "aantal_inspecties",
        "deklaagsoort", "aanlegdatum", "strook", "aantal_deklagen",
        "klein_voertuig", "middel_voertuig", "lang_voertuig",
        "totaal_voertuig", "distrnaam", "info",
        "wegbehnaam", "beginkm", "eindkm", "snelwegnummer", "wegnummer",
        "wegnr_aw", "rijrichtng", "oplopend", "afstand",
        "gps_coordinaten", "hectopunt_rd_coordinaten",
        "streetsmart_link", "google_maps_link", "pdok_viewer_link",
        "_alert_score", "hectopunt_geometry",
        # Door-mens-gemaakte annotaties — meegelift naar output zodat
        # downstream-systemen (LIMS, GIS, BI) precies weten welke
        # hectopunten de eindgebruiker gemarkeerd of bewerkt heeft.
        "Vlag", "Vlag_reden",
        "Levensduur", "Onderhoudsintervallen", "Onderhoudsmoment",
        "annotatie_bron",
    ]

    CHECKBOX_FILTERS: List[Tuple[str, str, bool]] = [
        ("deklaagsoort", "Deklagen",       True),
        ("wegnr_hmp",    "Snelwegnummer",  False),
        ("hecto_lttr",   "Hectoletter",    False),
        ("distrnaam",    "Districten",      False),
    ]

    RANGE_FILTERS: List[Tuple[str, str, str]] = [
        ("health_2023",     "kwaliteit 2023",     "_health_23"),
        ("visibility_2023", "zichtbaarheid 2023", "_vis_23"),
        ("health_2025",     "kwaliteit 2025",     "_health_25"),
        ("visibility_2025", "zichtbaarheid 2025", "_vis_25"),
        ("draaihoek",       "draaihoek",       "_max_hoek"),
        ("boogstraal",      "boogstraal",      "_boogstraal"),
        ("leeftijd",        "leeftijd",        "_leeftijd"),
    ]

    # ── Default-bereik per range filter (toegepast bij eerste laden) ──
    # (lo, hi, exclude_empty). exclude_empty=False overal → er wordt NOOIT een
    # hectopunt-rij verwijderd; range-filters knippen alleen losse waarden uit
    # de comma-cel (zie `_strip_outside_window`).
    #   visibility 2023+2025 : 0.0–10  → volledig open, niks gestript.
    #   health     2023     : 0.05–10 → strip de 0.0-sentinel, rijen blijven staan.
    #   health     2025     : 0.05–10 + "verberg lege rijen" AAN → strip 0.0 én
    #                          verberg rijen die daardoor leeg worden (alleen-0.0).
    #                          (kleinste echte score = 0.8.)
    RANGE_DEFAULTS: Dict[str, Tuple[Optional[float], Optional[float], bool]] = {
        "health_2023":     (0.05, 10.0, False),
        "visibility_2023": (0.0, 10.0, False),
        "health_2025":     (0.05, 10.0, True),
        "visibility_2025": (0.0, 10.0, False),
    }

    # ── PELT clustering ───────────────────────────────────────
    INSPECTION_COLS = ["health_2023", "health_2025",
                       "visibility_2023", "visibility_2025"]

    DEFAULT_WEIGHTS: Dict[str, float] = {
        "onderhoudsmoment": 2.0,
        "hoek":            3.0,
        "boogstraal_f":    0.0,
        "verkeer":         0.0,
        "verkeer_zwaar":   2.0,
        "insp_score":      0.0,
    }

    FEATURE_LABELS: Dict[str, str] = {
        "onderhoudsmoment": "Onderhoudsmoment (jaar)",
        "hoek":            "Draaihoek (som graden)",
        "boogstraal_f":    "Boogstraal",
        "verkeer":         "Verkeersintensiteit (totaal)",
        "verkeer_zwaar":   "Zwaar verkeer (% lang t.o.v. totaal)",
        "insp_score":      "Gemiddelde inspectiescore",
    }

    # Richting waarin een HOGERE ruwe feature-waarde "goed" (groen) of
    # "slecht" (rood) is. Bepaalt de oriëntatie van de gewogen 0-1 score
    # die de heatmap-kleur aanstuurt (1 = groen/goed, 0 = rood/slecht).
    #   +1 = hoger is beter   |   -1 = hoger is slechter
    FEATURE_GOOD_DIRECTION: Dict[str, int] = {
        "onderhoudsmoment": +1,  # later onderhoudsjaar = meer restlevensduur = beter
        "hoek":            -1,   # scherpere bocht = slechter
        "boogstraal_f":    +1,   # ruimere boog = beter
        "verkeer":         -1,   # meer verkeer = meer slijtage = slechter
        "verkeer_zwaar":   -1,   # meer zwaar verkeer = zwaardere belasting = slechter
        "insp_score":      +1,   # hogere inspectiescore = beter
    }

    # Hoe een ONTBREKENDE feature wordt ingevuld vóór 0-1 normalisatie.
    # Semantisch i.p.v. blind de mediaan: een rechte weg "mist" geen
    # bochthoek — hij heeft er gewoon geen (= 0°, ruimste boog).
    #   "zero"   -> 0.0            "min" -> kolom-minimum
    #   "max"    -> kolom-maximum  "median" -> kolom-mediaan (neutraal)
    FEATURE_FILL_POLICY: Dict[str, str] = {
        "hoek":            "zero",    # geen bocht = 0 graden draai
        "boogstraal_f":    "max",     # geen bocht = rechte weg = ruimste boog
        "verkeer":         "median",
        "verkeer_zwaar":   "median",  # onbekend aandeel zwaar = neutraal
        "onderhoudsmoment": "median",
        "insp_score":      "median",
    }


# ============================================================
# STREAMLIT PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="RWS Hectopunten Pipeline",
    page_icon=str(Settings.LOGO_PATH) if Settings.LOGO_PATH.exists() else None,
    layout="wide",
    initial_sidebar_state="expanded",
)


# ╔══════════════════════════════════════════════════════════╗
# ║  DATA PREPARATION — standalone block                     ║
# ║                                                          ║
# ║  Alles tussen deze banner en `END OF DATA PREPARATION`   ║
# ║  is bedoeld om los getrokken te kunnen worden (b.v.      ║
# ║  naar een eigen prep-script of notebook).                ║
# ║                                                          ║
# ║  Single entry point:                                     ║
# ║      prepare_dataset(raw_df, cache_key) -> prepared_df   ║
# ║                                                          ║
# ║  Onderdelen:                                             ║
# ║    1. Loading & flatten (file → DataFrame)               ║
# ║    2. Comma-list value extractors                        ║
# ║    3. Coördinaat-extractie (RD New)                      ║
# ║    4. Afgeleide scores (alert / inspectie)               ║
# ║    5. Orchestrator: prepare_dataset()                    ║
# ╚══════════════════════════════════════════════════════════╝

# ── 1. Loading & flatten ──────────────────────────────────
def _flatten_geodataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Zet een (Geo)DataFrame om naar een gewone pd.DataFrame met
    WKT-strings i.p.v. shapely geometry-objecten, zodat Streamlit kan cachen.

    Behoudt de ruwe shapely objecten in `_geom_raw_<col>` zodat we
    achteraf nog x/y kunnen extraheren zonder opnieuw te parsen.
    """
    try:
        import geopandas as gpd
        from shapely.geometry.base import BaseGeometry
    except ImportError:
        return pd.DataFrame(df)

    if isinstance(df, gpd.GeoDataFrame):
        df = pd.DataFrame(df)

    for col in list(df.columns):  # snapshot — we add columns inside the loop
        sample = df[col].dropna().head(1)
        if not sample.empty and isinstance(sample.iloc[0], BaseGeometry):
            # eerst x/y extraheren als het points zijn — daarna pas WKT-isen
            try:
                first = sample.iloc[0]
                if hasattr(first, "x") and hasattr(first, "y"):
                    xs = df[col].apply(
                        lambda g: float(g.x) if g is not None and hasattr(g, "x")
                        else (float(g.geoms[0].x) if g is not None and hasattr(g, "geoms")
                              else np.nan)
                    )
                    ys = df[col].apply(
                        lambda g: float(g.y) if g is not None and hasattr(g, "y")
                        else (float(g.geoms[0].y) if g is not None and hasattr(g, "geoms")
                              else np.nan)
                    )
                    df[f"_geom_x_{col}"] = xs
                    df[f"_geom_y_{col}"] = ys
            except Exception:
                pass
            df[col] = df[col].apply(lambda g: g.wkt if g is not None else None)
    return df


@st.cache_data(show_spinner=False)
def load_default_dataset(path_str: str, mtime: float) -> Optional[pd.DataFrame]:
    """Laad een pickle-dataset uit `Output/`."""
    path = Path(path_str)
    if not path.exists():
        return None
    obj = pd.read_pickle(path)
    if isinstance(obj, pd.Series):
        obj = obj.to_frame()
    elif isinstance(obj, dict):
        obj = pd.DataFrame(obj)
    elif not isinstance(obj, pd.DataFrame):
        return None
    return _flatten_geodataframe(obj)


@st.cache_data(show_spinner=False)
def load_uploaded_dataframe(file_bytes: bytes, name: str) -> pd.DataFrame:
    """Laad een door de gebruiker geüploade dataset."""
    buf = io.BytesIO(file_bytes)
    lower = name.lower()
    if lower.endswith(".parquet"):
        return _flatten_geodataframe(pd.read_parquet(buf))
    if lower.endswith((".xlsx", ".xls")):
        return _flatten_geodataframe(pd.read_excel(buf))
    if lower.endswith((".pkl", ".pickle")):
        obj = pd.read_pickle(buf)
        if isinstance(obj, pd.Series):
            obj = obj.to_frame()
        elif isinstance(obj, dict):
            obj = pd.DataFrame(obj)
        elif not isinstance(obj, pd.DataFrame):
            raise ValueError(
                f"Pickle bevat type {type(obj).__name__}, geen DataFrame."
            )
        return _flatten_geodataframe(obj)
    try:
        return pd.read_csv(buf)
    except Exception:
        buf.seek(0)
        return pd.read_csv(buf, sep=";")


def discover_default_datasets() -> List[Path]:
    """Vind alle bekende default datasets in Output/."""
    return [
        Settings.OUTPUT_DIR / name
        for name in Settings.DEFAULT_DATASETS
        if (Settings.OUTPUT_DIR / name).exists()
    ]


# ── 2. Comma-list value extractors ───────────────────────
# Health/visibility/draaihoek cellen kunnen meerdere waarden bevatten als
# comma-string ("7.9, 8.1, ..."). Deze helpers reduceren zo'n cel tot één
# scalar volgens een regel.
def _split_commas(value: Any) -> List[str]:
    """Split een comma-string in non-lege parts; lege/None-cel → []."""
    if pd.isna(value) or str(value).strip() in ("", "None"):
        return []
    return [p.strip() for p in str(value).split(",") if p.strip()]


def _parse_floats(value: Any) -> List[float]:
    """Comma-string → lijst floats, niet-parsebare parts overgeslagen."""
    out: List[float] = []
    for p in _split_commas(value):
        try:
            out.append(float(p))
        except (ValueError, TypeError):
            continue
    return out


def _min_float(value: Any) -> float:
    """Minimum over alle comma-waarden — zwakste meting bepaalt de score."""
    vals = _parse_floats(value)
    return min(vals) if vals else np.nan


def _max_abs_value(value: Any) -> float:
    """Waarde met grootste absolute magnitude uit comma-list."""
    vals = _parse_floats(value)
    return max(vals, key=abs) if vals else np.nan


def _sum_float(value: Any) -> float:
    """Som van alle comma-waarden (totaal afgelegde draai over de bocht-lijst).
    Spiegelt `som_draaihoek` uit het dataprep-notebook."""
    vals = _parse_floats(value)
    return sum(vals) if vals else np.nan


def _latest_date(value: Any) -> Any:
    parts = _split_commas(value)
    return max(parts) if parts else np.nan


def _safe_col(df: pd.DataFrame, name: str) -> pd.Series:
    """Pak een kolom of geef een NaN-Series met dezelfde index terug."""
    return df[name] if name in df.columns else pd.Series(np.nan, index=df.index)


def build_segment_key(df: pd.DataFrame,
                      by_zijde: bool = True,
                      by_lttr:  bool = True) -> pd.Series:
    """Bouw een segment_key Series: `<weg>_<zijde>_<hectoletter>`.

    Altijd op snelwegnummer (of wegnr_hmp als fallback). Zijde en
    hectoletter worden alleen toegevoegd als hun flag aanstaat én de
    kolom bestaat. Eén waarheidsbron voor zowel `prepare_dataset` als
    `run_clustering`.
    """
    if "snelwegnummer" in df.columns:
        weg_id = (pd.to_numeric(df["snelwegnummer"], errors="coerce")
                  .astype("Int64").astype(str))
    else:
        weg_id = df.get("wegnr_hmp", "").astype(str)

    parts: List[pd.Series] = [weg_id]
    if by_zijde and "Zijde" in df.columns:
        parts.append(df["Zijde"].astype(str))
    if by_lttr and "hecto_lttr" in df.columns:
        parts.append(
            df["hecto_lttr"].fillna("").astype(str).str.strip().replace("", "RIJBAAN")
        )

    out = parts[0]
    for p in parts[1:]:
        out = out.str.cat(p, sep="_")
    return out


# ── 3. Afgeleide scores (alert + inspectie) ───────────────
def _alert_score(df: pd.DataFrame) -> pd.Series:
    """Parabool-score: piekt rond s≈2.7, beloont meerdere medium-lage
    inspectiescores. f(s) = (10-s)^2 * (s+1) / C met C = 5324/27."""
    C = 5324 / 27

    def _contrib(s) -> float:
        if pd.isna(s):
            return np.nan
        s = max(0.0, min(10.0, float(s)))
        return (10 - s) ** 2 * (s + 1) / C

    score_cols = ["_health_23", "_vis_23", "_health_25", "_vis_25"]
    contribs = pd.DataFrame({
        c: df[c].apply(_contrib) if c in df.columns
        else pd.Series(np.nan, index=df.index)
        for c in score_cols
    })
    return contribs.mean(axis=1, skipna=True).fillna(0).clip(0, 1)


def _build_inspectie(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    """Combineer alle inspectiescores (health+visibility, beide jaren) tot
    één lijst per rij + bereken het minimum."""
    score_cols = ["health_2023", "visibility_2023",
                  "health_2025", "visibility_2025"]
    str_cols = [
        df[c].fillna("").astype(str).tolist() if c in df.columns
        else [""] * len(df)
        for c in score_cols
    ]
    scores_list, min_list = [], []
    for row_vals in zip(*str_cols):
        parts: List[str] = []
        nums:  List[float] = []
        for s in row_vals:
            for p in _split_commas(s):
                if p in ("nan", "None"):
                    continue
                parts.append(p)
                try:
                    nums.append(float(p))
                except ValueError:
                    pass
        scores_list.append(", ".join(parts) if parts else None)
        min_list.append(min(nums) if nums else np.nan)
    return (pd.Series(scores_list, index=df.index),
            pd.Series(min_list, index=df.index))


# ── 4. Coördinaat-extractie (RD New) ─────────────────────
def _extract_coords(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    """Probeer x/y te lezen uit verschillende geometriebronnen.
    Volgorde: geometry x/y kolommen → hectopunt_rd_coordinaten string →
              hectopunt_geometry WKT."""
    # 1) Door _flatten_geodataframe achtergelaten kolommen
    for col in df.columns:
        if col.startswith("_geom_x_"):
            base = col[len("_geom_x_"):]
            y_col = f"_geom_y_{base}"
            if y_col in df.columns:
                return df[col].astype(float), df[y_col].astype(float)

    # 2) string-gebaseerde coordinaten "x,y"
    if "hectopunt_rd_coordinaten" in df.columns:
        coords = df["hectopunt_rd_coordinaten"].astype(str).str.split(",", expand=True)
        if coords.shape[1] >= 2:
            xs = pd.to_numeric(coords[0], errors="coerce")
            ys = pd.to_numeric(coords[1], errors="coerce")
            return xs, ys

    # 3) WKT in hectopunt_geometry
    if "hectopunt_geometry" in df.columns:
        def _wkt_xy(v):
            if pd.isna(v):
                return np.nan, np.nan
            try:
                s = str(v).strip()
                if s.upper().startswith("POINT"):
                    inside = s[s.index("(") + 1: s.index(")")].split()
                    return float(inside[0]), float(inside[1])
                if "MULTIPOINT" in s.upper():
                    head = s[s.index("(") + 1:]
                    head = head.replace("(", "").replace(")", "").split(",")[0]
                    parts = head.strip().split()
                    return float(parts[0]), float(parts[1])
            except Exception:
                return np.nan, np.nan
            return np.nan, np.nan

        xy = df["hectopunt_geometry"].apply(_wkt_xy)
        return (xy.apply(lambda t: t[0]).astype(float),
                xy.apply(lambda t: t[1]).astype(float))

    return pd.Series(np.nan, index=df.index), pd.Series(np.nan, index=df.index)


# ── 5. Orchestrator ──────────────────────────────────────
# `prepare_dataset` is de single entry point van het hele prep-blok.
# De stappen leven elk in een eigen `_prep_*` functie zodat ze
# zelfstandig leesbaar/uitbreidbaar zijn.
_NUMERIC_PELT_COLS: List[str] = [
    "aantal_bochten", "boogstraal", "totaal_voertuig",
    "klein_voertuig", "middel_voertuig", "lang_voertuig", "draaihoek",
]


def _prep_inspection_scores(df: pd.DataFrame) -> None:
    """Reduceer comma-string inspectie-cellen tot één min-waarde per cel
    en leid trend/min-helpers af."""
    df["_health_23"] = _safe_col(df, "health_2023").apply(_min_float)
    df["_health_25"] = _safe_col(df, "health_2025").apply(_min_float)
    df["_vis_23"]    = _safe_col(df, "visibility_2023").apply(_min_float)
    df["_vis_25"]    = _safe_col(df, "visibility_2025").apply(_min_float)

    df["_min_health"]     = df["_health_25"].fillna(df["_health_23"])
    df["_min_visibility"] = df["_vis_25"].fillna(df["_vis_23"])
    df["_health_trend"]   = df["_health_25"] - df["_health_23"]


def _classify_bocht(radius: float) -> str:
    if pd.isna(radius):
        return "Geen bocht"
    return "Scherp (<400m)" if radius < Settings.CURVE_THRESHOLD else "Flauw (≥400m)"


def _prep_geometry_traffic(df: pd.DataFrame) -> None:
    """Geometrie + verkeer helpers (max-hoek, boogstraal, %-zwaar, bocht-cat)."""
    df["_max_hoek"]   = _safe_col(df, "draaihoek").apply(_max_abs_value)
    # Som van alle draaihoeken in de rij — cluster-feature `hoek`. Voorkeur de
    # voorberekende `som_draaihoek`-kolom (dataprep-notebook); anders zelf
    # optellen uit de ruwe comma-lijst zodat geüploade datasets ook werken.
    if "som_draaihoek" in df.columns:
        df["_som_hoek"] = pd.to_numeric(df["som_draaihoek"], errors="coerce")
    else:
        df["_som_hoek"] = _safe_col(df, "draaihoek").apply(_sum_float)
    df["_boogstraal"] = pd.to_numeric(_safe_col(df, "boogstraal"), errors="coerce")
    # Comma-aware scherpste (= kleinste) boogstraal uit de ruwe comma-lijst.
    # Moet hier berekend worden: `_prep_pelt_features` coerce't `boogstraal`
    # later naive naar numeriek (NaN bij comma-cellen) — dan is de ruwe
    # lijst weg. Dit is de bron voor de cluster-feature `boogstraal_f`.
    df["_boogstraal_sharp"] = _safe_col(df, "boogstraal").apply(_min_float)
    df["_totaal_vt"]  = pd.to_numeric(_safe_col(df, "totaal_voertuig"), errors="coerce")
    df["_lang_vt"]    = pd.to_numeric(_safe_col(df, "lang_voertuig"), errors="coerce")
    df["_pct_zwaar"]  = (
        df["_lang_vt"] / df["_totaal_vt"].replace(0, np.nan) * 100
    ).round(1)
    df["_bocht_cat"] = df["_boogstraal"].apply(_classify_bocht)


def _prep_dates_age(df: pd.DataFrame) -> None:
    """Bouw aanleg-jaar, leeftijd (jr) en leeftijd-string."""
    if "aanlegdatum" in df.columns:
        dates = pd.to_datetime(df["aanlegdatum"].apply(_latest_date), errors="coerce")
    else:
        dates = pd.Series(pd.NaT, index=df.index)
    df["_aanleg_jaar"]  = dates.dt.year
    df["_leeftijd"]     = (pd.Timestamp.today() - dates).dt.days / 365.25
    df["_leeftijd_str"] = df["_leeftijd"].apply(
        lambda x: f"{x:.0f} jr" if pd.notna(x) else "unknown"
    )


def _prep_alert_and_inspection(df: pd.DataFrame) -> None:
    df["_alert_score"] = _alert_score(df)
    df["_inspectie_scores"], df["_inspectie_min"] = _build_inspectie(df)


def _prep_coords(df: pd.DataFrame) -> None:
    rd_x, rd_y = _extract_coords(df)
    df["_rd_x"] = rd_x
    df["_rd_y"] = rd_y


def _prep_pelt_features(df: pd.DataFrame) -> None:
    """PELT-numerieke kolommen. INSPECTION_COLS blijven raw (comma-strings);
    insp_score komt uit de afgeleide _health/_vis min-kolommen."""
    # Cluster-feature `onderhoudsmoment` (jaar) komt al voorberekend uit het
    # dataprep-notebook; hier alleen naar numeriek coercen zodat PELT ermee
    # kan rekenen. Vervangt de oude `aanlegdatum_ord`-feature.
    df["onderhoudsmoment"] = (
        pd.to_numeric(df["onderhoudsmoment"], errors="coerce")
        if "onderhoudsmoment" in df.columns else np.nan
    )
    # Voorberekende levensduur (onderhoudsinterval in jr) — numeriek voor tabel
    # + KPI-scores + levensduur-grafiek.
    if "levensduur" in df.columns:
        df["levensduur"] = pd.to_numeric(df["levensduur"], errors="coerce")
    for c in _NUMERIC_PELT_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    for c in Settings.INSPECTION_COLS:
        if c not in df.columns:
            df[c] = np.nan

    # Cluster-features uit comma-aware bronnen — NIET uit de naive-gecoerce'de
    # `draaihoek`/`boogstraal` (die zijn NaN bij multi-segment-cellen).
    #   hoek          = grootste |draai| over de comma-lijst (scherpste sweep)
    #   boogstraal_f  = kleinste straal over de comma-lijst (scherpste boog)
    df["hoek"]         = df["_som_hoek"].abs()
    df["boogstraal_f"] = df["_boogstraal_sharp"]
    df["verkeer"]      = df["totaal_voertuig"]
    # Zwaar verkeer als eigen cluster-feature: aandeel lang verkeer (%),
    # comma-veilig afgeleid (_lang_vt/_totaal_vt) in _prep_geometry_traffic.
    # Orthogonaal aan `verkeer` (totaal): een rustige weg met veel vrachtwagens
    # belast het deklaag zwaarder dan een drukke weg met louter personenauto's.
    df["verkeer_zwaar"] = df["_pct_zwaar"]
    df["insp_score"]   = df[["_health_23", "_health_25",
                             "_vis_23", "_vis_25"]].mean(axis=1)


def _prep_segment_and_sort(df: pd.DataFrame) -> pd.DataFrame:
    """Segment-key zetten en sorteren op netwerk-volgorde. Retourneert
    een nieuwe (gesorteerde) df met fresh index."""
    df["hecto_lttr"] = df.get("hecto_lttr", "").fillna("").astype(str).str.strip()
    df["segment_key"] = build_segment_key(df, by_zijde=True, by_lttr=True)
    if "hectomtrng" in df.columns:
        df["hectomtrng"] = pd.to_numeric(df["hectomtrng"], errors="coerce")

    sort_cols: List[str] = []
    if "snelwegnummer" in df.columns:
        sort_cols.append("snelwegnummer")
    elif "wegnr_hmp" in df.columns:
        sort_cols.append("wegnr_hmp")
    for c in ("Zijde", "hecto_lttr", "hectomtrng"):
        if c in df.columns:
            sort_cols.append(c)
    return df.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)


@st.cache_data(show_spinner=False)
def prepare_dataset(_df_in: pd.DataFrame, cache_key: str) -> pd.DataFrame:
    """Single entry point: ruwe pickle → dashboard-ready DataFrame.

    Gecached via Streamlit per `cache_key`. Idempotent — dezelfde input
    levert exact dezelfde output.
    """
    df = _df_in.copy()
    logger.info(f"prepare_dataset op {len(df):,} rijen, {len(df.columns)} kolommen")

    _prep_inspection_scores(df)
    _prep_geometry_traffic(df)
    _prep_dates_age(df)
    _prep_alert_and_inspection(df)
    _prep_coords(df)
    _prep_pelt_features(df)
    df = _prep_segment_and_sort(df)

    logger.info("prepare_dataset klaar — %d kolommen", len(df.columns))
    return df


# ╔══════════════════════════════════════════════════════════╗
# ║  END OF DATA PREPARATION                                 ║
# ╚══════════════════════════════════════════════════════════╝


# ============================================================
# FILTERS (sidebar widgets + apply_filters)
# ------------------------------------------------------------
# `apply_filters` voert ook een kleine data-prep stap uit: na het
# strippen van comma-waarden buiten het bereik wordt
# `_inspectie_scores` opnieuw afgeleid. Die stap blijft hier
# bewust omdat het filter-keuze afhankelijk is — kan niet vooraf
# in `prepare_dataset` gebeuren.
# ============================================================
_STRIP_FILTER_COLS: Dict[str, Tuple[str, str]] = {
    "health_2023":     ("health_2023",     "_health_23"),
    "visibility_2023": ("visibility_2023", "_vis_23"),
    "health_2025":     ("health_2025",     "_health_25"),
    "visibility_2025": ("visibility_2025", "_vis_25"),
}


def _unique_column_values(df: pd.DataFrame, column: str,
                          comma_separated: bool = False) -> List[str]:
    if column not in df.columns:
        return []
    result: Set[str] = set()
    for raw in df[column].dropna().astype(str):
        items = raw.split(",") if comma_separated else [raw]
        result.update(
            item.strip() for item in items
            if item.strip() and item.strip() != "None"
        )
    return sorted(result)


def _strip_outside_window(cell: Any, lo: float, hi: float) -> Any:
    """Houd alleen comma-waarden in [lo, hi]. De rij blijft staan; alleen
    waardes buiten het venster worden uit de cel verwijderd. Werkt op een
    kopie — de output-pickle op disk wordt nooit aangepast."""
    if pd.isna(cell) or str(cell).strip() in ("", "None"):
        return cell
    kept: List[str] = []
    for p in str(cell).split(","):
        p = p.strip()
        if not p:
            continue
        try:
            v = float(p)
        except (ValueError, TypeError):
            continue
        if lo <= v <= hi:
            kept.append(p)
    return ", ".join(kept) if kept else np.nan


def _cell_is_empty(cell: Any) -> bool:
    if pd.isna(cell) or str(cell).strip() in ("", "None"):
        return True
    return not any(p.strip() for p in str(cell).split(","))


def _numeric_range(df: pd.DataFrame, df_col: str) -> Optional[Tuple[float, float]]:
    """Return (min, max) of df[df_col] as floats, or None if column is
    missing, all-NaN, or degenerate (min == max)."""
    if df_col not in df.columns:
        return None
    col_data = pd.to_numeric(df[df_col], errors="coerce").dropna()
    if col_data.empty:
        return None
    lo, hi = float(col_data.min()), float(col_data.max())
    if lo == hi:
        return None
    return lo, hi


def sidebar_filters(df: pd.DataFrame) -> Dict[str, Any]:
    """Bouw alle filter-widgets in de sidebar en geef de specificatie terug.
    Filter wordt later toegepast met `apply_filters(df, spec)`."""
    # Kaartlaag-keuze bovenaan de sidebar (links), boven de filters: de kaart
    # is de enige view en heeft geen eigen keuze-knop meer onder de kaart.
    st.sidebar.markdown("### Kaartlaag")
    if st.session_state.get("map_heatmap_col") not in _MAP_HEATMAP_OPTIONS:
        st.session_state.pop("map_heatmap_col", None)
    st.sidebar.selectbox(
        "Kleur de kaart op basis van:",
        options=_MAP_HEATMAP_OPTIONS,
        index=_MAP_HEATMAP_OPTIONS.index(_MAP_HEATMAP_DEFAULT),
        format_func=_heatmap_option_label,
        key="map_heatmap_col",
    )
    # Achtergrondkaart-keuze verwijderd (gebruikersverzoek): kaart gebruikt
    # altijd de standaard (_BASEMAP_DEFAULT). De consumer in render_map_tab valt
    # met `.get("map_basemap", _BASEMAP_DEFAULT)` automatisch terug op de default.

    st.sidebar.markdown("### Filters")

    spec: Dict[str, Any] = {
        "info_search": "",
        "only_deklaag": True,
        "checkbox":    {},
        "range":       {},
    }

    # ── Globale reset — alle filters op min/max, geen exclusies ──
    def _reset_all_filters(_df=df):
        st.session_state["filter_info_search"] = ""
        # "Toon alle rijen" → ook de deklaagregistratie-filter uit.
        st.session_state["filter_only_deklaag"] = False
        for col, _lbl, comma_sep in Settings.CHECKBOX_FILTERS:
            for o in _unique_column_values(_df, col, comma_sep):
                st.session_state[f"cb_{col}_{o}"] = False
        for key, _lbl, df_col in Settings.RANGE_FILTERS:
            rng = _numeric_range(_df, df_col)
            if rng is None:
                continue
            st.session_state[f"rng_{key}"] = rng
            st.session_state[f"rng_{key}_excl_empty"] = False

    st.sidebar.button(
        "Reset alle filters (toon alle rijen)",
        key="filter_reset_all",
        on_click=_reset_all_filters,
        use_container_width=True,
    )

    # Deklaagregistratie-filter (default AAN) staat ín de "Deklagen"-expander
    # hieronder (gebruikersverzoek). Seed alvast de spec zodat de waarde ook
    # klopt als die expander uitzonderlijk niet rendert (geen deklaagsoort-opties).
    spec["only_deklaag"] = st.session_state.get("filter_only_deklaag", True)

    # Info zoek
    with st.sidebar.expander("Info zoeken", expanded=False):
        spec["info_search"] = st.text_input(
            "Zoekterm (in kolom `info`)",
            value="",
            key="filter_info_search",
            placeholder="Bv. 'remspoor' of 'rijstrook'…",
        )

    # Checkbox-filters
    for col, label, comma_sep in Settings.CHECKBOX_FILTERS:
        opts = _unique_column_values(df, col, comma_sep)
        if not opts:
            continue
        with st.sidebar.expander(label, expanded=False):
            if col == "deklaagsoort":
                # Deklaagregistratie-filter (default AAN): toon alleen hectopunten
                # waarvan een deklaag geregistreerd is (deklaagsoort ingevuld).
                # Punten zonder registratie missen aanlegdatum/levensduur en zijn
                # voor het onderhoudsmodel niet bruikbaar.
                spec["only_deklaag"] = st.checkbox(
                    "Alleen met deklaagregistratie",
                    value=True,
                    key="filter_only_deklaag",
                    help="Aan (default): verberg hectopunten zonder geregistreerde "
                         "deklaag (geen deklaagsoort/aanlegdatum). Uit: toon ook "
                         "die punten.",
                )
                st.divider()
            c1, c2 = st.columns(2)
            sel_all_key = f"sel_all_{col}"
            desel_all_key = f"desel_all_{col}"

            # toggle helpers via session_state
            if c1.button("Alle", key=sel_all_key, use_container_width=True):
                for o in opts:
                    st.session_state[f"cb_{col}_{o}"] = True
            if c2.button("Geen", key=desel_all_key, use_container_width=True):
                for o in opts:
                    st.session_state[f"cb_{col}_{o}"] = False

            selected: List[str] = []
            for o in opts:
                key = f"cb_{col}_{o}"
                if key not in st.session_state:
                    st.session_state[key] = False
                if st.checkbox(o, key=key):
                    selected.append(o)
            spec["checkbox"][col] = (selected, comma_sep)

    # Range-filters
    for key, label, df_col in Settings.RANGE_FILTERS:
        rng = _numeric_range(df, df_col)
        if rng is None:
            continue
        data_min, data_max = rng

        # Per-filter default — wordt alleen toegepast bij eerste laden.
        default_lo_raw, default_hi_raw, default_excl = \
            Settings.RANGE_DEFAULTS.get(key, (None, None, False))
        default_lo = max(data_min, default_lo_raw) if default_lo_raw is not None else data_min
        default_hi = min(data_max, default_hi_raw) if default_hi_raw is not None else data_max

        slider_key = f"rng_{key}"
        excl_key   = f"rng_{key}_excl_empty"

        # Initialiseer session_state één keer met defaults.
        if slider_key not in st.session_state:
            st.session_state[slider_key] = (default_lo, default_hi)
        if excl_key not in st.session_state:
            st.session_state[excl_key] = default_excl

        with st.sidebar.expander(label, expanded=False):
            lo, hi = st.slider(
                "Bereik",
                min_value=data_min, max_value=data_max,
                # /200 zodat de 0.05-ondergrens van de health-filters exact op een
                # stap valt (bereik 0–10 → stap 0.05); voorkomt slider-snapping.
                step=max((data_max - data_min) / 200.0, 0.01),
                key=slider_key,
            )
            exclude_empty = st.checkbox(
                "Verberg lege rijen (na strippen)",
                key=excl_key,
            )

            # Reset-knop — on_click callback past session_state aan vóór
            # de widgets opnieuw renderen. Default-args bevriezen de
            # waarden van DEZE iteratie zodat de loop ze niet overschrijft.
            def _reset(_sk=slider_key, _ek=excl_key,
                       _lo=default_lo, _hi=default_hi, _ex=default_excl):
                st.session_state[_sk] = (_lo, _hi)
                st.session_state[_ek] = _ex

            st.button(
                "Reset (min/max, uit)", key=f"reset_{key}",
                on_click=_reset,
                use_container_width=True,
            )

            spec["range"][key] = {
                "df_col":        df_col,
                "lo":            lo,
                "hi":            hi,
                "data_min":      data_min,
                "data_max":      data_max,
                "exclude_empty": exclude_empty,
                "is_strip":      key in _STRIP_FILTER_COLS,
            }

    return spec


def apply_filters(df: pd.DataFrame, spec: Dict[str, Any]) -> pd.DataFrame:
    df = df.copy()

    # ── Deklaagregistratie ───────────────────────────────────
    # Standaard alleen hectopunten met geregistreerde deklaag (deklaagsoort
    # ingevuld). Rij-niveau filter; cellen blijven ongemoeid.
    if spec.get("only_deklaag", False) and "deklaagsoort" in df.columns:
        df = df[~df["deklaagsoort"].apply(_cell_is_empty)]

    # ── Info zoek ─────────────────────────────────────────────
    term = (spec.get("info_search") or "").strip().lower()
    if term and "info" in df.columns:
        df = df[df["info"].astype(str).str.lower().str.contains(term, na=False)]

    # ── Checkbox-filters ─────────────────────────────────────
    for key, (selected, comma_sep) in spec.get("checkbox", {}).items():
        if not selected or key not in df.columns:
            continue
        if comma_sep:
            df = df[df[key].apply(
                lambda cell: pd.notna(cell) and
                any(p.strip() in selected for p in str(cell).split(","))
            )]
        else:
            df = df[df[key].astype(str).isin(selected)]

    # ── Range-filters ────────────────────────────────────────
    # Filteren werkt altijd op rij-niveau; de cellen in de output-dataset
    # worden nooit gemuteerd. Voor health/visibility wordt elke rij behouden
    # zodra minstens één van haar comma-waarden binnen [lo, hi] valt — zo
    # blijven alle originele scores per hectopunt zichtbaar.
    for key, rf in spec.get("range", {}).items():
        col = rf["df_col"]
        if col not in df.columns:
            continue
        lo, hi = rf["lo"], rf["hi"]
        slider_active = lo > rf["data_min"] or hi < rf["data_max"]

        if key in _STRIP_FILTER_COLS:
            raw_col, derived_col = _STRIP_FILTER_COLS[key]
            if raw_col not in df.columns:
                continue
            if slider_active:
                # Strip per cel: behoud alleen comma-waarden in [lo, hi].
                df[raw_col] = df[raw_col].apply(
                    lambda cell, _lo=lo, _hi=hi: _strip_outside_window(cell, _lo, _hi)
                )
                if derived_col in df.columns:
                    df[derived_col] = df[raw_col].apply(_min_float)
            if rf["exclude_empty"]:
                df = df[~df[raw_col].apply(_cell_is_empty)]
        else:
            numeric = pd.to_numeric(df[col], errors="coerce")
            if rf["exclude_empty"]:
                df      = df[numeric.notna()]
                numeric = numeric.reindex(df.index)
            if slider_active:
                df = df[(numeric >= lo) & (numeric <= hi)]

    # Inspectiescores-string opnieuw afleiden uit de (ongemuteerde) bronkolommen.
    df["_inspectie_scores"], df["_inspectie_min"] = _build_inspectie(df)
    return df.reset_index(drop=True)


def _summarize_filters(spec: Dict[str, Any]) -> str:
    """Korte, leesbare samenvatting van de actieve filters (voor het PDF-rapport)."""
    parts: List[str] = []
    if spec.get("only_deklaag"):
        parts.append("alleen met deklaagregistratie")
    term = (spec.get("info_search") or "").strip()
    if term:
        parts.append(f"info bevat '{term}'")
    for key, (selected, _cs) in spec.get("checkbox", {}).items():
        if selected:
            parts.append(f"{key}: {len(selected)} geselecteerd")
    for key, rf in spec.get("range", {}).items():
        active = (rf["lo"] > rf["data_min"] or rf["hi"] < rf["data_max"]
                  or rf["exclude_empty"])
        if active:
            seg = f"{key} {rf['lo']:.2g}–{rf['hi']:.2g}"
            if rf["exclude_empty"]:
                seg += " (lege verborgen)"
            parts.append(seg)
    return "; ".join(parts) if parts else "geen actieve filters (volledige dataset)"


# ============================================================
# PELT CLUSTERING
# ------------------------------------------------------------
# Algoritme + post-clustering rang-prep (`attach_cluster_severity`).
# Die laatste hoort niet in `prepare_dataset` omdat hij van het
# clustering-resultaat afhangt — dus single source of truth voor
# cluster-kleuring leeft hier.
# ============================================================
def _feature_fill_value(col: pd.Series, policy: str) -> float:
    """Vul-waarde voor ontbrekende cellen volgens `FEATURE_FILL_POLICY`."""
    if policy == "zero":
        return 0.0
    if policy == "max":
        v = col.max()
    elif policy == "min":
        v = col.min()
    else:  # "median"
        v = col.median()
    return float(v) if pd.notna(v) else 0.0


def _active_feats(df: pd.DataFrame, weights: Dict[str, float]) -> List[str]:
    """Features met gewicht > 0 die bestaan én minstens één waarde hebben."""
    return [
        f for f, w in weights.items()
        if w > 0 and f in df.columns and df[f].notna().any()
    ]


def _normalized_features(
    df: pd.DataFrame, feats: List[str]
) -> Tuple[pd.DataFrame, Dict[str, Tuple[float, float]]]:
    """Per-feature MinMax 0-1 normalisatie over de hele dataset.

    Elke kolom wordt onafhankelijk geschaald naar [0, 1] zodat de
    *absolute schaal* (b.v. 1 miljard voertuigen) wegvalt en alleen de
    slider-gewichten de bijdrage bepalen — navolgbaar en controleerbaar.
    Ontbrekende cellen worden semantisch ingevuld (`FEATURE_FILL_POLICY`)
    vóór het schalen. Retourneert (genormaliseerde df in [0,1], {feat: (lo, hi)}).
    """
    out: Dict[str, pd.Series] = {}
    bounds: Dict[str, Tuple[float, float]] = {}
    for f in feats:
        raw = pd.to_numeric(df[f], errors="coerce")
        policy = Settings.FEATURE_FILL_POLICY.get(f, "median")
        filled = raw.fillna(_feature_fill_value(raw, policy))
        lo, hi = float(filled.min()), float(filled.max())
        bounds[f] = (lo, hi)
        if hi > lo:
            norm = (filled - lo) / (hi - lo)
        else:
            # Constante kolom levert geen onderscheid → 0 (telt niet mee).
            norm = pd.Series(0.0, index=df.index)
        out[f] = norm.clip(0.0, 1.0)
    return pd.DataFrame(out, index=df.index), bounds


def build_feature_matrix(
    df: pd.DataFrame, weights: Dict[str, float]
) -> Tuple[np.ndarray, List[str]]:
    """Bouw de gewogen, op 0-1 genormaliseerde feature-matrix voor PELT.

    Elke feature wordt eerst MinMax naar [0, 1] geschaald (zie
    `_normalized_features`) en dan vermenigvuldigd met zijn slider-gewicht.
    Daardoor ligt de bijdrage van een feature in [0, w_f] en bepaalt
    *alleen* het gewicht hoe zwaar hij meeweegt — niet de ruwe magnitude.

    Output is altijd 2D met shape (n, d) — ook bij d=1 — zodat downstream
    code (PELT, np.diff, ruptures) eenduidig kan rekenen.
    """
    feats = _active_feats(df, weights)
    if not feats:
        return np.empty((len(df), 0)), feats

    Xn, _ = _normalized_features(df, feats)
    Xw = Xn.values * np.array([weights[f] for f in feats])
    if Xw.ndim == 1:
        Xw = Xw.reshape(-1, 1)
    return np.ascontiguousarray(Xw, dtype=float), feats


def feature_goodness(df: pd.DataFrame, weights: Dict[str, float]) -> pd.Series:
    """Per-hectopunt gewogen 0-1 'goedheid' (1 = groen/goed, 0 = rood/slecht).

    Dit is de *single source of truth* voor de heatmap-ernst: de score is
    een gewogen gemiddelde van de op 0-1 genormaliseerde features, elk
    georiënteerd via `FEATURE_GOOD_DIRECTION` zodat hoog altijd 'goed' is.

        goodness = Σ_f  w_f · oriented_norm_f   /   Σ_f w_f

    Omdat alle features op dezelfde [0,1]-schaal staan en de oriëntatie
    expliciet is, is de score volledig terug te rekenen naar de sliders.
    """
    feats = _active_feats(df, weights)
    if not feats:
        return pd.Series(np.nan, index=df.index)

    Xn, _ = _normalized_features(df, feats)
    num = pd.Series(0.0, index=df.index)
    wsum = 0.0
    for f in feats:
        direction = Settings.FEATURE_GOOD_DIRECTION.get(f, +1)
        good = Xn[f] if direction > 0 else (1.0 - Xn[f])
        num = num + weights[f] * good
        wsum += weights[f]
    if wsum <= 0:
        return pd.Series(np.nan, index=df.index)
    return (num / wsum).clip(0.0, 1.0)


def _as_2d(sub: np.ndarray) -> np.ndarray:
    """Garandeer dat `sub` 2D is. Met 1 feature komt het soms binnen als 1D."""
    if sub.ndim == 1:
        return sub.reshape(-1, 1)
    return sub


def _fallback_changepoints(sub: np.ndarray, penalty: float) -> List[int]:
    """Eenvoudige fallback wanneer `ruptures` niet geïnstalleerd is."""
    sub = _as_2d(sub)
    if len(sub) < 2:
        return [len(sub)]
    d = np.linalg.norm(np.diff(sub, axis=0), axis=1)
    if d.size == 0:
        return [len(sub)]
    thr = d.mean() + (penalty / 4.0) * d.std()
    bkps = list(np.where(d > thr)[0] + 1)
    bkps.append(len(sub))
    return bkps


# Boven deze drempel schakelt `pelt_segment` automatisch over op `l2`
# voor RBF-aanvragen, omdat rbf kwadratisch geheugen vraagt (n×n kernel)
# en daardoor "blijft hangen" bij lange segmenten — met name als de
# gebruiker maar 1 feature kiest en alle hectoletters/zijdes samenneemt.
_RBF_SAFE_LIMIT = 4000


def pelt_segment(
    sub: np.ndarray,
    penalty: float,
    model: str,
    min_size: int,
    max_clusters_per_segment: Optional[int],
) -> List[int]:
    """Voer PELT uit op één segment, geef breakpoints terug incl. len(sub)."""
    sub = _as_2d(sub)
    n = len(sub)
    if n < 2 * max(1, min_size):
        return [n]

    # RBF heeft O(n²) kernel-matrix → bij heel lange segmenten downgraden
    # naar l2 zodat de UI niet hangt. l2 detecteert dezelfde mean-shifts
    # die in 1D feature-ruimte vrijwel altijd het signaal zijn.
    effective_model = model
    if model == "rbf" and n > _RBF_SAFE_LIMIT:
        effective_model = "l2"

    if HAS_RUPTURES:
        try:
            algo = rpt.Pelt(model=effective_model,
                            min_size=max(1, min_size)).fit(sub)
            bkps = algo.predict(pen=penalty)
        except Exception:
            bkps = _fallback_changepoints(sub, penalty)
    else:
        bkps = _fallback_changepoints(sub, penalty)

    # Zorg dat de laatste breakpoint altijd n is (ruptures-contract).
    if not bkps or bkps[-1] != n:
        bkps = [b for b in bkps if b < n] + [n]

    if max_clusters_per_segment and len(bkps) > max_clusters_per_segment:
        d = np.linalg.norm(np.diff(sub, axis=0), axis=1)
        candidate_pos = np.array(bkps[:-1])
        if len(candidate_pos) > 0:
            jumps = d[np.clip(candidate_pos - 1, 0, len(d) - 1)]
            keep_idx = candidate_pos[
                np.argsort(jumps)[::-1][: max_clusters_per_segment - 1]
            ]
            bkps = sorted({int(p) for p in keep_idx}) + [n]

    return bkps


def _position_codes(hm: np.ndarray, seg: Optional[np.ndarray] = None) -> np.ndarray:
    """Positie-code per element: opeenvolgende rijen met dezelfde hectomtrng
    (en hetzelfde segment) krijgen dezelfde code → parallelle banen (L/R,
    meerdere hectoletters) tellen als ÉÉN positie langs de weg. NaN-hectomtrng
    krijgt elk een unieke code zodat onbekende posities niet samenvloeien.
    Aanname: de input is al gesorteerd op (segment, hectomtrng)."""
    n = len(hm)
    codes = np.empty(n, dtype=np.int64)
    cur = -1
    prev_hm: Optional[float] = None
    prev_seg: Any = None
    for i in range(n):
        v = hm[i]
        s = seg[i] if seg is not None else None
        if v is None or (isinstance(v, float) and np.isnan(v)):
            cur += 1               # unieke code → nooit mergen
            codes[i] = cur
            prev_hm, prev_seg = None, s
            continue
        if prev_hm is None or v != prev_hm or s != prev_seg:
            cur += 1
            prev_hm, prev_seg = v, s
        codes[i] = cur
    return codes


def cluster_dataframe(
    df: pd.DataFrame,
    Xw: np.ndarray,
    penalty: float,
    model: str,
    min_size: int,
    max_clusters_per_segment: Optional[int],
    respect_segment_key: bool,
    aggregate_positions: bool = True,
) -> np.ndarray:
    """Ken cluster-id's toe per rij.

    `aggregate_positions` collapst rijen met dezelfde (segment, hectomtrng)
    tot één PELT-positie vóór de changepoint-detectie. Daardoor worden L- en
    R-banen (of meerdere hectoletters) op dezelfde hectometer als één
    *parallelle* netwerkpositie behandeld i.p.v. als opeenvolgende punten —
    ze belanden dan altijd in hetzelfde cluster, ook al wisselt de kwaliteit
    per kant. Welke kolommen samen één positie vormen volgt automatisch uit
    `segment_key`: staat 'Splits per Zijde' aan, dan zit Zijde al in de key en
    blijven L/R gescheiden; staat hij uit, dan vallen ze samen.
    """
    Xw = _as_2d(Xw) if Xw.size else Xw
    cluster_ids = np.zeros(len(df), dtype=int)
    next_id = 0

    if not respect_segment_key:
        groups = {"_ALL_": np.arange(len(df))}
    else:
        groups = {k: np.array(idx) for k, idx in df.groupby("segment_key").groups.items()}

    feat_dim = Xw.shape[1] if Xw.ndim == 2 else 0
    hm_all = (pd.to_numeric(df["hectomtrng"], errors="coerce").to_numpy()
              if aggregate_positions and "hectomtrng" in df.columns else None)
    seg_all = (df["segment_key"].to_numpy()
               if aggregate_positions and "segment_key" in df.columns else None)

    for _, idx in groups.items():
        if len(idx) == 0:
            continue
        if feat_dim == 0:
            cluster_ids[idx] = next_id
            next_id += 1
            continue

        sub = Xw[idx]
        if len(sub) == 1:
            cluster_ids[idx] = next_id
            next_id += 1
            continue

        if hm_all is not None:
            # Collapse naar parallelle posities, PELT over de positie-reeks,
            # cluster-id daarna terug-mappen naar álle rijen van die positie.
            pos_codes = _position_codes(
                hm_all[idx], seg_all[idx] if seg_all is not None else None)
            order = pd.unique(pos_codes)
            pos_means = np.vstack([sub[pos_codes == c].mean(axis=0) for c in order])
            bkps = pelt_segment(pos_means, penalty, model, min_size,
                                max_clusters_per_segment)
            code_to_id: Dict[Any, int] = {}
            start = 0
            for b in bkps:
                for j in range(start, b):
                    code_to_id[order[j]] = next_id
                next_id += 1
                start = b
            for local, c in enumerate(pos_codes):
                cluster_ids[idx[local]] = code_to_id[c]
        else:
            bkps = pelt_segment(sub, penalty, model, min_size,
                                max_clusters_per_segment)
            start = 0
            for b in bkps:
                cluster_ids[idx[start:b]] = next_id
                next_id += 1
                start = b

    return cluster_ids


def find_penalty_for_target_k(
    df: pd.DataFrame,
    Xw: np.ndarray,
    target_k: int,
    model: str,
    min_size: int,
    respect_segment_key: bool,
    lo: float = 0.1,
    hi: float = 500.0,
    iters: int = 25,
    tolerance: int = 0,
) -> Tuple[float, int]:
    """Binary search op penalty om in de buurt van `target_k` clusters te komen."""
    best: Tuple[Optional[float], Optional[int], float] = (None, None, float("inf"))
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        cids = cluster_dataframe(
            df, Xw, penalty=mid, model=model, min_size=min_size,
            max_clusters_per_segment=None,
            respect_segment_key=respect_segment_key,
        )
        k = int(pd.Series(cids).nunique())
        diff = abs(k - target_k)
        if diff < best[2]:
            best = (mid, k, diff)
        if diff <= tolerance:
            return mid, k
        if k > target_k:
            lo = mid
        else:
            hi = mid
    return float(best[0]) if best[0] is not None else 1.0, int(best[1] or 0)


def attach_cluster_severity(df: pd.DataFrame,
                            weights: Optional[Dict[str, float]] = None
                            ) -> pd.DataFrame:
    """Voeg `cluster_score` + `cluster_rank_pct` toe als kolommen — de single
    source of truth voor de heatmap-kleuring. Alle views (NL-kaart, diagnose,
    QGIS) lezen ALLEEN deze kolommen, geen view berekent zelf nog ranks.

    Met `weights` (PELT) is `cluster_score` het cluster-gemiddelde van de
    gewogen 0-1 feature-goedheid (`feature_goodness`), en is `cluster_rank_pct`
    diezelfde **absolute** 0-1 score (1 = groen/goed, 0 = rood/slecht). De
    kleur wordt dus rechtstreeks door de slider-gewichten bepaald en is exact
    terug te rekenen. Zonder weights valt het terug op de oude inspectie-rang.
    """
    if weights:
        df["_point_goodness"] = feature_goodness(df, weights)
        cluster_score = df.groupby("cluster")["_point_goodness"].mean()
        df["cluster_score"] = df["cluster"].map(cluster_score)
        # KLEUR: rek de absolute scores uit naar de volle 0-1 (min-max) zodat
        # het SLECHTSTE cluster rood en het BESTE groen wordt. De ruwe gewogen
        # score ligt vaak in een smalle hoge band (b.v. 0.5-0.95) → zonder
        # uitrekken kleurt de kaart bijna uniform groen. Zelfde uitrek-methode
        # als alle andere heatmap-lagen. De absolute score blijft in
        # `cluster_score` staan voor navolgbaarheid (tooltip/diagnose-tabel).
        color_pct = pd.Series(np.nan, index=cluster_score.index)
        valid = cluster_score.dropna()
        lo, hi = (float(valid.min()), float(valid.max())) if len(valid) else (0.0, 0.0)
        if len(valid) >= 2 and hi > lo:
            color_pct.loc[valid.index] = (valid - lo) / (hi - lo)
        elif len(valid) >= 1:
            color_pct.loc[valid.index] = 0.5
        df["cluster_rank_pct"] = df["cluster"].map(color_pct).clip(0.0, 1.0)
        return df

    cluster_score = df.groupby("cluster")["insp_score"].mean()
    rank_pct = pd.Series(np.nan, index=cluster_score.index, name="rank_pct")
    valid = cluster_score.dropna()
    if len(valid) >= 2:
        ranks = valid.rank(method="dense", ascending=True)
        n = float(ranks.max())
        rank_pct.loc[valid.index] = (ranks - 1.0) / (n - 1.0)
    elif len(valid) == 1:
        rank_pct.loc[valid.index] = 0.5

    df["cluster_score"]    = df["cluster"].map(cluster_score)
    df["cluster_rank_pct"] = df["cluster"].map(rank_pct)
    return df


# ============================================================
# DIAGNOSE — één hectopunt door de pipeline volgen
# ============================================================
def diagnose_point(
    df: pd.DataFrame,
    Xw: np.ndarray,
    used_feats: List[str],
    weights: Dict[str, float],
    point_idx: int,
    window: int = 5,
) -> Dict[str, Any]:
    """Bouw een diagnose-bundle voor één hectopunt op rij-index `point_idx`."""
    out: Dict[str, Any] = {"used_feats": used_feats}
    if not used_feats:
        return out

    seg_key = df.iloc[point_idx]["segment_key"]
    seg_idx = df.index[df["segment_key"] == seg_key].to_numpy()
    pos = int(np.where(seg_idx == point_idx)[0][0])
    lo, hi = max(0, pos - window), min(len(seg_idx), pos + window + 1)
    win_idx = seg_idx[lo:hi]

    Xn_full, bounds = _normalized_features(df, used_feats)

    raw_P = df.loc[point_idx, used_feats]
    filled_vals: Dict[str, float] = {}
    for f in used_feats:
        col = pd.to_numeric(df[f], errors="coerce")
        fillv = _feature_fill_value(col, Settings.FEATURE_FILL_POLICY.get(f, "median"))
        rv = pd.to_numeric(pd.Series([raw_P[f]]), errors="coerce").iloc[0]
        filled_vals[f] = fillv if pd.isna(rv) else float(rv)
    raw_P_filled = pd.Series(filled_vals)

    lo_P     = pd.Series({f: bounds[f][0] for f in used_feats})
    hi_P     = pd.Series({f: bounds[f][1] for f in used_feats})
    norm_P   = Xn_full.loc[point_idx, used_feats]           # 0-1 per feature
    w_series = pd.Series({f: weights.get(f, 0.0) for f in used_feats})
    y_P      = norm_P * w_series                            # bijdrage in afstand
    good_P   = pd.Series({
        f: (norm_P[f] if Settings.FEATURE_GOOD_DIRECTION.get(f, +1) > 0
            else 1.0 - norm_P[f])
        for f in used_feats
    })

    Xw_2d = _as_2d(Xw) if Xw.size else Xw
    Y_win = Xw_2d[win_idx]
    dist_win = (
        np.linalg.norm(np.diff(Y_win, axis=0), axis=1)
        if len(Y_win) > 1 else np.array([])
    )

    Y_seg = Xw_2d[seg_idx]
    dist_seg = (
        np.linalg.norm(np.diff(Y_seg, axis=0), axis=1)
        if len(Y_seg) > 1 else np.array([])
    )

    pca_explained = None
    if Y_seg.shape[0] >= 2 and Y_seg.shape[1] >= 2:
        from sklearn.decomposition import PCA
        pca = PCA(n_components=2)
        Y_seg_2d = pca.fit_transform(Y_seg)
        pca_explained = pca.explained_variance_ratio_
    elif Y_seg.shape[1] >= 1:
        Y_seg_2d = np.column_stack([Y_seg[:, 0], np.zeros(len(Y_seg))])
    else:
        Y_seg_2d = np.zeros((len(Y_seg), 2))

    out.update(
        segment_key=seg_key, seg_idx=seg_idx, pos_in_seg=pos,
        seg_len=len(seg_idx), win_idx=win_idx, win_offset=lo,
        raw_P=raw_P, raw_P_filled=raw_P_filled,
        lo=lo_P, hi=hi_P, norm_P=norm_P, good_P=good_P, y_P=y_P,
        weights=w_series, Y_win=Y_win, dist_win=dist_win,
        Y_seg=Y_seg, dist_seg=dist_seg,
        Y_seg_2d=Y_seg_2d, pca_explained=pca_explained,
    )
    return out


def plot_segment_diagnose(diag: Dict[str, Any], df: pd.DataFrame) -> Figure:
    """Twee plots: (1) hectopunten langs segment, (2) 2D PCA-projectie.
    Leest cluster-kleuren uit pipeline-kolommen — geen eigen rangberekening."""
    from matplotlib.lines import Line2D

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    seg_idx = diag["seg_idx"]
    sub = df.loc[seg_idx]

    hm = sub["hectomtrng"].to_numpy()
    Y_seg = np.vstack([diag["Y_seg_2d"]])
    clusters_seg = sub["cluster"].to_numpy()
    pos = diag["pos_in_seg"]

    point_pct = sub["cluster_rank_pct"].to_numpy()
    pct_by_cluster = _cluster_pct_lookup(sub)
    score_by_cluster = (
        sub.drop_duplicates("cluster")
           .set_index("cluster")["cluster_score"]
           .to_dict()
    )

    def _label_for(cl: int) -> str:
        s = score_by_cluster.get(int(cl))
        if s is None or (isinstance(s, float) and np.isnan(s)):
            return f"cluster {int(cl)}"
        return f"cluster {int(cl)} (score {float(s):.2f})"

    def _color_for(cl: int):
        return _cluster_color(cl, pct_by_cluster)

    # Plot 1: ingezoomde kaart van het wegsegment — hectopunten op hun
    # WERKELIJKE RD-coördinaten, gekleurd op cluster-ernst, op een PDOK-basemap.
    # Zo zie je ruimtelijk (op het snelwegennet) welke secties goed/slecht zijn
    # i.p.v. een abstracte 1D-as (gebruikersverzoek).
    sc = None
    xs_ser, ys_ser = _extract_coords(sub)
    xs = pd.to_numeric(xs_ser, errors="coerce").to_numpy()
    ys = pd.to_numeric(ys_ser, errors="coerce").to_numpy()
    valid = np.isfinite(xs) & np.isfinite(ys)
    if valid.sum() >= 2:
        vx, vy = xs[valid], ys[valid]
        cx, cy = float((vx.min() + vx.max()) / 2), float((vy.min() + vy.max()) / 2)
        # Vierkant venster + marge; ondergrens zodat een kort segment niet
        # absurd ver inzoomt.
        span = max(float(vx.max() - vx.min()), float(vy.max() - vy.min()), 1500.0)
        half = span * 1.25 / 2.0
        axes[0].set_xlim(cx - half, cx + half)
        axes[0].set_ylim(cy - half, cy + half)
        axes[0].set_aspect("equal")
        # PDOK-basemap onder de punten (crisp, ingezoomd). Faalt netjes terug op
        # géén basemap als contextily / het netwerk niet beschikbaar is.
        if _CTX_OK:
            try:
                ctx.add_basemap(axes[0], crs="EPSG:28992", source=_PDOK_URL,
                                attribution=False)
            except Exception as exc:
                logger.warning(f"Diagnose-basemap mislukt: {exc}")
            axes[0].set_xlim(cx - half, cx + half)   # zoom vasthouden na imshow
            axes[0].set_ylim(cy - half, cy + half)
        # Wegverloop als dunne lijn (punten staan in hectomtrng-volgorde).
        axes[0].plot(xs[valid], ys[valid], color="#555", lw=0.8, alpha=0.6,
                     zorder=3)
        sc = axes[0].scatter(
            xs[valid], ys[valid], s=42, c=point_pct[valid],
            cmap="RdYlGn", vmin=0.0, vmax=1.0, alpha=0.95,
            edgecolors="white", linewidths=0.5, zorder=4,
        )
        if valid[pos]:                               # P op werkelijke locatie
            axes[0].scatter([xs[pos]], [ys[pos]], s=170, facecolors="none",
                            edgecolors="black", linewidths=2, zorder=6)
        # Clustergrenzen: zwart ruitje op het midden tussen twee opeenvolgende
        # punten waar de cluster wisselt.
        bnd = np.where(np.diff(clusters_seg) != 0)[0]
        for b in bnd:
            if valid[b] and valid[b + 1]:
                mx, my = (xs[b] + xs[b + 1]) / 2.0, (ys[b] + ys[b + 1]) / 2.0
                axes[0].scatter([mx], [my], s=55, marker="D", c="black",
                                zorder=7)
        axes[0].set_xticks([])
        axes[0].set_yticks([])
        axes[0].set_title(f"Segment {diag['segment_key']} — locatie op het wegennet")
    else:
        # Fallback: geen coördinaten → oude 1D-weergave langs hectomtrng.
        if len(hm) > 1:
            sc = axes[0].scatter(
                hm, np.zeros(len(hm)), s=30,
                c=point_pct, cmap="RdYlGn", vmin=0.0, vmax=1.0, alpha=0.85,
            )
            axes[0].scatter(
                [hm[pos]], [0], s=140, facecolors="none", edgecolors="black",
                linewidths=2, zorder=5,
            )
            bnd = np.where(np.diff(clusters_seg) != 0)[0]
            for b in bnd:
                x0 = (hm[b] + hm[b + 1]) / 2.0
                axes[0].axvline(x0, color="black", lw=0.7, ls="--", alpha=0.5)
        axes[0].set_yticks([])
        axes[0].set_xlabel("hectomtrng (langs de weg)")
        axes[0].set_title(f"Segment {diag['segment_key']} — cluster-toewijzing")

    cluster_handles = [
        Line2D([], [], marker="o", linestyle="", markersize=7,
               color=_color_for(int(cl)), label=_label_for(int(cl)))
        for cl in np.unique(clusters_seg)
    ]
    p_handle = Line2D([], [], marker="o", mfc="none", mec="black",
                      linestyle="", mew=2, markersize=10, label="P (gekozen)")

    # Plot 2: 2D PCA
    sc2 = axes[1].scatter(
        Y_seg[:, 0], Y_seg[:, 1], s=25,
        c=point_pct, cmap="RdYlGn", vmin=0.0, vmax=1.0, alpha=0.85,
    )
    axes[1].scatter(
        [Y_seg[pos, 0]], [Y_seg[pos, 1]], s=180,
        facecolors="none", edgecolors="black", linewidths=2, zorder=5,
    )
    pca_var = diag.get("pca_explained")
    if pca_var is not None:
        axes[1].set_xlabel(f"PC1 ({pca_var[0] * 100:.0f}% var)")
        axes[1].set_ylabel(f"PC2 ({pca_var[1] * 100:.0f}% var)")
    else:
        axes[1].set_xlabel("y₁ (gewogen, 0-1 genormaliseerd)")
        axes[1].set_ylabel("y₂")
    axes[1].set_title("Feature-ruimte (2D PCA-projectie van gewogen vectoren)")
    axes[1].grid(alpha=0.3)

    cbar_target = sc2 if sc2 is not None else sc
    if cbar_target is not None:
        cbar = fig.colorbar(
            cbar_target, ax=axes[1], fraction=0.04, pad=0.02,
            ticks=[0.0, 0.5, 1.0],
        )
        cbar.ax.set_yticklabels(["slechtste", "midden", "beste"])
        cbar.set_label("Cluster-ernst (gewogen score, uitgerekt slechtste→beste)")

    # Eén gedeelde legenda ONDER beide plots, horizontaal uitgespreid. Bij veel
    # clusters voorkomt dit dat de per-as-legenda de scatterplots overlapt; de
    # breedte-indeling (ncol) houdt 'm laag i.p.v. een lange smalle kolom.
    handles = cluster_handles + [p_handle]
    ncol = min(len(handles), 6)
    nrow = -(-len(handles) // ncol)
    fig.tight_layout(rect=[0, 0.03 + 0.05 * nrow, 1, 1])
    fig.legend(handles=handles, loc="lower center", ncol=ncol, fontsize=7,
               framealpha=0.9, borderaxespad=0.3, handletextpad=0.4,
               columnspacing=1.1, bbox_to_anchor=(0.5, 0.0))
    return fig


def plot_pelt_score_diagnose(
    diag: Dict[str, Any],
    df: pd.DataFrame,
    penalty: Optional[float] = None,
) -> Figure:
    """PELT-score per hectopunt: ‖y_i − y_{i-1}‖ uitgezet tegen hectomtrng.

    Dit is precies het signaal dat PELT *ziet* tijdens changepoint-
    detectie. Hoge pieken = mogelijke clustergrens; β bepaalt hoe hoog
    een piek moet zijn om een echte breuk te worden. Verticale rode
    lijnen markeren de daadwerkelijk gekozen breuken.
    """
    seg_idx = diag["seg_idx"]
    sub = df.loc[seg_idx].reset_index(drop=True)
    hm = sub["hectomtrng"].to_numpy()
    clusters_seg = sub["cluster"].to_numpy()
    pos = diag["pos_in_seg"]
    dist_seg = diag.get("dist_seg", np.array([]))

    fig, ax = plt.subplots(figsize=(13, 4.5))

    pct_by_cluster = _cluster_pct_lookup(sub)

    def _color_for(cl: int):
        return _cluster_color(cl, pct_by_cluster)

    if len(dist_seg) == 0 or len(hm) < 2:
        ax.text(0.5, 0.5,
                "Segment heeft te weinig punten voor een score-plot.",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return fig

    # Een 'jump' hoort bij de overgang van punt i−1 naar punt i.
    # We tekenen elke staaf op de x-positie van punt i (de rechter-buur).
    x_jump = hm[1:]
    colors = [_color_for(int(cl)) for cl in clusters_seg[1:]]

    bar_width = 0.7
    if len(x_jump) > 1:
        gaps = np.diff(np.sort(x_jump))
        gaps = gaps[gaps > 0]
        if gaps.size:
            bar_width = float(np.median(gaps)) * 0.8

    ax.bar(x_jump, dist_seg, width=bar_width, color=colors,
           edgecolor="#444", linewidth=0.3, zorder=2)

    # Cluster-grenzen — verticale rode lijnen waar PELT échte breuken zette.
    bnd = np.where(np.diff(clusters_seg) != 0)[0]
    for j, b in enumerate(bnd):
        x0 = (hm[b] + hm[b + 1]) / 2.0
        ax.axvline(x0, color="#c0392b", lw=1.6, ls="--", alpha=0.9,
                   zorder=4, label="cluster-grens" if j == 0 else None)
        ax.text(x0, ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 1.0,
                f"  {int(clusters_seg[b])}→{int(clusters_seg[b + 1])}",
                color="#c0392b", fontsize=7, va="top", ha="left",
                rotation=90, alpha=0.9)

    # Markeer P
    if 0 <= pos < len(hm):
        ax.axvline(hm[pos], color="black", lw=1.0, ls=":", alpha=0.6,
                   zorder=3, label="P (gekozen punt)")

    # Statistische referentie-lijnen
    mu_d = float(np.mean(dist_seg))
    ax.axhline(mu_d, color="#2c3e50", lw=0.8, alpha=0.6,
               label=f"gemiddelde jump = {mu_d:.2f}")

    # Penalty β als referentie — niet 1-op-1 een drempel op één jump
    # (PELT optimaliseert globaal), maar wel een nuttige schaal.
    if penalty is not None:
        ax.axhline(float(penalty), color="#2980b9", lw=0.8, ls="-.",
                   alpha=0.6, label=f"β (penalty) = {penalty:.2f}")

    # Top-3 hoogste jumps annoteren
    if len(dist_seg) >= 1:
        top = np.argsort(dist_seg)[::-1][:3]
        for k in top:
            ax.annotate(
                f"{dist_seg[k]:.2f}",
                xy=(x_jump[k], dist_seg[k]),
                xytext=(0, 5), textcoords="offset points",
                ha="center", fontsize=7, color="#222",
            )

    ax.set_xlabel("hectomtrng (langs de weg)")
    ax.set_ylabel(r"PELT-score:  $\|y_i - y_{i-1}\|$  (gewogen feature-afstand)")
    ax.set_title(
        f"Segment {diag['segment_key']} — PELT-score per hectopunt "
        f"(N = {len(hm)}, {int(pd.Series(clusters_seg).nunique())} clusters)"
    )
    ax.grid(alpha=0.25, zorder=1)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    fig.tight_layout()
    return fig


# ============================================================
# CHARTS — kaarten, KDE, bocht × health
# ------------------------------------------------------------
# Plot-functies + thema + chart-registry voor de Grafieken-tab
# en voor "Genereer alles" naar `Output/chart_*.png`.
# ============================================================
@dataclass
class ChartTheme:
    bg:      str
    axes_bg: str
    fg:      str
    grid:    str

    @staticmethod
    def light() -> "ChartTheme":
        return ChartTheme("#F8F9FB", "#FFFFFF", "#222222", "#cccccc")


CHART_THEME = ChartTheme.light()
SCORE_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "score_rg", ["#d73027", "#fee08b", "#1a9850"]
)
RDYLGN_CMAP = plt.get_cmap("RdYlGn")
RDYLGN_R_CMAP = plt.get_cmap("RdYlGn_r")
_BOCHT_CAT_ORDER:  List[str] = ["Geen bocht", "Flauw (≥400m)", "Scherp (<400m)"]
_BOCHT_CAT_COLORS: List[str] = ["#888888",    "#3498db",        "#e74c3c"]


def _cluster_pct_lookup(sub: pd.DataFrame) -> Dict[int, float]:
    """cluster -> rank_pct dict, NaN-rows dropped."""
    return (
        sub.dropna(subset=["cluster_rank_pct"])
           .drop_duplicates("cluster")
           .set_index("cluster")["cluster_rank_pct"]
           .to_dict()
    )


def _cluster_color(cl: int, pct_by_cluster: Dict[int, float],
                   alpha: float = 0.85) -> Tuple[float, float, float, float]:
    """RGBA color for a cluster id from its rank percentile; grey if missing."""
    p = pct_by_cluster.get(int(cl))
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return (0.6, 0.6, 0.6, alpha)
    rgba = list(RDYLGN_CMAP(float(p)))
    rgba[3] = alpha
    return tuple(rgba)
_PDOK_URL = (
    "https://service.pdok.nl/brt/achtergrondkaart/wmts/v2_0"
    "/standaard/EPSG:3857/{z}/{x}/{y}.png"
)
# PDOK luchtfoto (RGB ortho 25 cm, Actueel = nieuwste vlucht) — gebruikt als
# achtergrond in de dashboard-kaart én voor de ingezoomde PDF-landschapskaart.
_PDOK_LUCHTFOTO_URL = (
    "https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0/Actueel_ortho25"
    "/EPSG:3857/{z}/{x}/{y}.jpeg"
)

# Keuze-achtergrond voor de interactieve kaart (selectbox in de sidebar).
# CORS-vriendelijke raster-tegels die deck.gl's TileLayer betrouwbaar laadt.
# (PDOK WMTS gaf in de browser vaak geen tegels → kaart leek onveranderd.)
_BASEMAP_SOURCES: List[Tuple[str, str]] = [
    ("Topografisch (OpenStreetMap)",
     "https://tile.openstreetmap.org/{z}/{x}/{y}.png"),
    ("Luchtfoto (Esri World Imagery)",
     "https://server.arcgisonline.com/ArcGIS/rest/services/"
     "World_Imagery/MapServer/tile/{z}/{y}/{x}"),
    ("Wegenkaart (Carto Voyager)",
     "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"),
]
_BASEMAP_DEFAULT = "Topografisch (OpenStreetMap)"


def _style_axes(ax, theme: ChartTheme = CHART_THEME, show_grid: bool = True) -> None:
    ax.set_facecolor(theme.axes_bg)
    for spine in ax.spines.values():
        spine.set_edgecolor(theme.grid)
    ax.tick_params(colors=theme.fg, which="both", labelsize=8)
    ax.xaxis.label.set_color(theme.fg)
    ax.yaxis.label.set_color(theme.fg)
    ax.title.set_color(theme.fg)
    if show_grid:
        ax.grid(True, color=theme.grid, linewidth=0.5, alpha=0.7)


def _add_nl_basemap(ax) -> None:
    """Laad achtergrondkaart uit lokale cache; download eenmalig als ontbreekt."""
    cache = Settings.BASEMAP_CACHE
    if cache.exists():
        try:
            data = np.load(str(cache))
            ax.imshow(
                data["img"], extent=data["ext"].tolist(),
                origin="upper", alpha=0.45, zorder=0,
                interpolation="bilinear",
            )
        except Exception as exc:
            logger.warning(f"Basemap laden mislukt: {exc}")
    elif _CTX_OK:
        # Probeer in foreground te downloaden — alleen 1 keer per sessie
        if not st.session_state.get("_basemap_download_tried"):
            st.session_state["_basemap_download_tried"] = True
            try:
                logger.info("PDOK basemap downloaden (eenmalig)…")
                Settings.OUTPUT_DIR.mkdir(exist_ok=True)
                fig = Figure()
                tmp_ax = fig.add_subplot(111)
                tmp_ax.set_xlim(0, 300_000)
                tmp_ax.set_ylim(289_000, 629_000)
                tmp_ax.set_aspect("equal")
                ctx.add_basemap(tmp_ax, crs="EPSG:28992",
                                source=_PDOK_URL, alpha=1.0, zoom=8)
                images = tmp_ax.get_images()
                if images:
                    img_data = np.asarray(images[0].get_array())
                    img_ext  = np.array(images[0].get_extent())
                    np.savez(str(cache), img=img_data, ext=img_ext)
                    logger.info(f"Basemap gecached: {cache}")
                    # nu opnieuw renderen op de doel-ax
                    ax.imshow(
                        img_data, extent=img_ext.tolist(),
                        origin="upper", alpha=0.45, zorder=0,
                    )
            except Exception as exc:
                logger.warning(f"Basemap downloaden mislukt: {exc}")


def _render_no_geometry(ax, theme: ChartTheme = CHART_THEME) -> None:
    ax.text(0.5, 0.5, "Geen geometrie beschikbaar",
            ha="center", va="center", color=theme.fg, transform=ax.transAxes)
    _style_axes(ax, theme, show_grid=False)


# ── Scatter map plots ───────────────────────────────────────
def _has_rd_coords(df: pd.DataFrame) -> bool:
    return "_rd_x" in df.columns and "_rd_y" in df.columns


def _style_rd_axes(ax) -> None:
    ax.set_aspect("equal")
    ax.tick_params(labelbottom=False, labelleft=False, length=0)
    _style_axes(ax, show_grid=False)


def _styled_colorbar(fig: Figure, sc, ax, label: Optional[str] = None,
                     shrink: float = 0.7) -> Any:
    cbar = fig.colorbar(sc, ax=ax, shrink=shrink, pad=0.02, fraction=0.03)
    if label:
        cbar.set_label(label, color=CHART_THEME.fg, fontsize=7)
    cbar.ax.tick_params(colors=CHART_THEME.fg, labelsize=7)
    cbar.outline.set_edgecolor(CHART_THEME.grid)
    return cbar


def _draw_rd_backdrop(ax, df: pd.DataFrame, mask: pd.Series,
                      size: float = 1.0, alpha: float = 0.2) -> None:
    """Teken alle punten zonder waarde als donkergrijze stippen onder de overlay."""
    backdrop = df[~mask & df["_rd_x"].notna() & df["_rd_y"].notna()]
    if backdrop.empty:
        return
    ax.scatter(backdrop["_rd_x"], backdrop["_rd_y"],
               c="#444", s=size, alpha=alpha, linewidths=0, rasterized=True)


def _render_rd_scatter_map(
    df: pd.DataFrame, values: pd.Series, title: str, *,
    cmap: Any = "RdYlGn_r",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    cbar_label: Optional[str] = None,
    point_size: float = 3.0,
    point_alpha: float = 0.8,
    backdrop_size: float = 1.0,
    backdrop_alpha: float = 0.25,
    show_count_in_title: bool = True,
) -> Figure:
    """Gemeenschappelijke RD New scatter-on-basemap. `values` heeft index van
    `df`; NaN-rijen worden als grijze backdrop getekend."""
    fig = Figure(figsize=(8, 7), facecolor=CHART_THEME.bg)
    ax = fig.add_subplot(111)

    if not _has_rd_coords(df):
        _render_no_geometry(ax)
        return fig

    mask = values.notna() & df["_rd_x"].notna() & df["_rd_y"].notna()
    _draw_rd_backdrop(ax, df, mask, size=backdrop_size, alpha=backdrop_alpha)

    sc = None
    if mask.any():
        sub = df[mask]
        v = values[mask]
        used_vmin = float(v.quantile(0.05)) if vmin is None else vmin
        used_vmax = float(v.quantile(0.95)) if vmax is None else vmax
        sc = ax.scatter(
            sub["_rd_x"], sub["_rd_y"], c=v, cmap=cmap,
            s=point_size, alpha=point_alpha, linewidths=0, rasterized=True,
            vmin=used_vmin, vmax=used_vmax,
        )
        _styled_colorbar(fig, sc, ax, label=cbar_label)

    _add_nl_basemap(ax)
    title_str = f"{title}  (n={int(mask.sum()):,})" if show_count_in_title else title
    ax.set_title(title_str, pad=6)
    _style_rd_axes(ax)
    fig.tight_layout(pad=1.2)
    return fig


def plot_scatter_map(df: pd.DataFrame, col: str, title: str) -> Figure:
    vals = (pd.to_numeric(df[col], errors="coerce") if col in df.columns
            else pd.Series(np.nan, index=df.index))
    return _render_rd_scatter_map(df, vals, title)


# ── Deklagen coverage ───────────────────────────────────────
def plot_deklagen_coverage(df: pd.DataFrame) -> Figure:
    fig = Figure(figsize=(8, 7), facecolor=CHART_THEME.bg)
    ax = fig.add_subplot(111)

    if "_rd_x" not in df.columns or "_rd_y" not in df.columns:
        _render_no_geometry(ax)
        return fig

    mask_all = df[["_rd_x", "_rd_y"]].notna().all(axis=1)
    mask_dek = mask_all & df["deklaagsoort"].notna() if "deklaagsoort" in df.columns else pd.Series(False, index=df.index)
    all_pts = df[mask_all]
    dek_pts = df[mask_dek]

    ax.scatter(all_pts["_rd_x"], all_pts["_rd_y"],
               c="#555", s=1.5, alpha=0.3, linewidths=0,
               rasterized=True, label="Alle hecto.")

    leeftijd = pd.to_numeric(dek_pts.get("_leeftijd"), errors="coerce")
    has_age = leeftijd.notna()

    if has_age.any():
        sub_age = dek_pts[has_age]
        age_vals = leeftijd[has_age]
        vmin, vmax = float(age_vals.quantile(0.05)), float(age_vals.quantile(0.95))
        sc = ax.scatter(sub_age["_rd_x"], sub_age["_rd_y"],
                        c=age_vals, cmap="RdYlGn_r",
                        s=3, alpha=0.85, linewidths=0, rasterized=True,
                        vmin=vmin, vmax=vmax)
        cbar = fig.colorbar(sc, ax=ax, shrink=0.65, pad=0.02, fraction=0.03)
        cbar.set_label("Leeftijd (jr)", color=CHART_THEME.fg, fontsize=7)
        cbar.ax.tick_params(colors=CHART_THEME.fg, labelsize=7)
        cbar.outline.set_edgecolor(CHART_THEME.grid)

    if (~has_age).any():
        sub_no = dek_pts[~has_age]
        ax.scatter(sub_no["_rd_x"], sub_no["_rd_y"],
                   c="#aaaaaa", s=3, alpha=0.6, linewidths=0,
                   rasterized=True, label="Leeftijd onbekend")

    pct = len(dek_pts) / max(len(all_pts), 1) * 100
    _add_nl_basemap(ax)
    ax.set_title(
        f"Deklagen dekking  {pct:.1f}%  ({len(dek_pts):,} / {len(all_pts):,})"
        "   oud → nieuw", pad=6,
    )
    if (~has_age).any():
        ax.legend(fontsize=7, markerscale=4, loc="lower right",
                  facecolor=CHART_THEME.axes_bg, edgecolor=CHART_THEME.grid,
                  labelcolor=CHART_THEME.fg)
    ax.set_aspect("equal")
    ax.tick_params(labelbottom=False, labelleft=False, length=0)
    _style_axes(ax, show_grid=False)
    fig.tight_layout(pad=1.2)
    return fig


# ── Bocht × health ──────────────────────────────────────────
def plot_bocht_health(df: pd.DataFrame) -> Figure:
    fig = Figure(figsize=(13, 5), facecolor=CHART_THEME.bg)
    ax_box = fig.add_subplot(1, 2, 1)
    ax_bar = fig.add_subplot(1, 2, 2)
    for a in (ax_box, ax_bar):
        _style_axes(a)

    if ("_bocht_cat" not in df.columns or "_min_health" not in df.columns
            or df.empty):
        ax_box.text(0.5, 0.5, "Geen data", ha="center", va="center",
                    color=CHART_THEME.fg, transform=ax_box.transAxes)
        return fig

    gb = df.groupby("_bocht_cat")["_min_health"]
    present = [c for c in _BOCHT_CAT_ORDER if c in gb.groups]
    box_data = [gb.get_group(c).dropna().to_numpy() for c in present]
    stats = gb.agg(["mean", "std"]).reindex(present)
    colors_p = [_BOCHT_CAT_COLORS[_BOCHT_CAT_ORDER.index(c)] for c in present]

    bp = ax_box.boxplot(box_data, patch_artist=True,
                        medianprops=dict(color="black", lw=2.5),
                        flierprops=dict(marker="o", markersize=3, alpha=0.3))
    for patch, c in zip(bp["boxes"], colors_p):
        patch.set_facecolor(c)
        patch.set_alpha(0.75)
    ax_box.set_xticks(range(1, len(present) + 1))
    ax_box.set_xticklabels(present, fontsize=8, rotation=18, ha="right")
    ax_box.set_ylabel("health")
    ax_box.set_ylim(0, 10)
    ax_box.axhline(7, color="#2FA572", ls="--", lw=1.5, alpha=0.7,
                   label="Grens goed (7)")
    ax_box.axhline(4, color="#e74c3c", ls="--", lw=1.5, alpha=0.7,
                   label="Grens slecht (4)")
    ax_box.set_title("Scoreverdeling per bochtkategorie")
    ax_box.legend(fontsize=7, facecolor=CHART_THEME.axes_bg,
                  edgecolor=CHART_THEME.grid, labelcolor=CHART_THEME.fg)

    means = stats["mean"].tolist()
    stds  = stats["std"].tolist()
    bars = ax_bar.bar(range(len(present)), means, yerr=stds, capsize=6,
                      color=colors_p, edgecolor="white", alpha=0.85)
    ax_bar.set_xticks(range(len(present)))
    ax_bar.set_xticklabels(present, fontsize=8, rotation=18, ha="right")
    ax_bar.set_ylabel("Gem. health score")
    ax_bar.set_ylim(0, 10)
    ax_bar.axhline(7, color="#2FA572", ls="--", lw=1.5, alpha=0.7)
    ax_bar.axhline(4, color="#e74c3c", ls="--", lw=1.5, alpha=0.7)
    ax_bar.set_title("Gem. score (±std) per categorie")
    for bar, mean_val, std_val in zip(bars, means, stds):
        ax_bar.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + (std_val or 0) + 0.15,
                    f"{mean_val:.2f}", ha="center", fontsize=9,
                    fontweight="bold", color=CHART_THEME.fg)

    fig.tight_layout(pad=1.5)
    return fig


# ── KDE plots ───────────────────────────────────────────────
def _render_kde_row(ax, data: np.ndarray, col_label: str) -> None:
    if len(data) < 5:
        ax.text(0.5, 0.5, "Onvoldoende data",
                ha="center", va="center", color=CHART_THEME.fg,
                transform=ax.transAxes)
        return

    sample = data if len(data) <= 5000 else np.random.choice(data, 5000, replace=False)
    kde = gaussian_kde(sample, bw_method=0.12)
    xmin, xmax = float(data.min()), float(data.max())
    x = np.linspace(xmin, xmax, 400)
    dens = kde(x)

    norm = mcolors.Normalize(vmin=xmin, vmax=xmax)
    for i in range(len(x) - 1):
        ax.fill_between(x[i:i + 2], dens[i:i + 2], alpha=0.85,
                        color=SCORE_CMAP(norm(x[i])))
    ax.plot(x, dens, color="#aaa", lw=0.8, alpha=0.5)

    T_SLECHT, T_MATIG = 4, 7
    for thresh in (T_SLECHT, T_MATIG):
        if xmin < thresh < xmax:
            ax.axvline(thresh, color=CHART_THEME.fg, lw=1.2, ls="--", zorder=5)
            ax.text(thresh + 0.08, dens.max() * 1.05, str(thresh),
                    fontsize=7.5, color=CHART_THEME.fg, va="bottom")

    zones = [
        (xmin,                min(T_SLECHT, xmax), "#d73027", "Slecht"),
        (max(xmin, T_SLECHT), min(T_MATIG,  xmax), "#d9a02b", "Matig"),
        (max(xmin, T_MATIG),  xmax,                "#1a9850", "Goed"),
    ]
    for z_lo, z_hi, color, lbl in zones:
        if z_hi > z_lo:
            pct = float(((data >= z_lo) & (data < z_hi)).mean() * 100)
            ax.text((z_lo + z_hi) / 2, dens.max() * 1.22,
                    f"{lbl}\n{pct:.1f}%", ha="center", va="bottom",
                    fontsize=8.5, fontweight="bold", color=color)

    med = float(np.median(data))
    ax.axvline(med, color=CHART_THEME.fg, lw=1.8, zorder=6)
    ax.text(med + 0.06, dens.max() * 0.55, f" med.\n {med:.2f}",
            fontsize=7.5, color=CHART_THEME.fg, va="center")

    ax.set_xlim(xmin - 0.1, xmax + 0.2)
    ax.set_ylim(0, dens.max() * 1.65)
    ax.set_title(col_label, fontsize=10, fontweight="bold",
                 loc="left", pad=6, color=CHART_THEME.fg)
    ax.set_xlabel("Score")
    ax.set_yticks([])
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_edgecolor(CHART_THEME.grid)
    ax.set_facecolor(CHART_THEME.axes_bg)
    ax.tick_params(colors=CHART_THEME.fg)


def plot_score_kde(df: pd.DataFrame, col_a: str, label_a: str,
                   col_b: str, label_b: str) -> Figure:
    fig = Figure(figsize=(11, 6), facecolor=CHART_THEME.bg)
    if not _SCIPY_OK:
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, "scipy vereist voor KDE plots",
                ha="center", va="center", color=CHART_THEME.fg,
                transform=ax.transAxes)
        _style_axes(ax, show_grid=False)
        return fig

    ax_a = fig.add_subplot(2, 1, 1)
    ax_b = fig.add_subplot(2, 1, 2)
    _render_kde_row(
        ax_a, df[col_a].dropna().values if col_a in df.columns else np.array([]), label_a
    )
    _render_kde_row(
        ax_b, df[col_b].dropna().values if col_b in df.columns else np.array([]), label_b
    )
    fig.tight_layout(pad=2.0)
    return fig


# ── Zichtbaarheid 2025 + Gemiddelde scores kaart ──────────────
def plot_visibility_map_2025(df: pd.DataFrame) -> Figure:
    vis = pd.to_numeric(df.get("_vis_25"), errors="coerce")
    fig = _render_rd_scatter_map(
        df, vis,
        title="visibility_2025",
        cmap="RdYlGn", vmin=0, vmax=10,
        cbar_label="visibility",
        point_size=5, point_alpha=0.85, backdrop_alpha=0.2,
    )
    # Achteraf "   slecht → goed" achter de count plakken
    if fig.axes:
        ax = fig.axes[0]
        ax.set_title(ax.get_title() + "   slecht → goed", pad=6)
    return fig


_GEM_SCORE_COLS = ["_health_23", "_vis_23", "_health_25", "_vis_25"]


def plot_gemiddelde_scores_kaart(df: pd.DataFrame) -> Figure:
    available = [c for c in _GEM_SCORE_COLS if c in df.columns]
    gem_score = (df[available].mean(axis=1) if available
                 else pd.Series(np.nan, index=df.index))
    fig = _render_rd_scatter_map(
        df, gem_score,
        title="Gem. inspectiescore",
        cmap=SCORE_CMAP, vmin=0, vmax=10,
        cbar_label="Gem. score (0–10)",
        point_size=5, point_alpha=0.88, backdrop_alpha=0.2,
    )
    if fig.axes:
        ax = fig.axes[0]
        ax.set_title(ax.get_title() + "   slecht → goed", pad=6)
        # Extra threshold-lijntjes in de colorbar
        for cbar_ax in [a for a in fig.axes if a is not ax]:
            for thresh in (4, 7):
                cbar_ax.axhline(thresh / 10, color="white",
                                lw=1.2, ls="--", alpha=0.85)
    return fig


# ── Chart registry ──────────────────────────────────────────
CHART_DEFINITIONS: List[Tuple[str, str, Callable[[pd.DataFrame], Figure]]] = [
    ("verkeers_klein",   "klein_voertuig (kaart)",          lambda d: plot_scatter_map(d, "klein_voertuig",  "klein_voertuig")),
    ("verkeers_middel",  "middel_voertuig (kaart)",         lambda d: plot_scatter_map(d, "middel_voertuig", "middel_voertuig")),
    ("verkeers_lang",    "lang_voertuig (kaart)",           lambda d: plot_scatter_map(d, "lang_voertuig",   "lang_voertuig")),
    ("verkeers_totaal",  "totaal_voertuig (kaart)",         lambda d: plot_scatter_map(d, "totaal_voertuig", "totaal_voertuig")),
    ("deklagen_cov",     "deklaagsoort dekking",            plot_deklagen_coverage),
    ("bocht_health",     "draaihoek × health",              plot_bocht_health),
    ("score_kde",        "KDE — min health / visibility",   lambda d: plot_score_kde(d, "_min_health", "health", "_min_visibility", "visibility")),
    ("score_kde_zoom",   "KDE — health_2023 vs health_2025", lambda d: plot_score_kde(d, "_health_23", "health_2023", "_health_25", "health_2025")),
    ("visibility_2025",  "visibility_2025 (kaart)",         plot_visibility_map_2025),
    ("gem_score_kaart",  "insp_score (kaart)",              plot_gemiddelde_scores_kaart),
]


def save_charts_to_disk(df: pd.DataFrame, keys: List[str]) -> List[Path]:
    """Schrijf de geselecteerde charts naar `Output/chart_<key>.png`."""
    if df.empty:
        return []
    Settings.OUTPUT_DIR.mkdir(exist_ok=True)
    saved: List[Path] = []
    registry = {k: fn for k, _, fn in CHART_DEFINITIONS}
    for key in keys:
        if key not in registry:
            continue
        try:
            fig = registry[key](df)
            path = Settings.OUTPUT_DIR / f"chart_{key}.png"
            fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
            saved.append(path)
        except Exception as exc:
            logger.warning(f"Chart {key} opslaan mislukt: {exc}")
    return saved


# ============================================================
# QGIS EXPORT — thematische lagen
# ------------------------------------------------------------
# Schrijft `qgis_hoek.gpkg`, `qgis_lang_voertuig.gpkg`,
# `qgis_leeftijd.gpkg`, `qgis_inspectie.gpkg` met ingebakken QML-stijl.
# ============================================================
_QGIS_LAYERS: List[Tuple[str, str, str, bool]] = [
    ("qgis_hoek",          "_max_hoek",      "Draaihoek (°)",  False),
    ("qgis_lang_voertuig", "lang_voertuig",  "Lang voertuig", False),
    ("qgis_leeftijd",      "_leeftijd",      "Leeftijd (jr)", False),
    ("qgis_inspectie",     "_inspectie_min", "Inspectie",     True),
]

_GPKG_EXTRA_ATTRS: List[Tuple[str, str, str]] = [
    ("draaihoek",         "draaihoek",         "TEXT"),
    ("boogstraal",        "boogstraal",        "TEXT"),
    ("health_2023",       "health_2023",       "TEXT"),
    ("visibility_2023",   "visibility_2023",   "TEXT"),
    ("health_2025",       "health_2025",       "TEXT"),
    ("visibility_2025",   "visibility_2025",   "TEXT"),
    ("_inspectie_scores", "inspectie_scores",  "TEXT"),
    ("deklaagsoort",      "deklaagsoort",      "TEXT"),
    ("aanlegdatum",       "aanlegdatum",       "TEXT"),
    ("strook",            "strook",            "TEXT"),
    ("klein_voertuig",    "klein_voertuig",    "REAL"),
    ("middel_voertuig",   "middel_voertuig",   "REAL"),
    ("lang_voertuig",     "lang_voertuig",     "REAL"),
    ("totaal_voertuig",   "totaal_voertuig",   "REAL"),
    ("distrnaam",         "distrnaam",         "TEXT"),
    ("info",              "info",              "TEXT"),
    ("streetsmart_link",  "streetsmart_link",  "TEXT"),
    ("google_maps_link",  "google_maps_link",  "TEXT"),
    ("_alert_score",      "alert_score",       "REAL"),
]


def _gpkg_point_blob(x: float, y: float, srs_id: int = 28992) -> bytes:
    """GeoPackage binary geometry voor een 2D point (LE, no envelope)."""
    return struct.pack("<2sBBi", b"GP", 0, 1, srs_id) + struct.pack("<BIdd", 1, 1, x, y)


def _qml_style_data_defined(size: str = "3") -> str:
    """QML met data-defined fillColor uit kolom `color_hex`.

    `size` = markergrootte in MM. De heatmap-kaartlagen gebruiken de grote
    5.0-variant zodat de punten op landelijke schaal goed zichtbaar zijn.
    """
    return (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        '<qgis version="3.28" styleCategories="Symbology">\n'
        '  <renderer-v2 type="singleSymbol" forceraster="0" enableorderby="0"'
        ' referencescale="-1" symbollevels="0">\n'
        '    <symbols>\n'
        '      <symbol type="marker" name="0" clip_to_extent="1" alpha="0.85" force_rhr="0">\n'
        '        <data_defined_properties>\n'
        '          <Option type="Map">\n'
        '            <Option name="name" value="" type="QString"/>\n'
        '            <Option name="properties"/>\n'
        '            <Option name="type" value="collection" type="QString"/>\n'
        '          </Option>\n'
        '        </data_defined_properties>\n'
        '        <layer class="SimpleMarker" pass="0" enabled="1" locked="0">\n'
        '          <Option type="Map">\n'
        '            <Option name="angle" value="0" type="QString"/>\n'
        '            <Option name="color" value="26,155,80,255" type="QString"/>\n'
        '            <Option name="joinstyle" value="bevel" type="QString"/>\n'
        '            <Option name="name" value="circle" type="QString"/>\n'
        '            <Option name="offset" value="0,0" type="QString"/>\n'
        '            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>\n'
        '            <Option name="offset_unit" value="MM" type="QString"/>\n'
        '            <Option name="outline_color" value="255,255,255,0" type="QString"/>\n'
        '            <Option name="outline_style" value="no" type="QString"/>\n'
        '            <Option name="outline_width" value="0" type="QString"/>\n'
        '            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>\n'
        '            <Option name="outline_width_unit" value="MM" type="QString"/>\n'
        '            <Option name="scale_method" value="diameter" type="QString"/>\n'
        f'            <Option name="size" value="{size}" type="QString"/>\n'
        '            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>\n'
        '            <Option name="size_unit" value="MM" type="QString"/>\n'
        '            <Option name="vertical_anchor_point" value="1" type="QString"/>\n'
        '          </Option>\n'
        '          <data_defined_properties>\n'
        '            <Option type="Map">\n'
        '              <Option name="name" value="" type="QString"/>\n'
        '              <Option name="properties" type="Map">\n'
        '                <Option name="fillColor" type="Map">\n'
        '                  <Option name="active" value="true" type="bool"/>\n'
        '                  <Option name="expression" value="&quot;color_hex&quot;" type="QString"/>\n'
        '                  <Option name="type" value="3" type="int"/>\n'
        '                </Option>\n'
        '              </Option>\n'
        '              <Option name="type" value="collection" type="QString"/>\n'
        '            </Option>\n'
        '          </data_defined_properties>\n'
        '        </layer>\n'
        '      </symbol>\n'
        '    </symbols>\n'
        '    <rotation/>\n'
        '    <sizescale/>\n'
        '  </renderer-v2>\n'
        '  <customproperties><Option/></customproperties>\n'
        '  <blendMode>0</blendMode>\n'
        '  <featureBlendMode>0</featureBlendMode>\n'
        '  <layerGeometryType>0</layerGeometryType>\n'
        '</qgis>'
    )


def _gpkg_safe_floats(series: pd.Series) -> List[Optional[float]]:
    """SQLite-veilige floats: NaN/inf/None → None, rest float()."""
    return [
        None if (v is None or pd.isna(v)
                 or (isinstance(v, float) and not np.isfinite(v)))
        else float(v)
        for v in series
    ]


def _gpkg_safe_strs(series: pd.Series) -> List[Optional[str]]:
    """SQLite-veilige strings: lege/NaN/'None' → None, rest str()."""
    return [
        None if (v is None or pd.isna(v) or str(v) in ("nan", "None", ""))
        else str(v)
        for v in series
    ]


def _gpkg_col(df: pd.DataFrame, name: str) -> pd.Series:
    """Pak kolom of None-Series met dezelfde index."""
    return (df[name] if name in df.columns
            else pd.Series([None] * len(df), index=df.index))


_GPKG_SRS_ROWS = [
    ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", "undefined"),
    ("Undefined geographic SRS",  0, "NONE",  0, "undefined", "undefined"),
    ("WGS 84", 4326, "EPSG", 4326,
     'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
     'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]', "WGS 84"),
    ("Amersfoort / RD New", 28992, "EPSG", 28992,
     'PROJCS["Amersfoort / RD New",GEOGCS["Amersfoort",'
     'DATUM["Amersfoort",SPHEROID["Bessel 1841",6377397.155,299.1528128]],'
     'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
     'PROJECTION["Oblique_Stereographic"],'
     'PARAMETER["latitude_of_origin",52.1561605555556],'
     'PARAMETER["central_meridian",5.38763888888889],'
     'PARAMETER["scale_factor",0.9999079],'
     'PARAMETER["false_easting",155000],'
     'PARAMETER["false_northing",463000],'
     'UNIT["metre",1]]', "RD New"),
]


def _gpkg_init_schema(cur: sqlite3.Cursor) -> None:
    """PRAGMAs + verplichte GPKG-metadatatabellen + SRS-rijen."""
    cur.execute("PRAGMA application_id = 1196444487")
    cur.execute("PRAGMA user_version = 10300")
    cur.executescript("""
        CREATE TABLE gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL, description TEXT
        );
        CREATE TABLE gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,
            identifier TEXT, description TEXT, last_change DATETIME,
            min_x REAL, min_y REAL, max_x REAL, max_y REAL, srs_id INTEGER
        );
        CREATE TABLE gpkg_geometry_columns (
            table_name TEXT NOT NULL, column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL, m TINYINT NOT NULL,
            CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name)
        );
    """)
    cur.executemany(
        "INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)",
        _GPKG_SRS_ROWS,
    )


def _gpkg_create_feature_table(cur: sqlite3.Cursor, tbl: str) -> None:
    """Feature-tabel met de standaard thematische kolommen + de extra
    attributen uit `_GPKG_EXTRA_ATTRS`."""
    extra_col_defs = ",\n            ".join(
        f"{gcol}  {stype}" for _, gcol, stype in _GPKG_EXTRA_ATTRS
    )
    cur.execute(f"""
        CREATE TABLE "{tbl}" (
            fid        INTEGER PRIMARY KEY AUTOINCREMENT,
            geom       BLOB,
            color_hex  TEXT,
            value      REAL,
            value_norm REAL,
            label      TEXT,
            wegnr_hmp  TEXT,
            hectomtrng REAL,
            hecto_lttr TEXT,
            zijde      TEXT,
            wvk_id     TEXT,
            {extra_col_defs}
        )
    """)


def _gpkg_collect_rows(sub: pd.DataFrame, label: str) -> List[tuple]:
    """Bouw de tuple-rijen voor `executemany` — exact in dezelfde
    kolomvolgorde als `_gpkg_create_feature_table`."""
    geoms      = [_gpkg_point_blob(x, y)
                  for x, y in zip(sub["_rd_x"].to_numpy(dtype=float),
                                  sub["_rd_y"].to_numpy(dtype=float))]
    base_cols = (
        geoms,
        sub["color_hex"].tolist(),
        _gpkg_safe_floats(sub["value"]),
        sub["value_norm"].tolist(),
        [label] * len(sub),
        _gpkg_safe_strs(_gpkg_col(sub, "wegnr_hmp")),
        _gpkg_safe_floats(_gpkg_col(sub, "hectomtrng")),
        _gpkg_safe_strs(_gpkg_col(sub, "hecto_lttr")),
        _gpkg_safe_strs(_gpkg_col(sub, "Zijde")),
        _gpkg_safe_strs(_gpkg_col(sub, "wvk_id")),
    )
    extra_cols = tuple(
        _gpkg_safe_floats(_gpkg_col(sub, dc)) if stype == "REAL"
        else _gpkg_safe_strs(_gpkg_col(sub, dc))
        for dc, _, stype in _GPKG_EXTRA_ATTRS
    )
    return list(zip(*base_cols, *extra_cols))


def _gpkg_register_layer(cur: sqlite3.Cursor, tbl: str, label: str,
                          xs: np.ndarray, ys: np.ndarray,
                          qml_size: str = "3") -> None:
    """gpkg_contents + gpkg_geometry_columns + ingebedde QML-stijl."""
    cur.execute(
        "INSERT INTO gpkg_contents VALUES (?,?,?,?,datetime('now'),?,?,?,?,?)",
        (tbl, "features", label, label,
         float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()), 28992),
    )
    cur.execute(
        "INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)",
        (tbl, "geom", "POINT", 28992, 0, 0),
    )
    cur.execute("""
        CREATE TABLE layer_styles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            f_table_catalog TEXT, f_table_schema TEXT, f_table_name TEXT,
            f_geometry_column TEXT, styleName TEXT, styleQML TEXT, styleSLD TEXT,
            useAsDefault BOOLEAN, description TEXT, owner TEXT, ui TEXT,
            update_time DATETIME DEFAULT (datetime('now'))
        )
    """)
    cur.execute(
        "INSERT INTO layer_styles "
        "(f_table_catalog,f_table_schema,f_table_name,f_geometry_column,"
        "styleName,styleQML,useAsDefault) VALUES ('','',?,?,'default',?,1)",
        (tbl, "geom", _qml_style_data_defined(qml_size)),
    )


# ── Heatmap-kaartlagen (alle keuzes uit de interactieve kaart) ───────────────
# Elke optie in `_MAP_HEATMAP_OPTIONS` wordt als eigen GPKG weggeschreven met
# EXACT dezelfde RdYlGn-kleuring als de kaart-tab (`_compute_map_heatmap_pct`).
# De ingebedde QML gebruikt de grote 5.0-markergrootte voor landelijke schaal.
_HEATMAP_QML_SIZE: str = "5"


def _heatmap_layer_stem(choice: str) -> str:
    """Slug een heatmap-keuze naar een veilige GPKG-/tabelnaam.
    'health (alle jaren)' → 'qgis_heatmap_health_alle_jaren'."""
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", choice.strip().lower()).strip("_")
    return f"qgis_heatmap_{slug}"


def write_heatmap_gpkg(work: pd.DataFrame, pct: pd.Series, stem: str,
                       label: str) -> Optional[Path]:
    """Schrijf één heatmap-laag (alle punten, RdYlGn op `pct`) naar `Output/`.

    `pct` = 0..1 (0 = rood/slecht, 1 = groen/goed), identiek aan de kaart.
    Markergrootte 5.0 via ingebedde QML. Returnt het pad of None.
    """
    if "_rd_x" not in work.columns or "_rd_y" not in work.columns:
        return None
    mask = work["_rd_x"].notna() & work["_rd_y"].notna()
    sub = work[mask].copy()
    if sub.empty:
        return None

    p = pd.to_numeric(pct.reindex(sub.index), errors="coerce").fillna(0.5).clip(0, 1)
    rgba = RDYLGN_CMAP(p.to_numpy(dtype=float))
    sub = sub.assign(
        color_hex  = ["#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255),
                                                    int(b * 255))
                      for r, g, b, _ in rgba],
        value      = p.round(4).values,
        value_norm = p.round(4).values,
    )

    Settings.OUTPUT_DIR.mkdir(exist_ok=True)
    gpkg_path = Settings.OUTPUT_DIR / f"{stem}.gpkg"
    if gpkg_path.exists():
        gpkg_path.unlink()

    tbl = stem.replace("-", "_")
    extra_col_names    = ", ".join(gc for _, gc, _ in _GPKG_EXTRA_ATTRS)
    extra_placeholders = ", ".join("?" for _ in _GPKG_EXTRA_ATTRS)

    conn = sqlite3.connect(str(gpkg_path))
    try:
        cur = conn.cursor()
        _gpkg_init_schema(cur)
        _gpkg_create_feature_table(cur, tbl)
        cur.executemany(
            f'INSERT INTO "{tbl}" '
            f'(geom,color_hex,value,value_norm,label,wegnr_hmp,hectomtrng,'
            f'hecto_lttr,zijde,wvk_id,{extra_col_names}) '
            f'VALUES (?,?,?,?,?,?,?,?,?,?,{extra_placeholders})',
            _gpkg_collect_rows(sub, label),
        )
        _gpkg_register_layer(
            cur, tbl, label,
            sub["_rd_x"].to_numpy(dtype=float),
            sub["_rd_y"].to_numpy(dtype=float),
            qml_size=_HEATMAP_QML_SIZE,
        )
        conn.commit()
    finally:
        conn.close()
    return gpkg_path


def export_all_heatmap_layers(
    df: pd.DataFrame,
    work: Optional[pd.DataFrame] = None,
    annotations: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Schrijf álle heatmap-keuzes (`_MAP_HEATMAP_OPTIONS`) als GPKG-lagen,
    elk gekleurd zoals de interactieve kaart, met markergrootte 5.0.

    `work`/`annotations` mogen voorberekend worden aangeleverd zodat de
    'Genereer alles'-knop de workframe maar één keer hoeft op te bouwen.
    """
    counts: Dict[str, int] = {}
    paths:  Dict[str, str] = {}
    errors: List[str] = []

    if annotations is None:
        annotations = load_annotations()
    if work is None:
        work = _build_map_workframe(df, annotations)
    if work is None or work.empty:
        errors.append("Heatmap-lagen: geen punten met coördinaten in de selectie.")
        return {"counts": counts, "paths": paths, "errors": errors}

    default_pct = _default_heatmap_pct(work)
    for choice in _MAP_HEATMAP_OPTIONS:
        try:
            pct = _compute_map_heatmap_pct(work, choice, default_pct, annotations)
            path = write_heatmap_gpkg(
                work, pct, _heatmap_layer_stem(choice), label=choice,
            )
            if path is None:
                counts[choice] = 0
            else:
                counts[choice] = int(len(work))
                paths[choice]  = str(path)
        except Exception as exc:
            errors.append(f"{choice}: {exc}")
    return {"counts": counts, "paths": paths, "errors": errors}


# ── Koppeling-lagen (door het Data_Preparation notebook geschreven) ──────────
# Het notebook schrijft tijdens de koppeling-stap rechtstreeks drie GPKG's
# naar Output/. Hier alleen verifiëren dat ze bestaan en feature-tellingen
# rapporteren in de "Genereer alles"-samenvatting.
#
#   qgis_hectopunten_punten       — 1 punt per hectopunt          (EPSG:28992)
#   qgis_inspecties_punten        — 1 punt per inspectie          (EPSG:28992)
#   qgis_inspecties_verbindingen  — 1 lijn inspectie→dichtstbijzijnde hectopunt
#
# De drie lagen zijn 1-op-1 consistent: elk lijn-eindpunt valt op een punt in
# qgis_hectopunten_punten (gebouwd uit exact dezelfde hecto_xy als de KDTree).
_SOURCE_GEOMETRY_LAYERS: List[Tuple[str, str]] = [
    ("qgis_hectopunten_punten",      "Hectopunten"),
    ("qgis_inspecties_punten",       "Inspecties (punten)"),
    ("qgis_inspecties_verbindingen", "Inspecties (verbindingen)"),
]


def collect_inspection_layers() -> Dict[str, Any]:
    """Inventariseer de inspectie-GPKG's die het notebook heeft weggeschreven.

    Geeft per laag een feature-telling en pad terug, of een foutmelding als
    het bestand nog ontbreekt (notebook nog niet gedraaid).
    """
    counts: Dict[str, int] = {}
    paths:  Dict[str, str] = {}
    errors: List[str] = []
    try:
        import geopandas as gpd
    except ImportError:
        gpd = None
        errors.append(
            "geopandas niet beschikbaar — feature-tellingen inspectie-lagen overgeslagen"
        )

    for stem, label in _SOURCE_GEOMETRY_LAYERS:
        gpkg_path = Settings.OUTPUT_DIR / f"{stem}.gpkg"
        if not gpkg_path.exists():
            errors.append(
                f"{label}: {gpkg_path.name} ontbreekt in Output/ — "
                "draai eerst de koppeling-stap in Data_Preparation.ipynb."
            )
            continue
        n = 0
        if gpd is not None:
            try:
                n = int(len(gpd.read_file(str(gpkg_path))))
            except Exception as exc:
                errors.append(f"{label}: lezen mislukt ({exc})")
                continue
        counts[label] = n
        paths[label]  = str(gpkg_path)
    return {"counts": counts, "paths": paths, "errors": errors}


# ============================================================
# QGIS EXPORT — clusters
# ------------------------------------------------------------
# Schrijft `hectopunten_clusters.gpkg` met categorized renderer
# op kolom `cluster`. Vereist `geopandas` + `shapely`.
# ============================================================
def _safe_for_gpkg(gdf):
    bad = [c for c in gdf.columns
           if (not isinstance(c, str)) or c.strip() in ("", "|")]
    if bad:
        gdf = gdf.drop(columns=bad)
    for c in gdf.columns:
        if c == gdf.geometry.name:
            continue
        if str(gdf[c].dtype) in ("Int64", "Int32", "boolean"):
            gdf[c] = gdf[c].astype(object).where(gdf[c].notna(), None)
    return gdf


def build_hectopunten_gdf(df: pd.DataFrame):
    """Puntenlaag met ALLE oorspronkelijke kolommen + cluster_id."""
    import geopandas as gpd
    from shapely.geometry import Point

    geoms = [Point(x, y) if pd.notna(x) and pd.notna(y) else None
             for x, y in zip(df["_rd_x"], df["_rd_y"])]
    # Coord-helperkolommen + _geom_* hulpkolommen weghalen vóór export.
    drop_cols = ["_rd_x", "_rd_y", *[c for c in df.columns if c.startswith("_geom_")]]
    sub = df.drop(columns=drop_cols, errors="ignore")
    gdf = gpd.GeoDataFrame(sub, geometry=geoms, crs="EPSG:28992")
    gdf = gdf[gdf.geometry.notna()].reset_index(drop=True)
    return _safe_for_gpkg(gdf)


def _embed_qml_in_gpkg(path: str, layer: str, qml: str) -> None:
    geom_col = "geom"
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?",
            (layer,),
        ).fetchone()
        if row and row[0]:
            geom_col = row[0]
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS layer_styles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                f_table_catalog TEXT(256),
                f_table_schema TEXT(256),
                f_table_name TEXT(256),
                f_geometry_column TEXT(256),
                styleName TEXT(30),
                styleQML TEXT,
                styleSLD TEXT,
                useAsDefault BOOLEAN,
                description TEXT,
                owner TEXT(30),
                ui TEXT(30),
                update_time DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
            """
        )
        cur.execute(
            """
            INSERT INTO layer_styles
              (f_table_catalog, f_table_schema, f_table_name, f_geometry_column,
               styleName, styleQML, useAsDefault, description, owner)
            VALUES ('', '', ?, ?, 'clusters', ?, 1, 'PELT cluster colors', '')
            """,
            (layer, geom_col, qml),
        )
        conn.commit()
    finally:
        conn.close()


def to_gpkg_bytes(gdf_points, qml: Optional[str] = None) -> bytes:
    """Schrijf één hectopunten-laag in een GeoPackage en geef bytes terug."""
    fd, path = tempfile.mkstemp(suffix=".gpkg")
    os.close(fd)
    if os.path.exists(path):
        os.unlink(path)
    try:
        gdf_points.to_file(path, layer="hectopunten", driver="GPKG")
        if qml:
            _embed_qml_in_gpkg(path, "hectopunten", qml)
        with open(path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(path):
            os.unlink(path)


def build_categorized_qml(
    cluster_ids: List[int],
    cluster_pct: Dict[int, float],
    cluster_scores: Optional[Dict[int, float]] = None,
) -> str:
    """Genereer een QGIS QML stylefile vanuit de pipeline-output."""
    sorted_ids = sorted(int(c) for c in cluster_ids)
    cmap = RDYLGN_CMAP

    cats: List[str] = []
    syms: List[str] = []
    for i, cl in enumerate(sorted_ids):
        p = cluster_pct.get(cl)
        p_ok = p is not None and not (isinstance(p, float) and np.isnan(p))
        if p_ok:
            r, g, b, _ = cmap(float(p))
            score = (cluster_scores or {}).get(cl)
            score_str = (
                f" (score {float(score):.2f})"
                if score is not None and not (isinstance(score, float) and np.isnan(score))
                else ""
            )
            label = f"Cluster {cl}{score_str}"
        else:
            h = (i * 0.6180339887498949) % 1.0
            r, g, b = colorsys.hls_to_rgb(h, 0.55, 0.7)
            label = f"Cluster {cl}"
        color = f"{int(r * 255)},{int(g * 255)},{int(b * 255)},255"
        cats.append(
            f'<category symbol="{i}" value="{cl}" label="{label}" render="true"/>'
        )
        syms.append(
            f'<symbol name="{i}" type="marker" alpha="1">'
            f'<layer class="SimpleMarker">'
            f'<Option type="Map">'
            f'<Option name="color" value="{color}" type="QString"/>'
            f'<Option name="outline_color" value="35,35,35,255" type="QString"/>'
            f'<Option name="outline_width" value="0.2" type="QString"/>'
            f'<Option name="size" value="2.6" type="QString"/>'
            f'<Option name="size_unit" value="MM" type="QString"/>'
            f'<Option name="name" value="circle" type="QString"/>'
            f'</Option></layer></symbol>'
        )
    return (
        '<!DOCTYPE qgis>\n'
        '<qgis styleCategories="Symbology" version="3.34">\n'
        '  <renderer-v2 type="categorizedSymbol" attr="cluster">\n'
        f'    <categories>{"".join(cats)}</categories>\n'
        f'    <symbols>{"".join(syms)}</symbols>\n'
        '  </renderer-v2>\n'
        '</qgis>\n'
    )


# ============================================================
# SIDEBAR — PELT controls (gewichten + parameters)
# ============================================================
CLUSTER_ALGORITHMS = ["PELT", "Random Forest", "Decision Tree"]


_PELT_MODEL_OPTIONS: List[str] = ["rbf", "l2", "l1", "normal"]
_PELT_MODES: List[str] = ["Drempelwaarde (PELT)", "Vast aantal clusters"]


def _render_pelt_weights(df: pd.DataFrame) -> Dict[str, float]:
    """Sliders voor feature-gewichten; ontbrekende features worden 0.0 + grijs."""
    st.markdown("**Feature gewichten**")
    st.caption("0 = uitschakelen. Hoger = telt zwaarder mee.")

    weights: Dict[str, float] = {}
    wcols = st.columns(2)
    for i, (feat, default) in enumerate(Settings.DEFAULT_WEIGHTS.items()):
        label = Settings.FEATURE_LABELS.get(feat, feat)
        present = feat in df.columns and df[feat].notna().any()
        with wcols[i % 2]:
            if not present:
                st.markdown(f"~~{label}~~ _(ontbreekt)_")
                weights[feat] = 0.0
                continue
            weights[feat] = st.slider(
                label, min_value=0.0, max_value=5.0,
                value=float(default), step=0.1, key=f"w_{feat}",
            )
    return weights


def _render_pelt_mode_penalty() -> Tuple[str, float, Optional[int]]:
    """Modus-radio + penalty-slider óf target-k input."""
    st.markdown("**Parameters**")
    p1, p2 = st.columns(2)
    with p1:
        mode = st.radio(
            "Modus", _PELT_MODES,
            help=(
                "Drempelwaarde: PELT bepaalt zelf hoeveel clusters je krijgt "
                "op basis van penalty β. Vast aantal: stel zelf K in; we "
                "zoeken de bijbehorende penalty via binary search."
            ),
            key="pelt_mode",
        )
    penalty  = 1.0
    target_k = None
    with p2:
        if mode == "Drempelwaarde (PELT)":
            penalty = st.slider(
                "Drempelwaarde (penalty β)",
                min_value=0.05, max_value=15.0, value=1.0, step=0.05,
                help="Hoger = minder, grotere clusters. Lager = fijner, meer. "
                     "Schaal past bij de 0-1 genormaliseerde features (was "
                     "vroeger ~8 bij z-scores).",
                key="pelt_penalty",
            )
        else:
            target_k = st.number_input(
                "Gewenst aantal clusters (totaal)",
                min_value=1, max_value=5000, value=50, step=1,
                help="Binary search zoekt penalty die hier het dichtst bij komt.",
                key="pelt_target_k",
            )
    return mode, penalty, target_k


def _render_pelt_model_minsize(weights: Dict[str, float]) -> Tuple[str, int, Optional[int]]:
    """Kostenfunctie + min-cluster-size + optionele cluster-cap."""
    n_active = sum(1 for w in weights.values() if w > 0)
    default_model = "l2" if n_active == 1 else "rbf"

    m1, m2 = st.columns(2)
    with m1:
        model = st.selectbox(
            "PELT kostenfunctie", _PELT_MODEL_OPTIONS,
            index=_PELT_MODEL_OPTIONS.index(default_model),
            help=(
                "rbf = robuust voor niet-lineaire shifts (O(n²) — kan traag "
                "zijn op lange segmenten); l2 = mean-shift (snel); l1 = "
                "mediaan-shift (robuust tegen outliers); normal = mean + variantie."
            ),
            key="pelt_model",
        )
    with m2:
        min_size = st.slider(
            "Min. hectopunten per cluster", 1, 20, 2,
            help="Voorkomt micro-clusters.",
            key="pelt_min_size",
        )

    if n_active == 1 and model == "rbf":
        st.info(
            "Met **1 feature** is `l2` of `l1` doorgaans veel sneller dan "
            "`rbf` — bij grote segmenten kan `rbf` lang duren."
        )

    max_per_seg: Optional[int] = None
    if st.checkbox("Max. aantal clusters per wegsegment",
                   value=False, key="pelt_use_cap"):
        max_per_seg = st.slider(
            "Max. clusters per segment", 1, 50, 5, key="pelt_max_cap",
        )
    return model, min_size, max_per_seg


def _render_pelt_grouping() -> Tuple[bool, bool, bool]:
    """Grouping-checkboxes: (respect_segment_key, group_by_zijde, group_by_lttr)."""
    st.markdown("**Groepering voor PELT**")
    st.caption(
        "Bepaalt over welke kolommen PELT *apart* draait. Uitvinken = "
        "punten van die kolom worden samengenomen in één PELT-reeks."
    )
    g1, g2, g3 = st.columns(3)
    with g1:
        respect = st.checkbox(
            "Respecteer wegnetwerk", value=True,
            help=(
                "Aan: PELT draait per groep (snelweg + optioneel zijde + "
                "hectoletter). Uit: één grote reeks over álle gefilterde punten."
            ),
            key="pelt_respect_segment",
        )
    with g2:
        by_zijde = st.checkbox(
            "Splits per Zijde (L/R)", value=False,
            help="Aan: L- en R-banen krijgen elk hun eigen PELT-reeks. "
                 "Uit (default): L+R op dezelfde hectometer tellen als één "
                 "parallelle positie.",
            key="pelt_group_zijde",
            disabled=not respect,
        )
    with g3:
        by_lttr = st.checkbox(
            "Splits per Hectoletter", value=False,
            help="Aan: hoofdrijbaan en letters krijgen elk een eigen reeks.",
            key="pelt_group_lttr",
            disabled=not respect,
        )
    return respect, by_zijde, by_lttr


def _pelt_param_block(df: pd.DataFrame) -> Dict[str, Any]:
    """PELT-specifieke widgets (inline). Bestaat uit 4 subblokken die elk
    één keuze-cluster renderen — makkelijker uit te breiden zonder de
    hele block te lezen."""
    weights = _render_pelt_weights(df)
    mode, penalty, target_k = _render_pelt_mode_penalty()
    model, min_size, max_per_seg = _render_pelt_model_minsize(weights)
    respect, by_zijde, by_lttr = _render_pelt_grouping()
    return {
        "weights":                  weights,
        "mode":                     mode,
        "penalty":                  penalty,
        "target_k":                 target_k,
        "model":                    model,
        "min_size":                 min_size,
        "max_clusters_per_segment": max_per_seg,
        "respect_segment_key":      respect,
        "group_by_zijde":           by_zijde,
        "group_by_lttr":            by_lttr,
    }


def _rf_param_block(df: pd.DataFrame) -> Dict[str, Any]:
    """Random Forest widgets — stub (algoritme nog niet aangesloten)."""
    st.info(
        "Random Forest clustering staat in de planning — widgets hieronder "
        "worden bewaard, maar de uitvoering valt nu terug op PELT-instellingen."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        n_estimators = st.slider("Aantal bomen", 10, 500, 100, step=10,
                                 key="rf_n_estimators")
    with c2:
        max_depth = st.slider("Max. diepte", 2, 50, 10, key="rf_max_depth")
    with c3:
        min_samples_leaf = st.slider("Min. samples per blad", 1, 50, 5,
                                     key="rf_min_samples_leaf")
    n_clusters = st.slider("Aantal clusters (k)", 2, 200, 20, key="rf_n_clusters")
    return {
        "n_estimators":     n_estimators,
        "max_depth":        max_depth,
        "min_samples_leaf": min_samples_leaf,
        "n_clusters":       n_clusters,
    }


def _dt_param_block(df: pd.DataFrame) -> Dict[str, Any]:
    """Decision Tree widgets — stub (algoritme nog niet aangesloten)."""
    st.info(
        "Decision Tree clustering staat in de planning — widgets worden "
        "bewaard, uitvoering valt nu terug op PELT-instellingen."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        max_depth = st.slider("Max. diepte", 2, 50, 8, key="dt_max_depth")
    with c2:
        min_samples_split = st.slider("Min. samples voor split", 2, 50, 5,
                                      key="dt_min_samples_split")
    with c3:
        criterion = st.selectbox("Criterium", ["gini", "entropy", "log_loss"],
                                 key="dt_criterion")
    n_clusters = st.slider("Aantal clusters (k)", 2, 200, 20, key="dt_n_clusters")
    return {
        "max_depth":         max_depth,
        "min_samples_split": min_samples_split,
        "criterion":         criterion,
        "n_clusters":        n_clusters,
    }


def inline_algo_controls(df: pd.DataFrame) -> Dict[str, Any]:
    """Inline algo selector + per-algo settings.

    Vervangt de oude sidebar_pelt_controls. PELT-velden worden altijd
    teruggegeven (ook bij RF/DT) zodat run_clustering op fallback PELT
    blijft draaien tot RF/DT echt geïmplementeerd zijn.
    """
    algo = st.radio(
        "Clustering algoritme",
        CLUSTER_ALGORITHMS,
        horizontal=True,
        help="Kies welk algoritme de clusters bepaalt. Settings hieronder "
             "passen zich aan op de keuze.",
        key="cluster_algo",
    )

    cfg: Dict[str, Any] = {"algo": algo}

    # PELT-block altijd renderen — fallback executor leest hier uit.
    # Géén st.expander meer: deze controls zitten ín de buitenste
    # "Clustering & diagnose"-expander en Streamlit verbiedt geneste
    # expanders. Bordered container met kop i.p.v. drawer.
    with st.container(border=True):
        st.markdown("**PELT instellingen**")
        pelt_cfg = _pelt_param_block(df)
    cfg.update(pelt_cfg)

    if algo == "Random Forest":
        with st.container(border=True):
            st.markdown("**Random Forest instellingen**")
            cfg["rf"] = _rf_param_block(df)
    elif algo == "Decision Tree":
        with st.container(border=True):
            st.markdown("**Decision Tree instellingen**")
            cfg["dt"] = _dt_param_block(df)

    return cfg


def run_clustering(df: pd.DataFrame, cfg: Dict[str, Any]) -> Tuple[pd.DataFrame, np.ndarray, List[str], float]:
    """Voer de complete PELT-pipeline uit en geef (clustered_df, Xw,
    used_feats, used_penalty) terug."""
    df = df.copy()

    # Bewaar de ORIGINELE rij-index als kolom vóór de sort+reset hieronder.
    # De kaart kleurt elk punt via work["_orig_idx"] → clustered, en die
    # _orig_idx is de oorspronkelijke df-index. Omdat we straks sorteren en
    # `reset_index` doen (PELT/cluster_dataframe eisen 0..n-1), zou een
    # index-gebaseerde lookup elk punt de kleur van een ANDER punt geven.
    # `_src_idx` houdt de juiste koppeling vast voor de heatmap.
    df["_src_idx"] = df.index

    # Herbouw segment_key dynamisch op basis van de groepering-keuzes —
    # zo zien diagnose/validatie exact dezelfde groepen als clustering.
    df["segment_key"] = build_segment_key(
        df,
        by_zijde=cfg.get("group_by_zijde", False),
        by_lttr=cfg.get("group_by_lttr", False),
    )
    # Resorteer binnen elk segment op hectomtrng zodat PELT echt
    # *langs de weg* loopt (anders blijft de oude sort-order van
    # prepare_dataset staan, wat L/R/letters door elkaar zet als die
    # uit het segment-key zijn weggelaten).
    sort_cols: List[str] = ["segment_key"]
    if "hectomtrng" in df.columns:
        sort_cols.append("hectomtrng")
    df = df.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)

    Xw, used_feats = build_feature_matrix(df, cfg["weights"])

    used_penalty = cfg["penalty"]
    if cfg["mode"] == "Vast aantal clusters":
        with st.spinner(f"Zoekt penalty die ~{cfg['target_k']} clusters oplevert..."):
            used_penalty, found_k = find_penalty_for_target_k(
                df, Xw,
                target_k=int(cfg["target_k"]),
                model=cfg["model"],
                min_size=cfg["min_size"],
                respect_segment_key=cfg["respect_segment_key"],
            )
        st.info(
            f"Binary search → penalty β = **{used_penalty:.3f}** geeft "
            f"**{found_k}** clusters (gevraagd: {cfg['target_k']})."
        )

    with st.spinner("Clusters berekenen..."):
        df["cluster"] = cluster_dataframe(
            df, Xw,
            penalty=used_penalty,
            model=cfg["model"],
            min_size=cfg["min_size"],
            max_clusters_per_segment=cfg["max_clusters_per_segment"],
            respect_segment_key=cfg["respect_segment_key"],
        )

    attach_cluster_severity(df, weights=cfg["weights"])
    return df, Xw, used_feats, used_penalty


# ============================================================
# OUTPUT GENERATIE — "Genereer alles" bundel
# ------------------------------------------------------------
# Schrijft Excel + Pickle + CSV + 4 thematische GPKG + alle PNG's
# + (indien clustering al gedraaid) de cluster-GPKG.
# Resultaat-summary wordt teruggegeven; cluster-bytes worden óók
# in `st.session_state` gezet zodat de download-knoppen in de
# Clustering-tab werken zonder hercompute.
# ============================================================
def generate_all_outputs(df: pd.DataFrame) -> Dict[str, Any]:
    """Genereer alle artefacten in één keer naar `Output/`:
    Excel, Pickle, CSV, 4 thematische QGIS-lagen, alle grafieken (PNG) en
    — indien clustering al is uitgevoerd — de cluster-GPKG met QML-stijl.
    """
    Settings.OUTPUT_DIR.mkdir(exist_ok=True)
    summary: Dict[str, Any] = {"written": [], "errors": [], "skipped": []}

    # 1. Excel
    try:
        xlsx_path = Settings.OUTPUT_DIR / "Hectopunten_filtered.xlsx"
        xlsx_path.write_bytes(export_excel_bytes(df))
        summary["written"].append(f"Excel → {xlsx_path.name}")
    except Exception as exc:
        summary["errors"].append(f"Excel: {exc}")

    # 2. Pickle
    try:
        pkl_path = Settings.OUTPUT_DIR / "Hectopunten_filtered.pkl"
        pkl_path.write_bytes(export_pickle_bytes(df))
        summary["written"].append(f"Pickle → {pkl_path.name}")
    except Exception as exc:
        summary["errors"].append(f"Pickle: {exc}")

    # 3. CSV
    try:
        csv_path = Settings.OUTPUT_DIR / "Hectopunten_filtered.csv"
        csv_path.write_bytes(df.to_csv(index=False).encode("utf-8"))
        summary["written"].append(f"CSV → {csv_path.name}")
    except Exception as exc:
        summary["errors"].append(f"CSV: {exc}")

    # 4. QGIS heatmap-kaartlagen — álle keuzes uit de interactieve kaart,
    # gekleurd zoals op het scherm, markergrootte 5.0. Workframe één keer
    # bouwen en hergebruiken voor de PDF (stap 8).
    annotations = load_annotations()
    map_work = None
    try:
        map_work = _build_map_workframe(df, annotations)
    except Exception as exc:
        summary["errors"].append(f"Kaart-workframe: {exc}")
    try:
        heat = export_all_heatmap_layers(df, work=map_work, annotations=annotations)
        for lbl, n in heat.get("counts", {}).items():
            summary["written"].append(f"QGIS-heatmaplaag {lbl}: {n:,} punten")
        summary["errors"].extend(heat.get("errors", []))
    except Exception as exc:
        summary["errors"].append(f"QGIS-heatmaplagen: {exc}")

    # 4b. Inspectie-lagen (door Data_Preparation notebook geschreven — alleen tellen)
    try:
        geom_result = collect_inspection_layers()
        for lbl, n in geom_result.get("counts", {}).items():
            if n > 0:
                summary["written"].append(f"QGIS-inspectielaag {lbl}: {n:,} features")
        summary["errors"].extend(geom_result.get("errors", []))
    except Exception as exc:
        summary["errors"].append(f"Inspectie-lagen: {exc}")

    # 5. Alle grafieken
    try:
        chart_keys = [k for k, _, _ in CHART_DEFINITIONS]
        saved = save_charts_to_disk(df, chart_keys)
        summary["written"].append(f"Grafieken (PNG): {len(saved)} bestanden")
    except Exception as exc:
        summary["errors"].append(f"Grafieken: {exc}")

    # 6. Cluster-GPKG (alleen als clustering al is uitgevoerd)
    clustered_df = st.session_state.get("_clustered_df")
    if (
        isinstance(clustered_df, pd.DataFrame)
        and "cluster" in clustered_df.columns
        and clustered_df.get("_rd_x") is not None
        and clustered_df["_rd_x"].notna().any()
    ):
        try:
            import geopandas as _gpd  # noqa: F401
            gdf_points = build_hectopunten_gdf(clustered_df)
            per_cluster = clustered_df.drop_duplicates("cluster").set_index("cluster")
            qml = build_categorized_qml(
                sorted(clustered_df["cluster"].unique().tolist()),
                cluster_pct=per_cluster["cluster_rank_pct"].to_dict(),
                cluster_scores=per_cluster["cluster_score"].to_dict(),
            )
            gpkg = to_gpkg_bytes(gdf_points, qml=qml)
            gpkg_path = Settings.OUTPUT_DIR / "hectopunten_clusters.gpkg"
            gpkg_path.write_bytes(gpkg)
            (Settings.OUTPUT_DIR / "hectopunten_clusters.qml").write_text(qml)
            st.session_state["_cluster_gpkg"] = gpkg
            st.session_state["_cluster_qml"] = qml
            st.session_state["_cluster_npts"] = len(gdf_points)
            summary["written"].append(
                f"Cluster-GPKG: {len(gdf_points):,} punten, "
                f"{clustered_df['cluster'].nunique()} clusters"
            )
        except ImportError:
            summary["skipped"].append(
                "Cluster-GPKG: `geopandas` niet geïnstalleerd."
            )
        except Exception as exc:
            summary["errors"].append(f"Cluster-GPKG: {exc}")
    else:
        summary["skipped"].append(
            "Cluster-GPKG: open eerst de Clustering-tab om clusters te berekenen."
        )

    # 7. Audit-log (CSV) — alleen schrijven als er regels bestaan, zodat
    # downstream-toolchains precies kunnen reconstrueren welke wijzigingen
    # de eindgebruiker heeft gedaan en wanneer.
    try:
        anno = load_annotations()
        log_rows = anno.get(AUDIT_LOG_KEY) or []
        if log_rows:
            log_df = pd.DataFrame(log_rows)
            log_path = Settings.OUTPUT_DIR / "hectopunt_audit_log.csv"
            log_path.write_bytes(log_df.to_csv(index=False).encode("utf-8"))
            summary["written"].append(
                f"Audit-log → {log_path.name} ({len(log_df):,} regels)"
            )
        else:
            summary["skipped"].append(
                "Audit-log: nog geen handmatige wijzigingen om te exporteren."
            )
    except Exception as exc:
        summary["errors"].append(f"Audit-log: {exc}")

    # 8. Onderhoudsrapport (PDF) — gemarkeerde punten. Hergebruikt de
    # kaart-workframe uit stap 4 zodat de vlaggen exact overeenkomen met
    # wat de kaart-tab toont.
    try:
        work_for_pdf = map_work if map_work is not None else df
        meta = {
            "generated": pd.Timestamp.now().strftime("%d-%m-%Y %H:%M"),
            "dataset": st.session_state.get("_dataset_label", "Output-dataset"),
            "filter_summary": st.session_state.get("_filter_summary",
                                                   "Standaardfilters"),
            "n_points": int(len(work_for_pdf)),
        }
        pdf_bytes = build_onderhoudsrapport_pdf(work_for_pdf, meta)
        pdf_path = Settings.OUTPUT_DIR / "onderhoudsrapport_gemarkeerd.pdf"
        pdf_path.write_bytes(pdf_bytes)
        n_flag = (int(work_for_pdf["_flag"].sum())
                  if "_flag" in work_for_pdf.columns else 0)
        summary["written"].append(
            f"Onderhoudsrapport (PDF) → {pdf_path.name} ({n_flag:,} gemarkeerd)"
        )
    except Exception as exc:
        summary["errors"].append(f"Onderhoudsrapport (PDF): {exc}")

    return summary


# ============================================================
# ANNOTATIES — Levensduur / Onderhoud (persistente JSON)
# ============================================================
ANNOTATION_COLUMNS: List[str] = [
    "Levensduur",
    "Onderhoudsintervallen",
    "Onderhoudsmoment",
    "Vlag",
    "Vlag_reden",
]
ANNOTATIONS_PATH: Path = Settings.OUTPUT_DIR / "hectopunt_annotations.json"

# Vlag-stelsel:
#   annotations[key]["Vlag"]       = "1" als rij door gebruiker gemarkeerd
#   annotations[key]["Vlag_reden"] = vrije tekst (waarom gemarkeerd)
#   audit_log                       = chronologische historie van menselijke
#                                     wijzigingen (set/unset/edit) per key.
FLAG_VALUE_ON: str = "1"
AUDIT_LOG_KEY: str = "_audit_log"


_ANNOTATION_KEY_COLS: List[str] = [
    "wvk_id", "wegnr_hmp", "hectomtrng", "hecto_lttr", "Zijde",
]


def _annotation_row_key(row: pd.Series) -> str:
    parts = [row.get(c, "") for c in _ANNOTATION_KEY_COLS]
    return "|".join("" if pd.isna(p) else str(p) for p in parts)


def _annotation_row_keys(df: pd.DataFrame) -> List[str]:
    """Vectorized batch version of `_annotation_row_key` for a whole frame.
    O(n) over column dtypes instead of O(n_rows) python-level iteration."""
    if len(df) == 0:
        return []
    pieces: List[pd.Series] = []
    for c in _ANNOTATION_KEY_COLS:
        if c in df.columns:
            s = df[c].astype("object").where(df[c].notna(), "").astype(str)
        else:
            s = pd.Series("", index=df.index, dtype=str)
        pieces.append(s.to_numpy())
    arr = np.char.add(pieces[0], "|")
    for i in range(1, len(pieces) - 1):
        arr = np.char.add(arr, pieces[i])
        arr = np.char.add(arr, "|")
    arr = np.char.add(arr, pieces[-1])
    return arr.tolist()


def load_annotations() -> Dict[str, Dict[str, str]]:
    """Annotaties + (impliciete) audit-log uit JSON laden.

    De audit-log leeft onder de speciale sleutel ``AUDIT_LOG_KEY`` zodat
    hij naast de per-rij annotaties in hetzelfde bestand blijft. Een oud
    bestand zonder log werkt gewoon door — de log wordt dan op het eerste
    schrijven aangemaakt."""
    if not ANNOTATIONS_PATH.exists():
        return {}
    try:
        return json.loads(ANNOTATIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_annotations(data: Dict[str, Dict[str, str]]) -> None:
    ANNOTATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ANNOTATIONS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _audit_user() -> str:
    """Beste-effort gebruikersnaam voor audit-trail. Streamlit heeft geen
    auth in OSS, dus pakken we OS-user als pragmatische default."""
    try:
        import os
        return os.environ.get("USER") or os.environ.get("USERNAME") or "onbekend"
    except Exception:
        return "onbekend"


def _audit_append(annotations: Dict[str, Any], key: str, action: str,
                  field: str = "", old: str = "", new: str = "",
                  note: str = "") -> None:
    """Voeg één regel toe aan de audit-log. Mutates ``annotations``."""
    log = annotations.setdefault(AUDIT_LOG_KEY, [])
    if not isinstance(log, list):
        log = []
        annotations[AUDIT_LOG_KEY] = log
    log.append({
        "ts":     pd.Timestamp.now().isoformat(timespec="seconds"),
        "user":   _audit_user(),
        "key":    key,
        "action": action,
        "field":  field,
        "old":    old,
        "new":    new,
        "note":   note,
    })


def _toggle_flag(annotations: Dict[str, Any], key: str, reden: str = "",
                 vlag_type: str = "") -> bool:
    """Zet of haal vlag eraf. Schrijft audit-regel. Returns nieuwe status.

    `vlag_type` = "positief" (groen) of "negatief" (rood); bepaalt de
    ring-/markeringskleur op de kaart en in het PDF-rapport."""
    rec = dict(annotations.get(key) or {})
    was_on = rec.get("Vlag") == FLAG_VALUE_ON
    if was_on:
        rec.pop("Vlag", None)
        rec.pop("Vlag_reden", None)
        rec.pop("Vlag_type", None)
        _audit_append(annotations, key, "flag_off",
                      field="Vlag", old=FLAG_VALUE_ON, new="", note=reden)
        new_on = False
    else:
        rec["Vlag"] = FLAG_VALUE_ON
        if reden:
            rec["Vlag_reden"] = reden
        if vlag_type:
            rec["Vlag_type"] = vlag_type
        _audit_append(annotations, key, "flag_on",
                      field="Vlag", old="", new=FLAG_VALUE_ON, note=reden)
        # Maak meteen de fotomap aan zodat de inspecteur er foto's in kan zetten.
        try:
            _hectopunt_foto_dir(key, create=True)
        except Exception:
            pass
        new_on = True
    # alleen niet-lege velden behouden
    rec = {k: v for k, v in rec.items() if v}
    if rec:
        annotations[key] = rec
    else:
        annotations.pop(key, None)
    return new_on


def _flagged_keys(annotations: Dict[str, Any]) -> set:
    out = set()
    for k, v in annotations.items():
        if k == AUDIT_LOG_KEY:
            continue
        if isinstance(v, dict) and v.get("Vlag") == FLAG_VALUE_ON:
            out.add(k)
    return out


# ── Foto-map per gemarkeerd hectopunt ─────────────────────────
# Elke gemarkeerde hectopunt krijgt een eigen mapje onder
# `Output/hectopunt_fotos/`. De inspecteur dropt daar 1–2 foto's in
# (handmatig of via de uploader bij de vlag); die foto's komen daarna
# in het PDF-onderhoudsrapport op de detailpagina van dat punt.
_FOTO_ROOT: Path = Settings.OUTPUT_DIR / "hectopunt_fotos"
_FOTO_EXTS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff",
}


def _hectopunt_foto_dirname(key: str) -> str:
    """Filesystem-veilige, leesbare mapnaam afgeleid van de annotatie-key.

    Leesbaar deel (weg/hm/zijde/letter) + 6-char hash van de volledige key,
    zodat de naam deterministisch én uniek is — ook als twee punten dezelfde
    weg/hm delen maar een ander `wvk_id`."""
    import re
    import hashlib

    parts = (key.split("|") + ["", "", "", "", ""])[:5]
    _wvk, weg, hm, lttr, zijde = parts
    bits: List[str] = []
    if weg.strip():
        bits.append(f"weg{weg.strip()}")
    if hm.strip():
        bits.append(f"hm{hm.strip()}")
    if zijde.strip():
        bits.append(zijde.strip())
    if lttr.strip():
        bits.append(f"l{lttr.strip()}")
    label = "_".join(bits) or "hectopunt"
    label = re.sub(r"[^0-9A-Za-z._-]+", "_", label).strip("_")[:60] or "hectopunt"
    suffix = hashlib.md5(key.encode("utf-8")).hexdigest()[:6]
    return f"{label}__{suffix}"


def _hectopunt_foto_dir(key: str, create: bool = False) -> Path:
    """Pad naar de fotomap van één hectopunt (optioneel direct aanmaken)."""
    d = _FOTO_ROOT / _hectopunt_foto_dirname(key)
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def _list_foto_files(d: Path) -> List[Path]:
    """Gesorteerde lijst beeldbestanden in een fotomap (leeg als map ontbreekt)."""
    if not d.exists():
        return []
    return sorted(
        p for p in d.iterdir()
        if p.is_file() and p.suffix.lower() in _FOTO_EXTS
    )


# ============================================================
# TAB RENDERERS — één functie per tab
# ============================================================
# Externe link-kolommen; centraal gedefinieerd zodat de detailrail- en
# attribuut-helpers (hieronder) ze kunnen uitsluiten en labelen.
_LINK_COLUMNS: Set[str] = {"streetsmart_link", "google_maps_link", "pdok_viewer_link"}
# Korte, leesbare labels voor de externe links in de detailrail (i.p.v. de
# ruwe kolomnamen `*_link`).
_RAIL_LINK_LABELS: Dict[str, str] = {
    "streetsmart_link": "StreetSmart",
    "google_maps_link": "Google Maps",
    "pdok_viewer_link": "PDOK",
}


# ── Asset-overview helpers + plots voor de Kaart-tab ──────────────
def _safe_num(v: Any) -> Optional[float]:
    """Cast veilig naar float; None bij NaN/missing/onparsebaar."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


DEFAULT_INTERVAL_YEARS = 8


def _resolve_interval_total(ann: Dict[str, str]) -> int:
    """Onderhoudsintervallen → Levensduur → fallback (jaren)."""
    for key in ("Onderhoudsintervallen", "Levensduur"):
        raw = ann.get(key)
        if raw in (None, ""):
            continue
        try:
            f = float(str(raw).strip().replace(",", "."))
            if not pd.isna(f):
                return int(round(f))
        except (TypeError, ValueError):
            continue
    return DEFAULT_INTERVAL_YEARS


def compute_remaining_life_series(
    df: pd.DataFrame,
    annotations: Optional[Dict[str, Dict[str, str]]] = None,
) -> pd.Series:
    """Vectorised resterende levensduur (jr) per rij.

    Eén bron van waarheid: KPI-card 'Resterende levensduur' én de tabel
    onder de asset-details lezen beide deze kolom.

    Voorkeur: de voorberekende `onderhoudsmoment`-kolom (uit het dataprep-
    notebook) → ``remaining = onderhoudsmoment − huidig_jaar``. Zo sluit de
    score exact aan op de levensduur-grafiek en de 'eerstvolgend onderhoud'-
    KPI. Voor rijen zonder onderhoudsmoment valt de oude logica in:
        remaining = max(interval_total − round(leeftijd), 0)
    waar interval_total uit annotaties komt (Onderhoudsintervallen →
    Levensduur → DEFAULT_INTERVAL_YEARS) en leeftijd uit `_leeftijd`.
    """
    if annotations is None:
        annotations = load_annotations()

    # ── Primair: onderhoudsmoment-kolom → jaren tot eerstvolgend onderhoud ──
    moment_raw = (df["onderhoudsmoment"] if "onderhoudsmoment" in df.columns
                  else pd.Series(np.nan, index=df.index))
    moment = pd.to_numeric(moment_raw, errors="coerce")
    today_year = int(pd.Timestamp.today().year)
    primary = moment - today_year

    # ── Fallback: oude interval − leeftijd ──
    leeftijd = pd.to_numeric(df.get("_leeftijd"), errors="coerce")
    if not annotations:
        intervals = pd.Series(DEFAULT_INTERVAL_YEARS, index=df.index, dtype="float64")
    else:
        keys = _annotation_row_keys(df)
        intervals = pd.Series(
            [_resolve_interval_total(annotations.get(k, {})) for k in keys],
            index=df.index, dtype="float64",
        )
    age = leeftijd.round()
    fallback = (intervals - age)
    fallback = fallback.where(age.notna(), other=np.nan)

    remaining = primary.where(moment.notna(), other=fallback)
    return remaining.clip(lower=0)


# ── Slijtage-model (AI-formule encapsulatie) ──────────────────────
# Waarheidstabel: deklaagleeftijd × bocht-geometrie × verkeer → slijtage/jr.
# Bron-tabel (in %/jr op de 0-100% kwaliteitsschaal):
#
#   Aanlegdatum     Hoek/straal       Verkeer        Slijtage
#   <2 jaar         Kort + scherp     ≥ 112 (×10³)   11.2 %/jr (Hoog)
#   2-6 jaar        Lang + scherp     ≥ 80  (×10³)    8.0 %/jr (Middel)
#   ≥7 jaar         —                 ≥ 40  (×10³)    4.0 %/jr (Laag)
#
# Tweak de drempels en rates hieronder als de AI-formule herijkt wordt.
WEAR_RULES: List[Dict[str, Any]] = [
    {
        "label":         "Hoog",
        "leeftijd_max":  2.0,
        "geom":          "kort_scherp",
        "verkeer_min":   112_000,
        "rate_pct_yr":   11.2,
        "description":   "Jong deklaag + scherpe korte bocht + zwaar verkeer",
    },
    {
        "label":         "Middel",
        "leeftijd_min":  2.0,
        "leeftijd_max":  6.0,
        "geom":          "lang_scherp",
        "verkeer_min":   80_000,
        "rate_pct_yr":   8.0,
        "description":   "Mature deklaag + lange scherpe bocht + medium verkeer",
    },
    {
        "label":         "Laag",
        "leeftijd_min":  7.0,
        "geom":          None,
        "verkeer_min":   40_000,
        "rate_pct_yr":   4.0,
        "description":   "Ouder deklaag, lage verkeersintensiteit",
    },
]
WEAR_DEFAULT_RATE_PCT_YR = 5.5  # fallback als geen bucket matcht


def _kpi_card_html(label: str, value: str, delta: Optional[str] = None,
                   bg: str = "#f3f4f6", accent: str = "#9ca3af",
                   sub: Optional[str] = None) -> str:
    """Compacte KPI-card met linker accent-balk en optionele achtergrondkleur."""
    # Lettergroottes groot gehouden: dashboard draait op een 65" TV die van
    # afstand door oudere kijkers wordt gelezen — leesbaarheid boven dichtheid.
    delta_html = (
        f'<div style="font-size:10px;color:#555;margin-top:1px;">{delta}</div>'
        if delta is not None else ""
    )
    sub_html = (
        f'<div style="font-size:9px;color:#777;margin-top:1px;font-style:italic;">{sub}</div>'
        if sub else ""
    )
    return (
        f'<div style="background:{bg};border-left:6px solid {accent};'
        f'padding:7px 13px;border-radius:6px;height:100%;">'
        f'<div style="font-size:9px;color:#555;text-transform:uppercase;'
        f'letter-spacing:0.4px;font-weight:700;">{label}</div>'
        f'<div style="font-size:21px;font-weight:800;color:#1a1a1a;'
        f'line-height:1.05;margin-top:2px;">{value}</div>'
        f'{delta_html}{sub_html}</div>'
    )


# Achtergrondkleur van de asset-grafieken — wit (origineel, professioneler).
_ASSET_FIG_BG = "#ffffff"


def _asset_axes(fig: Figure, title: str) -> Any:
    """Standaard ax met compacte titel — gebruikt door alle asset-plots."""
    ax = fig.add_subplot(111)
    ax.set_facecolor(_ASSET_FIG_BG)
    ax.set_title(title, fontsize=9, fontweight="bold",
                 color=Settings.COLOR_BLUE_PRIMARY, pad=4, loc="left")
    return ax


def _empty_asset_plot(title: str, message: str,
                      figsize: Tuple[float, float] = (3.0, 2.2)) -> Figure:
    fig = Figure(figsize=figsize, facecolor=_ASSET_FIG_BG)
    ax = _asset_axes(fig, title)
    ax.text(0.5, 0.45, message, ha="center", va="center",
            fontsize=9, color="#9aa0a6",
            transform=ax.transAxes, style="italic")
    ax.axis("off")
    return fig


def plot_curve_geometry(angle: Optional[float],
                        radius: Optional[float]) -> Figure:
    """Eén gecombineerde schets van draaihoek + boogstraal.

    * **Boog-radius** is log-geschaald van de werkelijke boogstraal:
      kleine R → strak gekromd, grote R → flauwe boog.
    * **Boog-sweep** = hoeksom (totale draai over alle bochten in de rij;
      visueel afgekapt op 180°).
    * Aangrenzende grijze lijntjes representeren de aan- en afvoerende
      wegsegmenten (tangentiaal aan de boog).
    """
    has_angle  = angle is not None and not pd.isna(angle)
    has_radius = radius is not None and not pd.isna(radius)

    # Vaste hoogte (2.8 in × 100 dpi = 280 px); samen met de verkeersgrafiek
    # (270 px) ≈ kaarthoogte (560 px) zodat de rechterkolom gelijk eindigt.
    fig = Figure(figsize=(3.0, 2.8), facecolor=_ASSET_FIG_BG)
    ax = _asset_axes(fig, "Bocht-geometrie")
    ax.set_aspect("equal")
    ax.axis("off")

    if not has_angle and not has_radius:
        ax.text(0.5, 0.5, "Geen bocht-data",
                ha="center", va="center", fontsize=9,
                color="#9aa0a6", transform=ax.transAxes, style="italic")
        fig.subplots_adjust(left=0.02, right=0.98, top=0.88, bottom=0.04)
        return fig

    # ── Bocht in z'n geheel ────────────────────────────────────────────
    # Vaste visuele straal: de échte straalwaarde staat ín de streep, dus de
    # tekening hoeft niet op schaal. De boog start RECHTS (0° = 3-uur, waar de
    # straal-streep eindigt) en draait tegen de klok in over de volledige
    # draaihoek — hoe groter de hoek, hoe verder de boog doorloopt.
    visual_r = 1.0
    cx, cy = 0.0, 0.0

    if has_angle:
        ang_val = float(angle)
        sweep = min(abs(ang_val), 360.0)          # toon de hele bocht (tot 360°)
    else:
        ang_val = None
        sweep = 30.0

    # Visuele ondergrens: een kleine draaihoek tekent anders een nauwelijks
    # zichtbaar stompje. De schets is niet op schaal (de échte waarde staat in
    # het label), dus we dwingen een minimale zichtbare boog af.
    visual_sweep = max(sweep, 55.0)
    theta = np.deg2rad(np.linspace(0.0, visual_sweep, 360))
    arc_x = cx + visual_r * np.cos(theta)
    arc_y = cy + visual_r * np.sin(theta)
    ax.plot(arc_x, arc_y, color="#dfe6ee", lw=12,
            solid_capstyle="round", zorder=1)
    ax.plot(arc_x, arc_y, color=Settings.COLOR_BLUE_PRIMARY, lw=5.0,
            solid_capstyle="round", zorder=2)

    # ── Straal als BREDE streep van middelpunt naar rechts (0°), waarde erín ─
    rad_str = (f"{float(radius):,.0f} m".replace(",", ".")
               if has_radius else "—")
    ax.plot([cx, cx + visual_r], [cy, cy],
            color=Settings.COLOR_GREY_PRIMARY, lw=18,
            solid_capstyle="butt", zorder=3)
    ax.text(cx + visual_r / 2.0, cy, f"R = {rad_str}",
            fontsize=9, fontweight="bold", ha="center", va="center",
            color="white", zorder=4)
    ax.scatter([cx], [cy], s=26, color=Settings.COLOR_GREY_PRIMARY,
               zorder=4, edgecolor="white", linewidths=1.0)

    # ── Draaihoek groot ín de boog ─────────────────────────────────────
    ang_str = f"{ang_val:.0f}°" if ang_val is not None else "—"
    mid = np.deg2rad(visual_sweep / 2.0)
    ax.text(cx + visual_r * 0.42 * np.cos(mid),
            cy + visual_r * 0.42 * np.sin(mid) + 0.18,
            ang_str, fontsize=18, fontweight="bold",
            ha="center", va="center",
            color=Settings.COLOR_BLUE_PRIMARY, zorder=4)

    # ── Scherp/flauw categorie linksboven (alleen als R bekend) ────────
    if has_radius:
        R = float(radius)
        cat = "Scherp" if R < Settings.CURVE_THRESHOLD else "Flauw"
        cat_color = "#c0392b" if R < Settings.CURVE_THRESHOLD \
            else Settings.COLOR_GREEN_PRIMARY
        ax.text(0.02, 0.98, cat, transform=ax.transAxes,
                fontsize=10, fontweight="bold", ha="left", va="top",
                color=cat_color, style="italic")

    # Begrens strak om de WERKELIJK getekende vorm (boog + straal-streep), niet
    # om de hele denkbeeldige cirkel — anders blijft de helft van het paneel
    # leeg (lege onder- en linkerkwadranten = de witruimte aan de buitenkant).
    # Vierkante bounding box rond de inhoud zodat aspect="equal" het paneel vult
    # en de tekening (incl. tekst) groot genoeg wordt voor de TV-weergave.
    xs = np.concatenate([arc_x, [cx, cx + visual_r]])
    ys = np.concatenate([arc_y, [cy]])
    x0, x1 = float(xs.min()), float(xs.max())
    y0, y1 = float(ys.min()), float(ys.max())
    box_cx, box_cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    half = max(x1 - x0, y1 - y0) / 2.0 + 0.22   # pad voor dikke lijnen + labels
    ax.set_xlim(box_cx - half, box_cx + half)
    ax.set_ylim(box_cy - half, box_cy + half)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.90, bottom=0.04)
    return fig


def _traffic_heatmap_color(value: Optional[float], col: str,
                           df: Optional[pd.DataFrame]) -> str:
    """RdYlGn-kleur voor één verkeerscategorie t.o.v. het bereik in de
    gefilterde dataset. Hoog = rood (slechter / drukker), laag = groen."""
    if value is None or df is None or col not in df.columns:
        return Settings.COLOR_GREY_PRIMARY
    pop = pd.to_numeric(df[col], errors="coerce").dropna()
    if pop.empty:
        return Settings.COLOR_GREY_PRIMARY
    vmin, vmax = float(pop.min()), float(pop.max())
    if vmin == vmax:
        return Settings.COLOR_GREY_PRIMARY
    pct = max(0.0, min(1.0, (float(value) - vmin) / (vmax - vmin)))
    r, g, b, _ = RDYLGN_R_CMAP(pct)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _traffic_gauge_ax(fig: Figure, rect: Tuple[float, float, float, float],
                      value: float, vmin: Optional[float],
                      vmax: Optional[float]) -> None:
    """Horizontale RdYlGn_r-gradientbalk (groen = rustig, rood = druk) op `rect`
    (figuur-fractie), met een ▼-pin op de relatieve positie van `value` binnen
    het dataset-bereik vmin..vmax. Zonder geldig bereik: alleen de balk."""
    gax = fig.add_axes(rect)
    gax.imshow(np.linspace(0, 1, 256).reshape(1, -1), aspect="auto",
               cmap="RdYlGn_r", extent=[0, 1, 0, 1])
    gax.set_xlim(0, 1)
    gax.set_ylim(0, 1)
    gax.set_xticks([])
    gax.set_yticks([])
    for sp in gax.spines.values():
        sp.set_edgecolor("#999")
        sp.set_linewidth(0.5)
    if vmin is not None and vmax is not None and vmax > vmin:
        pct = max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))
        gax.plot([pct, pct], [0, 1], color="#111", lw=1.5, zorder=4)
        gax.scatter([pct], [1.0], marker="v", s=42, color="#111",
                    zorder=5, clip_on=False)


def plot_traffic_composition(row: pd.Series,
                             df: Optional[pd.DataFrame] = None) -> Figure:
    """Verkeersopbouw als per-categorie kleur-uitlegbalken (geen donut meer).

    Per categorie een gradientbalk met een ▼-pin op de relatieve drukte van
    dít hectopunt en rechts de max-waarde (= drukste hectopunt), plus 'dit
    punt: N (pct%)'. Kleur = heatmap (RdYlGn_r) t.o.v. het bereik van die
    categorie over de hele gefilterde dataset (groen = rustig, rood = druk)."""
    totaal = _safe_num(row.get("totaal_voertuig"))
    cats = [
        (_safe_num(row.get("klein_voertuig")),
         "Personenauto's", "klein_voertuig"),
        (_safe_num(row.get("middel_voertuig")),
         "Bestelbusjes en kleine vrachtwagens", "middel_voertuig"),
        (_safe_num(row.get("lang_voertuig")),
         "Lange vrachtwagens", "lang_voertuig"),
    ]

    # (value, label, color, vmin, vmax) — alleen aanwezige categorieën.
    parts: List[Tuple[float, str, str, Optional[float], Optional[float]]] = []
    for v, lbl, col in cats:
        if v is None or v <= 0:
            continue
        vmin = vmax = None
        if df is not None and col in df.columns:
            pop = pd.to_numeric(df[col], errors="coerce").dropna()
            if not pop.empty:
                vmin, vmax = float(pop.min()), float(pop.max())
        parts.append((v, lbl, _traffic_heatmap_color(v, col, df), vmin, vmax))

    if not parts:
        return _empty_asset_plot("Verkeersopbouw", "Geen verkeersdata")

    values = [p[0] for p in parts]
    total_split = sum(values)

    def _fmt(x: float) -> str:
        return f"{int(round(x)):,}".replace(",", ".")

    fig = Figure(figsize=(3.0, 2.7), facecolor=_ASSET_FIG_BG)
    fig.suptitle("Verkeersopbouw", fontsize=9, fontweight="bold",
                 color=Settings.COLOR_BLUE_PRIMARY, x=0.04, y=0.985, ha="left")
    # Kleur-uitleg + eenheid (volle breedte, onder de titel).
    fig.text(0.04, 0.952, "Aantallen: motorvoertuigen per etmaal (24 u, gem. werkdag).",
             fontsize=6.1, color="#333", ha="left", va="top", fontweight="bold")
    fig.text(0.04, 0.928, "Kleur = relatieve drukte t.o.v. alle hectopunten.",
             fontsize=6.1, color="#555", ha="left", va="top")
    fig.text(0.04, 0.906, "groen = rustig · rood = druk · ▼ = dit punt",
             fontsize=6.1, color="#555", ha="left", va="top")
    # Totaal (stond eerst in het donut-midden; donut is verwijderd omdat de
    # balken dezelfde verdeling al tonen — gebruikersverzoek).
    if totaal is not None and totaal > 0:
        fig.text(0.04, 0.882, f"Totaal: {_fmt(totaal)} mvt/etmaal",
                 fontsize=7, fontweight="bold", color="#1a1a1a",
                 ha="left", va="top")

    # Per categorie naam + gradient-uitlegbalk met pin + max-waarde — nu over
    # de VOLLE breedte (geen donut links meer).
    import textwrap
    n = len(parts)
    top, bottom = 0.80, 0.06
    block = (top - bottom) / n
    gx0, gx1 = 0.06, 0.80
    for i, (v, lbl, color, vmin, vmax) in enumerate(parts):
        btop = top - i * block
        fig.text(gx0, btop, "■", fontsize=8.5, color=color,
                 ha="left", va="top")
        names = textwrap.wrap(lbl, width=48)[:2]
        for j, nl in enumerate(names):
            fig.text(gx0 + 0.035, btop - j * 0.030, nl, fontsize=7,
                     fontweight="bold", color="#222", ha="left", va="top")
        bar_h = 0.05
        bar_bottom = btop - len(names) * 0.030 - 0.016 - bar_h
        _traffic_gauge_ax(fig, [gx0, bar_bottom, gx1 - gx0, bar_h],
                          v, vmin, vmax)
        if vmax is not None:
            fig.text(gx1 + 0.012, bar_bottom + bar_h / 2, "max\n" + _fmt(vmax),
                     fontsize=6.2, color="#333", ha="left", va="center")
        pct = v / total_split * 100 if total_split > 0 else 0.0
        fig.text(gx0, bar_bottom - 0.008,
                 f"dit punt: {_fmt(v)}  ({pct:.0f}%)",
                 fontsize=6.5, color="#444", ha="left", va="top")
    return fig


# ── Slijtage-truthtable: bocht → levensduur · verkeer → cyclus-cap ─
WEAR_PLOT_RULES: Dict[str, Any] = {
    # Levensduur (jr). Eerste match in lijst wint.
    "lifespan": [
        {"label": "Scherpe bocht (>15°)",
         "cond":  lambda h: h is not None and abs(h) > 15,
         "years": 5},
        {"label": "Standaard / onbekend",
         "cond":  lambda h: True,
         "years": 12},
    ],
    # Zwaar verkeer >= 20e percentiel = top 80% → cyclus gecapt op 10 jr.
    "heavy_traffic_percentile": 20,
    "heavy_traffic_cap_years":  10,
    # Convexe decay: y = 100·(1 − (t/L)^p). p>1 = trager begin, sneller einde.
    "decay_exponent": 2.0,
    "year_min": 2010,
    # year_max stuurt de reset-/onderhoud-MATH: resets t/m 2040 zodat de
    # voorberekende `onderhoudsmoment` (loopt t/m 2037) altijd berekend kan
    # worden en KPI/tabel consistent blijven.
    "year_max": 2040,
    # axis_year_max stuurt ALLEEN de zichtbare x-as van de grafieken — op
    # gebruikersverzoek tot 2030. Curve/markers verder dan 2030 worden door de
    # x-limiet vanzelf afgekapt; de math hierboven blijft ongemoeid op 2040.
    "axis_year_max": 2030,
}


def _wear_lifespan(hoek: Optional[float]) -> Tuple[int, str]:
    for rule in WEAR_PLOT_RULES["lifespan"]:
        if rule["cond"](hoek):
            return rule["years"], rule["label"]
    return 12, "Standaard / onbekend"


def _is_heavy_top80(lang_vt: Optional[float],
                    df: Optional[pd.DataFrame]) -> bool:
    if df is None or lang_vt is None or "_lang_vt" not in df.columns:
        return False
    pop = pd.to_numeric(df["_lang_vt"], errors="coerce").dropna()
    if len(pop) == 0:
        return False
    p = float(np.nanpercentile(pop, WEAR_PLOT_RULES["heavy_traffic_percentile"]))
    return lang_vt >= p


def _latest_aanleg_year(raw: Any, default: int) -> int:
    if pd.isna(raw):
        return default
    best: Optional[int] = None
    for part in str(raw).split(","):
        dt = pd.to_datetime(part.strip(), errors="coerce")
        if pd.notna(dt):
            y = int(dt.year)
            if best is None or y > best:
                best = y
    return best if best is not None else default


def _wear_cycle_len_for_row(row: pd.Series,
                             df: Optional[pd.DataFrame]) -> int:
    """Cyclus-lengte (jr) per hectopunt — exact dezelfde formule als de
    levensduur-grafiek. Wordt ook door de KPI- en tabel-kolommen gebruikt,
    zodat 'eerstvolgend onderhoud' overal hetzelfde jaar oplevert.

    Voorkeur: de voorberekende `levensduur`-kolom (uit het dataprep-notebook).
    Alleen als die ontbreekt valt de oude bocht/verkeer-truthtable in."""
    lev = _safe_num(row.get("levensduur"))
    if lev is not None and lev > 0:
        return int(round(lev))
    hoek_raw = _safe_num(row.get("_max_hoek"))
    lifespan_yr, _ = _wear_lifespan(hoek_raw)
    heavy_top80 = _is_heavy_top80(_safe_num(row.get("_lang_vt")), df)
    if heavy_top80:
        return min(lifespan_yr, WEAR_PLOT_RULES["heavy_traffic_cap_years"])
    return lifespan_yr


def _wear_resets(anchor: float, cycle_len: int,
                  year_min: int, year_max: int) -> List[float]:
    """Lijst van alle reset-momenten (aanleg- + voorspelde onderhouds-jaren)
    binnen [year_min - cycle_len, year_max + cycle_len], gesorteerd."""
    resets: List[float] = []
    y = float(anchor)
    while y >= year_min - cycle_len:
        resets.append(y)
        y -= cycle_len
    y = float(anchor) + cycle_len
    while y <= year_max + cycle_len:
        resets.append(y)
        y += cycle_len
    resets.sort()
    return resets


def _next_onderhoud_year_for_row(row: pd.Series,
                                  df: Optional[pd.DataFrame],
                                  today_year: int) -> Optional[int]:
    """Eerstvolgend onderhoudsmoment (jaar) — afgeleid uit de chart-logica
    zodat KPI/tabel altijd in lijn zijn met de grafiek.

    Voorkeur: de voorberekende `onderhoudsmoment`-kolom (uit het dataprep-
    notebook). Alleen als die ontbreekt valt de oude reset-extrapolatie in."""
    moment = _safe_num(row.get("onderhoudsmoment"))
    if moment is not None and moment > 0:
        return int(round(moment))
    anchor_year = _latest_aanleg_year(row.get("aanlegdatum"), default=0)
    if anchor_year <= 0:
        return None
    cycle_len = _wear_cycle_len_for_row(row, df)
    resets = _wear_resets(
        anchor=anchor_year, cycle_len=cycle_len,
        year_min=WEAR_PLOT_RULES["year_min"],
        year_max=WEAR_PLOT_RULES["year_max"],
    )
    future = [r for r in resets if r >= today_year]
    return int(round(future[0])) if future else None


def _draw_wear_on_ax(ax: Any, row: pd.Series,
                     df: Optional[pd.DataFrame],
                     *, show_xlabel: bool = True,
                     show_xticklabels: bool = True,
                     show_nu_annotation: bool = True,
                     show_legend: bool = True) -> None:
    """Tekent de levensduur-curve (drempels, blauwe convex-decay, nu-lijn,
    eerstvolgend onderhoud) op een bestaande ax. Wordt gebruikt door
    ``plot_levensduur_deklagen_stacked`` — gridspec-figuur waar de
    deklagen-tijdslijn er strak tegenaan zit (hspace=0).
    Zo blijft één bron van waarheid voor de curve-logica."""
    YEAR_MIN = WEAR_PLOT_RULES["year_min"]
    YEAR_MAX = WEAR_PLOT_RULES["year_max"]
    AXIS_MAX = WEAR_PLOT_RULES["axis_year_max"]   # zichtbare x-as-einde
    P_DECAY  = WEAR_PLOT_RULES["decay_exponent"]
    today_year = int(pd.Timestamp.today().year)

    cycle_len = _wear_cycle_len_for_row(row, df)
    anchor = _latest_aanleg_year(row.get("aanlegdatum"), default=YEAR_MIN + 5)
    resets = _wear_resets(anchor, cycle_len, YEAR_MIN, YEAR_MAX)

    next_onderhoud = _next_onderhoud_year_for_row(row, df, today_year)
    curve_end = float(next_onderhoud) if next_onderhoud is not None \
                else float(AXIS_MAX)
    curve_end = min(curve_end, float(AXIS_MAX))

    step = 0.05
    xs = np.arange(YEAR_MIN, curve_end + step, step)
    sorted_resets = np.asarray(sorted(resets), dtype=float)
    idx = np.searchsorted(sorted_resets, xs, side="right") - 1
    np.clip(idx, 0, None, out=idx)
    prev_for_x = sorted_resets[idx]
    t = np.clip((xs - prev_for_x) / cycle_len, 0.0, 1.0)
    ys = 100.0 * (1.0 - t ** P_DECAY)

    eps = step / 2.0
    extra_x: List[float] = []
    extra_y: List[float] = []
    for r in resets:
        if YEAR_MIN < r <= curve_end:
            extra_x.append(r - eps); extra_y.append(0.0)
            extra_x.append(r);       extra_y.append(100.0)
    if extra_x:
        xs_full = np.concatenate([xs, np.array(extra_x)])
        ys_full = np.concatenate([ys, np.array(extra_y)])
        order = np.argsort(xs_full)
        xs_full = xs_full[order]
        ys_full = ys_full[order]
    else:
        xs_full, ys_full = xs, ys

    ax.axhspan(0, 30, color="#fee2e2", alpha=0.55, zorder=1)
    ax.axhline(30, color="#dc2626", lw=1.0, ls="--", alpha=0.75,
               zorder=2, label="Kritiek (30%)")
    ax.axhline(60, color="#d97706", lw=1.0, ls="--", alpha=0.75,
               zorder=2, label="Waarschuwing (60%)")

    mask_past = xs_full <= today_year
    mask_future = xs_full >= today_year
    if mask_past.any():
        ax.plot(xs_full[mask_past], ys_full[mask_past],
                color=Settings.COLOR_BLUE_PRIMARY, lw=2.2, zorder=4,
                label="Levensduur (geregistreerd)")
    if mask_future.any():
        ax.plot(xs_full[mask_future], ys_full[mask_future],
                color=Settings.COLOR_BLUE_PRIMARY, lw=2.0, ls="--",
                dashes=(4, 3), alpha=0.85, zorder=4,
                label="Levensduur (voorspeld)")

    if YEAR_MIN <= today_year <= AXIS_MAX:
        ax.axvline(today_year, color="#ea580c", lw=2.5, ls="-",
                   alpha=1.0, zorder=6, label=f"Nu ({today_year})")
        if show_nu_annotation:
            ax.annotate("nu", xy=(today_year, 0), xycoords="data",
                        xytext=(0, -42), textcoords="offset points",
                        ha="center", va="top",
                        fontsize=9, fontweight="bold", color="#ea580c",
                        annotation_clip=False, zorder=9)

    if next_onderhoud is not None and YEAR_MIN <= next_onderhoud <= AXIS_MAX:
        ax.axvline(next_onderhoud, color=Settings.COLOR_GREEN_PRIMARY,
                   lw=1.4, ls=":", alpha=0.85, zorder=5,
                   label=f"Volgend onderhoud ({next_onderhoud})")

    ax.set_xlim(YEAR_MIN, AXIS_MAX + 1.0)
    ax.set_ylim(0, 110)
    ax.set_xticks(range(YEAR_MIN, AXIS_MAX + 1, 5))
    if show_xlabel:
        ax.set_xlabel("Jaar", fontsize=8, color="#555")
    if not show_xticklabels:
        ax.tick_params(axis="x", labelbottom=False)
    ax.set_ylabel("Kwaliteit (%)", fontsize=8, color="#555")
    ax.tick_params(labelsize=7, colors="#666")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#cccccc")
    ax.spines["left"].set_color("#cccccc")

    if show_legend:
        ax.legend(loc="lower left", fontsize=7, framealpha=0.95,
                  edgecolor="#dddddd", ncol=3, columnspacing=1.0,
                  handlelength=2.0)


def _draw_aanleg_on_ax(ax: Any, row: pd.Series,
                       df: Optional[pd.DataFrame],
                       *, show_legend: bool = True) -> None:
    """Tekent de deklagen-tijdlijn (alleen de geregistreerde aanleg-momenten;
    géén voorspelde onderhoudsbollen op verzoek) op een bestaande ax. Wordt
    gebruikt door ``plot_levensduur_deklagen_stacked``."""
    YEAR_MIN = WEAR_PLOT_RULES["year_min"]
    AXIS_MAX = WEAR_PLOT_RULES["axis_year_max"]   # zichtbare x-as-einde
    today_year = int(pd.Timestamp.today().year)

    registered_years: List[int] = []
    raw = row.get("aanlegdatum")
    if pd.notna(raw):
        for part in str(raw).split(","):
            part = part.strip()
            if not part:
                continue
            dt = pd.to_datetime(part, errors="coerce")
            if pd.notna(dt) and YEAR_MIN <= dt.year <= AXIS_MAX:
                registered_years.append(int(dt.year))
    registered_years = sorted(set(registered_years))

    y_line = 0.5
    ax.hlines(y_line, YEAR_MIN, AXIS_MAX, color="#dddddd", lw=1.0, zorder=1)

    if registered_years:
        ax.scatter(registered_years, [y_line] * len(registered_years),
                   s=140, color=Settings.COLOR_GREEN_PRIMARY,
                   edgecolor="white", linewidths=1.8, zorder=4,
                   label="Geregistreerde aanleg")
        for ry in registered_years:
            ax.text(ry, y_line + 0.22, str(ry), ha="center", va="bottom",
                    fontsize=7, color=Settings.COLOR_GREEN_PRIMARY,
                    fontweight="bold")

    if YEAR_MIN <= today_year <= AXIS_MAX:
        ax.axvline(today_year, color="#ea580c", lw=2.0, ls="-",
                   alpha=1.0, zorder=5, label=f"Nu ({today_year})")

    ax.set_xlim(YEAR_MIN, AXIS_MAX + 1.0)
    ax.set_ylim(0, 1.0)
    ax.set_xticks(range(YEAR_MIN, AXIS_MAX + 1, 5))
    ax.set_yticks([])
    ax.tick_params(axis="x", labelsize=7, colors="#666")
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#cccccc")
    if show_legend:
        ax.legend(loc="upper right", fontsize=7, framealpha=0.95,
                  edgecolor="#dddddd", ncol=3, columnspacing=1.0,
                  handlelength=2.0)


def plot_levensduur_deklagen_stacked(
    row: pd.Series, df: Optional[pd.DataFrame] = None,
) -> Figure:
    """Levensduur-curve + deklagen-tijdslijn op één compacte figuur.

    Layout:
      * Twee subplots met gedeelde x-as, kleine ``hspace`` zodat de
        titel van de onderste subplot niet over de inhoud van de
        bovenste valt.
      * Helper-functies krijgen ``show_legend=False`` zodat hun
        individuele legendes niet over titels heen vallen — er is
        één gecombineerde legenda onderaan via ``fig.legend``.
      * Compactere figsize zodat de grafiek niet de helft van het
        scherm vult.
    """
    YEAR_MIN = WEAR_PLOT_RULES["year_min"]
    YEAR_MAX = WEAR_PLOT_RULES["axis_year_max"]   # titels = zichtbaar bereik

    # use_container_width=True pint de breedte op de container: dus alleen de
    # aspect (figh/figw) bepaalt de schermhoogte en figw de tekstgrootte op het
    # scherm (grotere figw → kleinere tekst). Bredere + lagere doek = korter
    # én kleinere tekst (gebruikersverzoek).
    fig = Figure(figsize=(11.0, 2.9), facecolor=_ASSET_FIG_BG)
    gs = fig.add_gridspec(2, 1, height_ratios=[3.2, 1.0], hspace=0.42)
    ax_top = fig.add_subplot(gs[0, 0])
    ax_bot = fig.add_subplot(gs[1, 0], sharex=ax_top)
    ax_top.set_facecolor(_ASSET_FIG_BG)
    ax_bot.set_facecolor(_ASSET_FIG_BG)

    ax_top.set_title(
        f"Levensduurverloop {YEAR_MIN}-{YEAR_MAX}",
        fontsize=8, fontweight="bold",
        color=Settings.COLOR_BLUE_PRIMARY, pad=4, loc="left",
    )
    _draw_wear_on_ax(
        ax_top, row, df,
        show_xlabel=False,
        show_xticklabels=False,
        show_nu_annotation=False,
        show_legend=False,
    )

    ax_bot.set_title(
        f"Deklagen — aanleg {YEAR_MIN}-{YEAR_MAX}",
        fontsize=8, fontweight="bold",
        color=Settings.COLOR_BLUE_PRIMARY, pad=4, loc="left",
    )
    _draw_aanleg_on_ax(ax_bot, row, df, show_legend=False)
    ax_bot.spines["top"].set_visible(True)
    ax_bot.spines["top"].set_color("#9ca3af")
    ax_bot.spines["top"].set_linewidth(1.0)

    # ── Gecombineerde legenda onderaan ──
    handles_top, labels_top = ax_top.get_legend_handles_labels()
    handles_bot, labels_bot = ax_bot.get_legend_handles_labels()
    seen: Set[str] = set()
    unique_handles: List[Any] = []
    unique_labels: List[str] = []
    for h, l in zip(handles_top + handles_bot, labels_top + labels_bot):
        if l in seen:
            continue
        seen.add(l)
        unique_handles.append(h)
        unique_labels.append(l)
    if unique_handles:
        fig.legend(
            unique_handles, unique_labels,
            loc="lower center", bbox_to_anchor=(0.5, 0.0),
            ncol=min(len(unique_handles), 4),
            fontsize=6.5, framealpha=0.95, edgecolor="#dddddd",
            columnspacing=1.4, handlelength=2.0,
        )

    fig.subplots_adjust(left=0.06, right=0.97, top=0.90, bottom=0.22)
    return fig


# Kolomvolgorde van de "Alle hectopunten"-tabel (gebruikersverzoek). Markering
# (markering) en opmerking worden in de render vóór deze lijst geplakt. Daarna:
# snelweg → hectometer → bocht (hoek/straal) → inspectie (health/vis 25→23) →
# deklaag/aanleg → verkeer → de rest.
_ASSET_TABLE_COLUMNS: List[Tuple[str, str]] = [
    ("wegnr_hmp",                "wegnr_hmp"),
    ("hectomtrng",               "hectomtrng"),
    ("draaihoek",                "draaihoek"),
    ("boogstraal",               "boogstraal"),
    ("health_2025",              "kwaliteit 2025"),
    ("visibility_2025",          "zichtbaarheid 2025"),
    ("health_2023",              "kwaliteit 2023"),
    ("visibility_2023",          "zichtbaarheid 2023"),
    ("deklaagsoort",             "deklaagsoort"),
    ("aanlegdatum",              "aanlegdatum"),
    ("aantal_deklagen",          "aantal_deklagen"),
    ("strook",                   "strook"),
    ("_leeftijd",                "leeftijd"),
    ("levensduur",               "levensduur"),
    ("onderhoudsmoment",         "onderhoudsmoment"),
    ("klein_voertuig",           "klein_voertuig"),
    ("middel_voertuig",          "middel_voertuig"),
    ("lang_voertuig",            "lang_voertuig"),
    ("totaal_voertuig",          "totaal_voertuig"),
    # ── de rest ──
    ("hecto_lttr",               "hecto_lttr"),
    ("Zijde",                    "Zijde"),
    ("distrnaam",                "distrnaam"),
    ("_resterende_levensduur",   "resterende_levensduur"),
    ("_onderhoudsinterval",      "onderhoudsinterval"),
    ("_eerstvolgend_onderhoud",  "eerstvolgend_onderhoud"),
    ("aantal_bochten",           "aantal_bochten"),
    ("aantal_inspecties",        "aantal_inspecties"),
    ("info",                     "info"),
]

# Per-kolom heatmap: True = "hoog = slecht" (rood bij hoge waarde),
# False = "hoog = goed" (groen bij hoge waarde).
_HEATMAP_TABLE_COLS: Dict[str, bool] = {
    "_resterende_levensduur":   False,
    "_onderhoudsinterval":      False,
    "_eerstvolgend_onderhoud":  False,
    "levensduur":               False,
    "onderhoudsmoment":         False,
    "_leeftijd":                True,
    "aanlegdatum":              True,
    "health_2023":              False,
    "visibility_2023":          False,
    "health_2025":              False,
    "visibility_2025":          False,
    "draaihoek":                True,
    "boogstraal":               False,
    "klein_voertuig":           True,
    "middel_voertuig":          True,
    "lang_voertuig":            True,
    "totaal_voertuig":          True,
}

# Kolommen waarvan de heatmap-kleur op een afgeleide numerieke serie moet
# rusten (bijv. aanlegdatum is tekst → kleur vanuit `_leeftijd`).
_HEATMAP_NUMERIC_SOURCE: Dict[str, str] = {
    "aanlegdatum": "_leeftijd",
}

# Kolommen die comma-lijsten kunnen bevatten ("7.5, 8.0"). Voor heatmap-
# kleur en bounds gebruiken we het gemiddelde van de lijst; de cel zelf
# blijft de volledige string tonen.
_COMMA_LIST_HEATMAP_COLS: Set[str] = {
    "health_2023", "visibility_2023",
    "health_2025", "visibility_2025",
    "draaihoek",   "boogstraal",
}


def _heatmap_bg_css(val: Any, vmin: float, vmax: float,
                    invert: bool) -> str:
    """RdYlGn achtergrond-CSS voor een cel; "" als waarde of bereik leeg is."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return ""
    if pd.isna(v) or pd.isna(vmin) or pd.isna(vmax) or vmin == vmax:
        return ""
    pct = (v - vmin) / (vmax - vmin)
    if invert:
        pct = 1.0 - pct
    pct = max(0.0, min(1.0, pct))
    r, g, b, _ = RDYLGN_CMAP(pct)
    return (f"background-color: rgba({int(r*255)},{int(g*255)},"
            f"{int(b*255)},0.55)")


_ASSET_TBL_PAGE_SIZE_OPTIONS: List[int] = [10, 25, 50, 100, 250]
_ASSET_TBL_DEFAULT_PAGE_SIZE: int = 25


def _render_asset_paginated_table(work: pd.DataFrame) -> None:
    """Lichte gepagineerde tabel — sortering op rest. levensduur, met
    instelbare paginagrootte. De gekozen grootte landt in session_state
    (`_asset_tbl_page_size`) en wordt door eventuele andere views
    overgenomen via dezelfde key.

    Materialiseert alleen de huidige pagina → ook bij 100k+ rijen
    blijft Streamlit responsief. NaN-levensduur onderaan.
    """
    if "_resterende_levensduur" not in work.columns:
        return

    st.markdown(
        "<div style='font-size:18px;font-weight:700;margin:14px 0 6px 0;'>"
        "Alle hectopunten</div>",
        unsafe_allow_html=True,
    )

    total = len(work)
    label_map = dict(_ASSET_TABLE_COLUMNS)
    label_to_raw = {lbl: c for c, lbl in _ASSET_TABLE_COLUMNS}
    cols = [c for c, _ in _ASSET_TABLE_COLUMNS if c in work.columns]
    rest_lbl = label_map.get("_resterende_levensduur")

    def _display_df(slice_df: pd.DataFrame) -> pd.DataFrame:
        """Bouw de toon-tabel: kolommen in vaste volgorde + markering/opmerking
        vooraan."""
        out = slice_df[cols].rename(columns=label_map)
        if "_flag" in slice_df.columns:
            out.insert(0, "markering",
                       slice_df["_flag"].map(lambda b: "●" if bool(b) else "").values)
        if "_flag_reden" in slice_df.columns:
            out.insert(1 if "markering" in out.columns else 0, "opmerking",
                       slice_df["_flag_reden"].fillna("").astype(str).values)
        return out

    # ── Schakelaar: kleuren (paginatie + 'Sorteren'-box) vs. klik-sorteren ──
    show_colors = st.toggle(
        "Heatmap-kleuren  ·  zet UIT om op kolomkoppen te klikken en alle rijen "
        "te sorteren",
        value=True,
        key="asset_tbl_colors",
        help="AAN: gekleurde cellen, sorteer via de 'Sorteren'-keuze. "
             "UIT: platte tabel — klik een kolomkop om ALLE rijen te sorteren "
             "(Streamlit blokkeert klik-sorteren op gekleurde cellen).",
    )

    # ════════════════════════════════════════════════════════════════════
    # MODUS B — platte, volledig sorteerbare tabel (klik op kolomkop sorteert
    # de HELE dataset; glide-grid virtualiseert dus ook duizenden rijen).
    # ════════════════════════════════════════════════════════════════════
    if not show_colors:
        _CAP = 10000
        shown = work if total <= _CAP else work.iloc[:_CAP]
        sub = _display_df(shown)
        row_ids = shown["_row_id"].to_numpy()

        col_config: Dict[str, Any] = {}
        if rest_lbl and rest_lbl in sub.columns:
            col_config[rest_lbl] = st.column_config.NumberColumn(
                rest_lbl, format="%.1f")

        if total > _CAP:
            st.caption(f"Klik op een kolomkop om te sorteren. Toont de eerste "
                       f"**{_CAP:,}** van **{total:,}** rijen.")
        else:
            st.caption(f"Klik op een kolomkop om **alle {total:,} rijen** te "
                       "sorteren (op/af).")

        event = st.dataframe(
            sub,
            use_container_width=True,
            hide_index=True,
            height=600,
            on_select="rerun",
            selection_mode="single-row",
            column_config=col_config,
            key="asset_tbl_select",
        )
        try:
            rows = (event.selection or {}).get("rows", []) if event else []
        except Exception:
            rows = []
        if rows:
            pos = int(rows[0])
            if 0 <= pos < len(row_ids):
                try:
                    st.session_state["_asset_tbl_selected_row_id"] = int(row_ids[pos])
                except Exception:
                    pass
        return

    # ════════════════════════════════════════════════════════════════════
    # MODUS A — heatmap-kleuren (Styler) + server-side sortering + paginatie.
    # ════════════════════════════════════════════════════════════════════
    # ── Multi-kolom sortering ─────────────────────────────────
    # Volgorde van geselecteerde kolommen = sorteer-prioriteit. Per kolom
    # apart in te stellen of oplopend of aflopend gesorteerd wordt.
    sort_options = [(c, lbl) for c, lbl in _ASSET_TABLE_COLUMNS
                    if c in work.columns]
    label_to_col_sort = {lbl: c for c, lbl in sort_options}
    sort_label_options = [lbl for _, lbl in sort_options]
    sort_state_key = "_asset_tbl_sort_labels"
    if sort_state_key not in st.session_state:
        # Géén kolom voorgeselecteerd → de tabel valt terug op de
        # standaardsortering: gemarkeerde hectopunten eerst (zie else-tak
        # hieronder). `_flag` is geen sorteer-kolomoptie, dus het kan niet via
        # de multiselect maar wel als impliciete default.
        st.session_state[sort_state_key] = []

    with st.expander("↕ Sorteren — kies kolom(men) (werkt over álle pagina's)",
                     expanded=True):
        st.caption(
            "Sorteren over álle pagina's: kies hier kolom(men) — eerste = "
            "primair, daarna secundair, enz. Wil je liever op de kolomkop "
            "klikken? Zet onder de tabel **Heatmap-kleuren UIT**; dan staat "
            "klik-sorteren aan (Streamlit blokkeert dat op gekleurde cellen)."
        )
        selected_sort_labels: List[str] = st.multiselect(
            "Sorteerkolommen — eerste = primair, daarna secundair, etc.",
            options=sort_label_options,
            key=sort_state_key,
        )
        asc_map: Dict[str, bool] = {}
        for lbl in selected_sort_labels:
            asc_key = f"_asset_tbl_sort_asc_{lbl}"
            if asc_key not in st.session_state:
                st.session_state[asc_key] = True
            c1, c2 = st.columns([3, 2], gap="small")
            c1.markdown(f"**{lbl}**")
            dir_choice = c2.radio(
                f"Richting {lbl}",
                options=["oplopend", "aflopend"],
                index=0 if st.session_state[asc_key] else 1,
                horizontal=True,
                key=f"_asset_tbl_sort_dir_{lbl}",
                label_visibility="collapsed",
            )
            asc_map[lbl] = (dir_choice == "oplopend")
            st.session_state[asc_key] = asc_map[lbl]

    if selected_sort_labels:
        sort_cols = [label_to_col_sort[lbl] for lbl in selected_sort_labels]
        ascending = [asc_map[lbl] for lbl in selected_sort_labels]
        arrow_marks = ["↑" if asc_map[l] else "↓" for l in selected_sort_labels]
        st.caption("Sortering: " + " → ".join(
            f"{l} {m}" for l, m in zip(selected_sort_labels, arrow_marks)
        ))
    else:
        # Standaard: gemarkeerde hectopunten bovenaan (_flag aflopend → True
        # eerst), daarna op resterende levensduur en inspectiescore
        # (gebruikersverzoek).
        sort_cols = ["_flag", "_resterende_levensduur", "insp_score"]
        ascending = [False, True, True]
        st.caption("Sortering: gemarkeerd eerst → resterende_levensduur ↑ → "
                   "insp_score ↑ (default)")

    # ── Paginagrootte-keuze (bovenaan, naast paginatie-controls) ──
    page_size_key = "_asset_tbl_page_size"
    if page_size_key not in st.session_state:
        st.session_state[page_size_key] = _ASSET_TBL_DEFAULT_PAGE_SIZE

    size_col, nav_prev, nav_info, nav_jump, nav_next = st.columns(
        [2, 1, 2, 2, 1], gap="small")

    page_size = int(size_col.selectbox(
        "Rijen per pagina",
        options=_ASSET_TBL_PAGE_SIZE_OPTIONS,
        index=_ASSET_TBL_PAGE_SIZE_OPTIONS.index(
            st.session_state[page_size_key]
            if st.session_state[page_size_key] in _ASSET_TBL_PAGE_SIZE_OPTIONS
            else _ASSET_TBL_DEFAULT_PAGE_SIZE),
        key="asset_tbl_page_size_select",
    ))
    st.session_state[page_size_key] = page_size

    n_pages = max(1, (total + page_size - 1) // page_size)

    # ── Sorteer-index opbouwen ────────────────────────────────
    # Index wordt gecached op basis van sort-spec + dataset-grootte zodat
    # we bij ongewijzigde keuze niet opnieuw sorteren.
    sort_sig = (tuple(sort_cols), tuple(ascending), total)
    cache_key = "_asset_tbl_order_cache"
    sig_key = "_asset_tbl_order_sig"
    if st.session_state.get(sig_key) != sort_sig:
        sort_frame = pd.DataFrame(index=work.index)
        for c in sort_cols:
            if c not in work.columns:
                sort_frame[c] = np.nan
                continue
            if c in _COMMA_LIST_HEATMAP_COLS:
                sort_frame[c] = work[c].apply(_comma_mean)
            elif c == "aanlegdatum":
                sort_frame[c] = pd.to_datetime(
                    work[c].apply(_latest_date), errors="coerce"
                )
            else:
                num = pd.to_numeric(work[c], errors="coerce")
                sort_frame[c] = num if num.notna().any() else work[c].astype(str)
        order = (sort_frame
                 .sort_values(by=sort_cols, ascending=ascending,
                              na_position="last", kind="mergesort")
                 .index.to_numpy())
        st.session_state[cache_key] = order
        st.session_state[sig_key] = sort_sig
        # Nieuwe sortering → terug naar pagina 1 zodat de eindgebruiker meteen
        # de bovenste resultaten van de nieuwe volgorde ziet.
        st.session_state["_asset_tbl_page"] = 1
    order = st.session_state[cache_key]

    page_key = "_asset_tbl_page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 1
    # Clamp huidige pagina als page_size of dataset gewijzigd is.
    if st.session_state[page_key] > n_pages:
        st.session_state[page_key] = n_pages

    if nav_prev.button("◀", key="asset_tbl_prev",
                       disabled=st.session_state[page_key] <= 1):
        st.session_state[page_key] -= 1
    if nav_next.button("▶", key="asset_tbl_next",
                       disabled=st.session_state[page_key] >= n_pages):
        st.session_state[page_key] += 1
    page = int(nav_jump.number_input(
        f"Pagina (1–{n_pages})", min_value=1, max_value=n_pages,
        value=int(st.session_state[page_key]), step=1, key="asset_tbl_page_input",
    ))
    st.session_state[page_key] = page
    start = (page - 1) * page_size
    end = min(start + page_size, total)
    nav_info.markdown(
        f"<div style='padding-top:30px;color:#555;font-size:13px;'>"
        f"Rij <b>{start + 1}–{end}</b> van <b>{total:,}</b></div>",
        unsafe_allow_html=True,
    )

    page_idx = order[start:end]
    # Kolommen exact in de volgorde van `_ASSET_TABLE_COLUMNS`; markering +
    # opmerking vooraan. Heatmap-kleuring werkt via `bounds_lbl`, ongeacht
    # de kolompositie.
    sub = _display_df(work.loc[page_idx])

    _num_cache: Dict[str, pd.Series] = {}

    def _numeric_series(col: str) -> pd.Series:
        """Numerieke serie voor color/bounds: comma-list cols → gemiddelde per cel.
        Tekst-kolommen met `_HEATMAP_NUMERIC_SOURCE` mapping → bron-kolom.
        Resultaat per-kolom gecached zodat herhaalde aanroepen vanuit `_style_col`
        de comma_mean-apply niet opnieuw uitvoeren."""
        if col in _num_cache:
            return _num_cache[col]
        src = _HEATMAP_NUMERIC_SOURCE.get(col, col)
        if src not in work.columns:
            ser = pd.Series(np.nan, index=work.index)
        elif src in _COMMA_LIST_HEATMAP_COLS:
            ser = work[src].apply(_comma_mean)
        else:
            ser = pd.to_numeric(work[src], errors="coerce")
        _num_cache[col] = ser
        return ser

    # Per-kolom heatmap-grenzen uit de VOLLEDIGE work (niet de pagina) zodat
    # kleuren stabiel zijn tussen pagina's.
    bounds_lbl: Dict[str, Tuple[float, float, bool]] = {}
    for col, invert in _HEATMAP_TABLE_COLS.items():
        if col not in work.columns:
            continue
        ser = _numeric_series(col)
        if ser.dropna().empty:
            continue
        bounds_lbl[label_map.get(col, col)] = (
            float(ser.min()), float(ser.max()), invert,
        )

    def _style_col(s: pd.Series) -> List[str]:
        if s.name not in bounds_lbl:
            return [""] * len(s)
        vmin, vmax, invert = bounds_lbl[s.name]
        raw_col = label_to_raw.get(s.name)
        src = _HEATMAP_NUMERIC_SOURCE.get(raw_col, raw_col)
        if (src and src in work.columns and src != raw_col) \
                or raw_col in _COMMA_LIST_HEATMAP_COLS:
            vals = _numeric_series(raw_col).loc[s.index]
        else:
            vals = s
        return [_heatmap_bg_css(v, vmin, vmax, invert) for v in vals]

    fmt: Dict[str, str] = {}
    if rest_lbl and rest_lbl in sub.columns:
        fmt[rest_lbl] = "{:.1f}"
    table_obj: Any = sub.style.apply(_style_col, axis=0).format(fmt, na_rep="—")

    event = st.dataframe(
        table_obj,
        use_container_width=True,
        hide_index=True,
        height=38 * len(sub) + 44,
        on_select="rerun",
        selection_mode="single-row",
        key="asset_tbl_select",
    )
    try:
        rows = (event.selection or {}).get("rows", []) if event else []
    except Exception:
        rows = []
    if rows:
        pos = int(rows[0])
        if 0 <= pos < len(page_idx):
            work_idx = page_idx[pos]
            try:
                row_id = int(work.loc[work_idx, "_row_id"])
                st.session_state["_asset_tbl_selected_row_id"] = row_id
            except Exception:
                pass


_MAP_HEATMAP_OPTIONS: List[str] = [
    "clusters",
    "health (alle jaren)",
    "visibility (alle jaren)",
    "draaihoek",
    "boogstraal",
    "verkeer",
    "klein_voertuig",
    "middel_voertuig",
    "lang_voertuig",
    "leeftijd",
    "resterende_levensduur",
    "onderhoudsinterval",
    "eerstvolgend_onderhoud",
]

# Leesbare labels voor de kaartlaag-keuze in de sidebar.
_HEATMAP_OPTION_LABELS: Dict[str, str] = {
    "clusters":                 "Clusters (onderhoudsernst)",
    "health (alle jaren)":      "Kwaliteit-score (alle jaren)",
    "visibility (alle jaren)":  "Zichtbaarheid-score (alle jaren)",
    "draaihoek":                "Draaihoek (scherpte bocht)",
    "boogstraal":               "Boogstraal",
    "verkeer":                  "Verkeer — totaal",
    "klein_voertuig":           "Verkeer — personenauto's (klein)",
    "middel_voertuig":          "Verkeer — bestelbus/kleine vracht (middel)",
    "lang_voertuig":            "Verkeer — lange vrachtwagens (groot)",
    "leeftijd":                 "Leeftijd deklaag",
    "resterende_levensduur":    "Resterende levensduur",
    "onderhoudsinterval":       "Onderhoudsinterval",
    "eerstvolgend_onderhoud":   "Eerstvolgend onderhoud",
}


def _heatmap_option_label(choice: str) -> str:
    return _HEATMAP_OPTION_LABELS.get(choice, choice)

# Hard-coded standaard-kleuring van de kaart-heatmap. Gebruikersverzoek:
# kaart opent standaard op het clusterresultaat (rood = slechtste cluster,
# groen = beste). Werkt omdat de clustering bij opstart voorberekend wordt en
# `_run_cluster_button` na die eerste run één keer rerunt zodat de kaart de
# clusters al heeft vóór de eerste interactie.
_MAP_HEATMAP_DEFAULT = "clusters"


# Legenda-tekst per heatmap-keuze: (titel, betekenis-ROOD (pct≈0),
# betekenis-GROEN (pct≈1)). De heatmap kleurt 0 = rood/slecht, 1 = groen/goed
# (zie `_compute_map_heatmap_pct`), dus de rood-/groen-labels beschrijven die
# uiteinden. Keuzes die hier ontbreken vallen terug op een generiek label.
_HEATMAP_LEGEND_TEXT: Dict[str, Tuple[str, str, str]] = {
    "clusters": (
        "Clusterkleur = gewogen onderhoudsernst (onderhoudsmoment · bocht · zwaar verkeer)",
        "Hoogste prioriteit — onderhoud op korte termijn (~enkele jaren)",
        "Laagste prioriteit — nog lang mee (~8–12 jaar)",
    ),
    "resterende_levensduur": (
        "Resterende levensduur tot eerstvolgend onderhoud",
        "Bijna op — onderhoud dichtbij",
        "Nog lang mee (~8–12 jaar)",
    ),
    "eerstvolgend_onderhoud": (
        "Eerstvolgend onderhoudsjaar",
        "Dichtbij / achterstallig",
        "Ver in de toekomst",
    ),
    "onderhoudsinterval": (
        "Onderhoudsinterval (levensduur in jaren)",
        "Kort interval — snelle slijtage",
        "Lang interval — robuust",
    ),
    "leeftijd": ("Leeftijd deklaag", "Oud", "Jong"),
    "draaihoek": ("Draaihoek (scherpte bocht)", "Scherpe / grote draai", "Recht / flauw"),
    "boogstraal": ("Boogstraal", "Krappe boog", "Ruime boog"),
    "verkeer": ("Verkeersintensiteit (totaal_voertuig, mvt/etmaal werkdag) — zelfde kolom als de verkeersgrafiek",
                "Druk — veel verkeer", "Rustig — weinig verkeer"),
    "klein_voertuig": ("Verkeer — personenauto's (klein, mvt/etmaal werkdag)",
                       "Druk", "Rustig"),
    "middel_voertuig": ("Verkeer — bestelbus/kleine vracht (middel, mvt/etmaal)",
                        "Druk", "Rustig"),
    "lang_voertuig": ("Verkeer — lange vrachtwagens (groot, mvt/etmaal werkdag)",
                      "Druk", "Rustig"),
    "health (alle jaren)": ("Health-score (alle jaren)", "Lage score", "Hoge score"),
    "visibility (alle jaren)": ("Visibility-score (alle jaren)", "Lage score", "Hoge score"),
}


def _render_heatmap_legend(choice: str) -> None:
    """Korte kleur-legenda onder de kaart: 4 RdYlGn-swatches (rood→groen) met
    de betekenis van beide uiteinden, afgestemd op de gekozen heatmap."""
    if choice == "hecto_lttr":
        st.caption(
            "Kleur per **hectoletter** (categorische kleuring — geen "
            "goed/slecht-schaal)."
        )
        return

    title, rood, groen = _HEATMAP_LEGEND_TEXT.get(
        choice, ("Kleurschaal", "Slecht / laag", "Goed / hoog")
    )
    swatch_hex = [
        "#%02x%02x%02x" % (int(c[0] * 255), int(c[1] * 255), int(c[2] * 255))
        for c in (RDYLGN_CMAP(p) for p in (0.06, 0.37, 0.63, 0.94))
    ]
    swatches = "".join(
        f"<span style='display:inline-block;width:32px;height:13px;"
        f"background:{h};border:1px solid #cfcfcf;'></span>"
        for h in swatch_hex
    )
    html = (
        "<div style='margin:4px 0 10px 0;'>"
        f"<div style='font-size:12px;font-weight:600;color:#444;margin-bottom:3px;'>"
        f"Legenda — {title}</div>"
        "<div style='display:flex;align-items:center;gap:8px;font-size:11px;"
        "color:#555;flex-wrap:wrap;'>"
        "<span style='display:inline-block;width:10px;height:10px;border-radius:50%;"
        f"background:#dc2626;'></span><span>{rood}</span>"
        f"<span style='white-space:nowrap;'>{swatches}</span>"
        "<span style='display:inline-block;width:10px;height:10px;border-radius:50%;"
        f"background:#16a34a;'></span><span>{groen}</span>"
        "</div></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _compute_map_heatmap_pct(
    work: pd.DataFrame,
    choice: str,
    default_pct: pd.Series,
    annotations: Dict[str, Dict[str, str]],
) -> pd.Series:
    """Reken kleur-percentages (0..1, RdYlGn) voor de kaart op basis van keuze.
    1.0 = groen (goed), 0.0 = rood (slecht)."""
    if choice == "alert_score" or choice not in _MAP_HEATMAP_OPTIONS:
        return default_pct

    # Resultaat van het clusteralgoritme als kleuring op de hoofd-kaart.
    # `cluster_rank_pct` = de door de sliders bepaalde gewogen score, uitgerekt
    # naar volle 0-1 (slechtste cluster = rood/0, beste = groen/1) zodat de
    # kaart contrast heeft i.p.v. een uniforme band. De ruwe absolute score
    # staat in `cluster_score`. Géén rainbow per cluster-ID maar ernst-gradient.
    if choice == "clusters":
        pct = _cluster_pct_for_work(work, st.session_state.get("_clustered_df"))
        if pct is None:
            return pd.Series(0.5, index=work.index)
        return pct.fillna(0.5).clip(0.0, 1.0)

    invert = False
    if choice == "health (alle jaren)":
        cols = [c for c in ("health_2023", "health_2025") if c in work.columns]
        if not cols:
            return pd.Series(0.5, index=work.index)
        v = pd.concat(
            [pd.to_numeric(work[c], errors="coerce") for c in cols], axis=1
        ).mean(axis=1)
    elif choice == "visibility (alle jaren)":
        cols = [c for c in ("visibility_2023", "visibility_2025")
                if c in work.columns]
        if not cols:
            return pd.Series(0.5, index=work.index)
        v = pd.concat(
            [pd.to_numeric(work[c], errors="coerce") for c in cols], axis=1
        ).mean(axis=1)
    elif choice == "draaihoek":
        v = pd.to_numeric(work.get("_max_hoek"), errors="coerce").abs()
        invert = True
    elif choice == "verkeer":
        # Exact dezelfde originele kolom als de verkeersopbouw-grafiek (donut):
        # de totale intensiteit `totaal_voertuig`. Zo geven kaart en grafiek
        # gegarandeerd dezelfde waarde. Druk = rood (zwaardere belasting).
        v = pd.to_numeric(work.get("totaal_voertuig"), errors="coerce")
        invert = True
    elif choice in ("klein_voertuig", "middel_voertuig", "lang_voertuig"):
        # Verkeer per voertuigcategorie — zelfde originele kolommen als de
        # verkeersopbouw-grafiek (klein/middel/groot). Druk = rood.
        v = pd.to_numeric(work.get(choice), errors="coerce")
        invert = True
    elif choice == "boogstraal":
        v = pd.to_numeric(work.get("_boogstraal"), errors="coerce")
    elif choice == "leeftijd":
        v = pd.to_numeric(work.get("_leeftijd"), errors="coerce")
        invert = True
    elif choice == "resterende_levensduur":
        v = pd.to_numeric(work.get("_resterende_levensduur"), errors="coerce")
    elif choice == "onderhoudsinterval":
        keys = _annotation_row_keys(work)
        v = pd.Series(
            [_resolve_interval_total(annotations.get(k, {})) for k in keys],
            index=work.index, dtype="float64",
        )
    elif choice == "eerstvolgend_onderhoud":
        # Synchroon met de levensduur-grafiek: `_eerstvolgend_onderhoud`
        # komt uit `_next_onderhoud_year_for_row`. Verder in de toekomst =
        # langer durend = groener; achterstallig/dichtbij = roder.
        v = pd.to_numeric(work.get("_eerstvolgend_onderhoud"), errors="coerce")
    elif choice == "hecto_lttr":
        ser = work.get("hecto_lttr")
        if ser is None:
            return pd.Series(0.5, index=work.index)
        codes = pd.Categorical(ser.astype(str).str.strip()).codes
        v = pd.Series(codes, index=work.index, dtype="float64") \
            .where(pd.Series(codes, index=work.index) >= 0, other=np.nan)
    else:
        return default_pct

    v = pd.to_numeric(v, errors="coerce")
    valid = v.dropna()
    if valid.empty:
        return pd.Series(0.5, index=work.index)
    vmin, vmax = float(valid.min()), float(valid.max())
    if vmin == vmax:
        return pd.Series(0.5, index=work.index)
    pct = (v - vmin) / (vmax - vmin)
    if invert:
        pct = 1.0 - pct
    return pct.fillna(0.5).clip(0.0, 1.0)


def _import_pydeck() -> Any:
    """Dynamische pydeck-import met inline error-message."""
    try:
        import pydeck as pdk
        return pdk
    except ImportError:
        st.error("pydeck niet beschikbaar — installeer met `pip install pydeck`.")
        return None


def _rd_to_wgs84_frame(df: pd.DataFrame,
                       extra_required_cols: Optional[List[str]] = None
                       ) -> Optional[pd.DataFrame]:
    """Drop NaN-coord rijen, voeg `_lon`/`_lat` (WGS84) toe, return None +
    streamlit warning bij fout."""
    if not _has_rd_coords(df):
        st.warning("Geen coördinaten in de dataset.")
        return None

    needed = ["_rd_x", "_rd_y"] + (extra_required_cols or [])
    work = df.dropna(subset=needed).copy()
    if work.empty:
        st.warning("Geen punten met geldige coördinaten in de selectie.")
        return None

    try:
        from pyproj import Transformer
        tf = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)
        lon, lat = tf.transform(work["_rd_x"].to_numpy(),
                                work["_rd_y"].to_numpy())
        work["_lon"] = lon
        work["_lat"] = lat
    except Exception as exc:
        st.error(f"Coördinatenconversie mislukt: {exc}")
        return None

    work = work.dropna(subset=["_lon", "_lat"])
    if work.empty:
        st.warning("Geen geldige punten na coördinatenconversie.")
        return None
    return work


_GLOBAL_COMPACT_CSS = """
<style>
/* Minder witruimte rond de hele pagina + compactere koppen/blokken. */
.block-container { padding-top: 2.6rem; padding-bottom: 1rem; }
h1 { font-size: 1.55rem; line-height: 1.2; margin-bottom: 0.1rem; padding-top: 0; }
h2, h3 { margin-top: 0.3rem; margin-bottom: 0.2rem; }
div[data-testid="stVerticalBlock"] { gap: 0.55rem; }
div[data-testid="stCaptionContainer"] { margin-top: -0.25rem; }
div[data-testid="stMetric"] { padding: 2px 0; }
hr { margin: 0.5rem 0; }
/* Sidebar (filterbalk) in geel #ffee00 (gebruikersverzoek). */
section[data-testid="stSidebar"],
section[data-testid="stSidebar"] > div,
div[data-testid="stSidebarContent"] { background-color: #ffee00; }
/* Widgets in de gele sidebar mee laten kleuren i.p.v. blauw/wit:
   gele vulling + donkere rand/tekst zodat ze leesbaar blijven. */
section[data-testid="stSidebar"] div[data-baseweb="select"] > div,
section[data-testid="stSidebar"] div[data-baseweb="input"],
section[data-testid="stSidebar"] .stTextInput input,
section[data-testid="stSidebar"] .stNumberInput input {
    background-color: #ffee00 !important;
    border-color: #1a1a1a !important;
    color: #1a1a1a !important;
}
section[data-testid="stSidebar"] .stButton > button {
    background-color: #ffee00 !important;
    color: #1a1a1a !important;
    border: 1px solid #1a1a1a !important;
}
section[data-testid="stSidebar"] .stButton > button:hover,
section[data-testid="stSidebar"] .stButton > button:focus {
    background-color: #ffe600 !important;
    color: #1a1a1a !important;
    border-color: #1a1a1a !important;
}
/* Selectie-KPI's compacter: kleinere getallen + labels (gebruikersverzoek). */
section[data-testid="stSidebar"] div[data-testid="stMetricValue"] {
    font-size: 1.35rem; line-height: 1.1;
}
section[data-testid="stSidebar"] div[data-testid="stMetricLabel"] p {
    font-size: 0.8rem;
}
section[data-testid="stSidebar"] div[data-testid="stMetricDelta"] {
    font-size: 0.8rem;
}
</style>
"""

_MAP_TAB_CSS = """
<style>
div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]
  div.stMarkdown p { margin-bottom: 0.2rem; }
div[data-testid="column"] div[data-testid="stMetric"] { padding: 4px 6px; }
/* Compactere bordered containers (markeer-widget + levensduur-grafiek):
   minder padding = minder witruimte rond scores/markeren. */
div[data-testid="stVerticalBlockBorderWrapper"] { padding: 8px 12px; }
/* Strakkere radio (Soort opmerking) en minder marge onder labels. */
div[data-testid="stRadio"] > label,
div[data-testid="stTextInput"] > label { margin-bottom: 1px; }
div[data-testid="stRadio"] { margin-bottom: 2px; }
/* Verkeersgrafiek strak ónder de bocht-geometrie schuiven (negatieve top-marge).
   KRITISCH: alleen de TWEEDE+ grafiek omhoog trekken, nooit de eerste — anders
   schuift de eerste grafiek ~6rem omhoog OVER de paginatitel "Preventief
   Toekomstbestendig Onderhoud…" heen (titel leek verdwenen / alleen zichtbaar
   bij hard naar boven scrollen). Adjacent-sibling-selector (`+`) raakt per
   definitie alleen een grafiek die een ándere grafiek vóór zich heeft. */
div[data-testid="column"]
  div[data-testid="stElementContainer"] + div[data-testid="stElementContainer"]
  div[data-testid="stImage"] { margin-top: -6rem; }
/* Detailrail leesbaar op een 65" TV: grotere attributen-tabel én minder wit
   tussen de gestapelde elementen (kop/links/kaarten/scores/attributen). */
.asset-attr-block div[data-testid="stDataFrame"] { font-size: 18px; }
.asset-attr-block div[data-testid="stDataFrame"] [role="gridcell"],
.asset-attr-block div[data-testid="stDataFrame"] [role="columnheader"] {
    font-size: 18px !important;
}
div[data-testid="column"] > div[data-testid="stVerticalBlock"] { gap: 0.35rem; }
</style>
"""

_DEFAULT_HECTOPUNT_WVK   = "189322009"
_DEFAULT_HECTOPUNT_HM    = 335
_DEFAULT_HECTOPUNT_ZIJDE = "LINKS"


def _format_hmp(hmp: Any) -> str:
    try:
        return f"{float(hmp) / 100:.1f}"
    except (TypeError, ValueError):
        return str(hmp)


def _pct_diff(new: Optional[float], old: Optional[float]) -> str:
    if new is None or old is None or old == 0:
        return "—"
    return f"{((new - old) / old) * 100:+.1f}%"


def _dev_color(new: Optional[float], old: Optional[float]) -> str:
    if new is None or old is None:
        return "#6b7280"
    if new < old:
        return "#dc2626"
    if new > old:
        return "#16a34a"
    return "#6b7280"


def _comma_floats(raw: Any) -> List[float]:
    """Parse "7.5, 8.0" → [7.5, 8.0]. Lege/onparsebare delen worden overgeslagen."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    if isinstance(raw, (int, float)):
        return [float(raw)]
    out: List[float] = []
    for p in str(raw).split(","):
        p = p.strip()
        if not p:
            continue
        try:
            out.append(float(p))
        except ValueError:
            continue
    return out


def _comma_mean(raw: Any) -> float:
    """Gemiddelde van een comma-string ("7.5, 8.0" → 7.75). NaN als leeg."""
    vals = _comma_floats(raw)
    return float(np.mean(vals)) if vals else float("nan")


def _mean_or_none(raw: Any) -> Optional[float]:
    vals = _comma_floats(raw)
    return float(np.mean(vals)) if vals else None


def _build_inspection_table_html(h23_raw: Any, h25_raw: Any,
                                 v23_raw: Any, v25_raw: Any) -> str:
    """Inspectiescores-card: toont ÁLLE bekende scores per cel (comma-list),
    plus het gemiddelde rechts en Δ% op gemiddelden 2023 → 2025."""
    rows = [
        ("health",     h23_raw, h25_raw),
        ("visibility", v23_raw, v25_raw),
    ]

    # Grote, leesbare fonts (65" TV, kijkers op afstand); compacte verticale
    # padding zodat de grotere tekst tóch zonder overlap en met weinig wit past.
    def _cell(raw: Any) -> str:
        vals = _comma_floats(raw)
        if not vals:
            return (
                '<div style="text-align:right;font-size:12px;color:#999;'
                'padding:7px 8px;border-top:1px solid #e5e7eb;">—</div>'
            )
        scores_html = " · ".join(f"{v:.1f}" for v in vals)
        mean_html = f" <span style=\"color:#888;font-size:10px;\">⌀{np.mean(vals):.1f}</span>"
        return (
            f'<div style="text-align:right;font-size:13px;color:#1a1a1a;'
            f'padding:7px 8px;border-top:1px solid #e5e7eb;'
            f'line-height:1.3;">{scores_html}{mean_html}</div>'
        )

    grid_rows = "".join(
        '<div style="display:contents;">'
        f'<div style="font-weight:700;color:#374151;font-size:13px;'
        f'padding:7px 8px;border-top:1px solid #e5e7eb;">{label}</div>'
        f'{_cell(v_old)}{_cell(v_new)}'
        f'<div style="text-align:right;font-size:13px;font-weight:700;'
        f'color:{_dev_color(_mean_or_none(v_new), _mean_or_none(v_old))};'
        f'padding:7px 8px;border-top:1px solid #e5e7eb;">'
        f'{_pct_diff(_mean_or_none(v_new), _mean_or_none(v_old))}</div>'
        '</div>'
        for label, v_old, v_new in rows
    )
    # Flex-kolom met height:100% + align-content:space-evenly op de grid → de
    # rijen spreiden over de VOLLE hoogte van de kaart (matcht de 3 KPI-kaarten
    # links), zodat er rechtsonder geen lege witruimte meer overblijft.
    return (
        f'<div style="background:#f9fafb;border-left:6px solid '
        f'{Settings.COLOR_BLUE_PRIMARY};border-radius:6px;padding:9px 12px;'
        f'height:100%;display:flex;flex-direction:column;">'
        '<div style="font-size:10.5px;color:#555;text-transform:uppercase;'
        'letter-spacing:0.4px;font-weight:700;margin-bottom:3px;">'
        'Inspectiescores (alle metingen per gebied)</div>'
        '<div style="flex:1;display:grid;grid-template-columns:1.2fr 1.6fr 1.6fr 0.7fr;'
        'align-content:space-evenly;">'
        '<div style="font-size:10px;color:#666;font-weight:700;padding:2px 8px;">&nbsp;</div>'
        '<div style="font-size:10px;color:#666;font-weight:700;padding:2px 8px;text-align:right;">2023</div>'
        '<div style="font-size:10px;color:#666;font-weight:700;padding:2px 8px;text-align:right;">2025</div>'
        '<div style="font-size:10px;color:#666;font-weight:700;padding:2px 8px;text-align:right;">Δ%</div>'
        f'{grid_rows}'
        '</div>'
        '<div style="font-size:8px;color:#8a8f98;margin-top:5px;'
        'border-top:1px solid #eceef1;padding-top:4px;">'
        'Per cel: alle metingen in dit gebied · ⌀ = gemiddelde · '
        'Δ% = verandering 2023 → 2025</div>'
        '</div>'
    )


def _build_map_workframe(df: pd.DataFrame,
                         annotations: Dict[str, Dict[str, str]]
                         ) -> Optional[pd.DataFrame]:
    """RD→WGS84 conversie + row_id + resterende levensduur +
    onderhoudsinterval + eerstvolgend onderhoud (jaar).

    `_eerstvolgend_onderhoud` gebruikt EXACT dezelfde formule als de
    levensduur-grafiek (``_next_onderhoud_year_for_row``) zodat KPI/tabel
    en chart altijd hetzelfde jaartal tonen.
    """
    work = _rd_to_wgs84_frame(df)
    if work is None:
        return None
    work["_orig_idx"] = work.index
    work = work.reset_index(drop=True)
    work["_row_id"] = work.index.astype(int)
    work["_resterende_levensduur"] = compute_remaining_life_series(work, annotations)

    keys = _annotation_row_keys(work)
    work["_anno_key"] = keys
    # Onderhoudsinterval: voorkeur de voorberekende `levensduur`-kolom; voor
    # rijen zonder waarde valt de annotatie-/default-interval in.
    _interval_fallback = pd.Series(
        [_resolve_interval_total(annotations.get(k, {})) for k in keys],
        index=work.index, dtype="float64",
    )
    if "levensduur" in work.columns:
        _lev = pd.to_numeric(work["levensduur"], errors="coerce")
        _interval = _lev.where(_lev.notna(), other=_interval_fallback)
    else:
        _interval = _interval_fallback
    work["_onderhoudsinterval"] = _interval.round().astype("Int64")
    today_year = int(pd.Timestamp.today().year)
    work["_eerstvolgend_onderhoud"] = pd.Series(
        [_next_onderhoud_year_for_row(r, work, today_year)
         for _, r in work.iterrows()],
        index=work.index, dtype="Int64",
    )
    flagged = _flagged_keys(annotations)
    work["_flag"] = pd.Series(
        [k in flagged for k in keys], index=work.index, dtype=bool,
    )
    work["_flag_reden"] = pd.Series(
        [(annotations.get(k) or {}).get("Vlag_reden", "") for k in keys],
        index=work.index, dtype="object",
    )
    # Sentiment van de markering: "positief" (groen) of "negatief" (rood).
    # Legacy-vlaggen zonder type tellen als negatief, zoals voorheen.
    work["_flag_type"] = pd.Series(
        [(annotations.get(k) or {}).get("Vlag_type", "") for k in keys],
        index=work.index, dtype="object",
    )
    return work


def _cluster_pct_for_work(work: pd.DataFrame,
                          clustered: Optional[pd.DataFrame]
                          ) -> Optional[pd.Series]:
    """Koppel elke kaart-rij aan de `cluster_rank_pct` van DAT punt via de
    bewaarde originele index (`_src_idx`). Direct op de index mappen is fout:
    `run_clustering` reset de index na het sorteren, dus index-lookup geeft
    elk punt de kleur van een ánder punt. None als de gecachte clustering
    ontbreekt, geen `_src_idx` heeft (oude cache) of niet bij `work` past."""
    if not (isinstance(clustered, pd.DataFrame)
            and "cluster_rank_pct" in clustered.columns
            and "_src_idx" in clustered.columns
            and "_orig_idx" in work.columns):
        return None
    lookup = (clustered.dropna(subset=["_src_idx"])
                       .drop_duplicates("_src_idx")
                       .set_index("_src_idx")["cluster_rank_pct"])
    return pd.to_numeric(work["_orig_idx"].map(lookup), errors="coerce")


def _default_heatmap_pct(work: pd.DataFrame) -> pd.Series:
    """Cluster-rang-pct uit eerdere clustering, anders 1-alert_score."""
    default_pct = _cluster_pct_for_work(work, st.session_state.get("_clustered_df"))
    if default_pct is None:
        default_pct = pd.Series(np.nan, index=work.index)

    if default_pct.isna().all() and "_alert_score" in work.columns:
        alert = pd.to_numeric(work["_alert_score"], errors="coerce").fillna(0.5)
        default_pct = 1.0 - alert.clip(0.0, 1.0)
    return default_pct.fillna(0.5).clip(0.0, 1.0)


def _apply_heatmap_colors(work: pd.DataFrame, pct: pd.Series) -> None:
    """Materialiseer _r/_g/_b kolommen uit RdYlGn-cmap voor pydeck."""
    rgba = RDYLGN_CMAP(pct.to_numpy(dtype=float))
    work["_r"] = (rgba[:, 0] * 255).astype(int)
    work["_g"] = (rgba[:, 1] * 255).astype(int)
    work["_b"] = (rgba[:, 2] * 255).astype(int)


def _build_tooltip(work: pd.DataFrame, pct: pd.Series) -> pd.Series:
    flag_prefix = ""
    if "_flag" in work.columns:
        flag_prefix = work["_flag"].map(
            lambda f: "<b>Gemarkeerd door gebruiker</b><br/>" if f else ""
        )
    reden = ""
    if "_flag_reden" in work.columns:
        reden = work["_flag_reden"].fillna("").astype(str)
        reden = reden.where(reden == "", "Reden: " + reden + "<br/>")
    base = (
        "<b>" + work.get("wegnr_hmp", "").astype(str)
        + " hmp " + work.get("hectomtrng", "").astype(str) + "</b><br/>"
        + "Score: " + pct.round(2).astype(str) + "<br/>"
        + "health_2025: " + work.get("health_2025", "").astype(str) + "<br/>"
        + "visibility_2025: " + work.get("visibility_2025", "").astype(str)
    )
    if isinstance(flag_prefix, pd.Series):
        return flag_prefix + reden + base
    return base


def _cross_icon_data(hex_color: str) -> Dict[str, Any]:
    """deck.gl IconLayer-icoon: een kruisje (×) in `hex_color` met witte halo,
    als inline base64-SVG data-URL. IconLayer rendert dit betrouwbaar op de
    luchtfoto — anders dan TextLayer, die in deze pydeck-setup niet tekende."""
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100' "
        "viewBox='0 0 100 100'>"
        "<g fill='none' stroke-linecap='round'>"
        "<line x1='26' y1='26' x2='74' y2='74' stroke='white' stroke-width='26'/>"
        "<line x1='74' y1='26' x2='26' y2='74' stroke='white' stroke-width='26'/>"
        f"<line x1='26' y1='26' x2='74' y2='74' stroke='{hex_color}' stroke-width='15'/>"
        f"<line x1='74' y1='26' x2='26' y2='74' stroke='{hex_color}' stroke-width='15'/>"
        "</g></svg>"
    )
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return {
        "url": f"data:image/svg+xml;base64,{b64}",
        "width": 100, "height": 100,
        "anchorX": 50, "anchorY": 50,
        "mask": False,
    }


# Twee vaste icoon-varianten (sentiment): groen = positieve opmerking,
# rood = negatieve (legacy zonder type telt als rood).
_CROSS_ICON_POS = _cross_icon_data("#16a34a")
_CROSS_ICON_NEG = _cross_icon_data("#dc2626")


def _build_hectopunt_deck(pdk: Any, work: pd.DataFrame,
                          focus_row_id: Optional[int] = None,
                          focus_zoom: float = 14.0,
                          base_url: str = _PDOK_URL) -> Any:
    # Onderste laag = gekozen achtergrond (sidebar): topografisch (PDOK BRT,
    # wegnamen/afritten/water) of luchtfoto (PDOK ortho). Raster-tegels via
    # deck.gl TileLayer.
    layers = [pdk.Layer(
        "TileLayer",
        data=base_url,
        min_zoom=0, max_zoom=19, tile_size=256,
        id="basemap",
    )]
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=work[["_lon", "_lat", "_r", "_g", "_b", "_tooltip", "_row_id"]],
        get_position=["_lon", "_lat"],
        get_fill_color=["_r", "_g", "_b", 200],
        get_radius=40,
        radius_min_pixels=4, radius_max_pixels=12,
        pickable=True, auto_highlight=True,
        id="hectopunten",
    ))

    # Vlag-laag: een gekleurd KRUISJE (×) op gemarkeerde hectopunten via een
    # IconLayer (inline SVG met witte halo voor contrast op de luchtfoto). Het
    # punt zélf houdt z'n heatmap-kleur uit de ScatterplotLayer eronder.
    # Kruiskleur = sentiment: groen = positieve opmerking, rood = negatieve
    # (legacy zonder type telt als rood). Klik blijft op de hoofdlaag pickable
    # (id="hectopunten") zodat row-selectie hetzelfde event-pad gebruikt.
    if "_flag" in work.columns and work["_flag"].any():
        cols = ["_lon", "_lat", "_row_id"]
        if "_flag_type" in work.columns:
            cols.append("_flag_type")
        flagged = work.loc[work["_flag"], cols].copy()
        is_pos = (flagged.get("_flag_type", pd.Series("", index=flagged.index))
                  .astype(str).str.lower().eq("positief"))
        flagged["_icon"] = [
            _CROSS_ICON_POS if p else _CROSS_ICON_NEG for p in is_pos
        ]
        layers.append(pdk.Layer(
            "IconLayer",
            data=flagged[["_lon", "_lat", "_icon"]],
            get_position=["_lon", "_lat"],
            get_icon="_icon",
            get_size=20,
            size_units="pixels",
            size_min_pixels=12, size_max_pixels=28,
            pickable=False,
            id="hectopunten_flag_cross",
        ))

    center_lat = float(work["_lat"].mean())
    center_lon = float(work["_lon"].mean())
    zoom = 8

    if focus_row_id is not None:
        focus = work.loc[work["_row_id"] == focus_row_id]
        if not focus.empty:
            f = focus.iloc[0]
            center_lat = float(f["_lat"])
            center_lon = float(f["_lon"])
            zoom = focus_zoom
            layers.append(pdk.Layer(
                "ScatterplotLayer",
                data=focus[["_lon", "_lat"]],
                get_position=["_lon", "_lat"],
                get_fill_color=[0, 0, 0, 0],
                get_line_color=[20, 110, 255, 255],
                line_width_min_pixels=3,
                get_radius=80,
                radius_min_pixels=10, radius_max_pixels=22,
                stroked=True, filled=False,
                pickable=False,
                id="hectopunten_focus",
            ))

    view_state = pdk.ViewState(
        latitude=center_lat, longitude=center_lon,
        zoom=zoom, pitch=0,
    )
    return pdk.Deck(
        layers=layers, initial_view_state=view_state,
        # map_provider=None ÉN map_style=None: schakel de ingebouwde Carto-
        # basemap volledig uit, anders tekent pydeck die er standaard onder en
        # lijkt het alsof de achtergrond niet verandert. Onze TileLayer is dan
        # de enige basemap → de keuze in de sidebar werkt echt door.
        map_provider=None,
        map_style=None,
        tooltip={"html": "{_tooltip}",
                 "style": {"backgroundColor": "#222", "color": "white"}},
    )


def _selected_row_id_from_event(event: Any) -> Optional[int]:
    try:
        objs = (event.selection or {}).get("objects", {}) if event else {}
        layer_objs = objs.get("hectopunten") or []
        if layer_objs:
            return int(layer_objs[0].get("_row_id"))
    except Exception:
        return None
    return None


def _resolve_selected_row_id(work: pd.DataFrame,
                             selected_row_id: Optional[int]) -> Optional[int]:
    """Geef row_id uit event terug, of val terug op het hardgecodeerde
    default-hectopunt. Valt dat ook buiten de huidige filterselectie,
    dan pakken we onvoorwaardelijk de eerste rij in `work` — zo is er
    bij opstart ALTIJD een asset zichtbaar onder de kaart.

    Tabel-selectie heeft voorrang op kaart-selectie zodat een rij-klik
    de kaart en het detailblok meteen synchroniseert. Een nieuwe map-klik
    op een ANDER punt overschrijft de tabel-selectie."""
    tbl_row_id = st.session_state.get("_asset_tbl_selected_row_id")

    if (selected_row_id is not None
            and tbl_row_id is not None
            and selected_row_id != tbl_row_id):
        st.session_state.pop("_asset_tbl_selected_row_id", None)
        tbl_row_id = None

    if tbl_row_id is not None and (work["_row_id"] == tbl_row_id).any():
        return int(tbl_row_id)
    if selected_row_id is not None:
        return selected_row_id
    if work.empty:
        st.info("Geen hectopunten in selectie.")
        return None
    try:
        wvk_match = work["wvk_id"].astype(str).str.strip() == _DEFAULT_HECTOPUNT_WVK
        hec_match = pd.to_numeric(work["hectomtrng"], errors="coerce") == _DEFAULT_HECTOPUNT_HM
        zij_match = (work["Zijde"].astype(str).str.strip().str.upper()
                     == _DEFAULT_HECTOPUNT_ZIJDE)
        default_rows = work.loc[wvk_match & hec_match & zij_match]
    except Exception:
        default_rows = work.iloc[0:0]

    if not default_rows.empty:
        st.caption(
            f"Standaard hectopunt getoond (WVK {_DEFAULT_HECTOPUNT_WVK} · "
            f"hec {_DEFAULT_HECTOPUNT_HM} · zijde {_DEFAULT_HECTOPUNT_ZIJDE}). "
            "Klik op een ander punt op de kaart voor details."
        )
        return int(default_rows.iloc[0]["_row_id"])

    # Laatste fallback: eerste rij in de filterselectie. Garandeert dat er
    # altijd asset-info onder de kaart staat — ook als de filters het
    # default-hectopunt eruit gooien.
    first = work.iloc[0]
    st.caption(
        "Standaard hectopunt valt buiten de huidige filterselectie — "
        f"eerste beschikbare punt getoond (WVK {first.get('wvk_id', '?')} · "
        f"hec {first.get('hectomtrng', '?')} · zijde {first.get('Zijde', '?')})."
    )
    return int(first["_row_id"])


def _render_flag_widget(row_data: pd.Series) -> None:
    """Vlag-toggle + vrije-tekst reden voor de geselecteerde hectopunt.

    Verandering schrijft naar `hectopunt_annotations.json` (Vlag/Vlag_reden)
    PLUS een regel in de audit-log. De rerun erna pakt de nieuwe vlag-status
    op in de kaart-laag en de asset-tabel."""
    key = _annotation_row_key(row_data)
    annotations = load_annotations()
    rec = annotations.get(key) or {}
    is_on = rec.get("Vlag") == FLAG_VALUE_ON
    reden_existing = rec.get("Vlag_reden", "")
    type_existing = (rec.get("Vlag_type") or "negatief").lower()

    _SENT_OPTS = ["Negatief (probleem)", "Positief (in orde)"]

    def _sent_to_type(choice: str) -> str:
        return "positief" if choice.startswith("Positief") else "negatief"

    with st.container(border=True):
        # Compacte layout: bediening links, foto's (groter) rechts ernaast
        # zodra het punt gemarkeerd is. Niet gemarkeerd → alleen bediening.
        if is_on:
            ctrl_col, foto_col = st.columns([3, 2], gap="medium")
        else:
            ctrl_col, foto_col = st.container(), None

        with ctrl_col:
            if is_on:
                col = "#16a34a" if type_existing == "positief" else "#dc2626"
                body = "Positief" if type_existing == "positief" else "Negatief"
            else:
                col, body = "#6b7280", "Niet gemarkeerd"
            st.markdown(
                "<div style='font-size:11px;color:#666;text-transform:uppercase;"
                "letter-spacing:0.4px;font-weight:600;'>Vlag-status</div>"
                f"<div style='font-size:18px;font-weight:700;color:{col};"
                f"line-height:1.15;margin-bottom:2px;'>{body}</div>",
                unsafe_allow_html=True,
            )
            sent_choice = st.radio(
                "Soort opmerking",
                options=_SENT_OPTS,
                index=1 if type_existing == "positief" else 0,
                horizontal=True,
                key=f"flag_type_{key}",
                help="Groen = positieve opmerking, rood = negatieve. Bepaalt de "
                     "kleur op de kaart en in het PDF-rapport.",
            )
            reden = st.text_input(
                "Reden / notitie (optioneel)",
                value=reden_existing,
                key=f"flag_reden_{key}",
                help="Wordt opgeslagen in het output-dataset én in de audit-log.",
            )
            label = "Verwijder vlag" if is_on else "Markeer hectopunt"
            btn_type = "secondary" if is_on else "primary"
            if st.button(label, key=f"flag_btn_{key}", type=btn_type,
                         use_container_width=True):
                _toggle_flag(annotations, key, reden=reden,
                             vlag_type=_sent_to_type(sent_choice))
                save_annotations(annotations)
                st.rerun()

        # Reden of soort opmerking gewijzigd bij een al-gemarkeerd punt → opslaan
        # zonder de vlag te wisselen, en herladen zodat de kaartkleur meteen klopt.
        if is_on:
            new_reden = reden.strip()
            new_type = _sent_to_type(sent_choice)
            rec2 = dict(annotations.get(key) or {})
            changed = False
            if new_reden != reden_existing.strip():
                if new_reden:
                    rec2["Vlag_reden"] = new_reden
                else:
                    rec2.pop("Vlag_reden", None)
                _audit_append(
                    annotations, key, "edit",
                    field="Vlag_reden", old=reden_existing, new=new_reden,
                    note="reden aangepast bij gemarkeerd punt",
                )
                changed = True
            if new_type != type_existing:
                rec2["Vlag_type"] = new_type
                _audit_append(
                    annotations, key, "edit",
                    field="Vlag_type", old=type_existing, new=new_type,
                    note="soort opmerking aangepast",
                )
                changed = True
            if changed:
                annotations[key] = {k: v for k, v in rec2.items() if v}
                save_annotations(annotations)
                st.rerun()

        # Foto's — rechts naast de bediening (groter, beter zichtbaar). De
        # inspecteur dropt 1–2 foto's; ze komen in het PDF-onderhoudsrapport.
        if is_on and foto_col is not None:
            with foto_col:
                foto_dir = _hectopunt_foto_dir(key, create=True)
                ups = st.file_uploader(
                    "Foto's toevoegen",
                    type=["png", "jpg", "jpeg", "webp", "bmp", "gif", "tif", "tiff"],
                    accept_multiple_files=True,
                    key=f"foto_upload_{key}",
                    label_visibility="collapsed",
                    help=f"Map: {foto_dir} — foto's verschijnen in het PDF-rapport.",
                )
                if ups:
                    saved = 0
                    for up in ups:
                        try:
                            data = up.getbuffer()
                            dest = foto_dir / Path(up.name).name
                            if (not dest.exists()) or dest.stat().st_size != len(data):
                                dest.write_bytes(data)
                                saved += 1
                        except Exception as exc:
                            st.warning(f"Foto '{up.name}' opslaan mislukte: {exc}")
                    if saved:
                        st.rerun()
                existing = _list_foto_files(foto_dir)
                if existing:
                    show = existing[:4]
                    try:
                        st.image([str(p) for p in show], width=170)
                    except Exception:
                        st.caption(", ".join(p.name for p in show))
                    if len(existing) > 4:
                        st.caption(f"+{len(existing) - 4} meer in de map.")
                else:
                    st.caption("Nog geen foto's — sleep ze hierboven naar binnen.")


def _levensduur_card_colors(remaining: Optional[int], interval: int
                            ) -> Tuple[str, str]:
    if remaining is None:
        return "#f3f4f6", Settings.COLOR_GREY_PRIMARY
    ratio = remaining / interval if interval else 0
    if ratio < 0.25:
        return "#fee2e2", "#dc2626"
    if ratio < 0.5:
        return "#fef3c7", "#d97706"
    return "#dcfce7", "#16a34a"


def _aanleg_card_colors(age_years: Optional[float]) -> Tuple[str, str]:
    if age_years is None:
        return "#f3f4f6", Settings.COLOR_GREY_PRIMARY
    if age_years > 12:
        return "#fee2e2", "#dc2626"
    if age_years > 8:
        return "#fef3c7", "#d97706"
    return "#dcfce7", "#16a34a"


def _onderhoud_card_colors(years_until: Optional[float]) -> Tuple[str, str]:
    if years_until is None:
        return "#f3f4f6", Settings.COLOR_GREY_PRIMARY
    if years_until < 2:
        return "#fee2e2", "#dc2626"
    if years_until < 5:
        return "#fef3c7", "#d97706"
    return "#dcfce7", "#16a34a"


def _render_asset_kpi_row(row_data: pd.Series,
                          annotations: Dict[str, Dict[str, str]],
                          work: Optional[pd.DataFrame] = None,
                          stacked: bool = False) -> None:
    leeftijd_jr = _safe_num(row_data.get("_leeftijd"))

    ann = annotations.get(_annotation_row_key(row_data), {})
    # Onderhoudsinterval: voorkeur de voorberekende `levensduur`-kolom,
    # anders de annotatie-/default-waarde.
    lev_col = _safe_num(row_data.get("levensduur"))
    interval_total = (int(round(lev_col)) if lev_col is not None and lev_col > 0
                      else _resolve_interval_total(ann))
    rem_val = row_data.get("_resterende_levensduur")
    remaining = None if pd.isna(rem_val) else int(rem_val)
    # Resterende levensduur als PERCENTAGE van het onderhoudsinterval
    # (gebruikersverzoek); de jaren-fractie staat in de sub-regel.
    if remaining is not None and interval_total:
        lev_value = f"{round(remaining / interval_total * 100)}%"
        lev_sub = f"{remaining}/{interval_total} jr resterend"
    else:
        lev_value = "—"
        lev_sub = f"—/{interval_total} jr resterend"
    lev_bg, lev_acc = _levensduur_card_colors(remaining, interval_total)

    aanleg_year = _latest_aanleg_year(row_data.get("aanlegdatum"), default=0)
    if aanleg_year > 0:
        aanleg_value = str(aanleg_year)
        aanleg_sub = (f"{leeftijd_jr:.0f} jr geleden"
                      if leeftijd_jr is not None else None)
    else:
        aanleg_value, aanleg_sub = "—", None
    aanleg_bg, aanleg_acc = _aanleg_card_colors(leeftijd_jr)

    today_year = int(pd.Timestamp.today().year)
    next_onderhoud = _next_onderhoud_year_for_row(row_data, work, today_year)
    if next_onderhoud is not None:
        years_until = float(next_onderhoud) - float(today_year)
        onderhoud_value = str(next_onderhoud)
        onderhoud_sub = (f"over {int(years_until)} jr"
                         if years_until >= 0 else "achterstallig")
    else:
        years_until = None
        onderhoud_value, onderhoud_sub = "—", None
    onderhoud_bg, onderhoud_acc = _onderhoud_card_colors(years_until)

    # Drie kaarten in één markdown-block (flex-kolom) i.p.v. drie losse
    # st.markdown-calls: Streamlit zet ~1rem ruimte tússen losse elementen,
    # dat gaf de overtollige witruimte. Eén block = strakke 6px-gaps.
    cards_html = (
        "<div style='display:flex;flex-direction:column;gap:6px;'>"
        + _kpi_card_html(
            "resterende_levensduur", lev_value,
            sub=lev_sub,
            bg=lev_bg, accent=lev_acc)
        + _kpi_card_html(
            "aanlegdatum", aanleg_value, sub=aanleg_sub,
            bg=aanleg_bg, accent=aanleg_acc)
        + _kpi_card_html(
            "eerstvolgend_onderhoud", onderhoud_value, sub=onderhoud_sub,
            bg=onderhoud_bg, accent=onderhoud_acc)
        + "</div>"
    )
    inspect_html = _build_inspection_table_html(
        row_data.get("health_2023"),     row_data.get("health_2025"),
        row_data.get("visibility_2023"), row_data.get("visibility_2025"),
    )
    if stacked:
        # Detailrail naast de kaart/grafieken: kaarten BÓVEN de inspectiescores
        # (gestapeld), zodat alles in één smalle kolom past.
        st.markdown(cards_html, unsafe_allow_html=True)
        st.markdown(inspect_html, unsafe_allow_html=True)
    else:
        # 2 kolommen: gekleurde KPI-kaarten links, inspectiescores rechts.
        kpi_cols = st.columns(2)
        kpi_cols[0].markdown(cards_html, unsafe_allow_html=True)
        kpi_cols[1].markdown(inspect_html, unsafe_allow_html=True)


def _resolve_initial_row_id(work: pd.DataFrame) -> Optional[int]:
    """Side-effect-free variant of `_resolve_selected_row_id` — picks the
    row that drives the upper layout (asset header + Bocht/Verkeer panes)
    BEFORE the map renders. No captions, no session_state mutations."""
    tbl_row_id = st.session_state.get("_asset_tbl_selected_row_id")
    if tbl_row_id is not None and (work["_row_id"] == tbl_row_id).any():
        return int(tbl_row_id)
    if work.empty:
        return None
    try:
        wvk_match = work["wvk_id"].astype(str).str.strip() == _DEFAULT_HECTOPUNT_WVK
        hec_match = pd.to_numeric(work["hectomtrng"], errors="coerce") == _DEFAULT_HECTOPUNT_HM
        zij_match = (work["Zijde"].astype(str).str.strip().str.upper()
                     == _DEFAULT_HECTOPUNT_ZIJDE)
        default_rows = work.loc[wvk_match & hec_match & zij_match]
    except Exception:
        default_rows = work.iloc[0:0]
    if not default_rows.empty:
        return int(default_rows.iloc[0]["_row_id"])
    return int(work.iloc[0]["_row_id"])


def _render_asset_attributes(row: pd.DataFrame, row_data: pd.Series,
                             n_cols: int = 4) -> None:
    st.markdown(
        "<div style='font-size:18px;font-weight:700;margin:8px 0 6px 0;'>"
        "Alle attributen</div>",
        unsafe_allow_html=True,
    )
    display_cols = [c for c, _ in Settings.TREE_COLUMNS
                    if c in row.columns and c not in _LINK_COLUMNS]
    label_map = dict(Settings.TREE_COLUMNS)
    detail = row_data[display_cols].rename(label_map)
    # Markeringsopmerking (Vlag_reden) vooraan toevoegen — staat niet in
    # TREE_COLUMNS maar is waardevolle context bij de attributen
    # (gebruikersverzoek). Leeg → "—".
    _opm = row_data.get("_flag_reden")
    _opm = "" if _opm is None or (isinstance(_opm, float) and pd.isna(_opm)) \
        else str(_opm).strip()
    detail = pd.concat([pd.Series({"opmerking": _opm or "—"}), detail])
    chunk = (len(detail) + n_cols - 1) // n_cols

    st.markdown('<div class="asset-attr-block">', unsafe_allow_html=True)
    attr_cols = st.columns(n_cols, gap="small")
    for i, col in enumerate(attr_cols):
        sub = detail.iloc[i * chunk:(i + 1) * chunk]
        if len(sub) == 0:
            continue
        # Slechts ~de helft van de rijen tonen; de rest zit achter een
        # inner-scroll (gebruikersverzoek: attributen nemen anders te veel
        # ruimte). 36px-rijen sluiten aan op het grotere font.
        _vis_rows = max(5, (len(sub) + 1) // 2)
        col.dataframe(
            sub.to_frame("Waarde"),
            use_container_width=True,
            height=36 * _vis_rows + 40,
        )
    st.markdown('</div>', unsafe_allow_html=True)


def _cluster_cfg_hash(cfg: Dict[str, Any]) -> str:
    """Stabiele hash van clustering-cfg. Verandert zodra een instelling
    wijzigt, zodat we de gecachte run kunnen invalideren."""
    import hashlib
    import json
    blob = json.dumps(cfg, sort_keys=True, default=str)
    return hashlib.md5(blob.encode("utf-8")).hexdigest()


def _run_cluster_button(df: pd.DataFrame, cfg: Dict[str, Any],
                        button_key: str) -> bool:
    """Render de 'Genereer clustering' knop + draai PELT ALLEEN bij een klik.

    Belangrijk: het gecachte resultaat wordt NOOIT weggegooid door een rerun
    die door iets anders is veroorzaakt (kaart-klik, filter-widget, fragment).
    Vroeger gebeurde dat wel: een tussentijdse rerun kon de clustering-widgets
    naar default resetten → cfg-hash wijzigt → cache gewist → kaart viel terug
    op geel en de diagnose verdween. Nu blijft het laatste resultaat staan tot
    de gebruiker zélf opnieuw op de knop drukt; wijken de instellingen of de
    filterselectie af, dan tonen we een melding i.p.v. de cache te slopen.
    """
    cfg_hash = _cluster_cfg_hash(cfg)

    clicked = st.button("Genereer clustering",
                        key=button_key, type="primary",
                        use_container_width=False)

    # Voorberekenen bij opstart: draai het cluster-algoritme automatisch zodra
    # de app voor het eerst laadt (nog geen resultaat in session_state), zodat
    # de eindgebruiker meteen een ingevulde clusterkaart + diagnose ziet zonder
    # eerst op de knop te hoeven drukken.
    first_run = "_clustered_df" not in st.session_state

    if clicked or first_run:
        try:
            spinner_msg = ("Clustering voorberekenen…" if first_run and not clicked
                           else "Clustering draaien…")
            with st.spinner(spinner_msg):
                clustered_df, Xw, used_feats, used_penalty = run_clustering(df, cfg)
        except Exception as exc:
            st.error(f"Clustering mislukte: {exc}")
            return False
        st.session_state["_clustered_df"]      = clustered_df
        st.session_state["_Xw"]                = Xw
        st.session_state["_used_feats"]        = used_feats
        st.session_state["_used_penalty"]      = used_penalty
        st.session_state["_clustered_cfg_hash"] = cfg_hash
        st.session_state["_clustered_len"]     = len(df)

        # Allereerste (auto) voorberekening: één rerun forceren. De kaart is
        # bovenaan deze render al getekend mét heatmap-keuze 'clusters' maar
        # zónder clusterresultaat (dat bestond toen nog niet). Na de rerun
        # vindt de kaart `_clustered_df` en kleurt hij meteen op clusters.
        if first_run and not clicked:
            st.rerun()

    have = "_clustered_df" in st.session_state
    if have:
        stale_len = st.session_state.get("_clustered_len") != len(df)
        stale_cfg = st.session_state.get("_clustered_cfg_hash") != cfg_hash
        if stale_len or stale_cfg:
            reden = "filterselectie" if stale_len else "instellingen"
            st.warning(
                f"De {reden} is gewijzigd sinds de laatste clustering — de kaart "
                "toont nog het vórige resultaat. Druk op **Genereer clustering** "
                "om bij te werken."
            )
    return have


def _render_inline_clustering_section(df: pd.DataFrame) -> None:
    """PELT-controls + clusterkaart in de Kaart-tab; deelt cfg via session_state.

    Clustering draait NIET automatisch bij elke setting-wijziging — dat is
    te traag op grote datasets. De gebruiker stelt eerst alles in en drukt
    daarna op de knop 'Genereer clustering'. Resultaat blijft tot een
    nieuwe genereer-actie of dataset-wissel.
    """
    st.divider()
    # Hele cluster→diagnose-blok in één in-/uitklapbare expander
    # (gebruikersverzoek: dichtklappen/openklappen wanneer je wilt). De body
    # van een expander draait áltijd (inklappen = puur visueel), dus de
    # clustering-cfg/widgets blijven bestaan en de andere tabs lezen `_pelt_cfg`
    # gewoon door — ook als het blok dichtgeklapt is.
    with st.expander("Clustering & diagnose", expanded=False):
        st.caption(
            "Algoritmekeuze + instellingen + clusterkaart + diagnose, allemaal "
            "in deze ene window. De gekozen instellingen worden ook door de "
            "Clustering- en Validatie-tabs gebruikt. Druk op **Genereer "
            "clustering** om het algoritme te draaien — wijzigingen daarvoor "
            "herrekenen niet automatisch."
        )

        cfg_inline = inline_algo_controls(df)
        st.session_state["_pelt_cfg"] = cfg_inline

        if sum(cfg_inline.get("weights", {}).values()) == 0:
            st.warning("Alle feature-gewichten staan op 0 — zet er minstens één hoger.")
            return

        _run_cluster_button(df, cfg_inline, button_key="cluster_generate_btn")

        clustered_df = st.session_state.get("_clustered_df")
        if clustered_df is None:
            st.info("Nog geen clustering gegenereerd — pas instellingen aan en druk op **Genereer clustering**.")
            return

        n_clusters = int(clustered_df["cluster"].nunique())
        sizes = clustered_df.groupby("cluster").size()
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Hectopunten", f"{len(clustered_df):,}")
        k2.metric("Clusters", f"{n_clusters:,}")
        k3.metric("Gem. clustergrootte", f"{sizes.mean():.1f}")
        k4.metric("Algoritme", cfg_inline.get("algo", "PELT"))

        # Géén 2e kaart meer (gebruikersverzoek: maar 1 kaart, de bovenste).
        # Het cluster-resultaat zie je op DIE kaart via de keuze **Clusters** in
        # de sidebar bij **Kaartlaag** — groen = goede gebieden, rood = slechte.
        st.success(
            "Clustering klaar. Kies links in de sidebar onder **Kaartlaag** de "
            "optie **Clusters (onderhoudsernst)** om het resultaat op de kaart te "
            "zien (groen = goed, rood = slecht)."
        )

        # Diagnose hoort bij het clusteralgoritme → direct hieronder in dezelfde
        # window. Als fragment, zodat het zoeken naar een hectopunt de zware
        # kaart hierboven niet herlaadt (gebruikersverzoek tegen vastlopen).
        render_diagnose_section(df, cfg_inline)


# Widget-keys waarvan de waarde MOET overleven, ook als hun widget een run
# niet gerenderd wordt. Reden: bij een kaart-klik doet `render_map_tab` een
# `st.rerun()` vóórdat de clustering-/diagnose-widgets onderaan getekend zijn.
# Streamlit ruimt session_state van niet-getekende widgets op → de sliders
# zouden naar default terugvallen, waardoor de cfg-hash wijzigt en de gecachte
# clustering onterecht wordt weggegooid (kaart wordt geel, diagnose verdwijnt).
_PERSIST_WIDGET_KEYS: List[str] = (
    ["cluster_algo", "pelt_mode", "pelt_penalty", "pelt_target_k",
     "pelt_model", "pelt_min_size", "pelt_use_cap", "pelt_max_cap",
     "pelt_respect_segment", "pelt_group_zijde", "pelt_group_lttr",
     # map_heatmap_col staat NIET in deze lijst: die widget leeft sinds de
     # verhuizing in de sidebar (sidebar_filters) en wordt dus élke run
     # getekend vóór render_map_tab. Self-assignment ná instantiatie =
     # StreamlitAPIException. Sidebar-state overleeft de rerun vanzelf.
     "diag_weg", "diag_zijde", "diag_lttr", "diag_hm", "diag_window"]
    + [f"w_{f}" for f in Settings.DEFAULT_WEIGHTS]
)


def _persist_widget_state(keys: List[str]) -> None:
    """Houd widget-state in leven over een tussentijdse `st.rerun()` heen.

    Streamlit verwijdert de session_state van widgets die in een run niet
    geïnstantieerd worden. Door de waarde aan zichzelf toe te wijzen (vóór de
    widget opnieuw rendert) blijft hij behouden, zodat de clustering-cfg
    stabiel blijft en de gecachte clustering niet onnodig invalideert."""
    for k in keys:
        if k in st.session_state:
            st.session_state[k] = st.session_state[k]


# ============================================================
# ONDERHOUDSRAPPORT (PDF) — printbare uitdraai van gemarkeerde punten
# ------------------------------------------------------------
# A4-rapport dat regio-inspecteurs uitprinten en met aannemers delen:
# per handmatig gemarkeerd hectopunt de LOCATIE (netjes per regel, incl.
# klikbare StreetSmart-/Google-Maps-links) en de TOELICHTING uit de
# markering. Géén prioriteit-/onderhoud-/restlevensduur-kolommen.
# Gebouwd met matplotlib PdfPages (geen externe PDF-dependency nodig).
# ============================================================
_RAP_ML, _RAP_MR = 0.06, 0.97          # marges (axes-fractie)
_RAP_TOP, _RAP_BOTTOM = 0.92, 0.055    # content-venster
_RAP_NAVY = "#1f3a5f"
_RAP_LINK = "#1a56db"                    # kleur voor klikbare links
_RAP_A4 = (8.27, 11.69)


def _rap_links(row: pd.Series) -> List[Tuple[str, str]]:
    """[(label, url)] voor geldige StreetSmart-/Google-Maps-links van de rij."""
    out: List[Tuple[str, str]] = []
    for label, col in (("StreetSmart", "streetsmart_link"),
                       ("Google Maps", "google_maps_link")):
        raw = row.get(col)
        url = str(raw).strip() if pd.notna(raw) else ""
        if url.lower().startswith("http"):
            out.append((label, url))
    return out


def _rap_gps(row: pd.Series) -> str:
    lat, lon = _safe_num(row.get("_lat")), _safe_num(row.get("_lon"))
    if lat is not None and lon is not None:
        return f"{lat:.5f}, {lon:.5f}"
    raw = row.get("gps_coordinaten")
    return str(raw) if pd.notna(raw) else "—"


def _rap_wrap(text: Any, chars: int) -> List[str]:
    import textwrap
    s = "" if text is None or (isinstance(text, float) and pd.isna(text)) else str(text)
    if not s.strip():
        return ["—"]
    out: List[str] = []
    for part in s.split("\n"):
        out.extend(textwrap.wrap(part, width=max(4, chars)) or [""])
    return out or ["—"]


# Kolommen die NIET als platte attribuut-regel op de detailpagina horen:
# links staan al als klikbare regels, geometrie/score zijn interne velden.
_RAP_SKIP_ATTR_COLS: Set[str] = set(_LINK_COLUMNS) | {
    "hectopunt_geometry", "_alert_score", "gps_coordinaten",
}


def _rap_fmt_val(v: Any) -> str:
    """Compacte tekstweergave van één celwaarde voor het rapport."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float):
        if pd.isna(v):
            return ""
        return str(int(v)) if float(v).is_integer() else f"{v:.2f}"
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def _rap_load_image(path: Path) -> Optional[np.ndarray]:
    """Beeldbestand als RGB-array (Pillow → matplotlib fallback). None bij fout."""
    try:
        from PIL import Image
        return np.asarray(Image.open(path).convert("RGB"))
    except Exception:
        try:
            return plt.imread(str(path))
        except Exception:
            return None


# ── Accentkleuren + Nederland-kaart ("Enderland") voor het rapport ──────────
_RAP_OK   = "#16a34a"
_RAP_WARN = "#d97706"
_RAP_BAD  = "#dc2626"
_RAP_MUTE = "#6b7280"

# Volledige Nederland-extent in RD New (EPSG:28992) — sluit aan op de
# gecachte PDOK-basemap (zie _add_nl_basemap / download-bounds).
_RAP_NL_XLIM = (0.0, 300_000.0)
_RAP_NL_YLIM = (289_000.0, 629_000.0)


def _rap_sent_color(row: Any) -> str:
    """Markeringskleur o.b.v. sentiment: groen = positieve opmerking, rood =
    negatieve (legacy/onbekend telt als negatief)."""
    try:
        t = str(row.get("_flag_type") or "").lower()
    except Exception:
        t = ""
    return _RAP_OK if t == "positief" else _RAP_BAD


# PDOK luchtfoto voor de sterk ingezoomde landschapskaart (zelfde bron als de
# dashboard-achtergrond).
_RAP_LUCHTFOTO_URL = _PDOK_LUCHTFOTO_URL
# Per-run guard: zodra één online tegel-fetch faalt, niet opnieuw proberen
# (voorkomt dat elk gemarkeerd punt opnieuw op een timeout wacht).
_RAP_RUNTIME: Dict[str, Any] = {"online": None}


def _rap_fmt_date(ts: Any) -> str:
    """ISO-timestamp → 'DD-MM-JJJJ' (of lege string bij onbekend)."""
    s = str(ts or "")[:10]
    try:
        y, m, d = s.split("-")
        return f"{d}-{m}-{y}"
    except Exception:
        return s


def _rap_remarks_by_key(annotations: Dict[str, Any]
                        ) -> Dict[str, List[Tuple[str, str]]]:
    """key → [(datum, opmerking)] uit de audit-log: elke markering-registratie
    (`flag_on`) en latere reden-aanpassing (`edit` op Vlag_reden) als gedateerde
    regel, zodat duplicaten van hetzelfde hectopunt op één pagina samengevoegd
    kunnen worden met de datum waarop er iets is opgemerkt."""
    out: Dict[str, List[Tuple[str, str]]] = {}
    log = annotations.get(AUDIT_LOG_KEY) or []
    if not isinstance(log, list):
        return out
    for e in log:
        if not isinstance(e, dict):
            continue
        action = e.get("action")
        if action == "flag_on":
            text = (e.get("note") or "").strip()
        elif action == "edit" and e.get("field") == "Vlag_reden":
            text = (e.get("new") or "").strip()
        else:
            continue
        out.setdefault(e.get("key") or "", []).append(
            (_rap_fmt_date(e.get("ts")), text))
    for key, items in out.items():           # opeenvolgende dubbels weglaten
        dedup: List[Tuple[str, str]] = []
        for it in items:
            if not dedup or dedup[-1] != it:
                dedup.append(it)
        out[key] = dedup
    return out


def _rap_zoom_axes(fig: Any, rect: Tuple[float, float, float, float],
                   cx: float, cy: float, half_m: float, *,
                   sources: Tuple[str, ...] = ()) -> Any:
    """Vierkant kaartje gecentreerd op (cx, cy) RD met halve breedte `half_m`
    meter. Probeert eerst online PDOK-tegels uit `sources`; valt anders terug op
    de gecachte NL-basemap (uitsnede). Tekent een rode ster op het punt."""
    iax = fig.add_axes(rect)
    iax.set_aspect("equal")
    iax.axis("off")
    iax.set_xlim(cx - half_m, cx + half_m)
    iax.set_ylim(cy - half_m, cy + half_m)
    drawn = False
    if _CTX_OK and sources and _RAP_RUNTIME.get("online") is not False:
        for src in sources:
            try:
                ctx.add_basemap(iax, crs="EPSG:28992", source=src,
                                attribution=False)
                _RAP_RUNTIME["online"] = True
                drawn = True
                break
            except Exception:
                continue
        if not drawn:
            _RAP_RUNTIME["online"] = False
    if not drawn:
        cache = Settings.BASEMAP_CACHE
        if cache.exists():
            try:
                data = np.load(str(cache))
                iax.imshow(data["img"], extent=data["ext"].tolist(),
                           origin="upper", zorder=0, interpolation="bilinear")
            except Exception:
                pass
    iax.set_xlim(cx - half_m, cx + half_m)    # basemap kan lims verzetten
    iax.set_ylim(cy - half_m, cy + half_m)
    iax.add_patch(mpatches.Rectangle((0, 0), 1, 1, transform=iax.transAxes,
                                     fill=False, edgecolor="#cdd4db", lw=0.8,
                                     zorder=9))
    iax.scatter([cx], [cy], s=260, marker="*", c=_RAP_BAD,
                edgecolors="white", linewidths=1.1, zorder=10)
    return iax, drawn


def _rap_detail_maps(fig: Any, ax: Any, row: pd.Series) -> None:
    """Twee locatiekaarten rechtsboven: (1) regiokaart (~¼ van Nederland) voor de
    globale ligging, en (2) een sterk ingezoomde luchtfoto/omgevingskaart zodat de
    eindgebruiker het landschap/gebied rond het punt herkent."""
    cx = _safe_num(row.get("_rd_x"))
    cy = _safe_num(row.get("_rd_y"))
    reg_rect = (0.63, 0.700, 0.305, 0.185)
    near_rect = (0.63, 0.500, 0.305, 0.185)
    ax.text(0.7825, 0.912, "Regio — globale ligging", fontsize=8.5,
            fontweight="bold", color=_RAP_NAVY, ha="center", va="top")
    ax.text(0.7825, 0.695, "Ingezoomd — landschap/gebied", fontsize=8.5,
            fontweight="bold", color=_RAP_NAVY, ha="center", va="top")
    if cx is None or cy is None:
        for r in (reg_rect, near_rect):
            iax = fig.add_axes(r)
            iax.axis("off")
            iax.add_patch(mpatches.Rectangle((0, 0), 1, 1, transform=iax.transAxes,
                                             fill=False, edgecolor="#cdd4db", lw=0.8))
            iax.text(0.5, 0.5, "(geen coördinaten)", transform=iax.transAxes,
                     ha="center", va="center", fontsize=7, color=_RAP_MUTE)
        return
    # 1) Regio ~80 km breed (¼ NL) — gecachte basemap volstaat.
    _rap_zoom_axes(fig, reg_rect, cx, cy, 40_000.0)
    # 2) Sterk ingezoomd ~1,6 km breed — online luchtfoto, fallback topo/cache.
    near_iax, near_online = _rap_zoom_axes(
        fig, near_rect, cx, cy, 800.0,
        sources=(_RAP_LUCHTFOTO_URL, _PDOK_URL))
    if not near_online:
        near_iax.text(0.5, 0.04, "(luchtfoto vereist internet)",
                      transform=near_iax.transAxes, ha="center", va="bottom",
                      fontsize=7, style="italic", color=_RAP_MUTE, zorder=11)


def _rap_enderland_map(fig: Any, rect: Tuple[float, float, float, float],
                       all_flagged: pd.DataFrame,
                       focus: Optional[pd.Series] = None) -> Any:
    """Locatiekaart op `rect` (fig-fractie) met de gemarkeerde punten.

    Zonder `focus` zoomt de kaart in op het GEBIED waar de gemarkeerde punten
    liggen (bounding box + marge) i.p.v. heel Nederland te tonen; de punten
    krijgen hun sentimentkleur (groen = positief, rood = negatief) en worden
    NIET genummerd. Met `focus` (één rij) toont 'm heel NL met die rij als grote
    ster en de overige punten gedempt erachter."""
    iax = fig.add_axes(rect)
    iax.set_aspect("equal")
    iax.axis("off")
    has_pts = (all_flagged is not None and not all_flagged.empty
               and "_rd_x" in all_flagged.columns)
    pts = (all_flagged[all_flagged["_rd_x"].notna() & all_flagged["_rd_y"].notna()]
           if has_pts else None)

    # Doel-extent bepalen vóór de basemap (imshow kan de assen-limieten
    # verzetten). Zonder focus: inzoomen op de bounding box van de punten.
    if focus is None and pts is not None and not pts.empty:
        xs = pd.to_numeric(pts["_rd_x"], errors="coerce")
        ys = pd.to_numeric(pts["_rd_y"], errors="coerce")
        cx = float((xs.min() + xs.max()) / 2.0)
        cy = float((ys.min() + ys.max()) / 2.0)
        # Vierkant venster: grootste spanwijdte, met ondergrens zodat een enkele
        # of strak geclusterde set niet absurd ver inzoomt, + ~15% marge.
        span = max(float(xs.max() - xs.min()),
                   float(ys.max() - ys.min()), 8_000.0)
        half = span * 1.15 / 2.0
        xlim, ylim = (cx - half, cx + half), (cy - half, cy + half)
    else:
        xlim, ylim = _RAP_NL_XLIM, _RAP_NL_YLIM

    iax.set_xlim(*xlim)
    iax.set_ylim(*ylim)
    try:
        _add_nl_basemap(iax)
    except Exception:
        pass
    iax.set_xlim(*xlim)          # na basemap opnieuw zetten → zoom vasthouden
    iax.set_ylim(*ylim)
    iax.add_patch(mpatches.Rectangle((0, 0), 1, 1, transform=iax.transAxes,
                                     fill=False, edgecolor="#cdd4db", lw=0.8,
                                     zorder=5))
    if pts is None or pts.empty:
        iax.text(0.5, 0.5, "(geen coördinaten)", transform=iax.transAxes,
                 ha="center", va="center", fontsize=7, color=_RAP_MUTE)
        return iax
    fx = _safe_num(focus.get("_rd_x")) if focus is not None else None
    fy = _safe_num(focus.get("_rd_y")) if focus is not None else None
    if focus is not None and fx is not None and fy is not None:
        iax.scatter(pts["_rd_x"], pts["_rd_y"], s=10, c=_RAP_MUTE,
                    edgecolors="none", alpha=0.55, zorder=6)
        iax.scatter([fx], [fy], s=240, marker="*", c=_rap_sent_color(focus),
                    edgecolors="white", linewidths=1.0, zorder=8)
    else:
        # Sentimentkleur per punt; géén nummering (gebruikersverzoek).
        colors = ([_rap_sent_color(p) for _, p in pts.iterrows()]
                  if "_flag_type" in pts.columns else _RAP_BAD)
        iax.scatter(pts["_rd_x"], pts["_rd_y"], s=22, c=colors,
                    edgecolors="white", linewidths=0.4, alpha=0.95, zorder=6)
    return iax


# Thematische groepering van alle attributen op de detailpagina.
_RAP_GROUPS: List[Tuple[str, List[str]]] = [
    ("Locatie & weg", ["wegnr_hmp", "hectomtrng", "hecto_lttr", "Zijde",
                       "strook", "rijrichtng", "distrnaam", "wegbehnaam",
                       "beginkm", "eindkm", "afstand", "snelwegnummer",
                       "wegnummer", "wegnr_aw", "oplopend", "wvk_id"]),
    ("Gezondheid & inspectie", ["health_2023", "visibility_2023", "health_2025",
                                "visibility_2025", "aantal_inspecties"]),
    ("Verkeersintensiteit", ["klein_voertuig", "middel_voertuig",
                             "lang_voertuig", "totaal_voertuig"]),
    ("Geometrie / bocht", ["draaihoek", "boogstraal", "aantal_bochten"]),
    ("Deklaag & leeftijd", ["deklaagsoort", "aanlegdatum", "aantal_deklagen",
                            "_leeftijd_str"]),
    ("Overig", ["info"]),
]


def _rap_render_groups(ax: Any, row: pd.Series, x_left: float, x_right: float,
                       top: float, bottom: float, lh: float = 0.0145,
                       ncols: int = 2, fs: float = 7.5) -> None:
    """Render álle beschikbare info als gegroepeerde 'definitielijst' over
    `ncols` kolommen — sectiekoppen in navy, waardes eronder. Stroomt naar de
    volgende kolom als de huidige vol is; rest valt onder '+N extra velden'."""
    labels = dict(Settings.TREE_COLUMNS)
    total_w = x_right - x_left
    colw = total_w / ncols
    cols_x = [x_left + i * colw for i in range(ncols)]
    max_chars = max(16, int((colw - 0.012) / 0.0072))   # past op kolombreedte
    ci = 0
    ty = top
    overflow = 0

    def to_next_col() -> bool:
        nonlocal ci, ty
        if ci < ncols - 1:
            ci += 1
            ty = top
            return True
        return False

    for title, cols in _RAP_GROUPS:
        pairs = [(labels.get(c, c), _rap_fmt_val(row.get(c))) for c in cols]
        pairs = [(l, v) for l, v in pairs if v]
        if not pairs:
            continue
        # Hele groep (kop + regels) vooraf inmeten: past die niet in de huidige
        # kolom, spring dan naar de volgende — voorkomt een 'wees'-kop onderaan.
        if ty - lh * (1 + len(pairs)) < bottom and not to_next_col():
            pass
        if ty - lh * 2 < bottom and not to_next_col():
            overflow += len(pairs)
            continue
        ax.text(cols_x[ci], ty, title.upper(), fontsize=fs, fontweight="bold",
                color=_RAP_NAVY, ha="left", va="top")
        ty -= lh * 1.15
        for lbl, val in pairs:
            if ty - lh < bottom and not to_next_col():
                overflow += 1
                continue
            text = f"{lbl}: {val}"
            if len(text) > max_chars:
                text = text[:max_chars - 1] + "…"
            ax.text(cols_x[ci], ty, text, fontsize=fs, color="#23272b",
                    ha="left", va="top")
            ty -= lh
        ty -= lh * 0.4
    if overflow:
        ax.text(x_right, bottom + 0.002,
                f"(+{overflow} extra velden — zie dataset-export)",
                fontsize=7, style="italic", color="#9aa3ac",
                ha="right", va="bottom")


def _rap_page(state: Dict[str, Any], meta: Dict[str, Any]) -> Tuple[Any, Any]:
    """Nieuw A4-vel met kop- en voetregel; geeft (fig, ax) terug."""
    fig = Figure(figsize=_RAP_A4, facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    # Voetregel
    state["page"] = state.get("page", 0) + 1
    ax.plot([_RAP_ML, _RAP_MR], [_RAP_BOTTOM - 0.012, _RAP_BOTTOM - 0.012],
            color="#cdd4db", lw=0.6)
    ax.text(_RAP_ML, _RAP_BOTTOM - 0.026,
            "Rijkswaterstaat — Onderhoudsrapport wegmarkeringen",
            fontsize=7, color="#7a828b", ha="left", va="top")
    ax.text((_RAP_ML + _RAP_MR) / 2, _RAP_BOTTOM - 0.026,
            meta.get("generated", ""), fontsize=7, color="#7a828b",
            ha="center", va="top")
    ax.text(_RAP_MR, _RAP_BOTTOM - 0.026, f"Pagina {state['page']}",
            fontsize=7, color="#7a828b", ha="right", va="top")
    return fig, ax


def _rap_detail_page(pdf: Any, state: Dict[str, Any], meta: Dict[str, Any],
                     row: pd.Series, foto_dir: Path, idx: int, total: int,
                     remarks: Optional[List[Tuple[str, str]]] = None) -> None:
    """Eén volledige A4-detailpagina voor één gemarkeerd hectopunt: kopband met
    locatie, de (over duplicaten samengevoegde, gedateerde) markeringsopmerkingen
    plus 5 vaste schrijfregels voor handmatige notities, twee locatiekaarten
    (regio + sterk ingezoomd), ALLE beschikbare info gegroepeerd in twee kolommen,
    klikbare links en 1–2 foto's uit de fotomap van dit punt."""
    fig, ax = _rap_page(state, meta)

    # ── Kopband (navy) met locatie-titel ──────────────────────
    ax.add_patch(mpatches.Rectangle((0, 0.93), 1, 0.07,
                                     facecolor=_RAP_NAVY, edgecolor="none"))
    loc_bits: List[str] = []
    weg = row.get("wegnr_hmp") or row.get("snelwegnummer")
    if pd.notna(weg) and str(weg).strip():
        loc_bits.append(f"Weg {str(weg).strip()}")
    hm = _safe_num(row.get("hectomtrng"))
    if hm is not None:
        loc_bits.append(f"hm {hm:.1f}")
    zij = str(row.get("Zijde") or "").strip()
    if zij:
        loc_bits.append(f"zijde {zij}")
    lttr = str(row.get("hecto_lttr") or "").strip()
    if lttr:
        loc_bits.append(f"letter {lttr}")
    title = "Hectopunt — " + (" · ".join(loc_bits) or "onbekende locatie")
    ax.text(_RAP_ML, 0.967, title, fontsize=15, fontweight="bold",
            color="white", ha="left", va="center")
    ax.text(_RAP_ML, 0.944, f"GPS: {_rap_gps(row)}", fontsize=8.5,
            color="#d6e0ec", ha="left", va="center")
    ax.text(_RAP_MR, 0.955, f"{idx} / {total}", fontsize=10, fontweight="bold",
            color="#d6e0ec", ha="right", va="center")

    # ── Twee locatiekaarten (rechtsboven): regio + sterk ingezoomd ─
    _rap_detail_maps(fig, ax, row)

    # ── Markeringsopmerking(en) + handgeschreven-notitieruimte (links) ─
    # Box met vaste onderkant (lijnt met de kaarten); de 5 schrijfregels worden
    # over de resthoogte verdeeld zodat er geen loze witruimte ontstaat.
    cb_x, cb_w, cb_top, cb_bottom = _RAP_ML, 0.51, 0.905, 0.500
    cb_h = cb_top - cb_bottom
    ax.add_patch(mpatches.Rectangle((cb_x, cb_bottom), cb_w, cb_h,
                                    facecolor="#eef3f9", edgecolor="#cdd9e8",
                                    lw=0.8, zorder=1))
    _sent_col = _rap_sent_color(row)
    _sent_txt = ("POSITIEF" if str(row.get("_flag_type") or "").lower()
                 == "positief" else "NEGATIEF")
    ax.add_patch(mpatches.Rectangle((cb_x, cb_bottom), 0.007, cb_h,
                                    facecolor=_sent_col, edgecolor="none", zorder=2))
    ax.text(cb_x + 0.02, cb_top - 0.018, "MARKERINGSOPMERKING(EN)",
            fontsize=9, fontweight="bold", color=_RAP_NAVY, ha="left", va="top")
    ax.text(cb_x + cb_w - 0.02, cb_top - 0.018, _sent_txt, fontsize=8.5,
            fontweight="bold", color=_sent_col, ha="right", va="top")

    items = list(remarks or [])
    disp: List[str] = []
    if items:
        for d, txt in items[:6]:
            body = txt or "(gemarkeerd — geen tekst)"
            line = (f"• {d}  —  {body}" if d else f"• {body}")
            disp.append(line[:63] + "…" if len(line) > 64 else line)
        if len(items) > 6:
            disp.append(f"(+{len(items) - 6} eerdere registratie(s))")
    else:
        fb = str(row.get("_flag_reden") or "").strip()
        disp = (_rap_wrap(fb, 60)[:4] if fb
                else ["— (geen opmerking geregistreerd)"])

    ty = cb_top - 0.045
    for line in disp:
        italic = line.startswith(("(", "—"))
        ax.text(cb_x + 0.02, ty, line, fontsize=8.5,
                color=("#9aa3ac" if italic else "#23272b"),
                style=("italic" if italic else "normal"), ha="left", va="top")
        ty -= 0.0185

    # 5 vaste schrijfregels — verdeeld over de resterende boxhoogte.
    ax.text(cb_x + 0.02, ty - 0.006, "Handmatige notities (aannemer):",
            fontsize=7.5, fontweight="bold", color="#54606b", ha="left", va="top")
    area_top, area_bottom, n_rules = ty - 0.034, cb_bottom + 0.024, 5
    step = max(0.022, (area_top - area_bottom) / (n_rules - 1))
    for i in range(n_rules):
        ry = area_top - i * step
        if ry < cb_bottom + 0.012:
            break
        ax.plot([cb_x + 0.02, cb_x + cb_w - 0.02], [ry, ry],
                color="#b8c2cf", lw=0.6)

    # ── Alle beschikbare informatie (compact, drie kolommen) ──
    ax.plot([_RAP_ML, _RAP_MR], [0.488, 0.488], color="#cdd4db", lw=0.6)
    ax.text(_RAP_ML, 0.480, "Alle beschikbare informatie", fontsize=10.5,
            fontweight="bold", color=_RAP_NAVY, ha="left", va="top")
    _rap_render_groups(ax, row, _RAP_ML, _RAP_MR, top=0.462, bottom=0.378,
                       lh=0.0135, ncols=3, fs=7.0)

    # ── Klikbare links ────────────────────────────────────────
    ax.plot([_RAP_ML, _RAP_MR], [0.372, 0.372], color="#cdd4db", lw=0.6)
    links = _rap_links(row)
    ax.text(_RAP_ML, 0.362, "Links:", fontsize=8.5, fontweight="bold",
            color="#54606b", ha="left", va="top")
    lx = 0.13
    if links:
        for label, url in links:
            ax.text(lx, 0.362, f"{label}  ↗", fontsize=8.5, color=_RAP_LINK,
                    ha="left", va="top", url=url)
            lx += 0.16
    else:
        ax.text(lx, 0.362, "geen links beschikbaar", fontsize=8.5,
                style="italic", color="#9aa3ac", ha="left", va="top")

    # ── Foto's — groot, op een rij (onderste helft van de pagina) ──
    ax.text(_RAP_ML, 0.340, "Foto's", fontsize=11, fontweight="bold",
            color=_RAP_NAVY, ha="left", va="top")
    photos = _list_foto_files(foto_dir)[:4]
    if photos:
        n = len(photos)
        gap = 0.02
        area_w = _RAP_MR - _RAP_ML
        bw = (area_w - gap * (n - 1)) / n
        by, bh = 0.050, 0.282
        for i, p in enumerate(photos):
            bx = _RAP_ML + i * (bw + gap)
            ax.add_patch(mpatches.Rectangle((bx, by), bw, bh, facecolor="#f4f6f8",
                                            edgecolor="#d9dee3", zorder=0))
            arr = _rap_load_image(p)
            iax = fig.add_axes([bx, by, bw, bh])
            if arr is not None:
                iax.imshow(arr)
            else:
                iax.text(0.5, 0.5, "(foto kon niet geladen worden)",
                         ha="center", va="center", fontsize=8, color="#b00020")
            iax.axis("off")
            ax.text(bx + bw / 2, by - 0.012, p.name[:34], fontsize=7,
                    color="#54606b", ha="center", va="top")
    else:
        ax.text(_RAP_ML, 0.318,
                f"Geen foto's in de map. Zet foto's neer in: {foto_dir.name}",
                fontsize=8.5, style="italic", color="#9aa3ac",
                ha="left", va="top")

    pdf.savefig(fig)
    plt.close(fig)


def _rap_flagged_section(pdf: Any, state: Dict[str, Any], meta: Dict[str, Any],
                         flagged: pd.DataFrame,
                         remarks_by_key: Optional[Dict[str, List[Tuple[str, str]]]] = None
                         ) -> None:
    """Eén detailpagina per (ontdubbeld) gemarkeerd hectopunt: gedateerde
    markeringsopmerkingen + schrijfregels, twee locatiekaarten, alle info,
    klikbare links en 1–2 foto's uit de fotomap van dat punt."""
    remarks_by_key = remarks_by_key or {}
    if flagged.empty:
        fig, ax = _rap_page(state, meta)
        ax.text(_RAP_ML, _RAP_TOP, "Gemarkeerde hectopunten — onderhoud nodig",
                fontsize=15, fontweight="bold", color=_RAP_NAVY,
                ha="left", va="top")
        ax.text(_RAP_ML, _RAP_TOP - 0.04,
                "Geen gemarkeerde hectopunten in de huidige selectie. "
                "Markeer punten via de vlag-knop op de kaart.",
                fontsize=9, style="italic", color="#7a828b",
                ha="left", va="top")
        pdf.savefig(fig)
        plt.close(fig)
        return

    total = int(len(flagged))
    for i, (_, r) in enumerate(flagged.iterrows(), start=1):
        key = _annotation_row_key(r)
        foto_dir = _hectopunt_foto_dir(key)
        _rap_detail_page(pdf, state, meta, r, foto_dir, i, total,
                         remarks=remarks_by_key.get(key))


def _rap_loc_label(row: pd.Series) -> str:
    """Compacte locatie-aanduiding (weg · hm · zijde · letter) voor lijsten."""
    bits: List[str] = []
    weg = row.get("wegnr_hmp") or row.get("snelwegnummer")
    if pd.notna(weg) and str(weg).strip():
        bits.append(str(weg).strip())
    hm = _safe_num(row.get("hectomtrng"))
    if hm is not None:
        bits.append(f"hm {hm:.1f}")
    z = str(row.get("Zijde") or "").strip()
    if z:
        bits.append(z)
    lt = str(row.get("hecto_lttr") or "").strip()
    if lt:
        bits.append(lt)
    return " · ".join(bits) or "onbekend"


def _rap_overview(pdf: Any, state: Dict[str, Any], meta: Dict[str, Any],
                  flagged: pd.DataFrame) -> None:
    """In-één-oogopslag pagina: links een Nederlandkaart met álle gemarkeerde
    punten (genummerd), rechts een inhoudsopgave die per punt de locatie, de
    markeringsopmerking en het paginanummer toont."""
    fig, ax = _rap_page(state, meta)
    page_offset = state["page"]            # detailpagina i → page_offset + i

    ax.add_patch(mpatches.Rectangle((0, 0.93), 1, 0.07,
                                    facecolor=_RAP_NAVY, edgecolor="none"))
    ax.text(_RAP_ML, 0.967, "Overzicht — gemarkeerde hectopunten",
            fontsize=15, fontweight="bold", color="white", ha="left", va="center")
    ax.text(_RAP_ML, 0.944,
            f"{len(flagged)} punt(en) · in één oogopslag: locatie, "
            "opmerking en paginanummer", fontsize=8.5, color="#d6e0ec",
            ha="left", va="center")

    if flagged.empty:
        ax.text(_RAP_ML, 0.86,
                "Geen gemarkeerde hectopunten in de huidige selectie. "
                "Markeer punten via de vlag-knop op de kaart.",
                fontsize=9.5, style="italic", color="#7a828b",
                ha="left", va="top")
        pdf.savefig(fig)
        plt.close(fig)
        return

    # ── Kaart bovenaan (vult ≥¼ van de pagina) ────────────────
    ax.text(0.5, 0.912,
            "Kaart — ingezoomd op de gemarkeerde punten "
            "(groen = positief, rood = negatief)",
            fontsize=9, fontweight="bold", color=_RAP_NAVY,
            ha="center", va="top")
    _rap_enderland_map(fig, (0.16, 0.605, 0.68, 0.300), flagged)

    # ── Opsomming gemarkeerde punten daaronder (vult de hele rest) ──
    n = int(len(flagged))
    reg_top, reg_bottom = 0.582, 0.050
    region_h = reg_top - reg_bottom

    # Header-/kolomregel.
    ax.text(_RAP_ML, reg_top + 0.026, "#   Locatie · markeringsopmerking",
            fontsize=8, fontweight="bold", color="#54606b", ha="left", va="top")
    ax.text(_RAP_MR, reg_top + 0.026, "pagina", fontsize=8, fontweight="bold",
            color="#54606b", ha="right", va="top")
    ax.plot([_RAP_ML, _RAP_MR], [reg_top + 0.012, reg_top + 0.012],
            color="#cdd4db", lw=0.6)

    # Zo min mogelijk kolommen kiezen (1→2→3) zodat alles met een leesbare
    # regelhoogte past; daarna de rijen over de volledige hoogte verdelen.
    MIN_ROWH = 0.0135
    ncols = 3
    for c in (1, 2, 3):
        rows = -(-n // c)                      # ceil(n / c)
        if rows * MIN_ROWH <= region_h:
            ncols = c
            break
    rows_per_col = max(1, -(-n // ncols))
    capacity = ncols * rows_per_col
    truncated = n > capacity
    rowh = min(0.075, region_h / rows_per_col)    # vul, maar niet absurd hoog
    used_h = rowh * rows_per_col
    start_top = reg_top - max(0.0, (region_h - used_h)) / 2.0   # blok centreren
    gap = 0.022
    colw = (_RAP_MR - _RAP_ML - gap * (ncols - 1)) / ncols
    text_chars = max(10, int((colw - 0.085) / 0.0088))
    fs = 9.0 if rowh >= 0.030 else (8.0 if rowh >= 0.020 else
                                    (7.2 if rowh >= 0.016 else 6.4))

    for i0 in range(min(n, capacity)):
        ci, ri = divmod(i0, rows_per_col)
        cx0 = _RAP_ML + ci * (colw + gap)
        row_top = start_top - ri * rowh
        cyc = row_top - rowh / 2.0                 # verticaal midden van de rij
        nlabel = i0 + 1
        if nlabel % 2 == 0:
            ax.add_patch(mpatches.Rectangle((cx0 - 0.004, row_top - rowh),
                                            colw + 0.008, rowh,
                                            facecolor="#f4f6f8", edgecolor="none",
                                            zorder=0))
        r = flagged.iloc[i0]
        loc = _rap_loc_label(r)
        opm = str(r.get("_flag_reden") or "").strip()
        s = f"{loc}  —  {opm}" if (opm and len(loc) + 4 < text_chars) else loc
        if len(s) > text_chars:
            s = s[:text_chars - 1] + "…"
        ax.text(cx0 + 0.004, cyc, str(nlabel), fontsize=fs, fontweight="bold",
                color=_rap_sent_color(r), ha="left", va="center")
        ax.text(cx0 + 0.034, cyc, s, fontsize=fs, color="#23272b",
                ha="left", va="center")
        ax.text(cx0 + colw, cyc, str(page_offset + nlabel), fontsize=fs,
                color="#54606b", ha="right", va="center")
    if truncated:
        ax.text(_RAP_MR, reg_bottom - 0.006,
                f"(+{n - capacity} meer — zie detailpagina's; "
                "alle punten staan wél op de kaart)",
                fontsize=7, style="italic", color="#9aa3ac",
                ha="right", va="top")

    pdf.savefig(fig)
    plt.close(fig)


def _rap_cover(pdf: Any, state: Dict[str, Any], meta: Dict[str, Any]) -> None:
    fig, ax = _rap_page(state, meta)
    # Donkere kopband
    ax.add_patch(mpatches.Rectangle((0, 0.86), 1, 0.14, facecolor=_RAP_NAVY,
                                    edgecolor="none"))
    if Settings.LOGO_PATH.exists():
        try:
            logo = plt.imread(str(Settings.LOGO_PATH))
            la = fig.add_axes([_RAP_ML, 0.875, 0.10, 0.10])
            la.imshow(logo)
            la.axis("off")
        except Exception:
            pass
    ax.text(0.50, 0.945, "Onderhoudsrapport Wegmarkeringen",
            fontsize=20, fontweight="bold", color="white", ha="center", va="center")
    ax.text(0.50, 0.905, "Gemarkeerde hectopunten — info, toelichting & foto’s",
            fontsize=10.5, color="#d6e0ec", ha="center", va="center")

    # Meta / kerncijfers
    y = 0.80
    ax.text(_RAP_ML, y, "Rapportgegevens", fontsize=12, fontweight="bold",
            color=_RAP_NAVY, ha="left", va="top")
    y -= 0.030
    info = [
        ("Gegenereerd op", meta.get("generated", "—")),
        ("Dataset", str(meta.get("dataset", "—"))),
        ("Actieve filters", meta.get("filter_summary", "—")),
    ]
    for label, val in info:
        ax.text(_RAP_ML, y, f"{label}:", fontsize=9, fontweight="bold",
                color="#54606b", ha="left", va="top")
        wrapped = _rap_wrap(val, 86)
        for j, line in enumerate(wrapped):
            ax.text(_RAP_ML + 0.16, y - j * 0.016, line, fontsize=9,
                    color="#23272b", ha="left", va="top")
        y -= max(0.020, 0.016 * len(wrapped) + 0.006)

    # Kerncijfer-kaarten (2)
    y -= 0.014
    cards = [
        ("Hectopunten (selectie)", f"{meta.get('n_points', 0):,}".replace(",", "."), _RAP_NAVY),
        ("Gemarkeerde punten", f"{meta.get('n_flagged', 0):,}".replace(",", "."), "#dc2626"),
    ]
    gap = 0.02
    cw = (_RAP_MR - _RAP_ML - gap * (len(cards) - 1)) / len(cards)
    x = _RAP_ML
    for label, val, color in cards:
        ax.add_patch(mpatches.Rectangle((x, y - 0.095), cw, 0.095,
                                        facecolor="#f4f6f8", edgecolor="#d9dee3"))
        ax.add_patch(mpatches.Rectangle((x, y - 0.095), 0.006, 0.095,
                                        facecolor=color, edgecolor="none"))
        ax.text(x + cw / 2, y - 0.038, val, fontsize=23, fontweight="bold",
                color=color, ha="center", va="center")
        ax.text(x + cw / 2, y - 0.078, label, fontsize=9.5, color="#54606b",
                ha="center", va="center")
        x += cw + gap
    y -= 0.130

    # Toelichting / gebruik
    uitleg = (
        "Dit rapport bevat uitsluitend de handmatig gemarkeerde hectopunten die "
        "onderhoud behoeven. De volgende pagina geeft een overzicht in één "
        "oogopslag: bovenaan een kaart van Nederland met álle gemarkeerde punten "
        "(genummerd) en daaronder de volledige opsomming (locatie · opmerking · "
        "paginanummer). Daarna krijgt elk punt een eigen detailpagina met de "
        "gedateerde markeringsopmerking(en) plus schrijfregels voor handmatige "
        "notities, twee locatiekaarten (regio + sterk ingezoomd op het landschap), "
        "álle beschikbare informatie, klikbare links naar StreetSmart en Google "
        "Maps, en 1–2 foto’s uit de fotomap van dat punt (`Output/hectopunt_fotos/`). "
        "Duplicaten van hetzelfde punt worden samengevoegd tot één pagina met de "
        "registratiedatums. Zo communiceert de regio-inspecteur direct met de "
        "aannemer waar en waarom de wegmarkering onderhoud nodig heeft."
    )
    for line in _rap_wrap(uitleg, 104):
        ax.text(_RAP_ML, y, line, fontsize=9.5, color="#54606b", ha="left", va="top")
        y -= 0.017

    pdf.savefig(fig)
    plt.close(fig)


def build_onderhoudsrapport_pdf(work: pd.DataFrame,
                                meta: Dict[str, Any]) -> bytes:
    """Bouw het onderhoudsrapport (alleen gemarkeerde punten) als PDF-bytes."""
    from matplotlib.backends.backend_pdf import PdfPages

    work = work.copy()
    if "_flag" in work.columns:
        flagged = work[work["_flag"] == True]            # noqa: E712 (bool-kolom)
    else:
        flagged = work.iloc[0:0]
    # Netwerkvolgorde zodat de inspecteur de route logisch kan aflopen.
    sort_cols = [c for c in ("wegnr_hmp", "hectomtrng", "Zijde", "hecto_lttr")
                 if c in flagged.columns]
    if sort_cols and not flagged.empty:
        flagged = flagged.sort_values(sort_cols, kind="mergesort")

    # Duplicaten van hetzelfde hectopunt (zelfde annotatie-key) samenvoegen tot
    # één detailpagina; de gedateerde opmerkingen-historie komt uit de audit-log.
    annotations = load_annotations()
    remarks_by_key = _rap_remarks_by_key(annotations)
    if not flagged.empty:
        flagged = flagged.assign(
            _anno_key=[_annotation_row_key(r) for _, r in flagged.iterrows()]
        ).drop_duplicates("_anno_key", keep="first")

    meta = dict(meta)
    meta["n_flagged"] = int(len(flagged))

    _RAP_RUNTIME["online"] = None          # online-tegel guard per rapport-run
    state: Dict[str, Any] = {"page": 0}
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        _rap_cover(pdf, state, meta)
        _rap_overview(pdf, state, meta, flagged)
        _rap_flagged_section(pdf, state, meta, flagged, remarks_by_key)
    return buf.getvalue()


def _render_onderhoudsrapport_button(df: pd.DataFrame, work: pd.DataFrame) -> None:
    """Knop onderaan de kaart-tab: genereert in ÉÉN klik het PDF-onderhoudsrapport
    én alle QGIS-kaartlagen (+ Excel/CSV/PNG's) naar `Output/`."""
    st.divider()
    st.markdown("### Genereer onderhoudsrapport + QGIS-kaartlagen")
    st.caption(
        "Eén knop schrijft naar `Output/`: het **PDF-onderhoudsrapport** "
        "(overzichtskaart van Nederland + opsomming + één detailpagina per "
        "gemarkeerd punt met twee locatiekaarten, gedateerde opmerkingen + "
        "schrijfregels, álle info, links en foto’s) **én alle "
        f"{len(_MAP_HEATMAP_OPTIONS)} QGIS-heatmapkaartlagen** "
        "(`qgis_heatmap_*.gpkg`, gekleurd zoals de interactieve kaart), plus "
        "Excel/CSV/PNG-grafieken en — als de Clustering-tab al gedraaid heeft — "
        "de cluster-GPKG. De PDF kun je hieronder ook direct downloaden."
    )

    n_flag = int(work["_flag"].sum()) if "_flag" in work.columns else 0
    if st.button("Genereer rapport (PDF) + QGIS-kaartlagen",
                 key="rapport_generate_btn", type="primary"):
        with st.spinner("Rapport én kaartlagen genereren naar Output/…"):
            result = generate_all_outputs(df)
        # De PDF die generate_all_outputs zojuist naar schijf schreef inlezen,
        # zodat de download-knop exact hetzelfde bestand aanbiedt.
        pdf_path = Settings.OUTPUT_DIR / "onderhoudsrapport_gemarkeerd.pdf"
        try:
            if pdf_path.exists():
                st.session_state["_rapport_pdf"] = pdf_path.read_bytes()
                st.session_state["_rapport_pdf_name"] = (
                    f"onderhoudsrapport_gemarkeerd_{pd.Timestamp.now():%Y%m%d_%H%M}.pdf"
                )
        except Exception as exc:
            st.error(f"PDF inlezen voor download mislukte: {exc}")
        # Samenvatting tonen zodat zichtbaar is dat óók de kaartlagen geschreven zijn.
        if result["written"]:
            lines = "\n".join(f"  • {ln}" for ln in result["written"])
            st.success(
                f"Opgeslagen in `{Settings.OUTPUT_DIR}`:\n\n```\n{lines}\n```"
            )
        for note in result["skipped"]:
            st.info(note)
        if result["errors"]:
            st.error("Fouten:\n" + "\n".join(f"• {e}" for e in result["errors"]))

    if n_flag == 0:
        st.info("Nog geen gemarkeerde punten in de selectie — markeer punten via de "
                "vlag-knop op de kaart; het rapport toont dan die punten. "
                "(De QGIS-kaartlagen worden óók zonder markeringen geschreven.)")

    if st.session_state.get("_rapport_pdf"):
        st.download_button(
            "Download rapport (PDF)",
            data=st.session_state["_rapport_pdf"],
            file_name=st.session_state.get("_rapport_pdf_name",
                                           "onderhoudsrapport.pdf"),
            mime="application/pdf",
            key="rapport_download_btn",
        )


def _halve_asset_fig(fig: Figure, w: float, h: float,
                     font_scale: float = 0.45) -> None:
    """Verklein een asset-grafiek tot HALVE schermmaat (`w`×`h` inch) en schaal
    álle tekst mee. De doek wordt fysiek kleiner; de lettertypes krijgen factor
    ``font_scale`` (default 0.45, íets onder de proportionele 0.5) zodat er
    extra witruimte tussen tekst en tekens overblijft en niets overlapt.

    Posities staan in figuur-/axes-fracties en schalen dus vanzelf mee; alleen
    de absolute punt-groottes moeten handmatig omlaag."""
    texts = list(fig.texts)
    for ax in fig.axes:
        texts.extend(ax.texts)
        texts.append(ax.title)                 # titel zit los van ax.texts
        texts.extend(ax.get_xticklabels())
        texts.extend(ax.get_yticklabels())
    for txt in texts:
        txt.set_fontsize(txt.get_fontsize() * font_scale)
    fig.set_size_inches(w, h)


def _render_asset_detail_rail(row: pd.DataFrame, row_data: pd.Series,
                              annotations: Dict[str, Dict[str, str]],
                              work: Optional[pd.DataFrame] = None) -> None:
    """Compacte asset-detailrail naast de kaart + bocht/verkeer-grafieken.

    Eén overzichtelijke kolom voor de verkeerscentrale: kop (weg · hmp ·
    zijde) + externe links, daaronder de KPI-kaarten + inspectiescores
    (gestapeld) en de volledige attributenlijst. Vervangt de losse blokken
    die voorheen ver ónder de kaart stonden (gebruikersverzoek: info náást
    de grafieken)."""
    # Kop + externe links samen op ÉÉN compacte regel (i.p.v. 3 grote knoppen
    # eronder) → scheelt verticale ruimte en is van afstand goed leesbaar.
    weg = row_data.get("wegnr_hmp", "")
    hmp = _format_hmp(row_data.get("hectomtrng", ""))
    zij = row_data.get("Zijde", "")
    link_defs = [(c, lbl) for c, lbl in Settings.TREE_COLUMNS
                 if c in _LINK_COLUMNS and c in row.columns]
    link_html = []
    for c, _lbl in link_defs:
        url = str(row_data.get(c, ""))
        if pd.notna(row_data.get(c)) and url.startswith("http"):
            name = _RAIL_LINK_LABELS.get(c, _lbl)
            link_html.append(
                f'<a href="{url}" target="_blank" style="color:'
                f'{Settings.COLOR_BLUE_PRIMARY};font-weight:700;'
                f'text-decoration:none;">{name}</a>'
            )
    links_str = (" &nbsp;·&nbsp; ".join(link_html)) if link_html else ""
    # Korte vrije-tekst uit de `info`-kolom, direct onder de kop en bóven de
    # links (gebruikersverzoek). Leeg/NaN → niets tonen.
    info_val = row_data.get("info", "")
    info_str = ("" if info_val is None
                or (isinstance(info_val, float) and pd.isna(info_val))
                else str(info_val).strip())
    st.markdown(
        f"<div style='font-size:20px;font-weight:800;margin:0 0 2px;'>"
        f"{weg} · hmp {hmp} · zijde {zij}</div>"
        + (f"<div style='font-size:15px;color:#16384f;margin:0 0 4px;'>"
           f"{info_str}</div>" if info_str else "")
        + (f"<div style='font-size:16px;margin:0 0 4px;'>{links_str}</div>"
           if links_str else ""),
        unsafe_allow_html=True,
    )

    _render_asset_kpi_row(row_data, annotations, work, stacked=True)
    _render_asset_attributes(row, row_data, n_cols=2)


def render_map_tab(df: pd.DataFrame) -> None:
    # Bescherm de clustering-/diagnose-instellingen tegen de selectie-rerun
    # verderop in deze functie (zie _PERSIST_WIDGET_KEYS).
    _persist_widget_state(_PERSIST_WIDGET_KEYS)

    st.markdown(_MAP_TAB_CSS, unsafe_allow_html=True)

    pdk = _import_pydeck()
    if pdk is None:
        return

    annotations = load_annotations()
    work = _build_map_workframe(df, annotations)
    if work is None:
        return

    heatmap_choice = st.session_state.get(
        "map_heatmap_col", _MAP_HEATMAP_DEFAULT
    )
    pct = _compute_map_heatmap_pct(
        work, heatmap_choice, _default_heatmap_pct(work), annotations,
    )
    _apply_heatmap_colors(work, pct)
    work["_tooltip"] = _build_tooltip(work, pct)

    # Resolve the active row up-front so the layout can show "Algemene info"
    # on top and place Bocht/Verkeer next to the map in the same render pass.
    pre_row_id = _resolve_initial_row_id(work)
    # Bij opstart (nog geen klik/selectie) de kaart iets verder uitgezoomd
    # openen; pas ná een selectie inzoomen op het gekozen punt.
    _startup = st.session_state.get("_asset_tbl_selected_row_id") is None
    # ~3× dichter inzoomen dan voorheen (gebruikersverzoek). Kaart-zoom is
    # logaritmisch: elke +1 = 2× dichter, dus 3× ≈ +log2(3) ≈ +1.585.
    focus_zoom = 12.6 if _startup else 15.6
    pre_row = None
    pre_row_data = None
    if pre_row_id is not None:
        sel = work.loc[work["_row_id"] == pre_row_id]
        if not sel.empty:
            pre_row = sel
            pre_row_data = sel.iloc[0]

    # 1. Kaart + Bocht/Verkeer + asset-detailrail ernaast (EERST — gebruiker:
    #    alle asset-info naast de grafieken i.p.v. ver onder de kaart, in één
    #    overzichtelijke detailrail voor de verkeerscentrale).
    base_url = dict(_BASEMAP_SOURCES).get(
        st.session_state.get("map_basemap", _BASEMAP_DEFAULT), _PDOK_URL
    )
    deck_key = f"hectopunten_map_{len(work)}_{pre_row_id}"
    if pre_row_data is not None:
        map_col, graph_col, info_col = st.columns([1.55, 0.95, 1.5], gap="small")
        with map_col:
            event = st.pydeck_chart(
                _build_hectopunt_deck(pdk, work, focus_row_id=pre_row_id,
                                  focus_zoom=focus_zoom, base_url=base_url),
                on_select="rerun",
                selection_mode="single-object",
                key=deck_key,
                use_container_width=True,
                height=784,
            )
        with graph_col:
            # Vaste pixel-hoogte (use_container_width=False → figh*dpi px), niet
            # responsief op kolombreedte. Gebruikersverzoek: bocht + verkeer op
            # HALVE maat (halve breedte én halve hoogte). De figsize wordt
            # gehalveerd; de lettertypes worden mét de doek meegeschaald maar
            # íets kleiner dan proportioneel (factor 0.45 i.p.v. 0.5), zodat er
            # extra ruimte tussen de tekst en tekens overblijft en niets overlapt.
            _fig_curve = plot_curve_geometry(
                _safe_num(pre_row_data.get("_som_hoek")),
                _safe_num(pre_row_data.get("_boogstraal")),
            )
            _halve_asset_fig(_fig_curve, 1.5, 1.15, font_scale=0.65)
            st.pyplot(
                _fig_curve,
                clear_figure=True,
                use_container_width=False,
            )
            _fig_traffic = plot_traffic_composition(pre_row_data, df=work)
            _halve_asset_fig(_fig_traffic, 1.5, 2.95, font_scale=0.75)
            st.pyplot(
                _fig_traffic,
                clear_figure=True,
                use_container_width=False,
            )
        with info_col:
            _render_asset_detail_rail(pre_row, pre_row_data, annotations, work)
    else:
        event = st.pydeck_chart(
            _build_hectopunt_deck(pdk, work, focus_row_id=pre_row_id,
                                  focus_zoom=focus_zoom, base_url=base_url),
            on_select="rerun",
            selection_mode="single-object",
            key=deck_key,
            use_container_width=True,
            height=784,
        )

    # Kleur-legenda onder de kaart — sluit aan op de zojuist gekleurde heatmap
    # (`heatmap_choice` stuurt óók `_compute_map_heatmap_pct` hierboven aan).
    _render_heatmap_legend(heatmap_choice)

    # 2. Selection capture — als gebruiker een nieuwe hectopunt klikt,
    # persist + rerun zodat de map-focus in de volgende render meeklimt.
    row_id = _resolve_selected_row_id(work, _selected_row_id_from_event(event))
    if row_id is not None and row_id != pre_row_id:
        st.session_state["_asset_tbl_selected_row_id"] = int(row_id)
        st.rerun()
    row = None
    row_data = None
    if row_id is not None:
        sel_row = work.loc[work["_row_id"] == row_id]
        if not sel_row.empty:
            row = sel_row
            row_data = sel_row.iloc[0]
        else:
            st.info("Selectie niet gevonden.")

    # 3. Grafiek levensduur+deklagen (volledige breedte) — DIRECT onder de
    #    kaart (gebruikersverzoek: kaart en levensduur-grafiek aansluitend).
    #    Alle overige asset-info (header, markeren, scores, attributen) staat
    #    hier ónder.
    if row_data is not None and row is not None:
        with st.container(border=True):
            st.pyplot(
                plot_levensduur_deklagen_stacked(row_data, df=work),
                clear_figure=True,
                use_container_width=True,
            )

    # 4. Markeren (vlag-/markeer-widget). Asset-header, scores (KPI +
    #    inspectiescores) en alle attributen staan nu in de detailrail náást
    #    de kaart/grafieken (sectie 1) i.p.v. hier onderaan.
    if pre_row is not None and pre_row_data is not None:
        _render_flag_widget(pre_row_data)

    # 4b. Onderhoudsrapport (PDF) + QGIS — direct bij het markeren
    #     (gebruikersverzoek: knop hoort vlak bij waar je punten markeert).
    _render_onderhoudsrapport_button(df, work)

    # 6. Voorspellend model
    _render_inline_clustering_section(df)

    # 7. Tabel — HELEMAAL onderaan (gebruikersverzoek)
    _render_asset_paginated_table(work)
    st.caption(f"Toont **{len(work):,}** gefilterde hectopunten.")


def _diagnose_state() -> Tuple[Optional[pd.DataFrame], Optional[np.ndarray],
                               Optional[List[str]], Optional[float]]:
    """Pak (clustered_df, Xw, used_feats, used_penalty) uit session_state."""
    return (
        st.session_state.get("_clustered_df"),
        st.session_state.get("_Xw"),
        st.session_state.get("_used_feats"),
        st.session_state.get("_used_penalty"),
    )


def _render_diagnose_header(cfg: Dict[str, Any],
                            used_feats: List[str],
                            used_penalty: Optional[float]) -> None:
    grp_parts = ["snelwegnummer"]
    if cfg.get("group_by_zijde", False):
        grp_parts.append("Zijde")
    if cfg.get("group_by_lttr", False):
        grp_parts.append("hecto_lttr")
    pen_str = (f"  ·  **β = {used_penalty:.2f}**"
               if used_penalty is not None else "")
    st.info(
        f"**Huidige groepering voor PELT:** `{' + '.join(grp_parts)}`  ·  "
        f"**Features:** `{', '.join(used_feats)}` ({len(used_feats)} actief)  ·  "
        f"**Model:** `{cfg.get('model', '?')}`{pen_str}"
    )


def _select_diagnose_point(clustered_df: pd.DataFrame) -> Optional[int]:
    """Cascading filters (weg → zijde → letter → hm); None = onmogelijke combo."""
    c1, c2, c3, c4 = st.columns(4)
    weg_col = ("snelwegnummer" if "snelwegnummer" in clustered_df.columns
               else "wegnr_hmp")
    weg_opts = sorted(clustered_df[weg_col].dropna().unique().tolist())
    # Standaard op de A12 (gebruikersverzoek). `snelwegnummer` noteert als "12",
    # `wegnr_hmp` als "A12" — beide vormen afvangen. Alleen de begin-index;
    # daarna wint de keuze van de gebruiker via session_state (key="diag_weg").
    _weg_opts_str = [str(o) for o in weg_opts]
    _diag_default_idx = 0
    for _cand in ("A12", "12"):
        if _cand in _weg_opts_str:
            _diag_default_idx = _weg_opts_str.index(_cand)
            break
    weg = c1.selectbox(weg_col, weg_opts, index=_diag_default_idx, key="diag_weg")

    sub_weg = clustered_df[clustered_df[weg_col] == weg]
    zij_opts = sorted(sub_weg["Zijde"].dropna().unique().tolist())
    if not zij_opts:
        st.warning("Geen zijdes voor deze weg.")
        return None
    zij = c2.selectbox("Zijde", zij_opts, key="diag_zijde")

    sub_wz = sub_weg[sub_weg["Zijde"] == zij]
    lttr_display = sorted(
        sub_wz["hecto_lttr"].replace("", "RIJBAAN").dropna().unique().tolist()
    )
    if not lttr_display:
        st.warning("Geen hectoletters in deze combinatie.")
        return None
    lttr_choice = c3.selectbox("Hectoletter", lttr_display, key="diag_lttr")
    lttr_raw = "" if lttr_choice == "RIJBAAN" else lttr_choice

    sub_wzl = sub_wz[sub_wz["hecto_lttr"] == lttr_raw]
    hm_opts = sorted(sub_wzl["hectomtrng"].dropna().astype(int).unique().tolist())
    if not hm_opts:
        st.warning("Geen hectopunten in deze combinatie.")
        return None
    hm_choice = c4.selectbox("Hectomtrng", hm_opts, key="diag_hm")
    return int(sub_wzl.index[sub_wzl["hectomtrng"] == hm_choice][0])


def _diag_feature_column(diag: Dict[str, Any], key: str,
                         feats: List[str]) -> List[Any]:
    return [diag[key][f] for f in feats]


def _render_diag_step1(diag: Dict[str, Any], used_feats: List[str]) -> None:
    st.markdown("#### Stap 1 — Ruwe waarden van P")
    st.caption("Ontbrekende cellen worden semantisch ingevuld (geen bocht = 0° / "
               "ruimste boog; overige = mediaan), niet blind met de mediaan.")
    st.dataframe(pd.DataFrame({
        "feature":                  used_feats,
        "y_raw (ruw)":              _diag_feature_column(diag, "raw_P", used_feats),
        "y_filled (na fill-policy)": _diag_feature_column(diag, "raw_P_filled", used_feats),
    }), hide_index=True, use_container_width=True)


def _render_diag_step2(diag: Dict[str, Any], used_feats: List[str]) -> None:
    st.markdown(r"#### Stap 2 — Normalisatie 0-1:  $n = (y - \min) / (\max - \min)$")
    st.caption("min/max per feature over de hele dataset. Zo valt de absolute "
               "schaal (b.v. miljoenen voertuigen) weg en ligt elke feature in [0, 1].")
    st.dataframe(pd.DataFrame({
        "feature":     used_feats,
        "y_filled":    _diag_feature_column(diag, "raw_P_filled", used_feats),
        "min":         _diag_feature_column(diag, "lo", used_feats),
        "max":         _diag_feature_column(diag, "hi", used_feats),
        "n (0-1)":     _diag_feature_column(diag, "norm_P", used_feats),
    }), hide_index=True, use_container_width=True)


def _render_diag_step3(diag: Dict[str, Any], used_feats: List[str]) -> None:
    st.markdown(r"#### Stap 3 — Wegen + oriëntatie")
    st.caption(
        "Voor de **afstand** (clustering) telt elke feature mee als n·w. Voor de "
        "**kleur** (ernst) wordt n eerst georiënteerd zodat hoog = goed (groen), "
        "daarna gewogen gemiddeld → de 0-1 score die de heatmap aanstuurt."
    )
    st.dataframe(pd.DataFrame({
        "feature":         used_feats,
        "n (0-1)":         _diag_feature_column(diag, "norm_P",  used_feats),
        "w (slider)":      _diag_feature_column(diag, "weights", used_feats),
        "afstand n·w":     _diag_feature_column(diag, "y_P",     used_feats),
        "goedheid (1=goed)": _diag_feature_column(diag, "good_P", used_feats),
    }), hide_index=True, use_container_width=True)
    st.markdown(
        f"De feature-vector van P heeft **{len(used_feats)} dimensies** "
        "— PELT werkt direct in deze ruimte, géén plat-slaan naar 2D."
    )


def _render_diag_step4(diag: Dict[str, Any],
                       clustered_df: pd.DataFrame) -> None:
    st.markdown("#### Stap 4 — De buren in de geordende sequence")
    st.caption(
        "PELT loopt over deze geordende reeks. ‖y_i − y_{i+1}‖ is de "
        "euclidische afstand in de gewogen feature-ruimte — het signaal "
        "waarop changepoints worden getriggerd."
    )
    win_cols = [c for c in
                ["wegnr_hmp", "Zijde", "hecto_lttr", "hectomtrng", "cluster"]
                if c in clustered_df.columns]
    win_df = clustered_df.loc[diag["win_idx"], win_cols].reset_index(drop=True)
    win_df.insert(0, "P?",
                  ["← P" if (i + diag["win_offset"]) == diag["pos_in_seg"]
                   else "" for i in range(len(win_df))])
    win_df["‖y_i − y_{i+1}‖"] = list(np.round(diag["dist_win"], 3)) + [np.nan]
    st.dataframe(win_df, hide_index=True, use_container_width=True)


def _render_diag_step5(diag: Dict[str, Any],
                       clustered_df: pd.DataFrame,
                       point_idx: int) -> None:
    p_cluster = int(clustered_df.iloc[point_idx]["cluster"])
    n_same = int((clustered_df["cluster"] == p_cluster).sum())
    st.markdown(
        f"#### Stap 5 — Resultaat: P zit in **cluster {p_cluster}** "
        f"({n_same} hectopunten)."
    )
    sub_seg = clustered_df.loc[diag["seg_idx"]].reset_index(drop=True)
    sub_seg["_pos"] = range(len(sub_seg))
    grenzen = sub_seg["cluster"].diff().fillna(0).abs() > 0
    if grenzen.any():
        grens_pos = sub_seg.loc[grenzen, "_pos"].tolist()
        st.write(f"Cluster-grenzen in dit segment op posities: "
                 f"{grens_pos} (P staat op positie {diag['pos_in_seg']}).")
    else:
        st.write("Eén cluster over het hele segment — geen changepoints.")


def _render_diag_step6(diag: Dict[str, Any],
                       clustered_df: pd.DataFrame,
                       used_feats: List[str],
                       used_penalty: Optional[float]) -> None:
    st.markdown(r"#### Stap 6 — PELT-score per hectopunt:  $\|y_i - y_{i-1}\|$")
    st.caption(
        "Per hectopunt zie je de **gewogen feature-afstand** tot zijn "
        "voorganger. Dit is precies het signaal dat PELT gebruikt om "
        "changepoints te kiezen: hoge pieken zijn kandidaat-grenzen, "
        "β bepaalt de minimumprijs voor een echte breuk. "
        "Rode stippellijnen = de daadwerkelijk gekozen clustergrenzen, "
        "zwarte stippellijn = P."
    )
    if len(used_feats) == 1:
        st.caption(
            f"Met slechts 1 feature (`{used_feats[0]}`) is de jump-afstand "
            "gelijk aan |Δz · w| van die ene feature — PELT detecteert dan "
            "puur sprongen in deze grootheid langs de weg."
        )
    st.pyplot(
        plot_pelt_score_diagnose(diag, clustered_df, penalty=used_penalty),
        clear_figure=True,
    )


def _render_diag_step7(diag: Dict[str, Any],
                       clustered_df: pd.DataFrame,
                       used_feats: List[str]) -> None:
    st.markdown("#### Stap 7 — Cluster-toewijzing & feature-ruimte")
    if len(used_feats) >= 2:
        viz_help = (
            "**Links:** ingezoomde kaart van het wegsegment — de hectopunten "
            "op hun **werkelijke locatie** op het snelwegennet, gekleurd op "
            "cluster-ernst (rood = slecht, groen = goed). Zwart ringetje = P, "
            "zwarte ruitjes = clustergrenzen. Zo zie je ruimtelijk welke "
            "wegsecties goed of slecht zijn.  \n"
            "**Rechts:** dezelfde punten in **2D-PCA** van de gewogen "
            "feature-ruimte — een 2D-schaduw van de "
            f"{len(used_feats)}-dimensionale ruimte waarin PELT rekent. "
            "Punten in dezelfde cluster horen hier dicht bij elkaar te liggen."
        )
    else:
        viz_help = (
            "**Links:** ingezoomde kaart van het wegsegment — de hectopunten "
            "op hun werkelijke locatie, gekleurd op cluster-ernst.  \n"
            f"**Rechts:** met 1 feature (`{used_feats[0]}`) is de "
            "feature-ruimte 1D — de y-as is constant 0, x = "
            "gestandaardiseerde + gewogen waarde."
        )
    st.caption(viz_help)
    st.pyplot(plot_segment_diagnose(diag, clustered_df), clear_figure=True)


def _render_diag_step8(diag: Dict[str, Any],
                       clustered_df: pd.DataFrame) -> None:
    dist_seg = diag.get("dist_seg", np.array([]))
    if len(dist_seg) == 0:
        return
    sub_seg = clustered_df.loc[diag["seg_idx"]].reset_index(drop=True)
    cl_arr = sub_seg["cluster"].to_numpy()
    bnd = np.where(np.diff(cl_arr) != 0)[0]
    if not len(bnd):
        return

    mu_d = float(np.mean(dist_seg))
    md_d = float(np.median(dist_seg))
    rows = []
    for b in bnd:
        d = float(dist_seg[b]) if b < len(dist_seg) else float("nan")
        rows.append({
            "tussen hm":    f"{int(sub_seg['hectomtrng'].iloc[b])} → "
                            f"{int(sub_seg['hectomtrng'].iloc[b + 1])}",
            "‖Δy‖":         round(d, 3),
            "× gemiddelde": round(d / mu_d, 2) if mu_d > 0 else None,
            "cluster":      f"{int(cl_arr[b])} → {int(cl_arr[b + 1])}",
        })
    st.markdown("#### Stap 8 — Waarom hier een breuk? (top-jumps van het segment)")
    st.caption(
        f"Gem. jump in dit segment: **{mu_d:.3f}**, mediaan: "
        f"**{md_d:.3f}**. PELT kiest een breuk waar de jump zó groot is "
        "dat β·(extra cluster) goedkoper is dan de extra binnen-cluster-kosten."
    )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


@st.fragment
def render_diagnose_section(df: pd.DataFrame, cfg: Dict[str, Any]) -> None:
    """Diagnose van één hectopunt — leeft als losse **fragment** direct onder
    de clusterkaart in de Kaart-tab (gebruikersverzoek: alles van het
    clusteralgoritme in één window).

    `@st.fragment` zorgt dat het *zoeken* naar een hectopunt — de cascading
    selectboxes (weg → zijde → letter → hm) + de window-slider — alléén dít
    blok opnieuw uitvoert. De zware pydeck-kaart en de clusterkaart erboven
    blijven staan en hoeven niet te herladen, dus de app loopt niet meer vast
    bij elke klik. De clustering zelf draait nog steeds alleen op de knop
    **Genereer clustering**; deze diagnose leest puur de gecachte uitkomst.
    """
    st.divider()
    st.markdown("### Diagnose één hectopunt door de PELT-pipeline")
    st.caption(
        "Volg één gekozen hectopunt door alle stappen: ruw → "
        "gestandaardiseerd → gewogen → PELT-input → cluster. Zo is "
        "iedere tussenstap navolgbaar en wiskundig verifieerbaar. Het kiezen "
        "van een punt hertekent alleen dit blok — de kaart hierboven blijft staan."
    )

    clustered_df, Xw, used_feats, used_penalty = _diagnose_state()

    if (clustered_df is None or Xw is None or used_feats is None
            or len(clustered_df) != len(df)):
        st.info(
            "Nog geen clustering gegenereerd voor deze instellingen — druk "
            "hierboven op **Genereer clustering**. Wijzig je daarna filters of "
            "instellingen? Genereer opnieuw."
        )
        return
    if not used_feats:
        st.warning("Geen features actief — zet minstens één gewicht > 0.")
        return

    _render_diagnose_header(cfg, used_feats, used_penalty)

    point_idx = _select_diagnose_point(clustered_df)
    if point_idx is None:
        return

    window = st.slider("Aantal buren tonen (± in segment)", 2, 20, 5,
                       key="diag_window")
    diag = diagnose_point(
        clustered_df, Xw, used_feats, cfg["weights"], point_idx, window=window,
    )

    st.markdown(
        f"**Segment-key:** `{diag['segment_key']}` — "
        f"P is hectopunt **{diag['pos_in_seg'] + 1} / {diag['seg_len']}** "
        f"in dit segment."
    )

    _render_diag_step1(diag, used_feats)
    _render_diag_step2(diag, used_feats)
    _render_diag_step3(diag, used_feats)
    _render_diag_step4(diag, clustered_df)
    _render_diag_step5(diag, clustered_df, point_idx)
    _render_diag_step6(diag, clustered_df, used_feats, used_penalty)
    _render_diag_step7(diag, clustered_df, used_feats)
    _render_diag_step8(diag, clustered_df)


# ============================================================
# MAIN APP
# ============================================================
def _select_dataset_source() -> Tuple[Optional[pd.DataFrame], str, str]:
    """Toon dataset-selectie + upload — return (df, cache_key, label)."""
    raw: Optional[pd.DataFrame] = None
    cache_key = ""
    label     = ""

    with st.sidebar.expander("Dataset — kies bestaand of upload", expanded=False):
        available = discover_default_datasets()
        if available:
            names = [p.name for p in available]
            picked = st.selectbox(
                "Bestaande dataset uit Output/",
                names, index=0, key="ds_pick_existing",
            )
            picked_path = Settings.OUTPUT_DIR / picked
        else:
            picked_path = None
            st.info(f"Geen pickles gevonden in `{Settings.OUTPUT_DIR}`.")

        uploaded = st.file_uploader(
            "Of upload een eigen dataset (CSV / Parquet / Excel / Pickle)",
            type=["csv", "parquet", "xlsx", "xls", "pkl", "pickle"],
            key="ds_upload",
        )
        if uploaded is not None:
            file_bytes = uploaded.getvalue()
            raw = load_uploaded_dataframe(file_bytes, uploaded.name)
            cache_key = f"upload::{uploaded.name}::{len(file_bytes)}"
            label = f"upload `{uploaded.name}`"
        elif picked_path is not None:
            try:
                mtime = picked_path.stat().st_mtime
                raw = load_default_dataset(str(picked_path), mtime)
                cache_key = f"default::{picked_path.name}::{mtime}"
                label = f"`{picked_path.name}`"
            except Exception as exc:
                st.error(f"Kon `{picked_path.name}` niet laden: {exc}")
                raw = None

    return raw, cache_key, label


def main() -> None:
    # Globale compacte styling — minder witruimte boven/onder blokken en koppen
    # (gebruikersverzoek: alles iets compacter, minder witregels).
    st.markdown(_GLOBAL_COMPACT_CSS, unsafe_allow_html=True)

    # Rijkswaterstaat-logo linksboven in de sidebar, bóven de filters
    # (gebruikersverzoek). Titel staat compact (≈ half formaat van st.title) in
    # de hoofdkolom.
    if Settings.LOGO_PATH.exists():
        # Bron is 1042×505 px (scherp); vul de sidebarbreedte i.p.v. width=150
        # zodat het logo groot en leesbaar is op de 65"-TV (gebruikersverzoek).
        st.sidebar.image(str(Settings.LOGO_PATH), use_container_width=True)
    st.markdown(
        "<div style='font-size:1.5rem;font-weight:800;line-height:1.2;"
        "color:#154273;margin:1.6rem 0 0.4rem;'>"
        "Preventief Toekomstbestendig Onderhoud aan de Wegmarkeringen</div>",
        unsafe_allow_html=True,
    )

    if not HAS_RUPTURES:
        st.warning(
            "Package `ruptures` is niet geïnstalleerd — een fallback "
            "changepoint detector wordt gebruikt. Voor productie: "
            "`pip install ruptures`."
        )

    # ── 1. Data laden ──────────────────────────────────────
    raw, cache_key, label = _select_dataset_source()
    if raw is None:
        st.sidebar.info(
            f"Geen dataset geladen. Verwachte locatie: `{Settings.OUTPUT_DIR}/"
            f"{Settings.DEFAULT_DATASETS[0]}`.  \n"
            "Of upload zelf een bestand in de sidebar."
        )
        st.stop()

    # ── 2. Data preparation (gecached) ─────────────────────
    with st.spinner("Features berekenen (eenmalig per dataset)…"):
        engineered = prepare_dataset(raw, cache_key)

    # Reserveer de "Selectie"-KPI's DIRECT onder de dataset-keuze, bóven
    # Kaartlaag/Filters (gebruikersverzoek). De placeholder wordt hieronder
    # gevuld zodra de gefilterde telling bekend is (na de filter-widgets).
    selectie_box = st.sidebar.container()

    # ── 3. Sidebar — filters (PELT-controls staan inline in de Kaart-tab) ──
    filter_spec = sidebar_filters(engineered)

    # ── 4. Filters toepassen ───────────────────────────────
    filtered_df = apply_filters(engineered, filter_spec)

    # Context voor het PDF-onderhoudsrapport (gelezen in de kaart-tab).
    st.session_state["_dataset_label"] = label
    st.session_state["_filter_summary"] = _summarize_filters(filter_spec)

    # Vul de gereserveerde Selectie-placeholder (rendert visueel boven Kaartlaag).
    with selectie_box:
        st.markdown("### Selectie")
        sk1, sk2 = st.columns(2)
        sk1.metric("Hectopunten", f"{len(filtered_df):,}",
                   delta=(f"−{len(engineered) - len(filtered_df):,}"
                          if len(filtered_df) != len(engineered) else None),
                   delta_color="off")
        sk2.metric("Bron-dataset", f"{len(engineered):,}")

    if filtered_df.empty:
        st.error("Filters geven 0 rijen terug — versoepel de filters in de sidebar.")
        st.stop()

    # ── 5. Alleen de Kaart ─────────────────────────────────
    # Gebruikersverzoek: tabs Grafieken/Clustering/Validatie/Theorie PELT
    # verwijderd; er is nog maar één window (de kaart), dus ook geen
    # tab-keuze meer nodig. Clustering draait nog steeds inline in deze view.
    render_map_tab(filtered_df)


# ============================================================
# ENTRYPOINT
# ============================================================
try:
    from streamlit.runtime import exists as _st_runtime_exists
except ImportError:
    _st_runtime_exists = lambda: True  # noqa: E731


# ============================================================
# TABEL — annotatie-merge + downloads (Excel / pickle)
# ------------------------------------------------------------
# Bewust onderaan (gebruikersverzoek). Deze defs worden via
# main() → render_map_tab aangeroepen ná module-load, dus ze
# hoeven niet boven ENTRYPOINT te staan.
# ============================================================


def _merge_annotations_into_df(df: pd.DataFrame) -> pd.DataFrame:
    """Smelt de door-mens-gemaakte annotaties (Vlag/Levensduur/Onderhoud/…)
    in een KOPIE van ``df`` zodat downstream-output altijd weet welke
    wijzigingen de eindgebruiker heeft gedaan.

    Extra kolom ``annotatie_bron`` documenteert ``"mens"`` voor rijen waar
    één of meer annotaties zijn ingevuld; lege rijen krijgen ``""``."""
    if df.empty:
        return df
    annotations = load_annotations()
    keys = _annotation_row_keys(df)
    out = df.copy()
    out["Vlag"] = [
        FLAG_VALUE_ON if (annotations.get(k) or {}).get("Vlag") == FLAG_VALUE_ON
        else "" for k in keys
    ]
    for field in ("Vlag_reden", "Levensduur",
                  "Onderhoudsintervallen", "Onderhoudsmoment"):
        out[field] = [(annotations.get(k) or {}).get(field, "") for k in keys]
    has_any = pd.Series(
        [any((annotations.get(k) or {}).get(f) for f in
             ("Vlag", "Vlag_reden", "Levensduur",
              "Onderhoudsintervallen", "Onderhoudsmoment"))
         for k in keys],
        index=out.index,
    )
    out["annotatie_bron"] = np.where(has_any, "mens", "")
    return out


def export_excel_bytes(df: pd.DataFrame) -> bytes:
    """Schrijf de gefilterde dataset als Excel naar bytes (incl. annotaties)."""
    merged = _merge_annotations_into_df(df)
    cols = [c for c in Settings.EXPORT_COLUMNS if c in merged.columns]
    export_df = merged[cols].copy()
    for col in export_df.columns:
        if "object" in str(export_df[col].dtype) or col == "hectopunt_geometry":
            export_df[col] = export_df[col].astype(str)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Hectopunten")
        # Audit-log op een tweede tabblad zodat één bestand het complete
        # verhaal vertelt.
        annotations = load_annotations()
        log_rows = annotations.get(AUDIT_LOG_KEY) or []
        if log_rows:
            pd.DataFrame(log_rows).to_excel(
                writer, index=False, sheet_name="Audit_log",
            )
    return buf.getvalue()


def export_pickle_bytes(df: pd.DataFrame) -> bytes:
    """Schrijf de gefilterde dataset als pickle naar bytes (incl. annotaties)."""
    merged = _merge_annotations_into_df(df)
    buf = io.BytesIO()
    merged.to_pickle(buf)
    return buf.getvalue()


# ============================================================
# ENTRYPOINT — moet ONDERAAN staan: main() draait pas nadat ALLE
# functies in dit bestand gedefinieerd zijn (anders NameError op o.a.
# export_excel_bytes / export_pickle_bytes, die Streamlit elke rerun
# van boven naar beneden opnieuw evalueert).
# ============================================================
if __name__ == "__main__":
    if not _st_runtime_exists():
        import sys
        sys.stderr.write(
            "\n[!] Dit script moet via Streamlit gestart worden.\n"
            "    Gebruik:\n"
            f"        streamlit run \"{__file__}\"\n\n"
        )
        sys.exit(1)
    main()
