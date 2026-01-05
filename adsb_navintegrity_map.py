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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
MAP_WIDTH = '100%'
MAP_HEIGHT = '700'
DEFAULT_ZOOM = 6
UPDATE_INTERVAL_MS = 30 * 1000  # 30 seconds
MAX_TRACE_LENGTH = 60  # Maximum number of positions to keep for each aircraft
TRACE_WEIGHT = 2
OLD_FLIGHT_CLEANUP_THRESHOLD = 300  # Remove flights not seen in 5 minutes (5 * 60 seconds)
API_TIMEOUT_SECONDS = 10

def nic_to_color(nic: Optional[int]) -> str:
    """Map NIC (Navigation Integrity Category) value to a color.
    
    Args:
        nic: Navigation Integrity Category value (0-11)
        
    Returns:
        Color string for the marker
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


# Create a dictionary that maps location names to URLs and center coordinates
location_data: Dict[str, Tuple[str, List[float]]] = {
    'Finnmark (adsb.one)': ("https://api.adsb.one/v2/point/69.724193/19.039474/250", [69.724193, 19.039474]),
    'Finnmark (adsb.lol)': ("https://api.adsb.lol/v2/lat/69.724193/lon/19.039474/dist/250", [69.724193, 19.039474]),
    'Baltic Sea (adsb.one)': ("https://api.adsb.one/v2/point/55.546281/18.039474/150", [55.546281, 18.039474]),
    'Baltic Sea (adsb.lol)': ("https://api.adsb.lol/v2/lat/55.546281/lon/18.039474/dist/150", [55.546281, 18.039474]),
    'Ankara (adsb.one)': ("https://api.adsb.one/v2/point/39.912781/32.788112/250", [39.912781, 32.788112]),
    'Ankara (adsb.lol)': ("https://api.adsb.lol/v2/lat/39.912781/lon/32.788112/dist/250", [39.912781, 32.788112])
    # Add other locations and APIs here...
}

# Create a Dash app
app = dash.Dash(__name__)
server = app.server

def get_initial_map_html() -> str:
    """Get initial map HTML, creating a blank map if file doesn't exist."""
    try:
        with open('map.html', 'r') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("map.html not found, creating initial blank map")
        initial_map = folium.Map(location=[60.0, 10.0], zoom_start=DEFAULT_ZOOM)
        return initial_map.get_root().render()

# Define the layout of the app
app.layout = html.Div([
    dcc.Dropdown(
        id='location-dropdown',
        options=[
            {'label': location, 'value': location} for location in location_data.keys()
        ],
        value='Finnmark (adsb.one)'  # default value
    ),
    html.Iframe(id='map', srcDoc=get_initial_map_html(), width=MAP_WIDTH, height=MAP_HEIGHT),
    dash_table.DataTable(
    id='table',
    columns=[{"name": i, "id": i} for i in ["flight", "nic", "lat", "lon", "alt_geom", "gs", "sil"]],
    data=[],
    sort_action='native',  # enable sorting
    sort_by = [{"column_id": "nic", "direction": "asc"}],
    filter_action='native',  # enable filtering
    row_selectable='multi',  # enable multiple row selection
    
    style_data_conditional=[  # style cells conditionally
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
# Initialize prev_locations as a dictionary of deques with aircraft traces
prev_locations: Dict[str, Deque[Tuple[List[float], str]]] = defaultdict(lambda: deque(maxlen=MAX_TRACE_LENGTH))
# Track last seen time for each flight to enable cleanup
last_seen: Dict[str, float] = {}

def fetch_aircraft_data(url: str) -> Optional[Dict[str, Any]]:
    """Fetch aircraft data from API with error handling.
    
    Args:
        url: API endpoint URL
        
    Returns:
        JSON response as dictionary, or None if request failed
    """
    try:
        response = requests.get(url, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        logger.error(f"API request timed out: {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        return None


def cleanup_old_flights(current_time: float) -> None:
    """Remove flights that haven't been seen recently to prevent memory leaks.
    
    Args:
        current_time: Current timestamp
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
        logger.info(f"Cleaned up {len(flights_to_remove)} old flights")


def create_map_with_aircraft(center: List[float], api_response: Dict[str, Any]) -> folium.Map:
    """Create a folium map with aircraft markers and traces.
    
    Args:
        center: Map center coordinates [lat, lon]
        api_response: API response containing aircraft data
        
    Returns:
        Folium map object
    """
    map_obj = folium.Map(location=center, zoom_start=DEFAULT_ZOOM)
    current_time = time.time()
    current_locations: Dict[str, Tuple[List[float], str]] = {}
    
    # Add markers for each aircraft
    for aircraft in api_response.get("ac", []):
        lat = aircraft.get("lat")
        lon = aircraft.get("lon")
        nic = aircraft.get("nic")
        flight = aircraft.get("flight", "").strip()
        
        if lat is None or lon is None or nic is None or not flight:
            continue
            
        color = nic_to_color(nic)
        icon = folium.Icon(icon='plane', color=color, prefix='fa') if flight else None
        
        # Add marker to the map
        folium.Marker(
            location=[lat, lon],
            icon=icon,
            popup=(
                f"NIC: {nic}, FLIGHT: {flight}, "
                f"Altitude(ft): {aircraft.get('alt_geom')}, "
                f"Speed(m/s): {aircraft.get('gs')}"
            ),
            tooltip=flight
        ).add_to(map_obj)
        
        # Update current location and last seen time
        current_locations[flight] = ([lat, lon], color)
        last_seen[flight] = current_time
        
        # Add to position history
        prev_locations[flight].append(current_locations[flight])
    
    # Draw traces for all flights (moved outside aircraft loop for efficiency)
    for flight, locations_colors in prev_locations.items():
        if len(locations_colors) >= 2:
            for i in range(len(locations_colors) - 1):
                folium.PolyLine(
                    [locations_colors[i][0], locations_colors[i + 1][0]],
                    color=locations_colors[i][1],
                    weight=TRACE_WEIGHT
                ).add_to(map_obj)
    
    # Cleanup old flights
    cleanup_old_flights(current_time)
    
    return map_obj


def process_dataframe(api_response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Process API response into a cleaned dataframe for the table.
    
    Args:
        api_response: API response containing aircraft data
        
    Returns:
        List of dictionaries for the data table
    """
    df = pd.DataFrame(api_response.get("ac", []))
    
    if df.empty:
        return []
    
    # Replace empty strings and 'nan' with NaN
    if 'flight' in df.columns:
        df['flight'] = df['flight'].replace(['', 'nan', 'None'], pd.NA)
        # Drop rows where 'flight' is NaN
        df = df.dropna(subset=['flight'])
    
    if df.empty:
        return []
    
    # Convert 'flight' to string, all else to numeric
    for col in df.columns:
        if col == 'flight':
            df[col] = df[col].astype(str)
        else:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    return df.to_dict('records')


# Define a callback that updates the map
@app.callback(
    [Output('map', 'srcDoc'), Output('table', 'data')],
    [Input('interval-component', 'n_intervals'), Input('location-dropdown', 'value')]
)
def update_map(_n_intervals: int, selected_location: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Update map and table with current aircraft data.
    
    Args:
        _n_intervals: Number of intervals elapsed (unused)
        selected_location: Selected location from dropdown
        
    Returns:
        Tuple of (map HTML string, table data as list of dicts)
    """
    try:
        selected_url, selected_center = location_data[selected_location]
    except KeyError:
        logger.error(f"Invalid location selected: {selected_location}")
        return get_initial_map_html(), []
    
    # Fetch aircraft data from API
    api_response = fetch_aircraft_data(selected_url)
    
    if api_response is None:
        # Return empty map and table on API failure
        error_map = folium.Map(location=selected_center, zoom_start=DEFAULT_ZOOM)
        return error_map.get_root().render(), []
    
    # Create map with aircraft markers and traces
    map_obj = create_map_with_aircraft(selected_center, api_response)
    
    # Process data for table
    table_data = process_dataframe(api_response)
    
    # Render map to HTML string
    html_string = map_obj.get_root().render()
    
    return html_string, table_data

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8050) 
