from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import os
import subprocess
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_DIR = os.path.join(BASE, "snapshots")

def get_latest_snapshot():
    snaps = sorted([f for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".json")])
    if not snaps:
        return {}
    with open(os.path.join(SNAPSHOT_DIR, snaps[-1]), encoding="utf-8") as f:
        return json.load(f)

@app.get("/api/trips")
def get_trips():
    with open(os.path.join(BASE, "trips.json"), encoding="utf-8") as f:
        trips = json.load(f)["trips"]
    
    snapshot = get_latest_snapshot()
    
    result = []
    for t in trips:
        if not t.get("enabled", True):
            continue
        tid = t["id"]
        snap = snapshot.get(tid, {})
        result.append({
            "trip": t,
            "data": snap
        })
    return {"trips": result, "updatedAt": datetime.now().isoformat()}

@app.post("/api/refresh")
def refresh_trip(trip_id: str):
    print(f"Triggering background update for {trip_id}...")
    try:
        res = subprocess.run(
            ["python", "travel_tracker.py", "--single", trip_id],
            cwd=BASE,
            capture_output=True, text=True, encoding="utf-8"
        )
        if res.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Scraping failed: {res.stderr}")
            
        return {"status": "success", "message": f"Updated {trip_id} successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class SearchQuery(BaseModel):
    destination: str
    depart: str  # YYYY-MM-DD
    return_date: str  # YYYY-MM-DD
    adults: int

@app.post("/api/search")
def dynamic_search(query: SearchQuery):
    import uuid
    from datetime import datetime
    
    trip_id = f"search-{uuid.uuid4().hex[:6]}"
    
    dynamic_trip = {
        "id": trip_id,
        "enabled": True,
        "from": "ATH",
        "to": query.destination,
        "city": query.destination,
        "depart": query.depart,
        "return": query.return_date,
        "adults": query.adults
    }
    
    temp_file = os.path.join(BASE, "temp_trips.json")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump({"trips": [dynamic_trip]}, f)
        
    try:
        # Run tracker pointing to temp_file
        res = subprocess.run(
            ["python", "travel_tracker.py", "--file", "temp_trips.json", "--single", trip_id],
            cwd=BASE,
            capture_output=True, text=True, encoding="utf-8"
        )
        if res.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Search failed: {res.stderr}")
            
        # Read the latest snapshot which now has our dynamic trip
        snapshot = get_latest_snapshot()
        snap_data = snapshot.get(trip_id, {})
        
        return {
            "status": "success",
            "trip": dynamic_trip,
            "data": snap_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
