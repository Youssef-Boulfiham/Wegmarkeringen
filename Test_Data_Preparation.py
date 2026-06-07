"""
Test_Data_Preparation.py
─────────────────────────────────────────────────────────────────────────────
Iedere code-cel uit het notebook is hier een losse unittest, in dezelfde
  • de datum + tijd waarop hij gestart is
  • per cel de duur in seconden
  • aan het eind de totale duur van het hele programma
  • een lijst van alle Output/-bestanden met hun groottes
  • een tree van de folderstructuur (Output/ + Input/)
  • een verantwoording: hoeveel tests gelukt, hoeveel overgeslagen

Draaien (vanuit de Notebooks-map):
    python Test_Data_Preparation.py

De tests delen state via klasse-attributen (cls.df, cls.wegvakken, ...).
Volgorde is hard nodig — vandaar de leading 0's in de test-namen.
─────────────────────────────────────────────────────────────────────────────
"""
import os
import time
import unittest
import zipfile
import urllib.request
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from pyproj import Transformer
from shapely import wkt
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform
from scipy.spatial import cKDTree
from scipy.spatial.distance import cdist

# Pandas-opmaak gelijk aan notebook — anders kapt-ie de prints af.
pd.set_option('display.max_rows', 1000)
pd.set_option('display.max_columns', 1000)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', None)
pd.set_option('display.expand_frame_repr', False)
pd.set_option('display.float_format', '{:.6f}'.format)
pd.set_option('display.max_seq_items', None)
pd.set_option('display.precision', 10)
pd.set_option('display.show_dimensions', True)
np.set_printoptions(threshold=np.inf, linewidth=np.inf)

OUTPUT_DIR = Path("Output")
INPUT_DIR  = Path("Input")

# Globals voor de verantwoording aan het eind.
START_TIJD = None
START_DATUM = None
CEL_DUREN = {}  # test_naam -> duur in seconden


# ─────────────────────────────────────────────────────────────────────────────
# Hulpjes voor het eindrapport
# ─────────────────────────────────────────────────────────────────────────────
def _bytes_str(n):
    """Bytes naar leesbare string (1.5 MB, 230 KB, ...)."""
    for eenheid in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.1f} {eenheid}"
        n /= 1024
    return f"{n:.1f} TB"


def _folderboom(pad, prefix="", max_diepte=3, _diepte=0):
    """Korte tree van een map. Bestanden krijgen hun grootte erachter."""
    pad = Path(pad)
    if not pad.exists():
        return f"{prefix}(map ontbreekt: {pad})"
    items = sorted(p for p in pad.iterdir() if not p.name.startswith('.'))
    regels = []
    for i, p in enumerate(items):
        is_last = (i == len(items) - 1)
        teken = '└── ' if is_last else '├── '
        if p.is_dir():
            regels.append(f"{prefix}{teken}{p.name}/")
            if _diepte < max_diepte:
                vervolg = '    ' if is_last else '│   '
                sub = _folderboom(p, prefix + vervolg, max_diepte, _diepte + 1)
                if sub:
                    regels.append(sub)
        else:
            try:
                grootte = _bytes_str(p.stat().st_size)
            except OSError:
                grootte = '?'
            regels.append(f"{prefix}{teken}{p.name}  ({grootte})")
    return '\n'.join(regels)


def _output_overzicht():
    """Platte lijst van alle bestanden in Output/ met hun grootte."""
    if not OUTPUT_DIR.exists():
        return []
    rijen = []
    for p in sorted(OUTPUT_DIR.rglob('*')):
        if p.is_file() and not p.name.startswith('.'):
            try:
                rijen.append((str(p), p.stat().st_size))
            except OSError:
                rijen.append((str(p), 0))
    return rijen


# ─────────────────────────────────────────────────────────────────────────────
# QGIS-stijl helpers — schrijven QML's en bedden ze als default in de GPKG
# ─────────────────────────────────────────────────────────────────────────────
import sqlite3
from xml.sax.saxutils import escape as _xml_escape


def _qml_point(rgb, size=4):
    """Single-symbol QML voor een puntlaag (cirkel)."""
    r, g, b = rgb
    return (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        "<qgis styleCategories=\"Symbology\" version=\"3.34\">\n"
        " <renderer-v2 type=\"singleSymbol\" forceraster=\"0\" enableorderby=\"0\" symbollevels=\"0\">\n"
        "  <symbols>\n"
        "   <symbol name=\"0\" alpha=\"1\" type=\"marker\" clip_to_extent=\"1\" force_rhr=\"0\">\n"
        "    <layer pass=\"0\" locked=\"0\" enabled=\"1\" class=\"SimpleMarker\">\n"
        "     <Option type=\"Map\">\n"
        f"      <Option type=\"QString\" name=\"color\" value=\"{r},{g},{b},255\"/>\n"
        "      <Option type=\"QString\" name=\"name\" value=\"circle\"/>\n"
        f"      <Option type=\"QString\" name=\"outline_color\" value=\"{max(0,r-50)},{max(0,g-50)},{max(0,b-50)},255\"/>\n"
        "      <Option type=\"QString\" name=\"outline_style\" value=\"solid\"/>\n"
        "      <Option type=\"QString\" name=\"outline_width\" value=\"0.2\"/>\n"
        "      <Option type=\"QString\" name=\"outline_width_unit\" value=\"MM\"/>\n"
        f"      <Option type=\"QString\" name=\"size\" value=\"{size}\"/>\n"
        "      <Option type=\"QString\" name=\"size_unit\" value=\"MM\"/>\n"
        "      <Option type=\"QString\" name=\"scale_method\" value=\"diameter\"/>\n"
        "      <Option type=\"QString\" name=\"joinstyle\" value=\"bevel\"/>\n"
        "      <Option type=\"QString\" name=\"angle\" value=\"0\"/>\n"
        "      <Option type=\"QString\" name=\"offset\" value=\"0,0\"/>\n"
        "      <Option type=\"QString\" name=\"offset_unit\" value=\"MM\"/>\n"
        "      <Option type=\"QString\" name=\"horizontal_anchor_point\" value=\"1\"/>\n"
        "      <Option type=\"QString\" name=\"vertical_anchor_point\" value=\"1\"/>\n"
        "     </Option>\n"
        "    </layer>\n"
        "   </symbol>\n"
        "  </symbols>\n"
        " </renderer-v2>\n"
        " <layerGeometryType>0</layerGeometryType>\n"
        "</qgis>\n"
    )


def _line_symbol_xml(name, rgb, width):
    """Genereer <symbol>-blok voor een lijn (gebruikt door single + categorized)."""
    r, g, b = rgb
    return (
        f"   <symbol name=\"{name}\" alpha=\"1\" type=\"line\" clip_to_extent=\"1\" force_rhr=\"0\">\n"
        "    <layer pass=\"0\" locked=\"0\" enabled=\"1\" class=\"SimpleLine\">\n"
        "     <Option type=\"Map\">\n"
        f"      <Option type=\"QString\" name=\"line_color\" value=\"{r},{g},{b},255\"/>\n"
        "      <Option type=\"QString\" name=\"line_style\" value=\"solid\"/>\n"
        f"      <Option type=\"QString\" name=\"line_width\" value=\"{width}\"/>\n"
        "      <Option type=\"QString\" name=\"line_width_unit\" value=\"MM\"/>\n"
        "      <Option type=\"QString\" name=\"capstyle\" value=\"square\"/>\n"
        "      <Option type=\"QString\" name=\"joinstyle\" value=\"bevel\"/>\n"
        "      <Option type=\"QString\" name=\"use_custom_dash\" value=\"0\"/>\n"
        "      <Option type=\"QString\" name=\"draw_inside_polygon\" value=\"0\"/>\n"
        "      <Option type=\"QString\" name=\"offset\" value=\"0\"/>\n"
        "      <Option type=\"QString\" name=\"offset_unit\" value=\"MM\"/>\n"
        "     </Option>\n"
        "    </layer>\n"
        "   </symbol>\n"
    )


def _qml_line(rgb, width=2):
    """Single-symbol QML voor een lijnlaag."""
    return (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        "<qgis styleCategories=\"Symbology\" version=\"3.34\">\n"
        " <renderer-v2 type=\"singleSymbol\" forceraster=\"0\" enableorderby=\"0\" symbollevels=\"0\">\n"
        "  <symbols>\n"
        f"{_line_symbol_xml('0', rgb, width)}"
        "  </symbols>\n"
        " </renderer-v2>\n"
        " <layerGeometryType>1</layerGeometryType>\n"
        "</qgis>\n"
    )


def _qml_line_categorized(attr, categories, width=2):
    """Categorized lijn-QML. categories=[(value|None, label, rgb), ...]."""
    cats, syms = [], []
    for i, (value, label, rgb) in enumerate(categories):
        v = '' if value is None else _xml_escape(str(value), {'"': '&quot;'})
        l = _xml_escape(label, {'"': '&quot;'})
        cats.append(f'   <category render="true" value="{v}" symbol="{i}" label="{l}"/>\n')
        syms.append(_line_symbol_xml(str(i), rgb, width))
    return (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        "<qgis styleCategories=\"Symbology\" version=\"3.34\">\n"
        f" <renderer-v2 type=\"categorizedSymbol\" attr=\"{attr}\" forceraster=\"0\" enableorderby=\"0\" symbollevels=\"0\">\n"
        "  <categories>\n"
        f"{''.join(cats)}"
        "  </categories>\n"
        "  <symbols>\n"
        f"{''.join(syms)}"
        "  </symbols>\n"
        " </renderer-v2>\n"
        " <layerGeometryType>1</layerGeometryType>\n"
        "</qgis>\n"
    )


def _embed_default_style(gpkg_pad, layer_naam, qml_inhoud):
    """Bed een QML-stijl als default style in de GPKG layer_styles-tabel."""
    with sqlite3.connect(gpkg_pad) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS layer_styles ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " f_table_catalog VARCHAR(256), f_table_schema VARCHAR(256),"
            " f_table_name VARCHAR(256), f_geometry_column VARCHAR(256),"
            " styleName TEXT, styleQML TEXT, styleSLD TEXT,"
            " useAsDefault BOOLEAN, description TEXT, owner VARCHAR(30),"
            " ui TEXT, update_time TIMESTAMP DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
            ")"
        )
        # Idempotent: gooi bestaande default-style voor deze layer weg
        conn.execute("DELETE FROM layer_styles WHERE f_table_name=? AND useAsDefault=1",
                     (layer_naam,))
        row = conn.execute(
            "SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?",
            (layer_naam,)
        ).fetchone()
        geom_col = row[0] if row else 'geom'
        conn.execute(
            "INSERT INTO layer_styles "
            "(f_table_catalog,f_table_schema,f_table_name,f_geometry_column,"
            " styleName,styleQML,useAsDefault,description,owner) "
            "VALUES ('','',?,?,'default',?,1,'auto-gegenereerde QC-stijl','')",
            (layer_naam, geom_col, qml_inhoud)
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# De eigenlijke tests
# ─────────────────────────────────────────────────────────────────────────────
class TestDataPreparation(unittest.TestCase):
    """Spiegel van Data_Preparation.ipynb. Eén test per cel, in volgorde."""

    # --- setup/teardown voor de hele klasse ----------------------------------

    @classmethod
    def setUpClass(cls):
        global START_TIJD, START_DATUM
        START_TIJD = time.time()
        START_DATUM = datetime.now()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        print()
        print('═' * 78)
        print(f'  Test_Data_Preparation — gestart op {START_DATUM:%Y-%m-%d %H:%M:%S}')
        print(f'  Werkmap : {Path.cwd()}')
        print('═' * 78)

    @classmethod
    def tearDownClass(cls):
        eind = datetime.now()
        totaal = time.time() - START_TIJD
        print()
        print('═' * 78)
        print('  KLAAR — Verantwoording')
        print('═' * 78)
        print(f'  Gestart   : {START_DATUM:%Y-%m-%d %H:%M:%S}')
        print(f'  Geëindigd : {eind:%Y-%m-%d %H:%M:%S}')
        print(f'  Totaal    : {int(totaal)}s  ({totaal/60:.1f} min)')
        print()
        print('  ── Duur per cel ────────────────────────────────────────────')
        for naam, dur in CEL_DUREN.items():
            print(f'    {naam:55s} {dur:>5d}s')
        print()
        print('  ── Output-bestanden ────────────────────────────────────────')
        rijen = _output_overzicht()
        totaal_bytes = 0
        for pad, grootte in rijen:
            print(f'    {pad:55s} {_bytes_str(grootte):>10s}')
            totaal_bytes += grootte
        streep = '─' * 55
        print(f'    {streep} {"─" * 10}')
        print(f'    {"TOTAAL":55s} {_bytes_str(totaal_bytes):>10s}')
        print()
        print('  ── Folderstructuur Output/ ────────────────────────────────')
        print(_folderboom(OUTPUT_DIR, prefix='    '))
        print()
        print('  ── Folderstructuur Input/ (1 laag diep) ──────────────────')
        print(_folderboom(INPUT_DIR, prefix='    ', max_diepte=1))
        print('═' * 78)

    # --- setup/teardown per test ---------------------------------------------

    def setUp(self):
        self._t0 = time.time()
        print()
        print(f'─── {self._testMethodName} ' + '─' * (60 - len(self._testMethodName)))

    def tearDown(self):
        dur = int(time.time() - self._t0)
        CEL_DUREN[self._testMethodName] = dur
        print(f'─── klaar in {dur}s ' + '─' * (60 - len(str(dur))))

    # =========================================================================
    # CEL 1 — Modules
    # =========================================================================
    def test_01_modules_inladen(self):
        """Cel 1: alle imports die het notebook nodig heeft. Hoort gewoon te lukken."""
        from UnitTest import (
            Timer, Duur, meet_duur, toon_duur,
            convert_wkt_string_to_gps,
            batch_transform_geometry_to_gps_string,
            convert_coords_to_gps,
        )
        # Helpers die later nog nodig zijn (INWEVA, Deklagen) bewaren op de klasse.
        type(self).Duur = Duur
        type(self).Timer = Timer
        # Even checken dat de zware libs er ook bij zijn:
        self.assertIsNotNone(gpd)
        self.assertIsNotNone(pd)
        self.assertIsNotNone(np)
        print('Alle modules en helpers staan klaar.')

    # =========================================================================
    # CEL 3+5 — Wegvakken laden (uit pickle als-ie er is, anders uit NWB)
    # =========================================================================
    def test_02_wegvakken_laden(self):
        """Wegvakken laden: pickle indien aanwezig, anders NWB filteren + wegschrijven."""
        cls = type(self)
        pkl = Path("Output/wegvakken.pkl")

        if pkl.exists():
            wegvakken = pd.read_pickle(pkl)
            print(f'Wegvakken geladen uit pickle : {wegvakken.shape[0]:,} rijen, '
                  f'{wegvakken.shape[1]} kolommen')
        else:
            wegvakken = gpd.read_file(
                "Input/Beschrijvende_Plaatsaanduiding_systematiek/nwb-wegen-08_01_2026.gpkg",
                layer="wegvakken")
            wegvakken = wegvakken[wegvakken['wegnr_hmp'].isin(
                ['A12', 'A4', 'A20', 'N11', 'N14', 'A13', 'A44', 'A16', 'N44', 'A27', 'A2'])]
            wegvakken = wegvakken.rename(columns={'geometry': 'wegvak_geometry'})
            wegvakken = wegvakken[['wvk_id', 'rijrichtng', 'wegnummer', 'wegnr_hmp', 'wegnr_aw',
                                   'beginkm', 'eindkm', 'wegbehnaam', 'distrnaam', 'wegvak_geometry']]
            wegvakken.to_pickle(pkl)
            print(f'wegvakken.pkl weggeschreven : {len(wegvakken):,} rijen')

        cls.wegvakken = wegvakken
        print(wegvakken.sample(1).T)
        self.assertGreater(len(wegvakken), 0)
        self.assertIn('wvk_id', wegvakken.columns)
        self.assertIn('wegvak_geometry', wegvakken.columns)

    # =========================================================================
    # CEL 7 — Hectopunten inlezen
    # =========================================================================
    def test_04_hectopunten_inlezen(self):
        """Cel 7: hectopunten-laag uit dezelfde gpkg trekken."""
        cls = type(self)
        hectopunten_ = gpd.read_file(
            "Input/Beschrijvende_Plaatsaanduiding_systematiek/nwb-wegen-08_01_2026.gpkg",
            layer='hectopunten')
        cls.hectopunten = hectopunten_.copy()
        self.assertGreater(len(cls.hectopunten), 0)

    # =========================================================================
    # CEL 8 — Hectopunten-overzicht
    # =========================================================================
    def test_05_hectopunten_overzicht(self):
        """Cel 8: hoeveel hectopunten + één willekeurige rij T-en."""
        cls = type(self)
        hectopunten = cls.hectopunten
        print(f'Hectopunten geladen: {hectopunten.shape[0]:,} rijen, '
              f'{hectopunten.shape[1]} kolommen')
        print(hectopunten.sample(1).T)
        self.assertGreater(hectopunten.shape[1], 0)

    # =========================================================================
    # CEL 9 — Hectopunten opschonen
    # =========================================================================
    def test_06_hectopunten_opschonen(self):
        """Cel 9: kolom hernoemen, sorteren, types vastzetten, meter erbij."""
        cls = type(self)
        hectopunten = cls.hectopunten
        hectopunten = hectopunten.rename(columns={'geometry': 'hectopunt_geometry'})
        hectopunten = hectopunten.sort_values(by='wvk_id', ascending=True).reset_index()
        hectopunten['meter'] = hectopunten['hectomtrng'] * 1000
        hectopunten = hectopunten.astype({
            'wvk_id':     'int',
            'hectomtrng': 'int',
            'hecto_lttr': 'string',
        })
        hectopunten = hectopunten[['hectomtrng', 'afstand', 'wvk_id',
                                   'hecto_lttr', 'hectopunt_geometry']]
        cls.hectopunten = hectopunten
        self.assertIn('hectopunt_geometry', hectopunten.columns)
        self.assertEqual(hectopunten['wvk_id'].dtype.kind, 'i')

    # =========================================================================
    # CEL 10 — Eerste rij even bekijken
    # =========================================================================
    def test_07_hectopunten_kop(self):
        """Cel 10: visuele check op de eerste rij."""
        cls = type(self)
        print(cls.hectopunten.head(1).T)
        self.assertGreater(len(cls.hectopunten), 0)

    # =========================================================================
    # CEL 11 — Merge hectopunten ↔ wegvakken
    # =========================================================================
    def test_08_merge_hectopunten_wegvakken(self):
        """Cel 11: inner merge op wvk_id; duplicaten-rapport erbij."""
        cls = type(self)
        hectopunten = cls.hectopunten
        wegvakken   = cls.wegvakken
        hectopunten_voor = len(hectopunten)
        wegvakken_voor   = len(wegvakken)

        df = hectopunten.merge(wegvakken, on='wvk_id', how='inner')
        aantal_duplicaten = df['wvk_id'].duplicated().sum()
        heeft_duplicaten = "Ja" if aantal_duplicaten > 0 else "Nee"

        print(f'Hectopunten voor merge : {hectopunten_voor:,}')
        print(f'Wegvakken  voor merge  : {wegvakken_voor:,}')
        print(f'Hectopunten na merge   : {df.shape[0]:,}')
        print(f'Verlies hectopunten    : {hectopunten_voor - df.shape[0]:,} '
              f'({(hectopunten_voor - df.shape[0]) / hectopunten_voor * 100:.1f}%)')
        print(f'Kolommen na merge ({len(df.columns)}): {df.columns.tolist()}')
        print(f'Duplicaten in wvk_id   : {heeft_duplicaten} ({aantal_duplicaten:,} stuks)')
        if aantal_duplicaten > 0:
            print('\nVoorbeelden van duplicaten:')
            print(df[df['wvk_id'].duplicated(keep=False)]
                  .sort_values('wvk_id').head(4).T)

        cls.df = df
        self.assertGreater(df.shape[0], 0)
        self.assertIn('beginkm', df.columns)
        self.assertIn('eindkm', df.columns)
        self.assertIn('hectopunt_geometry', df.columns)

    # =========================================================================
    # CEL 12 — Zijde, oplopend, snelwegnummer
    # =========================================================================
    def test_09_zijde_oplopend_snelwegnummer(self):
        """Cel 12: Rechts/Links en snelwegnummer als int + lege info/-kolom."""
        cls = type(self)
        df = cls.df
        df['Zijde']         = np.where(df['beginkm'] < df['eindkm'], 'Rechts', 'Links')
        df['oplopend']      = np.where(df['beginkm'] < df['eindkm'], 'R', 'L')
        df['snelwegnummer'] = df['wegnr_hmp'].str.replace(r'\D', '', regex=True).astype(int)
        df['|']    = ''
        df['info'] = ''
        cls.df = df
        print(df.sample(1).T)
        for k in ('Zijde', 'oplopend', 'snelwegnummer', 'info'):
            self.assertIn(k, df.columns)

    # =========================================================================
    # CEL 14 — Verrijken met GPS, RD en kaartlinks
    # =========================================================================
    def test_10_gps_en_kaartlinks(self):
        """Cel 14: per hectopunt GPS, RD-coord, Google Maps / StreetSmart / PDOK-link."""
        cls = type(self)
        df = cls.df

        _TRANSFORMER = Transformer.from_crs('EPSG:28992', 'EPSG:4326', always_xy=True)
        _OFFSET_X, _OFFSET_Y = 89.35, 128.84
        _NWB_UUID = "f2437a92-ddd3-4777-a1bc-fdf4b4a7fcb8"
        _LAYERS = f"{_NWB_UUID};hectopunten;_;1,{_NWB_UUID};wegvakken;_;1"
        _ZOOM = 12.5

        geoms = df['hectopunt_geometry'].to_numpy()
        n = len(geoms)
        xs = np.full(n, np.nan)
        ys = np.full(n, np.nan)
        for i, g in enumerate(geoms):
            if g is None:
                continue
            gt = g.geom_type
            if gt == 'Point':
                xs[i] = g.x
                ys[i] = g.y
            elif gt == 'MultiPoint':
                p = g.geoms[0]
                xs[i] = p.x
                ys[i] = p.y

        valid = ~np.isnan(xs)
        lons = np.full(n, np.nan)
        lats = np.full(n, np.nan)
        if valid.any():
            lons[valid], lats[valid] = _TRANSFORMER.transform(xs[valid], ys[valid])

        rd_coords         = [None] * n
        gps_coords        = [None] * n
        google_links      = [None] * n
        streetsmart_links = [None] * n
        pdok_links        = [None] * n

        for i in range(n):
            if not valid[i]:
                continue
            x = round(xs[i], 2)
            y = round(ys[i], 2)
            lat = lats[i]
            lon = lons[i]
            gps = f"{lat:.6f}, {lon:.6f}"
            rd_coords[i]    = f"{x:.2f}, {y:.2f}"
            gps_coords[i]   = gps
            google_links[i] = f"https://www.google.com/maps/search/?api=1&query={gps}"
            minX = round(x - _OFFSET_X, 2)
            minY = round(y - _OFFSET_Y, 2)
            maxX = round(x + _OFFSET_X, 2)
            maxY = round(y + _OFFSET_Y, 2)
            streetsmart_links[i] = (
                f"https://streetsmart.cyclomedia.com/streetsmart/"
                f"?mq={minX};{minY};{maxX};{maxY}&msrs=EPSG:28992"
            )
            pdok_links[i] = (
                f"https://app.pdok.nl/viewer/#x={x:.2f}&y={y:.2f}&z={_ZOOM}"
                f"&background=BRT-A%20standaard&layers={_LAYERS}"
            )

        df['gps_coordinaten']          = gps_coords
        df['google_maps_link']         = google_links
        df['hectopunt_rd_coordinaten'] = rd_coords
        df['streetsmart_link']         = streetsmart_links
        df['pdok_viewer_link']         = pdok_links

        df.to_pickle("Output/Data_Analyse-Dataset.pkl")
        cls.df = df
        print(f'Verrijkt en weggeschreven naar Output/Data_Analyse-Dataset.pkl '
              f'({len(df):,} rijen).')

        for k in ('gps_coordinaten', 'google_maps_link',
                  'hectopunt_rd_coordinaten', 'streetsmart_link', 'pdok_viewer_link'):
            self.assertIn(k, df.columns)
        self.assertTrue(Path("Output/Data_Analyse-Dataset.pkl").exists())

    # =========================================================================
    # CEL 16 — Pickle terugladen
    # =========================================================================
    def test_11_dataset_uit_pickle(self):
        """Cel 16: hele dataset terughalen uit pickle."""
        cls = type(self)
        df = pd.read_pickle("Output/Data_Analyse-Dataset.pkl")
        print(f'hectopunten geladen : {df.shape[0]:,} rijen, '
              f'{df.shape[1]} kolommen')
        cls.df = df
        self.assertGreater(df.shape[0], 0)

    # =========================================================================
    # CEL 17 — INWEVA koppelen
    # =========================================================================
    def test_12_inweva_koppelen(self):
        """Cel 17: INWEVA downloaden (eerste keer), netwerk + werkdag inlezen, koppelen per wvk_id."""
        cls = type(self)
        df = cls.df
        Duur = cls.Duur

        JAAR = 2025
        INWEVA_DIR = Path("Input/Inweva")
        INWEVA_DIR.mkdir(parents=True, exist_ok=True)
        INWEVA_ZIP = INWEVA_DIR / f'INWEVA_{JAAR}.zip'
        INWEVA_EXTRACTED = INWEVA_DIR / f'INWEVA_{JAAR}'
        URL = f'https://downloads.rijkswaterstaatdata.nl/inweva/INWEVA_{JAAR}.zip'

        def download_inweva():
            if not INWEVA_ZIP.exists():
                with Duur('Download INWEVA'):
                    urllib.request.urlretrieve(URL, INWEVA_ZIP)
            if not INWEVA_EXTRACTED.exists():
                with zipfile.ZipFile(INWEVA_ZIP) as z:
                    z.extractall(INWEVA_DIR)

        def lees_netwerk():
            shp_pad = INWEVA_EXTRACTED / f'INWEVA_{JAAR}_netwerk' / f'INWEVA{JAAR}.shp'
            with Duur('Inlezen INWEVA shapefile'):
                netwerk = gpd.read_file(shp_pad)
            netwerk['VBN_ID'] = netwerk['VBN_ID'].astype(str)
            return netwerk

        def lees_werkdag():
            return pd.read_csv(
                INWEVA_EXTRACTED / f'inweva_werkdag_{JAAR}DEC.csv',
                sep=';', dtype={'VBN_ID': str})

        def bouw_inweva_per_wvk(netwerk, werkdag):
            inweva = netwerk.merge(
                werkdag[['VBN_ID', 'AL_E_WR', 'L1_E_WR', 'L2_E_WR', 'L3_E_WR']],
                on='VBN_ID', how='left'
            )
            inweva_wvk = (
                inweva
                .assign(WVK_ID=inweva['WVK_IDS'].fillna('').str.split(','))
                .explode('WVK_ID')
            )
            inweva_wvk['WVK_ID'] = inweva_wvk['WVK_ID'].str.strip()
            inweva_wvk = inweva_wvk[inweva_wvk['WVK_ID'] != '']
            inweva_wvk['wvk_id'] = pd.to_numeric(inweva_wvk['WVK_ID'], errors='coerce').astype('Int64')

            per_wvk = (
                inweva_wvk[['wvk_id', 'L1_E_WR', 'L2_E_WR', 'L3_E_WR', 'AL_E_WR', 'VBNOMSTXT']]
                .drop_duplicates(subset='wvk_id', keep='first')
                .reset_index(drop=True)
                .rename(columns={
                    'L1_E_WR': 'klein_voertuig',
                    'L2_E_WR': 'middel_voertuig',
                    'L3_E_WR': 'lang_voertuig',
                    'AL_E_WR': 'totaal_voertuig',
                    'VBNOMSTXT': '_inweva_omschrijving',
                })
            )
            voertuig_cols = ['klein_voertuig', 'middel_voertuig', 'lang_voertuig', 'totaal_voertuig']
            per_wvk[voertuig_cols] = per_wvk[voertuig_cols].fillna(0).round().astype('Int64')
            per_wvk['wvk_id'] = per_wvk['wvk_id'].astype('Int64')
            return per_wvk

        def koppel_inweva(df, inweva_per_wvk):
            n_voor = len(df)
            voertuig_cols = ['klein_voertuig', 'middel_voertuig', 'lang_voertuig',
                             'totaal_voertuig', '_inweva_omschrijving']
            df = df.drop(columns=[c for c in voertuig_cols if c in df.columns])
            df['wvk_id'] = pd.to_numeric(df['wvk_id'], errors='coerce').astype('Int64')
            df = df.merge(inweva_per_wvk, on='wvk_id', how='left')
            assert len(df) == n_voor, f'Hectopunten omvang VERANDERD! {n_voor} -> {len(df)}'
            return df

        download_inweva()
        netwerk = lees_netwerk()
        werkdag = lees_werkdag()
        inweva_per_wvk = bouw_inweva_per_wvk(netwerk, werkdag)

        df_voor = len(df)
        df = koppel_inweva(df, inweva_per_wvk)
        df = df.loc[:, ~df.columns.duplicated()].copy()

        # VBNOMSTXT als steekwoord aan info plakken
        df['info'] = df['info'].fillna('').astype(str)
        omschr = df['_inweva_omschrijving'].fillna('').astype(str)
        df['info'] = df['info'] + omschr.where(omschr == '', ' | ' + omschr).where(df['info'] != '', omschr)
        df = df.drop(columns=['_inweva_omschrijving'])

        cols = [
            'wvk_id', 'wegnr_hmp', 'Zijde', 'hectomtrng', 'hecto_lttr',
            'klein_voertuig', 'middel_voertuig', 'lang_voertuig',
            'totaal_voertuig', 'distrnaam', 'info',
            'streetsmart_link', 'google_maps_link', 'pdok_viewer_link', '|', 'wegbehnaam',
            'beginkm', 'eindkm', 'snelwegnummer', 'wegnummer', 'wegnr_aw',
            'rijrichtng', 'oplopend', 'afstand',
            'hectopunt_geometry', 'wegvak_geometry',
            'gps_coordinaten', 'hectopunt_rd_coordinaten',
        ]
        df = df[cols]
        df = df.loc[:, ~df.columns.duplicated()].copy()

        df.to_pickle("Output/Data_Analyse-Dataset.pkl")
        df = pd.read_pickle("Output/Data_Analyse-Dataset.pkl")
        cls.df = df

        print(f'Wegvakken geladen : {df.shape[0]:,} rijen, {df.shape[1]} kolommen')
        n_match = df['totaal_voertuig'].notna().sum()
        print(f'Hectopunten voor merge : {df_voor:,}')
        print(f'Hectopunten na merge   : {df.shape[0]:,}')
        print(f'Hectopunten mét INWEVA : {n_match:,} ({n_match / len(df) * 100:.1f}%)')
        print(f'Kolommen na merge ({len(df.columns)}): {df.columns.tolist()}')

        for k in ('klein_voertuig', 'middel_voertuig', 'lang_voertuig', 'totaal_voertuig'):
            self.assertIn(k, df.columns)
        self.assertEqual(len(df), df_voor)

    # =========================================================================
    # CEL 19 — Bochten koppelen
    # =========================================================================
    def test_13_bochten_koppelen(self):
        """Cel 19: bochten nearest-matchen aan hectopunten binnen 250 m, dezelfde wvk."""
        cls = type(self)
        df = cls.df

        bochten = gpd.read_file("Input/Bochten/bochten_w.shp")
        bochten.rename(columns={'WVK_ID': 'wvk_id'}, inplace=True)
        bochten['wvk_id'] = bochten['wvk_id'].astype(float)
        print(f'Bochten geladen: {bochten.shape[0]:,} rijen, {bochten.shape[1]} kolommen')

        hecto_wvk   = {int(x) for x in df['wvk_id'].dropna().tolist()}
        bocht_wvk   = {int(x) for x in bochten['wvk_id'].dropna().tolist()}
        overlap_wvk = hecto_wvk & bocht_wvk
        print(f'Hectopunten (wvk_ids): {len(hecto_wvk):,}')
        print(f'Bochten     (wvk_ids): {len(bocht_wvk):,}')

        _hecto_voor   = len(df)
        _bochten_voor = len(bochten)

        transformer = Transformer.from_crs('EPSG:28992', 'EPSG:4326', always_xy=True)

        def _coords(geom):
            if geom is None:
                return None
            if geom.geom_type == 'LineString':
                return list(geom.coords)
            if geom.geom_type == 'MultiLineString':
                return [c for line in geom.geoms for c in line.coords]
            return None

        def rd_coords_flat(geom):
            coords = _coords(geom)
            if coords is None:
                return None
            return ", ".join(f"{round(x,3)}, {round(y,3)}" for x, y in coords)

        def gps_coords_flat(geom):
            coords = _coords(geom)
            if coords is None:
                return None
            return ", ".join(
                f"{round(lat,6)}, {round(lon,6)}"
                for x, y in coords
                for lon, lat in [transformer.transform(x, y)]
            )

        df['hectopunt_geometry_flat'] = df['hectopunt_geometry'].apply(
            lambda g: f"{repr(g.geoms[0].x)}, {repr(g.geoms[0].y)}"
        )
        bochten['bochten_geometry_flat']   = bochten['geometry'].apply(
            lambda g: ', '.join(f"{x}, {y}" for x, y in g.coords))
        bochten['bochten_rd_coordinaten']  = bochten['geometry'].apply(rd_coords_flat)
        bochten['bochten_gps_coordinaten'] = bochten['geometry'].apply(gps_coords_flat)

        def parse_first_rd_point(geom_str):
            parts = str(geom_str).split(',')
            return float(parts[0].strip()), float(parts[1].strip())

        def parse_middle_rd_point(geom_str):
            parts  = [float(p.strip()) for p in str(geom_str).split(',')]
            coords = [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]
            return coords[len(coords) // 2]

        df['_rd_x'], df['_rd_y'] = zip(*df['hectopunt_geometry_flat'].apply(parse_first_rd_point))
        bochten['_rd_x'], bochten['_rd_y'] = zip(*bochten['bochten_geometry_flat'].apply(parse_middle_rd_point))
        df = df.reset_index(drop=True)

        # 1) Twee-pass matching:
        #    pass 1 — zelfde wvk_id, binnen 250 m (preferent: zelfde wegvak = zelfde fysieke deel)
        #    pass 2 — voor ongematchte bochten: dichtstbijzijnde hectopunt globaal binnen 50 m
        #             (vangt bochten op die op een wegvak liggen dat door de wegnr-filter is
        #              weggevallen — typisch op-/afritten/verbindingsbanen naast de hoofdrijbaan).
        #    Drempel 50 m is gekozen omdat p90 van de pass-1-matches op ~48 m ligt; streng
        #    genoeg om geen wilde matches in interchanges te krijgen.
        hecto_per_wvk = {wvk: sub for wvk, sub in df.groupby('wvk_id')}
        bocht_naar_hecto = {}
        match_methode   = {}  # bocht_idx -> 'zelfde_wvk' / 'global_<=50m'

        # Pass 1: zelfde wvk, ≤250 m
        for bocht_idx, brow in bochten.iterrows():
            sub = hecto_per_wvk.get(brow['wvk_id'])
            if sub is None or sub.empty:
                continue
            bpt       = np.array([[brow['_rd_x'], brow['_rd_y']]])
            hpts      = sub[['_rd_x', '_rd_y']].values
            distances = cdist(bpt, hpts)[0]
            nearest   = np.argmin(distances)
            if distances[nearest] <= 250:
                bocht_naar_hecto[bocht_idx] = sub.index[nearest]
                match_methode[bocht_idx]   = 'zelfde_wvk'

        # Pass 2: globale fallback voor de rest, ≤50 m
        _GLOBAL_FALLBACK_MAX = 50.0
        _tree = cKDTree(df[['_rd_x', '_rd_y']].values)
        _ongematcht_mask = ~bochten.index.isin(list(bocht_naar_hecto.keys()))
        if _ongematcht_mask.any():
            _ongematcht = bochten.loc[_ongematcht_mask]
            _bxy        = _ongematcht[['_rd_x', '_rd_y']].values
            _d_glob, _i_glob = _tree.query(_bxy, k=1)
            for offset, bocht_idx in enumerate(_ongematcht.index):
                if _d_glob[offset] <= _GLOBAL_FALLBACK_MAX:
                    bocht_naar_hecto[bocht_idx] = int(_i_glob[offset])
                    match_methode[bocht_idx]   = 'global_<=50m'
        _n_pass1 = sum(1 for v in match_methode.values() if v == 'zelfde_wvk')
        _n_pass2 = sum(1 for v in match_methode.values() if v == 'global_<=50m')
        print(f'Matches pass 1 (zelfde wvk, ≤250m)   : {_n_pass1:,}')
        print(f'Matches pass 2 (globaal, ≤50m)       : {_n_pass2:,}')

        # 2) per hectopunt: alle bochten verzamelen
        hecto_naar_bochten = defaultdict(list)
        for bocht_idx, hecto_pos in bocht_naar_hecto.items():
            hecto_naar_bochten[hecto_pos].append(bocht_idx)

        # 3) per hectopunt: comma-strings opbouwen
        def _join(idxs, kol):
            return ', '.join(str(bochten.loc[i, kol]) for i in idxs)

        draaihoek_kol, boogstraal_kol     = [], []
        geom_flat_kol, rd_kol, gps_kol    = [], [], []
        check_lijn_kol, aantal_kol        = [], []

        for pos in range(len(df)):
            idxs = hecto_naar_bochten.get(pos, [])
            aantal_kol.append(len(idxs))
            if not idxs:
                draaihoek_kol.append(None);  boogstraal_kol.append(None)
                geom_flat_kol.append(None);  rd_kol.append(None)
                gps_kol.append(None);        check_lijn_kol.append(None)
                continue
            draaihoek_kol .append(_join(idxs, 'DRAAIHOEK'))
            boogstraal_kol.append(_join(idxs, 'BOOGSTRAAL'))
            geom_flat_kol .append(_join(idxs, 'bochten_geometry_flat'))
            rd_kol        .append(_join(idxs, 'bochten_rd_coordinaten'))
            gps_kol       .append(_join(idxs, 'bochten_gps_coordinaten'))
            hx, hy = df.loc[pos, '_rd_x'], df.loc[pos, '_rd_y']
            check_lijn_kol.append(', '.join(
                f"LINESTRING ({hx} {hy}, {bochten.loc[i, '_rd_x']} {bochten.loc[i, '_rd_y']})"
                for i in idxs
            ))

        df['draaihoek']               = draaihoek_kol
        df['boogstraal']              = boogstraal_kol
        df['bochten_geometry_flat']   = geom_flat_kol
        df['bochten_rd_coordinaten']  = rd_kol
        df['bochten_gps_coordinaten'] = gps_kol
        df['aantal_bochten']          = aantal_kol
        df['check_koppeling_lijn']    = check_lijn_kol

        # 4) QC-kaartlagen bochten (zelfde stramien als inspecties; hectopunten-laag
        #    wordt al door test_14 geschreven, dus die slaan we hier over).
        KAARTLAGEN_DIR = Path("Output/Kaartlagen")
        KAARTLAGEN_DIR.mkdir(parents=True, exist_ok=True)
        BOCHTEN_LIJNEN_PAD       = str(KAARTLAGEN_DIR / "Kwaliteitscontrole_bochten_lijnen.gpkg")
        BOCHTEN_VERBINDINGEN_PAD = str(KAARTLAGEN_DIR / "Kwaliteitscontrole_bochten_verbindingen.gpkg")

        # 4a) Bochten-laag: ALLE bochten (gematcht én ongematcht).
        _bocht_attr_cols = [c for c in ['wvk_id', 'DRAAIHOEK', 'BOOGSTRAAL']
                            if c in bochten.columns]
        bochten_lijnen_laag = gpd.GeoDataFrame(
            {**{c: bochten[c].values for c in _bocht_attr_cols},
             '_bocht_idx':    bochten.index.values.astype('int64'),
             '_hecto_idx':    pd.array(
                 [bocht_naar_hecto.get(i) for i in bochten.index], dtype='Int64'),
             'gematcht':      [i in bocht_naar_hecto for i in bochten.index],
             'match_methode': [match_methode.get(i) for i in bochten.index]},
            geometry=bochten['geometry'].tolist(),
            crs='EPSG:28992',
        )
        bochten_lijnen_laag.to_file(BOCHTEN_LIJNEN_PAD, driver='GPKG')
        _embed_default_style(BOCHTEN_LIJNEN_PAD, Path(BOCHTEN_LIJNEN_PAD).stem,
                             _qml_line((40, 90, 200), width=2))
        print(f'QC bochten-laag       : {BOCHTEN_LIJNEN_PAD}  '
              f'({len(bochten_lijnen_laag):,} bochten)')

        # 4b) Verbindingen-laag: lijn van bocht-middelpunt naar gekoppelde hectopunt.
        _verb_geoms, _verb_bocht_idxs, _verb_hecto_idxs, _verb_methode = [], [], [], []
        for bocht_idx, hecto_pos in bocht_naar_hecto.items():
            bx, by = bochten.loc[bocht_idx, '_rd_x'], bochten.loc[bocht_idx, '_rd_y']
            hx, hy = df.loc[hecto_pos, '_rd_x'], df.loc[hecto_pos, '_rd_y']
            _verb_geoms.append(LineString([(bx, by), (hx, hy)]))
            _verb_bocht_idxs.append(bocht_idx)
            _verb_hecto_idxs.append(hecto_pos)
            _verb_methode.append(match_methode[bocht_idx])
        bochten_verbindingen_laag = gpd.GeoDataFrame(
            {'_bocht_idx':    _verb_bocht_idxs,
             '_hecto_idx':    _verb_hecto_idxs,
             'match_methode': _verb_methode},
            geometry=_verb_geoms,
            crs='EPSG:28992',
        )
        bochten_verbindingen_laag.to_file(BOCHTEN_VERBINDINGEN_PAD, driver='GPKG')
        _embed_default_style(BOCHTEN_VERBINDINGEN_PAD, Path(BOCHTEN_VERBINDINGEN_PAD).stem,
                             _qml_line((220, 30, 30), width=2))
        print(f'QC verbindingen-laag  : {BOCHTEN_VERBINDINGEN_PAD}  '
              f'({len(bochten_verbindingen_laag):,} lijnen)')

        cls.BOCHTEN_LIJNEN_PAD       = BOCHTEN_LIJNEN_PAD
        cls.BOCHTEN_VERBINDINGEN_PAD = BOCHTEN_VERBINDINGEN_PAD

        df.drop(columns=['_rd_x', '_rd_y'], inplace=True)
        bochten.drop(columns=['_rd_x', '_rd_y'], inplace=True)
        df = df.sort_values('aantal_bochten', ascending=False).reset_index(drop=True)
        df = df[['wvk_id', 'wegnr_hmp', 'Zijde', 'hectomtrng', 'hecto_lttr',
                 'draaihoek', 'boogstraal',
                 'klein_voertuig', 'middel_voertuig', 'lang_voertuig', 'totaal_voertuig',
                 'distrnaam', 'info', 'streetsmart_link', 'google_maps_link', 'pdok_viewer_link', '|',
                 'wegbehnaam', 'beginkm', 'eindkm', 'snelwegnummer', 'wegnummer',
                 'wegnr_aw', 'rijrichtng', 'oplopend', 'afstand',
                 'hectopunt_geometry', 'wegvak_geometry', 'gps_coordinaten',
                 'hectopunt_rd_coordinaten', 'hectopunt_geometry_flat',
                 'bochten_geometry_flat', 'bochten_rd_coordinaten', 'bochten_gps_coordinaten',
                 'aantal_bochten', 'check_koppeling_lijn']]
        df.to_pickle("Output/Data_Analyse-Dataset.pkl")
        df = pd.read_pickle("Output/Data_Analyse-Dataset.pkl")
        cls.df = df
        print(f'Wegvakken geladen : {df.shape[0]:,} rijen, {df.shape[1]} kolommen')

        # 5) diagnostiek
        hecto_match   = sum(1 for v in aantal_kol if v > 0)
        hecto_geen    = len(df) - hecto_match
        bochten_match = len(bocht_naar_hecto)
        bochten_geen  = _bochten_voor - bochten_match
        max_per_hecto = max(aantal_kol) if aantal_kol else 0

        print(f'── Hectopunten ──────────────────────────────')
        print(f'  Voor koppeling   : {_hecto_voor:,}')
        print(f'  Na koppeling     : {len(df):,}')
        print(f'  Met bocht(en)    : {hecto_match:,}  ({hecto_match/len(df)*100:.1f}%)')
        print(f'  Zonder bocht     : {hecto_geen:,}  ({hecto_geen/len(df)*100:.1f}%)')
        print(f'  Max bochten/hecto: {max_per_hecto}')
        print(f'── Bochten ──────────────────────────────────')
        print(f'  Voor koppeling   : {_bochten_voor:,}')
        print(f'  Gekoppeld        : {bochten_match:,}  ({bochten_match/_bochten_voor*100:.1f}%)')
        print(f'  Ongekoppeld      : {bochten_geen:,}  ({bochten_geen/_bochten_voor*100:.1f}%)')
        print(f'Kolommen na koppeling ({len(df.columns)}): {df.columns.tolist()}')

        for k in ('draaihoek', 'boogstraal', 'aantal_bochten'):
            self.assertIn(k, df.columns)
        self.assertTrue(Path(BOCHTEN_LIJNEN_PAD).exists())
        self.assertTrue(Path(BOCHTEN_VERBINDINGEN_PAD).exists())

    # =========================================================================
    # CEL 21 — Inspectigence (2023 + 2025) koppelen
    # =========================================================================
    def test_14_inspectigence_koppelen(self):
        """Cel 21: 2023 en 2025-inspecties nearest-matchen + QC-lagen wegschrijven."""
        cls = type(self)
        df = cls.df

        PAD_2023 = "Input/Wegmarkeringen/Inspectigence-2023/csv/Inspectigence_Part04_2023.csv"
        PAD_2025 = "Input/Wegmarkeringen/Inspectigence-2025/csv/Inspectigence_Part04_2025.csv"
        KAARTLAGEN_DIR = Path("Output/Kaartlagen")
        KAARTLAGEN_DIR.mkdir(parents=True, exist_ok=True)
        INSPECTIES_PUNTEN_PAD       = str(KAARTLAGEN_DIR / "Kwaliteitscontrole_inspecties_punten.gpkg")
        INSPECTIES_VERBINDINGEN_PAD = str(KAARTLAGEN_DIR / "Kwaliteitscontrole_inspecties_verbindingen.gpkg")
        HECTOPUNTEN_PAD             = str(KAARTLAGEN_DIR / "Kwaliteitscontrole_hectopunten_punten.gpkg")

        transformer_to_rd = Transformer.from_crs('EPSG:4326', 'EPSG:28992', always_xy=True)

        def lees_inspectigence(pad):
            ins = pd.read_csv(pad)
            ins = ins.rename(columns={'Health_Score': 'health',
                                      'Visibility_Score': 'visibility'})
            ins = ins.drop_duplicates(subset=['KeyID'], keep='first').reset_index(drop=True)
            return ins[['KeyID', 'Geometry', 'health', 'visibility', 'BENAMING']]

        def parse_geom(g):
            return g if isinstance(g, BaseGeometry) else wkt.loads(g)

        def naar_rd(geom):
            return shapely_transform(transformer_to_rd.transform, geom)

        def linestring_midpunt(geom_rd):
            return geom_rd.interpolate(0.5, normalized=True)

        def parse_hectopunt_rd(geom):
            pt = geom.geoms[0] if hasattr(geom, 'geoms') else geom
            return pt.x, pt.y

        def sorteer_csv(s, ascending=True):
            if pd.isna(s):
                return s
            vals = sorted((float(v.strip()) for v in str(s).split(',') if v.strip()),
                          reverse=not ascending)
            return ', '.join(f'{v}' for v in vals)

        def eerste_waarde(s, default):
            return float(str(s).split(',')[0]) if pd.notna(s) else default

        def koppel_inspectigence(df, ins, jaar, hecto_xy, tree):
            ins = ins.copy()
            ins['Geometry'] = ins['Geometry'].apply(parse_geom).apply(naar_rd)
            midpunten = ins['Geometry'].apply(linestring_midpunt).tolist()
            ins_xy    = np.array([(p.x, p.y) for p in midpunten])

            _, indices = tree.query(ins_xy, k=1)
            matched_hecto_xy = hecto_xy[indices]

            qc = pd.DataFrame({
                'jaar':        jaar,
                'KeyID':       ins['KeyID'].values,
                'health':      ins['health'].values,
                'visibility':  ins['visibility'].values,
                'BENAMING':    ins['BENAMING'].values,
                '_hecto_idx':  indices,
                'punt':        midpunten,
                'verbinding': [LineString([(ix, iy), (hx, hy)])
                               for (ix, iy), (hx, hy) in zip(ins_xy, matched_hecto_xy)],
            })

            join_asc      = lambda s: ', '.join(f'{v}' for v in sorted(float(x) for x in s.dropna().tolist()))
            join_benaming = lambda s: ' | '.join(sorted(set(s.dropna().astype(str).tolist())))

            grouped = (
                qc.groupby('_hecto_idx', as_index=False)
                  .agg({'health':     join_asc,
                        'visibility': join_asc,
                        'BENAMING':   join_benaming})
            )
            grouped[f'_n_{jaar}'] = qc.groupby('_hecto_idx').size().values
            grouped = grouped.rename(columns={
                'health':     f'health_{jaar}',
                'visibility': f'visibility_{jaar}',
                'BENAMING':   f'_benaming_{jaar}',
            })

            df = df.reset_index(drop=True)
            df['_hecto_idx'] = df.index
            df = df.merge(grouped, on='_hecto_idx', how='left').drop(columns=['_hecto_idx'])
            return df, qc

        def voeg_benaming_aan_info(df):
            df['info'] = df['info'].fillna('').astype(str)
            samen = []
            for ben23, ben25 in zip(df['_benaming_2023'].fillna(''), df['_benaming_2025'].fillna('')):
                delen = [b for b in (ben23, ben25) if b]
                samen.append(' | '.join(sorted(set(' | '.join(delen).split(' | ')))) if delen else '')
            extra = pd.Series(samen, index=df.index)
            df['info'] = np.where(
                extra == '', df['info'],
                np.where(df['info'] == '', extra, df['info'] + ' | ' + extra)
            )
            return df.drop(columns=['_benaming_2023', '_benaming_2025'])

        def diagnose(df, ins, jaar):
            n_h     = len(df)
            n_match = df[f'health_{jaar}'].notna().sum()
            print(f'-- Inspectigence {jaar} ------------------------')
            print(f'  Hectopunten              : {n_h:,}')
            print(f'  Inspectigence-records    : {len(ins):,}')
            print(f'  Hectopunten met match    : {n_match:,} ({n_match/n_h*100:.1f}%)')
            print(f'  Hectopunten zonder match : {n_h - n_match:,} ({(n_h - n_match)/n_h*100:.1f}%)')

        # 0) Schone start
        oud = [c for c in df.columns
               if c.startswith(('ins_', 'ins23_', 'ins25_', 'ins2023_', 'ins2025_'))
               or c in ('health_2023', 'visibility_2023', 'health_2025', 'visibility_2025',
                        'aantal_inspecties', '_benaming_2023', '_benaming_2025',
                        'geometry_2023', 'geometry_2025',
                        'verbindingslijn_2023', 'verbindingslijn_2025')]
        df = df.drop(columns=oud, errors='ignore')

        # 1) KDTree over hectopunten
        hecto_xy = np.array(df['hectopunt_geometry'].apply(parse_hectopunt_rd).tolist())
        tree     = cKDTree(hecto_xy)

        # 1b) Hectopunten-puntenlaag wegschrijven
        _hecto_attr_cols = [c for c in ['wegnr_hmp', 'hectomtrng', 'hecto_lttr',
                                        'Zijde', 'wvk_id', 'distrnaam', 'deklaagsoort']
                            if c in df.columns]
        hectopunten_punten_laag = gpd.GeoDataFrame(
            {**{c: df[c].values for c in _hecto_attr_cols},
             '_hecto_idx': np.arange(len(df))},
            geometry=[Point(x, y) for x, y in hecto_xy],
            crs='EPSG:28992',
        )
        hectopunten_punten_laag.to_file(HECTOPUNTEN_PAD, driver='GPKG')
        _embed_default_style(HECTOPUNTEN_PAD, Path(HECTOPUNTEN_PAD).stem,
                             _qml_point((40, 160, 60), size=4))
        print(f'Hectopunten-puntenlaag : {HECTOPUNTEN_PAD}  '
              f'({len(hectopunten_punten_laag):,} punten)')

        # 2) Inlezen + koppelen
        _hecto_voor = len(df)
        ins_2023 = lees_inspectigence(PAD_2023)
        ins_2025 = lees_inspectigence(PAD_2025)
        print(f'Inspectigence 2023 : {len(ins_2023):,} records')
        print(f'Inspectigence 2025 : {len(ins_2025):,} records')

        df, qc_2023 = koppel_inspectigence(df, ins_2023, jaar=2023, hecto_xy=hecto_xy, tree=tree)
        df, qc_2025 = koppel_inspectigence(df, ins_2025, jaar=2025, hecto_xy=hecto_xy, tree=tree)
        assert len(df) == _hecto_voor, f'Hectopunten omvang VERANDERD! {_hecto_voor} -> {len(df)}'

        # 3) Testcase-kaartlagen wegschrijven
        qc_alle = pd.concat([qc_2023, qc_2025], ignore_index=True)
        inspecties_punten = gpd.GeoDataFrame(
            qc_alle[['jaar', 'KeyID', 'health', 'visibility', 'BENAMING', '_hecto_idx']],
            geometry=qc_alle['punt'].tolist(),
            crs='EPSG:28992',
        )
        inspecties_verbindingen = gpd.GeoDataFrame(
            qc_alle[['jaar', 'KeyID', '_hecto_idx']],
            geometry=qc_alle['verbinding'].tolist(),
            crs='EPSG:28992',
        )
        inspecties_punten.to_file(INSPECTIES_PUNTEN_PAD, driver='GPKG')
        inspecties_verbindingen.to_file(INSPECTIES_VERBINDINGEN_PAD, driver='GPKG')
        _embed_default_style(INSPECTIES_PUNTEN_PAD, Path(INSPECTIES_PUNTEN_PAD).stem,
                             _qml_point((40, 90, 200), size=4))
        _embed_default_style(INSPECTIES_VERBINDINGEN_PAD, Path(INSPECTIES_VERBINDINGEN_PAD).stem,
                             _qml_line((220, 30, 30), width=2))
        print(f'QC-puntenlaag       : {INSPECTIES_PUNTEN_PAD}  ({len(inspecties_punten):,} punten)')
        print(f'QC-verbindingenlaag : {INSPECTIES_VERBINDINGEN_PAD}  ({len(inspecties_verbindingen):,} lijnen)')

        # 4) BENAMING aan info plakken
        df = voeg_benaming_aan_info(df)

        # 5) aantal_inspecties = max over beide jaren
        df['aantal_inspecties'] = df[['_n_2023', '_n_2025']].max(axis=1).astype('Int64')
        df = df.drop(columns=['_n_2023', '_n_2025'])

        # 6) Per cel intern sorteren
        df['draaihoek']  = df['draaihoek'].apply(lambda s: sorteer_csv(s, ascending=False))
        df['boogstraal'] = df['boogstraal'].apply(lambda s: sorteer_csv(s, ascending=True))

        # 7) Kolomvolgorde
        score_cols = ['health_2023', 'visibility_2023', 'health_2025', 'visibility_2025']
        for i, c in enumerate(score_cols):
            df.insert(df.columns.get_loc('boogstraal') + 1 + i, c, df.pop(c))
        df['aantal_inspecties'] = df.pop('aantal_inspecties')

        # 8) Sorteren df: hoogste hoek boven, dan laagste visibility_2025
        df = (df
              .assign(
                  _max_hoek=df['draaihoek'].apply(lambda s: eerste_waarde(s, -np.inf)),
                  _min_vis =df['visibility_2025'].apply(lambda s: eerste_waarde(s,  np.inf)),
              )
              .sort_values(['_max_hoek', '_min_vis'], ascending=[False, True])
              .drop(columns=['_max_hoek', '_min_vis'])
              .reset_index(drop=True))

        df.to_pickle("Output/Data_Analyse-Dataset.pkl")
        df = pd.read_pickle("Output/Data_Analyse-Dataset.pkl")
        cls.df = df
        cls.ins_2023 = ins_2023
        cls.ins_2025 = ins_2025
        cls.INSPECTIES_PUNTEN_PAD       = INSPECTIES_PUNTEN_PAD
        cls.INSPECTIES_VERBINDINGEN_PAD = INSPECTIES_VERBINDINGEN_PAD
        print(f'Wegvakken geladen : {df.shape[0]:,} rijen, {df.shape[1]} kolommen')

        # 9) Diagnose
        print()
        diagnose(df, ins_2023, 2023)
        print()
        diagnose(df, ins_2025, 2025)
        print()
        print(f'Hectopunten voor koppeling : {_hecto_voor:,}')
        print(f'Hectopunten na koppeling   : {len(df):,}')
        print(f'Max inspecties per hecto   : {df["aantal_inspecties"].max()}')
        print(f'Kolommen na koppeling ({len(df.columns)}): {df.columns.tolist()}')

        for k in ('health_2023', 'visibility_2023',
                  'health_2025', 'visibility_2025', 'aantal_inspecties'):
            self.assertIn(k, df.columns)
        self.assertTrue(Path(INSPECTIES_PUNTEN_PAD).exists())
        self.assertTrue(Path(INSPECTIES_VERBINDINGEN_PAD).exists())
        self.assertTrue(Path(HECTOPUNTEN_PAD).exists())

    # =========================================================================
    # CEL 22 — QC-kaartlagen terug-laden en checken
    # =========================================================================
    def test_15_qc_kaartlagen_check(self):
        """Cel 22: de twee QC-lagen weer inlezen en checken dat ze 1-op-1 zijn."""
        cls = type(self)
        qc_punten       = gpd.read_file(cls.INSPECTIES_PUNTEN_PAD,
                                        layer=Path(cls.INSPECTIES_PUNTEN_PAD).stem)
        qc_verbindingen = gpd.read_file(cls.INSPECTIES_VERBINDINGEN_PAD,
                                        layer=Path(cls.INSPECTIES_VERBINDINGEN_PAD).stem)
        print(f'{cls.INSPECTIES_PUNTEN_PAD:50s} -> {len(qc_punten):,} punten,  '
              f'CRS {qc_punten.crs.to_string()}')
        print(f'{cls.INSPECTIES_VERBINDINGEN_PAD:50s} -> {len(qc_verbindingen):,} lijnen, '
              f'CRS {qc_verbindingen.crs.to_string()}')
        self.assertEqual(len(qc_punten), len(qc_verbindingen),
                         'Punt- en verbindingen-laag moeten 1-op-1 zijn')
        print(qc_punten.sample(min(3, len(qc_punten))))
        print(qc_verbindingen.sample(min(3, len(qc_verbindingen))))

    # =========================================================================
    # CEL 22b — QC-kaartlagen bochten terug-laden en checken
    # =========================================================================
    def test_15a_qc_bochten_check(self):
        """De twee bocht-QC-lagen weer inlezen en checken dat ze consistent zijn."""
        cls = type(self)
        qc_bochten      = gpd.read_file(cls.BOCHTEN_LIJNEN_PAD,
                                        layer=Path(cls.BOCHTEN_LIJNEN_PAD).stem)
        qc_verbindingen = gpd.read_file(cls.BOCHTEN_VERBINDINGEN_PAD,
                                        layer=Path(cls.BOCHTEN_VERBINDINGEN_PAD).stem)
        print(f'{cls.BOCHTEN_LIJNEN_PAD:55s} -> {len(qc_bochten):,} bochten, '
              f'CRS {qc_bochten.crs.to_string()}')
        print(f'{cls.BOCHTEN_VERBINDINGEN_PAD:55s} -> {len(qc_verbindingen):,} lijnen, '
              f'CRS {qc_verbindingen.crs.to_string()}')
        # Alle bochten zitten in de lijnenlaag; verbindingen is een subset (alleen gematcht).
        self.assertGreaterEqual(len(qc_bochten), len(qc_verbindingen),
                                'Bochten-laag bevat ALLE bochten, dus ≥ aantal verbindingen.')
        gematcht_in_bochten = int(qc_bochten['gematcht'].sum())
        self.assertEqual(gematcht_in_bochten, len(qc_verbindingen),
                         'Aantal gematchte bochten moet gelijk zijn aan aantal verbindingslijnen.')
        print(qc_bochten.sample(min(3, len(qc_bochten))))
        print(qc_verbindingen.sample(min(3, len(qc_verbindingen))))

    # =========================================================================
    # CEL 24 — Deklagen via range-join
    # =========================================================================
    def test_16_deklagen_koppelen(self):
        """Cel 24: Deklagen-Excel inlezen en via range-join (VAN_hm ≤ hectomtrng ≤ TOT_hm) erbij plakken."""
        cls = type(self)
        df = cls.df
        Duur = cls.Duur

        DEKLAGEN_XLS = Path('Input/Deklagen/Deklagen_M26_NL_Totaal Definitief.xls')

        def lees_deklagen():
            with Duur('Inlezen Deklagenlijst'):
                dek = pd.read_excel(DEKLAGEN_XLS, sheet_name='DeklagenM26Totaal')
            dek = dek.dropna(subset=['VAN', 'TOT']).copy()
            dek['AANLEGDATUM'] = pd.to_datetime(dek['AANLEGDATUM'], format='%d-%m-%Y', errors='coerce')
            dek['wegnr_hmp'] = dek['WEG'].astype(int).apply(lambda n: f'A{n}')
            # VAN/TOT in km; hectomtrng in hectometers — dus ×10.
            dek['VAN_hm'] = (dek['VAN'] * 10).round().astype(int)
            dek['TOT_hm'] = (dek['TOT'] * 10).round().astype(int)
            return dek

        def koppel_deklagen(df, dek):
            kandidaten = df[['wvk_id', 'wegnr_hmp', 'hectomtrng']].merge(
                dek, on='wegnr_hmp', how='inner'
            )
            masker = (
                (kandidaten['hectomtrng'] >= kandidaten['VAN_hm']) &
                (kandidaten['hectomtrng'] <= kandidaten['TOT_hm'])
            )
            matches = kandidaten[masker].drop_duplicates(
                subset=['wvk_id', 'hectomtrng', 'BAAN', 'STROOK', 'VAN', 'TOT', 'AANLEGDATUM']
            )
            return matches.sort_values('AANLEGDATUM')

        def slimme_join(s):
            vals = s.dropna().astype(str).tolist()
            if not vals:
                return None
            unieke = list(dict.fromkeys(vals))
            if len(unieke) == 1:
                return unieke[0]
            if all(v == 'ALL' for v in unieke):
                return 'ALL'
            return ', '.join(unieke)

        def aggregeer_per_hectopunt(matches):
            return (
                matches
                .groupby(['wvk_id', 'hectomtrng'], as_index=False)
                .agg(
                    deklaagsoort=('DEKLAAGSOORT', slimme_join),
                    aanlegdatum=('AANLEGDATUM', lambda s: ', '.join(
                        s.dt.strftime('%Y-%m-%d').dropna().unique())),
                    strook=('STROOK', slimme_join),
                    aantal_deklagen=('DEKLAAGSOORT', 'size'),
                )
            )

        def diagnose(df, dek, matches):
            n_h      = len(df)
            n_match  = df['deklaagsoort'].notna().sum()
            wegen_in_dek = set(dek['wegnr_hmp'])
            wegen_in_df  = set(df['wegnr_hmp'].dropna())
            ontbreekt    = wegen_in_df - wegen_in_dek

            print(f'── Deklagen ─────────────────────────────────')
            print(f'  Hectopunten              : {n_h:,}')
            print(f'  Deklagen-records         : {len(dek):,}')
            print(f'  Range-matches (lang)     : {len(matches):,}')
            print(f'  Hectopunten met deklaag  : {n_match:,} ({n_match/n_h*100:.1f}%)')
            print(f'  Hectopunten zonder       : {n_h - n_match:,} ({(n_h - n_match)/n_h*100:.1f}%)')
            print(f'  Max deklagen / hecto     : {df["aantal_deklagen"].max()}')
            print(f'  Mediaan deklagen / hecto : {df["aantal_deklagen"].median()}')
            print(f'  Wegen in df              : {sorted(wegen_in_df)}')
            print(f'  Wegen in df NIET in dek  : {sorted(ontbreekt) if ontbreekt else "geen"}')

        # 0) Schone start
        df = df.drop(columns=['deklaagsoort', 'aanlegdatum', 'strook', 'aantal_deklagen'],
                     errors='ignore')

        # 1) Inlezen
        _hecto_voor = len(df)
        dek = lees_deklagen()
        print(f'Deklagen-records         : {len(dek):,}')

        # 2) Koppelen + aggregeren
        matches     = koppel_deklagen(df, dek)
        deklagen_hp = aggregeer_per_hectopunt(matches)
        print(f'Range-matches            : {len(matches):,}')
        print(f'Unieke hectopunten match : {len(deklagen_hp):,}')

        # 3) Merge terug op hectopunten
        df = df.merge(deklagen_hp, on=['wvk_id', 'hectomtrng'], how='left')
        assert len(df) == _hecto_voor, f'Hectopunten omvang VERANDERD! {_hecto_voor} -> {len(df)}'

        # 4) Kolomvolgorde
        nieuwe_cols = ['deklaagsoort', 'aanlegdatum', 'strook']
        for i, c in enumerate(nieuwe_cols):
            df.insert(df.columns.get_loc('visibility_2025') + 1 + i, c, df.pop(c))
        df['aantal_deklagen'] = df.pop('aantal_deklagen')

        # 5) Info opschonen
        df['info'] = df['info'].fillna('').astype(str).apply(
            lambda s: ' | '.join(dict.fromkeys(p.strip() for p in s.split('|') if p.strip()))
        )

        # 6) Opslaan + laden
        df.to_pickle("Output/Data_Analyse-Dataset.pkl")
        df = pd.read_pickle("Output/Data_Analyse-Dataset.pkl")
        cls.df = df
        print(f'Wegvakken geladen : {df.shape[0]:,} rijen, {df.shape[1]} kolommen')

        # 7) Diagnose
        print()
        diagnose(df, dek, matches)
        print()
        print(f'Hectopunten voor koppeling : {_hecto_voor:,}')
        print(f'Hectopunten na koppeling   : {len(df):,}')
        print(f'Kolommen na koppeling ({len(df.columns)}): {df.columns.tolist()}')

        for k in ('deklaagsoort', 'aanlegdatum', 'strook', 'aantal_deklagen'):
            self.assertIn(k, df.columns)

    # =========================================================================
    # CEL 35 — Kolommen-overzicht
    # =========================================================================
    def test_17_kolommen_overzicht(self):
        """Cel 35: sluitcheck — de hele kolommenlijst van de eindset."""
        cls = type(self)
        print(cls.df.columns)
        self.assertIn('wvk_id', cls.df.columns)


# ─────────────────────────────────────────────────────────────────────────────
# Eigen runner — zodat de verantwoording uit tearDownClass altijd op het scherm
# komt, ook als er onderweg een test struikelt.
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    loader = unittest.TestLoader()
    # Alfabetische sortering = onze 01..17-volgorde.
    loader.sortTestMethodsUsing = staticmethod(lambda a, b: (a > b) - (a < b))
    suite = loader.loadTestsFromTestCase(TestDataPreparation)
    runner = unittest.TextTestRunner(verbosity=2)
    resultaat = runner.run(suite)

    # Korte verantwoording in 1 oogopslag (komt na de tearDownClass-uitvoer):
    print()
    print('═' * 78)
    print('  Samenvatting unittest-runner')
    print('═' * 78)
    print(f'  Tests uitgevoerd : {resultaat.testsRun}')
    print(f'  Geslaagd         : {resultaat.testsRun - len(resultaat.failures) - len(resultaat.errors) - len(resultaat.skipped)}')
    print(f'  Overgeslagen     : {len(resultaat.skipped)}')
    print(f'  Gefaald          : {len(resultaat.failures)}')
    print(f'  Errors           : {len(resultaat.errors)}')
    print('═' * 78)

    raise SystemExit(0 if resultaat.wasSuccessful() else 1)
