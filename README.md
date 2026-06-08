# Wegmarkeringen — Preventief Toekomstbestendig Onderhoud

Dashboard dat per hectopunt laat zien hoe de wegmarkeringen ervoor staan
(kwaliteit, zichtbaarheid, verkeer, levensduur) en helpt bepalen wáár en
wánneer onderhoud nodig is. Gemaakt voor Rijkswaterstaat.

## Wat zit erin

| Bestand | Doel |
|---|---|
| `main.py` | Het dashboard (Streamlit): interactieve kaart, filters, clustering, asset-detail en onderhoudsrapport. |
| `Data_Preparation.ipynb` | Notebook dat de ruwe bronbestanden inleest en omzet naar één dataset voor het dashboard. |
| `UnitTest.py` | Tests op de data-preparatie. |

## Aan de slag

```bash
pip install -r requirements.txt
streamlit run main.py
```

## Mapstructuur

```
Wegmarkeringen/
├── main.py                       # Streamlit-dashboard
├── Data_Preparation.ipynb        # data-prep notebook
├── UnitTest.py                   # tests op de data-prep
├── requirements.txt              # dependencies
├── README.md
├── LICENSE
├── Input/                        # bronbestanden — NIET in repo, zelf vullen
│   ├── Wegmarkeringen/
│   ├── Bochten/
│   ├── Deklagen/
│   ├── INWEVA/                   # verkeersintensiteit
│   └── Beschrijvende_Plaatsaanduiding_systematiek/
└── Output/                       # resultaten — NIET in repo, wordt gegenereerd
    ├── Kaartlagen/               # QGIS-lagen (.gpkg)
    └── hectopunt_fotos/          # foto's per gemarkeerd hectopunt
```

`Input/` en `Output/` staan als lege mappen in de repo (via `.gitkeep`).
Data en foto's blijven bewust buiten GitHub — te groot, en het is
RWS-data die niet publiek hoort.

## Werkwijze

1. `Data_Preparation.ipynb` draaien → bouwt de dataset in `Output/`.
2. `streamlit run main.py` → dashboard opent in de browser.
3. In het dashboard: filteren, hectopunten markeren en een
   PDF-onderhoudsrapport (alleen de negatieve markeringen) uitdraaien.
