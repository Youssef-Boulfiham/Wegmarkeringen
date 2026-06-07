import re
from pyproj import Transformer
import pandas as pd
import time
from IPython.display import display, clear_output
import ipywidgets as widgets
import threading


class Timer:
    """
    Context manager voor het tonen van een timer tijdens langdurige operaties.
    
    Gebruik:
    --------
    with Timer("Bezig met laden van data"):
        # je code hier
        data = gpd.read_file(...)
    """
    
    def __init__(self, message="Bezig"):
        self.message = message
        self.start_time = None
        self.output = None
        self.stop_timer = None
        self.timer_thread = None
    
    def __enter__(self):
        # Create output widget voor live updates
        self.output = widgets.Output()
        display(self.output)
        
        # Start timer
        self.start_time = time.time()
        
        # Background timer
        self.stop_timer = threading.Event()
        
        def timer_loop():
            while not self.stop_timer.is_set():
                elapsed = int(time.time() - self.start_time)
                with self.output:
                    clear_output(wait=True)
                    print(f"{self.message}... {elapsed} seconden")
                time.sleep(1)
        
        self.timer_thread = threading.Thread(target=timer_loop)
        self.timer_thread.start()
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Stop de timer
        self.stop_timer.set()
        self.timer_thread.join()
        
        # Toon eindresultaat
        elapsed = int(time.time() - self.start_time)
        with self.output:
            clear_output(wait=True)
            if exc_type is None:
                print(f"✓ Klaar in {elapsed} seconden")
            else:
                print(f"✗ Fout na {elapsed} seconden")


# Nieuwe functies voor eenvoudig gebruik vanuit andere bestanden
def bereken_duur(func):
    """
    Decorator die de duur van een functie meet en print.
    
    Voorbeeld in ander bestand:
    @bereken_duur
    def mijn_functie():
        time.sleep(2)
    """
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = int(time.time() - start)
        print(f"✓ {func.__name__} duurde {elapsed} seconden")
        return result
    return wrapper


def met_timer(bericht="Uitvoeren"):
    """
    Context manager die alleen de totale duur toont zonder threading.
    
    Voorbeeld in ander bestand:
    with met_timer("Data laden"):
        data = load_data()
    """
    class SimpleTimer:
        def __init__(self, message):
            self.message = message
            self.start_time = None
        
        def __enter__(self):
            print(f"{self.message}...")
            self.start_time = time.time()
            return self
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            elapsed = int(time.time() - self.start_time)
            if exc_type is None:
                print(f"✓ {self.message} klaar in {elapsed} seconden")
            else:
                print(f"✗ {self.message} mislukt na {elapsed} seconden")
    
    return SimpleTimer(bericht)


def toon_duur(func, *args, **kwargs):
    """
    Voert een functie uit en print de duur.
    
    Voorbeeld in ander bestand:
    resultaat = toon_duur(mijn_functie, arg1, arg2)
    """
    start = time.time()
    result = func(*args, **kwargs)
    elapsed = int(time.time() - start)
    print(f"✓ Duur: {elapsed} seconden")
    return result


class Duur:
    """Simpele timer die alleen eindduur toont."""
    
    def __init__(self, naam=""):
        self.naam = naam
        self.start = None
        
    def __enter__(self):
        self.start = time.time()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        duur = int(time.time() - self.start)
        if self.naam:
            print(f"{self.naam} duurde {duur} seconden")
        else:
            print(f"Duur: {duur} seconden")

def meet_duur(func, *args, **kwargs):
    """Voert functie uit en toont duur."""
    start = time.time()
    result = func(*args, **kwargs)
    print(f"{func.__name__} duurde {int(time.time() - start)} seconden")
    return result


# ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
#   waarbij origineel met linestring benaming is
# DEZE IS OM EEN ENKELE KOLOMWAARDE VAN geometry om te zetten naar latitude, longtitude
# werkt zowel met enkele als meerdere

def convert_wkt_string_to_gps(wkt_string):
    """
    Input: Een WKT string (bijv. 'LINESTRING (135587... 452281...)')
    Output: Een string "lat, lon" (bij 1 punt) OF een lijst ["lat, lon", ...] (bij meer)
    """
    
    # 1. Gebruik Regex om alle getallenparen te vinden
    # Dit zoekt naar patronen van "Getal[spatie]Getal" en negeert tekst als "LINESTRING" of "(...)"
    raw_coords = re.findall(r"([0-9]+\.?[0-9]*)\s+([0-9]+\.?[0-9]*)", str(wkt_string))
    
    output_list = []
    
    # 2. Loop door alle gevonden paren heen
    for x_str, y_str in raw_coords:
        x = float(x_str)
        y = float(y_str)
        
        # 3. Transformeer X, Y (RD) naar Lat, Lon (GPS)
        lat, lon = transformer.transform(x, y)
        
        # Voeg toe als string "lat, lon"
        output_list.append(f"{lat}, {lon}")
    
    # 4. Retourneer logica: eentje als string, meerdere als lijst
    if len(output_list) == 1:
        return output_list[0]
    elif len(output_list) > 1:
        return output_list
    else:
        return None # Geen coördinaten gevonden

# # === VOORBEELD GEBRUIK ===

# # 1. Definieer welk rijnummer en kolomnummer je wilt
# rij_idx = 0       # De eerste rij
# kolom_idx = 8     # De 6e kolom (bijv. waar je WKT string staat)

# # 2. Haal de string op met .iat (integer access)
# # .iat[rij, kolom] is heel strikt en snel voor enkele waardes
# ruwe_wkt_string = df.iat[rij_idx, kolom_idx]

# # Even checken wat we eruit hebben gehaald (debug print)
# print(f"Input string: {ruwe_wkt_string}") 

# # 3. Gooi de string in de functie
# resultaat = convert_wkt_string_to_gps(ruwe_wkt_string)

# # 4. Print het resultaat
# print("\nOutput:")
# if isinstance(resultaat, list):
#     for punt in resultaat:
#         print(punt)
# else:
#     print(resultaat)

# VERSIE 2:

def convert_coords_to_gps(coord_string):
    # 1. Zet de string om naar een lijst met floats (split op komma)
    vals = [float(x) for x in coord_string.split(',')]

    # 2. Loop door de paren heen en transformeer
    # vals[::2] pakt alle X-waardes, vals[1::2] pakt alle Y-waardes
    return [
        f"{lat}, {lon}"
        for lat, lon in (transformer.transform(x, y) for x, y in zip(vals[::2], vals[1::2]))
    ]


# ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
# DEZE OM EEN HELE KOLOM  GEOMETRY OM TE ZETTEN NAAR LAT, LON



# Initialiseer transformator (RD -> GPS)
transformer = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=False)

def batch_transform_geometry_to_gps_string(geometry_series):
    def transform_single_wkt(wkt_value):
        if not wkt_value:
            return ""
        
        # Extractie van X Y paren uit de string
        coords = re.findall(r"([0-9]+\.?[0-9]*)\s+([0-9]+\.?[0-9]*)", str(wkt_value))
        
        results = []
        for x_str, y_str in coords:
            lat, lon = transformer.transform(float(x_str), float(y_str))
            # Afronden op 6 decimalen voor leesbaarheid (optioneel)
            results.append(f"{lat:.6f}, {lon:.6f}")
        
        return ", ".join(results)

    return geometry_series.apply(transform_single_wkt)
# # === VOORBEELD GEBRUIK ===

# df['gps_coords'] = batch_transform_geometry_to_gps_string(df.iloc[:, 8])

# df.head(1)
