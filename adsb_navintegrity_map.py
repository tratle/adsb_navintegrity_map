from pathlib import Path
from typing import Dict, List, Tuple, Deque, Optional, Any
import dash
from dash import html, dcc, dash_table
from dash.dependencies import Input, Output
import folium
import requests
import pandas as pd
from collections import deque, defaultdict
import time
import logging

# Konfigurer logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Konstanter
MAP_WIDTH = '100%'
MAP_HEIGHT = '700'
DEFAULT_ZOOM = 7
UPDATE_INTERVAL_MS = 30 * 1000  # 30 seconds
MAX_TRACE_LENGTH = 60  # Maksimalt antall posisjoner som beholdes for hvert fly
TRACE_WEIGHT = 2
OLD_FLIGHT_CLEANUP_THRESHOLD = 300  # Fjern fly som ikke er sett på 5 minutter (5 * 60 sekunder)
API_TIMEOUT_SECONDS = 10
MAP_HTML_PATH = Path(__file__).resolve().with_name('map.html')

def nic_to_color(nic: Optional[int]) -> str:
    """Mappe NIC-verdien (Navigation Integrity Category) til en farge.
    
    Args:
        nic: Verdi for Navigation Integrity Category (0-11)
        
    Returns:
        Fargestreng for markøren
    """
    if nic is None:
        return 'black'
    if 1 <= nic <= 2:
        return 'darkred'
    elif 3 <= nic <= 4:
        return 'red'
    elif 5 <= nic <= 6:
        return 'orange'
    elif 7 <= nic <= 9:
        return 'green'
    elif 10 <= nic <= 11:
        return 'darkgreen'
    else:
        return 'black'


# Lag en ordbok som mapper stedsnavn til URL-er og sentrumkoordinater
location_labels: Dict[str, str] = {
    'Finnmark (airplanes.live)': 'Finnmark (airplanes.live)',
    'Finnmark (adsb.lol)': 'Finnmark (adsb.lol)',
    'Baltic Sea (airplanes.live)': 'Østersjøen (airplanes.live)',
    'Baltic Sea (adsb.lol)': 'Østersjøen (adsb.lol)',
    'Ankara (airplanes.live)': 'Ankara (airplanes.live)',
    'Ankara (adsb.lol)': 'Ankara (adsb.lol)',
    'Varna (airplanes.live)': 'Varna (airplanes.live)',
    'Varna (adsb.lol)': 'Varna (adsb.lol)',
    'Andøya (airplanes.live)': 'Andøya (airplanes.live)',
    'Andøya (adsb.lol)': 'Andøya (adsb.lol)',
}

# Lag en ordbok som mapper stedsnavn til URL-er og sentrumkoordinater
location_data: Dict[str, Tuple[str, List[float]]] = {
    'Finnmark (airplanes.live)': ("https://api.airplanes.live/v2/point/69.724193/19.039474/250", [69.72, 30.00]),
    'Finnmark (adsb.lol)': ("https://api.adsb.lol/v2/lat/69.724193/lon/19.039474/dist/250", [69.72, 30.00]),
    'Baltic Sea (airplanes.live)': ("https://api.airplanes.live/v2/point/55.546281/18.039474/250", [55.546281, 18.039474]),
    'Baltic Sea (adsb.lol)': ("https://api.adsb.lol/v2/lat/55.546281/lon/18.039474/dist/250", [55.546281, 18.039474]),
    'Ankara (airplanes.live)': ("https://api.airplanes.live/v2/point/39.912781/32.788112/250", [39.912781, 32.788112]),
    'Ankara (adsb.lol)': ("https://api.adsb.lol/v2/lat/39.912781/lon/32.788112/dist/250", [39.912781, 32.788112]),
    'Varna (airplanes.live)': ("https://api.airplanes.live/v2/point/43.214050/27.914733/250", [43.214050, 27.914733]),
    'Varna (adsb.lol)': ("https://api.adsb.lol/v2/lat/43.214050/lon/27.914733/dist/250", [43.214050, 27.914733]),
    'Andøya (airplanes.live)': ("https://api.airplanes.live/v2/point/69.292500/16.144167/250", [69.292500, 16.144167]),
    'Andøya (adsb.lol)': ("https://api.adsb.lol/v2/lat/69.292500/lon/16.144167/dist/250", [69.292500, 16.144167])
    # Legg til andre steder og API-er her...
}

# Lag en Dash-app
app = dash.Dash(__name__)
server = app.server

def get_initial_map_html() -> str:
    """Hent HTML for startkartet, og lag et tomt kart hvis filen ikke finnes."""
    try:
        with MAP_HTML_PATH.open('r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("map.html ble ikke funnet, oppretter et tomt startkart")
        initial_map = folium.Map(location=[60.0, 10.0], zoom_start=DEFAULT_ZOOM)
        return initial_map.get_root().render()

# Definer layouten for appen
app.layout = html.Div([
    dcc.Dropdown(
        id='location-dropdown',
        options=[
            {'label': location_labels.get(location, location), 'value': location}
            for location in location_data.keys()
        ],
        value='Finnmark (airplanes.live)'  # standardverdi
    ),
    html.Iframe(id='map', srcDoc=get_initial_map_html(), width=MAP_WIDTH, height=MAP_HEIGHT),
    dash_table.DataTable(
    id='table',
    columns=[
        {"name": navn, "id": felt}
        for navn, felt in [
            ("Flyvning", "flight"),
            ("NAC P", "nac_p"),
            ("NIC", "nic"),
            ("Breddegrad", "lat"),
            ("Lengdegrad", "lon"),
            ("Høyde", "alt_geom"),
            ("Fart", "gs"),
            ("SIL", "sil"),
        ]
    ],
    data=[],
    sort_action='native',  # aktiver sortering
    sort_by = [{"column_id": "nic", "direction": "asc"}],
    filter_action='native',  # aktiver filtrering
    row_selectable='multi',  # aktiver flervalg av rader
    
    style_data_conditional=[  # stil celler betinget
        {
            'if': {'row_index': 'odd'},
            'backgroundColor': 'rgb(248, 248, 248)'
        },
        {
            'if': {'column_id': 'flight'},
            'backgroundColor': 'rgb(255, 255, 255)',
            'color': 'black'
        }]
    ),
    dcc.Interval(
        id='interval-component',
        interval=UPDATE_INTERVAL_MS,
        n_intervals=0
    )
])
# Initialiser prev_locations som en dictionary med deque-er for trajektorer
prev_locations: Dict[str, Deque[Tuple[List[float], str]]] = defaultdict(lambda: deque(maxlen=MAX_TRACE_LENGTH))
# Spor sist sett-tid for hver flyvning for å kunne rydde opp
last_seen: Dict[str, float] = {}

def fetch_aircraft_data(url: str) -> Optional[Dict[str, Any]]:
    """Hent flydata fra API-et med feilhåndtering.
    
    Args:
        url: URL til API-endepunktet
        
    Returns:
        JSON-svar som ordbok, eller None hvis forespørselen feilet
    """
    try:
        response = requests.get(url, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        logger.error(f"API-forespørselen fikk tidsavbrudd: {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API-forespørsel mislyktes: {e}")
        return None
    except ValueError as e:
        logger.error(f"Klarte ikke å tolke JSON-svaret: {e}")
        return None


def cleanup_old_flights(current_time: float) -> None:
    """Fjern flyvninger som ikke har vært sett nylig for å unngå minnelekkasjer.
    
    Args:
        current_time: Nåværende tidsstempel
    """
    flights_to_remove = [
        flight for flight, last_time in last_seen.items()
        if current_time - last_time > OLD_FLIGHT_CLEANUP_THRESHOLD
    ]
    for flight in flights_to_remove:
        if flight in prev_locations:
            del prev_locations[flight]
        if flight in last_seen:
            del last_seen[flight]
    if flights_to_remove:
        logger.info(f"Ryddet opp {len(flights_to_remove)} gamle flyvninger")


def create_map_with_aircraft(center: List[float], api_response: Dict[str, Any]) -> folium.Map:
    """Lag et folium-kart med markører og trajektorer for fly.
    
    Args:
        center: Koordinater for kartets sentrum [lat, lon]
        api_response: API-svar som inneholder flydata
        
    Returns:
        Folium-kartobjekt
    """
    map_obj = folium.Map(location=center, zoom_start=DEFAULT_ZOOM)
    current_time = time.time()
    current_locations: Dict[str, Tuple[List[float], str]] = {}
    
    # Legg til markører for hvert fly
    for aircraft in api_response.get("ac", []):
        lat = aircraft.get("lat")
        lon = aircraft.get("lon")
        nic = aircraft.get("nic")
        flight = aircraft.get("flight", "").strip()
        
        if lat is None or lon is None or nic is None or not flight:
            continue
            
        color = nic_to_color(nic)
        icon = folium.Icon(icon='plane', color=color, prefix='fa') if flight else None
        
        # Bygg popup-innhold med HTML-link til airplanes.live
        icao = aircraft.get('addr') or aircraft.get('icao') or aircraft.get('hex')
        if icao:
            airplanes_live_url = f"https://globe.airplanes.live/?icao={icao.lower()}"
            popup_html = (
                f"<b>FLYVNING: {flight}</b><br>"
                f"NIC: {nic}<br>"
                f"Høyde(ft): {aircraft.get('alt_geom')}<br>"
                f"Fart(m/s): {aircraft.get('gs')}<br>"
                f"<a href='{airplanes_live_url}' target='_blank'>Se på airplanes.live</a>"
            )
            popup = folium.Popup(popup_html, max_width=300)
        else:
            popup = (
                f"NIC: {nic}, FLYVNING: {flight}, "
                f"Høyde(ft): {aircraft.get('alt_geom')}, "
                f"Fart(m/s): {aircraft.get('gs')}"
            )
        
        # Legg markøren på kartet
        folium.Marker(
            location=[lat, lon],
            icon=icon,
            popup=popup,
            tooltip=flight
        ).add_to(map_obj)
        
        # Oppdater gjeldende posisjon og sist sett-tid
        current_locations[flight] = ([lat, lon], color)
        last_seen[flight] = current_time
        
        # Legg til i posisjonshistorikken
        prev_locations[flight].append(current_locations[flight])
    
    # Tegn trajektorer for alle flyvninger (flyttet ut av løkken for ytelse)
    for flight, locations_colors in prev_locations.items():
        if len(locations_colors) >= 2:
            for i in range(len(locations_colors) - 1):
                folium.PolyLine(
                    [locations_colors[i][0], locations_colors[i + 1][0]],
                    color=locations_colors[i][1],
                    weight=TRACE_WEIGHT
                ).add_to(map_obj)
    
    # Rydd opp gamle flyvninger
    cleanup_old_flights(current_time)
    
    return map_obj


def process_dataframe(api_response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Behandle API-svaret til en ryddet dataframe for tabellen.
    
    Args:
        api_response: API-svar som inneholder flydata
        
    Returns:
        Liste med ordbøker for datatabellen
    """
    df = pd.DataFrame(api_response.get("ac", []))
    
    if df.empty:
        return []
    
    # Erstatt tomme strenger og 'nan' med NaN
    if 'flight' in df.columns:
        df['flight'] = df['flight'].replace(['', 'nan', 'None'], pd.NA)
        # Fjern rader der 'flight' er NaN
        df = df.dropna(subset=['flight'])
    
    if df.empty:
        return []
    
    # Gjør 'flight' om til tekst, og resten til numeriske verdier
    for col in df.columns:
        if col == 'flight':
            df[col] = df[col].astype(str)
        else:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    return df.to_dict('records')


# Definer en callback som oppdaterer kartet
@app.callback(
    [Output('map', 'srcDoc'), Output('table', 'data')],
    [Input('interval-component', 'n_intervals'), Input('location-dropdown', 'value')]
)
def update_map(_n_intervals: int, selected_location: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Oppdater kart og tabell med gjeldende flydata.
    
    Args:
        _n_intervals: Antall intervaller som har gått (ikke brukt)
        selected_location: Valgt sted fra nedtrekksmenyen
        
    Returns:
        Tuple av (HTML-streng for kartet, tabelldata som liste med ordbøker)
    """
    try:
        selected_url, selected_center = location_data[selected_location]
    except KeyError:
        logger.error(f"Ugyldig plassering valgt: {selected_location}")
        return get_initial_map_html(), []
    
    # Hent flydata fra API-et
    api_response = fetch_aircraft_data(selected_url)
    
    if api_response is None:
        # Returner tomt kart og tabell ved API-feil
        error_map = folium.Map(location=selected_center, zoom_start=DEFAULT_ZOOM)
        return error_map.get_root().render(), []
    
    # Lag kart med markører og spor for fly
    map_obj = create_map_with_aircraft(selected_center, api_response)
    
    # Behandle data for tabellen
    table_data = process_dataframe(api_response)
    
    # Gjengi kartet som HTML-streng
    html_string = map_obj.get_root().render()
    
    return html_string, table_data

if __name__ == '__main__':
    app.run(debug=False, host='127.0.0.1', port=8050) 
