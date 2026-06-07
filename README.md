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
pip install streamlit pandas numpy scikit-learn matplotlib ruptures \
            pyarrow shapely geopandas scipy contextily openpyxl
streamlit run main.py
```

## Mappen

- `Input/` — bronbestanden (wegmarkeringen, bochten, deklagen, verkeer). **Niet** in de repo; zet je eigen data hier neer.
- `Output/` — gegenereerde resultaten (datasets, QGIS-lagen, foto's, PDF-rapport). Ook niet in de repo.

De mapstructuur staat er wel (lege mappen via `.gitkeep`); data en foto's
blijven bewust buiten GitHub vanwege de bestandsgrootte.

## Werkwijze

1. `Data_Preparation.ipynb` draaien → bouwt de dataset in `Output/`.
2. `streamlit run main.py` → dashboard opent in de browser.
3. In het dashboard: filteren, hectopunten markeren en een
   PDF-onderhoudsrapport (alleen de negatieve markeringen) uitdraaien.
