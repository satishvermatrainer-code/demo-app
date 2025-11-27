from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import os
import logging
import json
import time
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from bson import ObjectId
import ssl
from pathlib import Path

# ---------- Logging: single-line JSON logs per request ----------
logger = logging.getLogger("demo_app")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# ---------- Config (from env) ----------
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("mongoDb", "app")
MONGO_COLLECTION = os.getenv("mongoCollection", "orders")
MONGO_CA_FILE = os.getenv("MONGO_CA_FILE", "/etc/ssl/mongo/ca.pem")

if not MONGO_URI:
    logger.warning(json.dumps({"level": "warning", "msg": "MONGO_URI not set; health checks will fail"}))

app = FastAPI()

# ---------- Mongo client (motor + TLS) ----------
mongo_client: AsyncIOMotorClient | None = None

@app.on_event("startup")
async def startup_event():
    global mongo_client

    tls_params = {}
    ca_file_path = Path(MONGO_CA_FILE)

    # Enable TLS if CA file exists
    if ca_file_path.exists():
        logger.info(json.dumps({
            "msg": "TLS Enabled for MongoDB",
            "ca_file": str(ca_file_path)
        }))
        tls_params = {
            "tls": True,
            "tlsCAFile": str(ca_file_path)
        }
    else:
        logger.warning(json.dumps({
            "msg": "TLS CA file not found, fallback to non-TLS",
            "path": str(ca_file_path)
        }))

    mongo_client = AsyncIOMotorClient(
        MONGO_URI,
        serverSelectionTimeoutMS=3000,
        **tls_params
    )

    try:
        await mongo_client.admin.command("ping")
        logger.info(json.dumps({"msg": "MongoDB connected successfully"}))
    except Exception as e:
        logger.error(json.dumps({
            "msg": "Initial MongoDB connection failed",
            "error": str(e)
        }))

@app.on_event("shutdown")
async def shutdown_event():
    global mongo_client
    if mongo_client:
        mongo_client.close()

# ---------- Health ----------
@app.get("/healthz")
async def health():
    if not mongo_client:
        raise HTTPException(status_code=503, detail="Mongo client not configured")
    try:
        await mongo_client.admin.command("ping")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

# ---------- Data Model ----------
class OrderIn(BaseModel):
    orderId: str

# ---------- Helpers ----------
def get_collection():
    if not mongo_client:
        raise HTTPException(status_code=503, detail="Mongo not configured")
    return mongo_client[MONGO_DB][MONGO_COLLECTION]

# ---------- Endpoints ----------
@app.post("/orders")
async def create_order(order: OrderIn):
    coll = get_collection()
    doc = {"orderId": order.orderId, "ts": datetime.utcnow().isoformat() + "Z"}
    res = await coll.insert_one(doc)
    return {"inserted": True, "id": str(res.inserted_id)}

@app.get("/orders/count")
async def count_orders():
    coll = get_collection()
    count = await coll.count_documents({})
    return {"count": int(count)}

@app.get("/ready")
async def ready():
    return await health()