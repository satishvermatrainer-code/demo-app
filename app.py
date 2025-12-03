import os, json, logging
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime

# Logging setup
logger = logging.getLogger("demo_app")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(handler)

# Config from environment
USERNAME          = os.getenv("MONGODB_USERNAME")
PASSWORD          = os.getenv("MONGODB_PASSWORD")
HOST              = os.getenv("MONGODB_HOST")
PORT              = os.getenv("MONGODB_PORT")
QUERY_PARAMS      = os.getenv("MONGO_QUERY_PARAMS")
MONGO_DB          = os.getenv("MONGO_DB")
MONGO_COLLECTION  = os.getenv("MONGO_COLLECTION")

# Build Mongo URI dynamically (without TLS)
MONGO_URI = f"mongodb://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/"
if QUERY_PARAMS:
    MONGO_URI += f"?{QUERY_PARAMS}"

app = FastAPI()
mongo_client: AsyncIOMotorClient | None = None

@app.on_event("startup")
async def startup_event():
    global mongo_client
    mongo_client = AsyncIOMotorClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000
    )

    try:
        await mongo_client.admin.command("ping")
        logger.info(json.dumps({"msg": "MongoDB connected successfully"}))
    except Exception as e:
        logger.error(json.dumps({"msg": "MongoDB connection failed", "error": str(e)}))

@app.on_event("shutdown")
async def shutdown_event():
    if mongo_client:
        mongo_client.close()

class OrderIn(BaseModel):
    orderId: str

def get_collection():
    if not mongo_client:
        raise HTTPException(status_code=503, detail="Mongo client not ready")
    return mongo_client[MONGO_DB][MONGO_COLLECTION]

@app.post("/orders")
async def create_order(order: OrderIn):
    res = await get_collection().insert_one({
        "orderId": order.orderId,
        "ts": datetime.utcnow().isoformat() + "Z"
    })
    return {"inserted": True, "id": str(res.inserted_id)}

@app.get("/orders/count")
async def count_orders():
    return {"count": await get_collection().count_documents({})}

@app.get("/healthz")
async def health():
    try:
        await mongo_client.admin.command("ping")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)}

@app.get("/ready")
async def ready():
    return await health()
