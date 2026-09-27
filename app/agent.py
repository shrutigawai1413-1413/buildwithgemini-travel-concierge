# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import os
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from dotenv import load_dotenv
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors.agent_engine_sandbox_code_executor import AgentEngineSandboxCodeExecutor
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from .a2ui_utils import a2ui_callback

load_dotenv()


async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None


# Hardcode GCP Project ID and Bucket Name for Agent Platform compatibility
FIRESTORE_PROJECT = "qwiklabs-gcp-02-b9b8cd363ddd"
BUCKET_NAME = "travel-concierge-media-qwiklabs-gcp-02-b9b8cd363ddd"

# Initialize AgentEngineSandboxCodeExecutor from deployment_metadata.json if present
code_executor = None
deployment_metadata_path = os.path.join(
    os.path.dirname(__file__), "..", "deployment_metadata.json"
)
if os.path.exists(deployment_metadata_path):
    try:
        with open(deployment_metadata_path, "r") as f:
            meta = json.load(f)
        remote_agent_runtime_id = meta.get("remote_agent_runtime_id")
        sandbox_resource_name = meta.get("sandbox_resource_name")
        if sandbox_resource_name or remote_agent_runtime_id:
            code_executor = AgentEngineSandboxCodeExecutor(
                sandbox_resource_name=sandbox_resource_name,
                agent_engine_resource_name=remote_agent_runtime_id,
            )
    except Exception as e:
        print(f"Warning: Failed to load AgentEngineSandboxCodeExecutor: {e}")


def get_firestore_client() -> firestore.Client:
    return firestore.Client(project=FIRESTORE_PROJECT)


def search_destinations(country: str = "", category: str = "") -> list[dict]:
    """Search for travel destinations in the Firestore database filtered by country or category.

    Args:
        country: Optional country name to filter by (e.g., 'Japan', 'France').
        category: Optional travel category to filter by (e.g., 'Culture & Nature', 'Food & Romance').

    Returns:
        A list of destination dictionaries.
    """
    db = get_firestore_client()
    collection_ref = db.collection("destinations")
    results = []

    for doc in collection_ref.stream():
        data = doc.to_dict()
        data["id"] = doc.id
        match = True
        if country and country.lower() not in data.get("country", "").lower():
            match = False
        if category and category.lower() not in data.get("category", "").lower():
            match = False
        if match:
            results.append(data)

    return results


def get_destination_details(destination_id: str) -> dict:
    """Retrieve detailed information about a specific travel destination from Firestore by its ID.

    Args:
        destination_id: The ID/slug of the destination (e.g., 'tokyo', 'kyoto', 'paris', 'rome', 'bali').

    Returns:
        A dictionary with destination details or an error message if not found.
    """
    db = get_firestore_client()
    doc_ref = db.collection("destinations").document(destination_id.lower())
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        data["id"] = doc.id
        return data
    return {"error": f"Destination '{destination_id}' not found."}


def add_destination(
    destination_id: str,
    name: str,
    country: str,
    category: str,
    description: str,
    rating: float = 4.5,
) -> dict:
    """Add a new travel destination or update an existing one in Firestore.

    Args:
        destination_id: Unique identifier for the destination (e.g., 'new_york').
        name: Name of the destination city or spot (e.g., 'New York').
        country: Country where the destination is located (e.g., 'USA').
        category: Travel category (e.g., 'Urban Exploration').
        description: A brief summary or highlight of the destination.
        rating: Rating out of 5.0 (e.g., 4.7).

    Returns:
        A confirmation dictionary with the saved destination details.
    """
    db = get_firestore_client()
    doc_ref = db.collection("destinations").document(destination_id.lower())
    data = {
        "name": name,
        "country": country,
        "category": category,
        "description": description,
        "rating": float(rating),
    }
    doc_ref.set(data)
    data["id"] = doc_ref.id
    return {"status": "success", "destination": data}


def fetch_destination_info(location_name: str) -> dict:
    """Fetches real-world encyclopedia summary, description, and thumbnail image for a travel spot or landmark.

    Args:
        location_name: Name of the city, landmark, or attraction (e.g. 'Kyoto', 'Eiffel Tower', 'Colosseum', 'Bali').

    Returns:
        A dictionary containing the location title, description, summary, and thumbnail photo URL.
    """
    api_key = os.getenv("WIKIPEDIA_API_KEY", "")
    user_agent = os.getenv("WIKIPEDIA_USER_AGENT", "NovaSmartTravelConcierge/1.0")
    formatted_title = urllib.parse.quote(location_name.replace(" ", "_").strip())
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{formatted_title}"

    headers = {"User-Agent": user_agent}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
        return {
            "status": "success",
            "title": data.get("title", location_name),
            "description": data.get("description", ""),
            "extract": data.get("extract", ""),
            "thumbnail_url": data.get("thumbnail", {}).get("source", ""),
            "content_url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
        }
    except Exception as e:
        return {"error": f"Failed to fetch real-world info for '{location_name}': {str(e)}"}


def convert_currency(
    amount: float, from_currency: str = "USD", to_currency: str = "EUR"
) -> dict:
    """Converts a budget or price amount from one currency to another using live exchange rates.

    Args:
        amount: The numerical amount to convert (e.g. 150.0).
        from_currency: 3-letter currency code to convert from (default 'USD').
        to_currency: 3-letter currency code to convert to (e.g. 'JPY', 'EUR', 'GBP').

    Returns:
        A dictionary containing conversion results and exchange rate.
    """
    from_curr = from_currency.upper().strip()
    to_curr = to_currency.upper().strip()
    try:
        url = f"https://open.er-api.com/v6/latest/{from_curr}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
        rates = data.get("rates", {})
        if to_curr in rates:
            rate = rates[to_curr]
            converted = round(amount * rate, 2)
            return {
                "status": "success",
                "original_amount": amount,
                "from_currency": from_curr,
                "converted_amount": converted,
                "to_currency": to_curr,
                "exchange_rate": rate,
            }
        return {"error": f"Currency code '{to_curr}' not found in exchange rate response."}
    except Exception as e:
        return {"error": f"Failed to fetch exchange rates: {str(e)}"}


def geocode_address(address: str) -> dict:
    """Converts a street address or location name into geographic coordinates (latitude and longitude).

    Args:
        address: The location or address string to geocode (e.g. 'Kyoto Station', 'Eiffel Tower, Paris').

    Returns:
        A dictionary containing the formatted address, latitude, and longitude.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        return {"error": "GOOGLE_MAPS_API_KEY environment variable is not set."}

    try:
        encoded_addr = urllib.parse.quote(address.strip())
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_addr}&key={api_key}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        if data.get("status") == "OK" and data.get("results"):
            result = data["results"][0]
            loc = result.get("geometry", {}).get("location", {})
            return {
                "status": "success",
                "address": result.get("formatted_address", address),
                "location": {
                    "latitude": loc.get("lat"),
                    "longitude": loc.get("lng"),
                },
            }
        return {"error": f"Geocoding failed: {data.get('status', 'NO_RESULTS_FOUND')}"}
    except Exception as e:
        return {"error": f"Failed to geocode address '{address}': {str(e)}"}


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "tourist_attraction",
    radius_meters: float = 2000.0,
) -> dict:
    """Finds nearby places of a specific type around given coordinates using the Places API (New).

    Args:
        latitude: Latitude of the center point.
        longitude: Longitude of the center point.
        place_type: Type of place to search for (e.g. 'tourist_attraction', 'restaurant', 'cafe', 'museum', 'lodging').
        radius_meters: Search radius in meters (default 2000 meters).

    Returns:
        A list of key fields for nearby places (name, address, location).
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        return {"error": "GOOGLE_MAPS_API_KEY environment variable is not set."}

    url = "https://places.googleapis.com/v1/places:searchNearby"
    payload = {
        "includedTypes": [place_type],
        "maxResultCount": 5,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius": radius_meters,
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        places_list = []
        for place in data.get("places", []):
            name = place.get("displayName", {}).get("text", "")
            addr = place.get("formattedAddress", "")
            loc = place.get("location", {})
            places_list.append({
                "name": name,
                "address": addr,
                "location": {
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude"),
                },
            })

        return {
            "status": "success",
            "count": len(places_list),
            "places": places_list,
        }
    except Exception as e:
        return {"error": f"Failed to search nearby places: {str(e)}"}


def generate_destination_image(
    prompt: str,
    destination_name: str,
    tool_context: ToolContext,
) -> dict:
    """Generates a showcase image for a travel destination using gemini-3.1-flash-lite-image model in global region.
    Saves the image as a Playground artifact and uploads the image bytes directly to Cloud Storage.

    Args:
        prompt: Detailed visual prompt describing the travel image to generate.
        destination_name: The name or slug of the destination (e.g. 'kyoto', 'paris').
        tool_context: ADK context for saving artifacts.

    Returns:
        A dictionary containing the artifact filename and the public GCS image URL.
    """
    try:
        client = genai.Client(
            vertexai=True,
            project=FIRESTORE_PROJECT,
            location="global",
        )
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=[prompt],
        )

        image_bytes = None
        mime_type = "image/jpeg"

        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    if part.inline_data.mime_type:
                        mime_type = part.inline_data.mime_type
                    break

        if not image_bytes:
            return {"error": "No image data was generated by the model."}

        ext = "jpg" if "jpeg" in mime_type or "jpg" in mime_type else "png"
        safe_slug = destination_name.lower().replace(" ", "_").strip()
        filename = f"{safe_slug}_{int(datetime.datetime.now().timestamp())}.{ext}"

        # 1. Save as artifact for Playground's Artifacts panel
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload image bytes directly to public GCS bucket
        storage_client = storage.Client(project=FIRESTORE_PROJECT)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"

        return {
            "status": "success",
            "artifact_filename": filename,
            "public_image_url": public_url,
        }
    except Exception as e:
        return {"error": f"Failed to generate destination image: {str(e)}"}


def generate_destination_video(
    prompt: str,
    destination_name: str,
    tool_context: ToolContext,
) -> dict:
    """Generates a short showcase video for a travel destination using gemini-omni-flash-preview model in global region.
    Saves the video as a Playground artifact and uploads the video bytes directly to Cloud Storage.

    Args:
        prompt: Detailed visual prompt describing the travel video to generate.
        destination_name: The name or slug of the destination (e.g. 'kyoto', 'hawaii').
        tool_context: ADK context for saving artifacts.

    Returns:
        A dictionary containing the artifact filename and the public GCS video URL.
    """
    try:
        client = genai.Client(
            vertexai=True,
            project=FIRESTORE_PROJECT,
            location="global",
        )
        res = client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
        )

        video_bytes = None
        mime_type = "video/mp4"

        if hasattr(res, "output_video") and res.output_video:
            import base64
            data = getattr(res.output_video, "data", None)
            if isinstance(data, bytes):
                video_bytes = data
            elif isinstance(data, str):
                video_bytes = base64.b64decode(data)
        elif hasattr(res, "outputs") and res.outputs:
            for out in res.outputs:
                if hasattr(out, "video") and out.video:
                    import base64
                    data = getattr(out.video, "data", None)
                    if isinstance(data, bytes):
                        video_bytes = data
                    elif isinstance(data, str):
                        video_bytes = base64.b64decode(data)
                    break

        if not video_bytes and hasattr(res, "video_bytes") and res.video_bytes:
            video_bytes = res.video_bytes

        if not video_bytes:
            return {"error": "No video data was returned by the model."}

        safe_slug = destination_name.lower().replace(" ", "_").strip()
        filename = f"{safe_slug}_{int(datetime.datetime.now().timestamp())}.mp4"

        # 1. Save as artifact for Playground's Artifacts panel
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload video bytes directly to public GCS bucket
        storage_client = storage.Client(project=FIRESTORE_PROJECT)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"

        return {
            "status": "success",
            "artifact_filename": filename,
            "public_video_url": public_url,
        }
    except Exception as e:
        return {"error": f"Failed to generate destination video: {str(e)}"}


def get_weather(query: str) -> str:
    """Simulates a web search. Use it get information on weather.

    Args:
        query: A string containing the location to get weather information for.

    Returns:
        A string with the simulated weather information for the queried location.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        return "It's 60 degrees and foggy."
    return "It's 90 degrees and sunny."


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        query: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are the NovaSmart Travel Concierge, a personalized travel assistant. "
        "You remember the user's stated preferences, dietary restrictions, and ALL user allergies "
        "(such as food, medication, or environmental allergies) across conversations. "
        "Always pay close attention to any mentioned allergies, record them in memory, and ensure all "
        "travel, restaurant, hotel, and activity recommendations strictly accommodate and respect these allergies. "
        "You also help users discover travel destinations, geocode addresses into coordinates, "
        "find nearby tourist attractions and restaurants using Google Places, "
        "generate travel showcase images using Gemini image models, "
        "generate short travel showcase videos using Gemini Omni video models, "
        "search catalog recommendations, fetch real-world landmark summaries, view details, "
        "add new destinations, convert travel budgets into local currencies, "
        "execute Python code safely in a sandbox, and check weather and local time. "
        "Use your tools whenever appropriate."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=a2ui_instruction,
    code_executor=code_executor,
    tools=[
        PreloadMemoryTool(),
        get_weather,
        get_current_time,
        search_destinations,
        get_destination_details,
        add_destination,
        convert_currency,
        fetch_destination_info,
        geocode_address,
        find_nearby_places,
        generate_destination_image,
        generate_destination_video,
    ],
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)






