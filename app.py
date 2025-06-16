#  Final working and demoable

import os
import asyncio
from datetime import date, datetime
import pytz
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import streamlit as st
from dotenv import load_dotenv
from openai import AzureOpenAI
import requests
import traceback
import folium
import pdfkit
import tempfile
from pathlib import Path
from streamlit_folium import st_folium

load_dotenv()

# Setup Azure OpenAI client
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version="2024-05-01-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

# Page config
st.set_page_config(page_title="AI Travel Planner", page_icon="✈️", layout="wide")

st.title("✈️ AI Travel Planner")
st.markdown("""
This AI-powered travel planner helps you create personalized travel itineraries using:
- 🗺️ Maps and navigation
- 🌤️ Weather forecasts
- 🏨 Accommodation booking
- 🗕️ Calendar management
""")

# Azure Agent call
def get_ai_response(message):
    try:
        response = client.chat.completions.create(
            model=os.getenv("AZURE_DEPLOYMENT_ID"),
            messages=[
                {"role": "system", "content": "You are an AI travel planning assistant."},
                {"role": "user", "content": message}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error fetching AI response: {str(e)}"

        # Geocode utility using OpenRouteService
def geocode(place):
    try:
        ors_key = os.getenv("ORS_API_KEY")
        geocode_url = "https://api.openrouteservice.org/geocode/search"
        r = requests.get(geocode_url, params={"api_key": ors_key, "text": place})
        r.raise_for_status()
        features = r.json().get('features')
        if not features:
            raise Exception(f"No coordinates found for {place}")
        return features[0]['geometry']['coordinates']  # [lng, lat]
    except Exception as e:
        st.warning(f"Geocoding failed for '{place}': {str(e)}")
        return None


# OpenRouteService Distance & Coordinates
def get_distance_km(source, destination):
    try:
        ors_key = os.getenv("ORS_API_KEY")
        if not ors_key:
            raise ValueError("ORS_API_KEY is missing in environment.")

        def geocode(place):
            geo_url = "https://api.openrouteservice.org/geocode/search"
            params = {"api_key": ors_key, "text": place}
            res = requests.get(geo_url, params=params)
            res.raise_for_status()
            data = res.json()
            if "features" not in data or not data["features"]:
                raise ValueError(f"Geocoding failed for '{place}'")
            return data["features"][0]["geometry"]["coordinates"]

        # Get coordinates
        coord_start = geocode(source)
        coord_end = geocode(destination)

        # Request full route geometry
        directions_url = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
        headers = {"Authorization": ors_key, "Content-Type": "application/json"}
        body = {"coordinates": [coord_start, coord_end]}
        response = requests.post(directions_url, headers=headers, json=body)
        response.raise_for_status()

        route_data = response.json()
        segment = route_data["features"][0]["properties"]["segments"][0]
        distance_km = segment["distance"] / 1000

        # Extract full route polyline coordinates
        route_coords = [[pt[1], pt[0]] for pt in route_data["features"][0]["geometry"]["coordinates"]]

        return distance_km, coord_start, coord_end, route_coords

    except Exception as e:
        st.error(f"❌ Routing error: {e}")
        st.text(traceback.format_exc())
        return None, None, None, None

# Map Route Viewer
def show_route_on_map(start_coords, end_coords, route_coords):
    try:
        m = folium.Map(location=[(start_coords[1] + end_coords[1]) / 2,
                                 (start_coords[0] + end_coords[0]) / 2], zoom_start=6)

        folium.Marker([start_coords[1], start_coords[0]], popup="Start", icon=folium.Icon(color="green")).add_to(m)
        folium.Marker([end_coords[1], end_coords[0]], popup="End", icon=folium.Icon(color="red")).add_to(m)
        folium.PolyLine(route_coords, color="blue", weight=5).add_to(m)

        st.markdown("**🗺️ Route Map:**")
        st_folium(m, width=725)
    except Exception as e:
        st.error("Map error: " + str(e))


# AccuWeather Forecast
def get_weather(city):
    try:
        key = os.getenv("ACCUWEATHER_API_KEY")
        loc_url = f"http://dataservice.accuweather.com/locations/v1/cities/search?apikey={key}&q={city}"
        loc_response = requests.get(loc_url).json()
        if not loc_response:
            return "No weather data found."
        loc_key = loc_response[0]['Key']
        forecast_url = f"http://dataservice.accuweather.com/forecasts/v1/daily/1day/{loc_key}?apikey={key}&metric=true"
        forecast = requests.get(forecast_url).json()
        return forecast['DailyForecasts'][0]['Day']['IconPhrase'] + ", " + str(forecast['DailyForecasts'][0]['Temperature']['Maximum']['Value']) + "°C"
    except Exception as e:
        return f"Weather error: {str(e)}"

# Google Calendar
def add_event_to_calendar(summary, start, end):
    try:
        if isinstance(start, date):
            start = datetime.combine(start, datetime.min.time())
        if isinstance(end, date):
            end = datetime.combine(end, datetime.min.time())

        creds = Credentials(
            None,
            refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET")
        )

        service = build("calendar", "v3", credentials=creds)

        event = {
            "summary": summary,
            "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Kolkata"},
        }

        created_event = service.events().insert(calendarId="primary", body=event).execute()
        return created_event.get("htmlLink", "No link")
    except Exception as e:
        return f"Calendar error: {e}\n{traceback.format_exc()}"

def generate_itinerary_pdf(html_content):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            pdfkit.from_string(html_content, tmp_file.name)
            return tmp_file.name
    except Exception as e:
        st.error(f"❌ PDF generation failed: {e}")
        return None

# UI inputs
col1, col2 = st.columns(2)
with col1:
    source = st.text_input("Source", placeholder="Enter your departure city")
    destination = st.text_input("Destination", placeholder="Enter your destination city")
    travel_dates = st.date_input("Travel Dates", [date.today(), date.today()], min_value=date.today())

with col2:
    budget = st.number_input("Budget (in USD)", min_value=0, max_value=100000, step=100)
    travel_preferences = st.multiselect("Travel Preferences", [
        "Adventure", "Relaxation", "Sightseeing", "Cultural Experiences",
        "Beach", "Mountain", "Luxury", "Budget-Friendly", "Food & Dining",
        "Shopping", "Nightlife", "Family-Friendly"
    ])

st.subheader("Additional Preferences")
col3, col4 = st.columns(2)
with col3:
    accommodation_type = st.selectbox("Preferred Accommodation", ["Any", "Hotel", "Hostel", "Apartment", "Resort"])
    transportation_mode = st.multiselect("Preferred Transportation", ["Train", "Bus", "Flight", "Rental Car"])

with col4:
    dietary_restrictions = st.multiselect("Dietary Restrictions", [
        "None", "Vegetarian", "Vegan", "Gluten-Free", "Halal", "Kosher"
    ])

# Trigger
if st.button("Plan My Trip", type="primary") or st.session_state.get("trip_planned"):
    if not source or not destination:
        st.error("Please enter both source and destination cities.")
    else:
        if "trip_planned" not in st.session_state:
            st.session_state.trip_planned = True
            st.session_state.trip_data = {}

            with st.spinner("🤖 AI Agents are planning your perfect trip..."):
                try:
                    message = f"""
                    Plan a trip with the following details:
                    - From: {source}
                    - To: {destination}
                    - Dates: {travel_dates[0]} to {travel_dates[1]}
                    - Budget in USD: ${budget}
                    - Preferences: {', '.join(travel_preferences)}
                    - Accommodation: {accommodation_type}
                    - Transportation: {', '.join(transportation_mode)}
                    - Dietary Restrictions: {', '.join(dietary_restrictions)}
                    """

                    st.session_state.trip_data["response"] = get_ai_response(message)

                    destination_slug = destination.lower().replace(" ", "-")
                    st.session_state.trip_data["destination_slug"] = destination_slug

                    distance_km, coord_start, coord_end, route_coords = get_distance_km(source, destination)
                    st.session_state.trip_data.update({
                        "distance_km": distance_km,
                        "coord_start": coord_start,
                        "coord_end": coord_end,
                        "route_coords": route_coords,
                    })

                    st.session_state.trip_data["forecast"] = get_weather(destination)
                    st.session_state.trip_data["calendar_link"] = add_event_to_calendar(
                        f"Trip to {destination}", travel_dates[0], travel_dates[1]
                    )

                except Exception as e:
                    st.error(f"An error occurred: {str(e)}")
                    st.text(traceback.format_exc())

        # Render output after planning
if "trip_data" in st.session_state:
    data = st.session_state.trip_data
    if "response" in data:
        st.success("✅ Your travel plan is ready!")
        st.markdown(data["response"])

        st.markdown("**🔗 Helpful Booking Links:**")
        st.markdown(f"[🏨 Airbnb stays in {destination}](https://www.airbnb.com/s/{data['destination_slug']})")
        st.markdown(f"[🛏️ MakeMyTrip deals in {destination}](https://www.makemytrip.com/hotels/{data['destination_slug']}-hotels.html)")
        st.markdown(f"[🚗 RentalCars in {destination}](https://www.rentalcars.com/SearchResults.do?dropCity={data['destination_slug']})")
        st.markdown(f"**Weather in {destination}:** {data['forecast']}")
        st.markdown(f"**Calendar Event:** [View Event]({data['calendar_link']})")

        if data.get("distance_km") is not None:
            st.markdown(f"**Distance:** {round(data['distance_km'], 2)} km")
            show_route_on_map(data["coord_start"], data["coord_end"], data["route_coords"])

        #st.markdown(f"**Weather in {destination}:** {data['forecast']}")
        #st.markdown(f"**Calendar Event:** [View Event]({data['calendar_link']})")

st.markdown("---")
st.markdown("""
<div style='text-align: center'>
    <p>Powered by AI Travel Planning Agents</p>
    <p>Your personal travel assistant for creating memorable experiences</p>
</div>
""", unsafe_allow_html=True)
