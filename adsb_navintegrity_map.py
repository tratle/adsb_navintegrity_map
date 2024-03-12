import dash
from dash import html
from dash import dcc
from dash import dash_table
from dash.dependencies import Input, Output
import folium
import requests
import webbrowser
from threading import Timer
import pandas as pd
from collections import deque, defaultdict

# Define a function that maps a "nic" value to a color
def nic_to_color(nic):
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
        return 'black'  # default color


# Create a dictionary that maps location names to URLs and center coordinates
location_data = {
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

# Define the layout of the app
app.layout = html.Div([
    dcc.Dropdown(
        id='location-dropdown',
        options=[
            {'label': location, 'value': location} for location in location_data.keys()
            
        ],
        value='Finnmark (adsb.one)' # default value
    ),
    html.Iframe(id='map', srcDoc=open('map.html', 'r').read(), width='100%', height='700'),
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
        interval=60*1000,  # in milliseconds
        n_intervals=0
    )
])
# Initialize prev_locations as a dictionary of deques
prev_locations = defaultdict(lambda: deque(maxlen=60))

# Define a callback that updates the map
@app.callback(
    [Output('map', 'srcDoc'), Output('table', 'data')],
    [Input('interval-component', 'n_intervals'), Input('location-dropdown', 'value')]
)
def update_map(n, selected_location):
    selected_url, selected_center = location_data[selected_location]
    # Create a folium map
   
    m_2 = folium.Map(location=selected_center, zoom_start=6)
    
    # Make a request to the API
    api_result = requests.get(selected_url)
        
    api_response = api_result.json()

    current_locations = {}

    # Add a marker to the map for each aircraft
    for aircraft in api_response.get("ac", []):
        lat = aircraft.get("lat")
        lon = aircraft.get("lon")
        nic = aircraft.get("nic")
        flight = aircraft.get("flight")
        if lat is not None and lon is not None and nic is not None and flight is not None:
            # Map the "nic" value to a color
            color = nic_to_color(nic)

            # If the flight name is 'nan', set the icon to None
            if flight == '':
                icon = None
            else:
                icon = folium.Icon(icon='plane', color=color, prefix='fa')
            
            

            # Add a marker to the map
            folium.Marker(
                location=[lat, lon],
                icon=icon,
                popup=(f"NIC: {nic}, FLIGHT: {flight}, Altitude(ft): {aircraft.get('alt_geom')}, Speed(m/s): {aircraft.get('gs')}"),
                tooltip=flight
            ).add_to(m_2)

            # Update the dictionary with the current location and color of the aircraft
            current_locations[aircraft.get('flight')] = ([lat, lon], color)

            # Get the previous locations and colors of the aircraft
            prev_locations_colors = prev_locations[aircraft.get('flight')]  # This will automatically create a new deque if the flight is not found
            # If the flight is in the current_locations dictionary, append the current location and color to the list
            if flight in current_locations:
                prev_locations_colors.append(current_locations[flight])
           
                        
            # Update the prev_locations dictionary
            prev_locations[aircraft.get('flight')] = prev_locations_colors
        
        # Draw the traces for all flights in the prev_locations dictionary
        for flight, locations_colors in prev_locations.items():
            if len(locations_colors) >= 2:
                for i in range(len(locations_colors) - 1):
                    folium.PolyLine([locations_colors[i][0], locations_colors[i + 1][0]], color=locations_colors[i][1], weight=2).add_to(m_2)

            

           
    # Create a DataFrame from the API response
    df = pd.DataFrame(api_response.get("ac", []))
    
    # Replace empty strings and 'nan' with NaN
    df['flight'] = df['flight'].replace(['', 'nan', 'None'], pd.NA)
    
    # Drop rows where 'flight' is NaN
    df = df.dropna(subset=['flight'])
    
    # Convert 'flight' to string, all else float
    df = df.apply(lambda col: col.astype(str) if col.name == 'flight' else pd.to_numeric(col, errors='coerce'))
    
    # Save the map to an HTML string
    html_string = m_2.get_root().render()

    return html_string, df.to_dict('records')

if __name__ == '__main__':
    # Open a web browser window to the Dash app
    app.run(debug=True) 