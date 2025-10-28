import requests
import logging
from flask import current_app

def get_city_from_coords(lat, lng):
    """
    Get city name from latitude and longitude using OpenStreetMap Nominatim API
    """
    try:
        if not lat or not lng:
            return "Location not available"
        
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}&zoom=10"
        headers = {
            'User-Agent': 'AttendancePro System/1.0 (contact@company.com)'
        }
        
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            address = data.get('address', {})
            
            city = address.get('city') or address.get('town') or address.get('village') or address.get('county')
            state = address.get('state')
            country = address.get('country')
            
            location_parts = []
            if city:
                location_parts.append(city)
            if state:
                location_parts.append(state)
            if country:
                location_parts.append(country)
            
            return ", ".join(location_parts) if location_parts else "Unknown location"
        else:
            return f"Lat: {lat}, Lng: {lng}"
    except Exception as e:
        logging.error(f"Geocoding error: {str(e)}")
        return f"Lat: {lat}, Lng: {lng}"

def get_location_details(lat, lng):
    """
    Get detailed location information including city, state, country
    """
    try:
        if not lat or not lng:
            return {"city": "Unknown", "state": "Unknown", "country": "Unknown"}
        
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}&zoom=10"
        headers = {
            'User-Agent': 'AttendancePro System/1.0 (contact@company.com)'
        }
        
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            address = data.get('address', {})
            
            return {
                "city": address.get('city') or address.get('town') or address.get('village') or address.get('county') or "Unknown",
                "state": address.get('state') or "Unknown",
                "country": address.get('country') or "Unknown"
            }
        else:
            return {"city": "Unknown", "state": "Unknown", "country": "Unknown"}
    except Exception as e:
        logging.error(f"Detailed geocoding error: {str(e)}")
        return {"city": "Unknown", "state": "Unknown", "country": "Unknown"}