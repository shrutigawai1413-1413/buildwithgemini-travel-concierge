"""Seed script for Firestore destinations collection."""

from google.cloud import firestore

# Hardcoded project ID as required to prevent project number resolution errors
PROJECT_ID = "qwiklabs-gcp-02-b9b8cd363ddd"
COLLECTION_NAME = "destinations"

INITIAL_DESTINATIONS = [
    {
        "destination_id": "tokyo",
        "name": "Tokyo",
        "country": "Japan",
        "description": "A bustling metropolis blending ultramodern skyscrapers with historic temples.",
        "best_season": "Spring (March-May) & Autumn (September-November)",
        "average_daily_budget_usd": 150,
        "highlights": ["Shinjuku Nightlife", "Senso-ji Temple", "Tsukiji Outer Market"],
        "rating": 4.9,
    },
    {
        "destination_id": "kyoto",
        "name": "Kyoto",
        "country": "Japan",
        "description": "Famed for its classical Buddhist temples, gardens, imperial palaces, and traditional wooden houses.",
        "best_season": "Autumn (October-November) & Spring (April)",
        "average_daily_budget_usd": 130,
        "highlights": ["Fushimi Inari Shrine", "Arashiyama Bamboo Grove", "Kinkaku-ji"],
        "rating": 4.8,
    },
    {
        "destination_id": "paris",
        "name": "Paris",
        "country": "France",
        "description": "Global center for art, fashion, gastronomy, and culture with iconic monuments.",
        "best_season": "Spring (April-May) & Autumn (September-October)",
        "average_daily_budget_usd": 180,
        "highlights": ["Eiffel Tower", "Louvre Museum", "Montmartre Cafe Walk"],
        "rating": 4.7,
    },
    {
        "destination_id": "rome",
        "name": "Rome",
        "country": "Italy",
        "description": "A sprawling city with nearly 3,000 years of globally influential art, architecture, and culture.",
        "best_season": "Spring (April-May) & Autumn (September-October)",
        "average_daily_budget_usd": 140,
        "highlights": ["Colosseum", "Vatican Museums", "Trevi Fountain"],
        "rating": 4.8,
    },
    {
        "destination_id": "bali",
        "name": "Bali",
        "country": "Indonesia",
        "description": "Indonesian island known for iconic rice paddies, forested volcanic mountains, and coral reefs.",
        "best_season": "Dry Season (April-October)",
        "average_daily_budget_usd": 80,
        "highlights": ["Ubud Rice Terraces", "Uluwatu Temple", "Canggu Beach Sunset"],
        "rating": 4.6,
    },
]


def seed_database():
    db = firestore.Client(project=PROJECT_ID)
    print(f"Connecting to Firestore for project: {PROJECT_ID}")
    
    collection_ref = db.collection(COLLECTION_NAME)
    for dest in INITIAL_DESTINATIONS:
        doc_id = dest["destination_id"]
        doc_ref = collection_ref.document(doc_id)
        doc_ref.set(dest)
        print(f"  ✓ Seeded destination: {dest['name']} (ID: {doc_id})")

    print("Database seeding completed successfully!")


if __name__ == "__main__":
    seed_database()
