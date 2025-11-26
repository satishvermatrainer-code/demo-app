### FILE: app.py
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import os
import logging
import json
import time
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from bson import ObjectId

# ---------- Logging: single-line JSON logs per request ----------
logger = logging.getLogger("demo_app")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# ---------- Config (from env) ----------
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "app")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "orders")

if not MONGO_URI:
    # We do not raise here because in some test environments user may want to run without Mongo.
    logger.warning(json.dumps({"level": "warning", "msg": "MONGO_URI not set; health checks will fail until provided"}))

app = FastAPI()

# Middleware to log every request as a single-line JSON
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        status_code = 500
        raise
    finally:
        latency_ms = int((time.time() - start) * 1000)
        log = {
            "method": request.method,
            "path": request.url.path,
            "status": status_code,
            "latency_ms": latency_ms,
            "ts": datetime.utcnow().isoformat() + "Z"
        }
        logger.info(json.dumps(log))
    return response

# ---------- Mongo client (motor) ----------
mongo_client: AsyncIOMotorClient | None = None

@app.on_event("startup")
async def startup_event():
    global mongo_client
    if MONGO_URI:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        # Optional: set a short serverSelectionTimeoutMS to avoid hanging probes
        try:
            # test connection quickly
            await mongo_client.admin.command("ping")
            logger.info(json.dumps({"level": "info", "msg": "Connected to MongoDB"}))
        except Exception as e:
            logger.warning(json.dumps({"level": "warning", "msg": "Mongo connection failed at startup", "error": str(e)}))

@app.on_event("shutdown")
async def shutdown_event():
    global mongo_client
    if mongo_client:
        mongo_client.close()

# ---------- Health endpoint ----------
@app.get("/healthz")
async def healthz():
    """Return 200 when a fast Mongo ping succeeds, else 503."""
    if not mongo_client:
        raise HTTPException(status_code=503, detail="no mongo client configured")
    try:
        await mongo_client.admin.command("ping")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"mongo ping failed: {e}")

# ---------- Data model ----------
class OrderIn(BaseModel):
    orderId: str

# ---------- Helper: get collection ----------
def get_collection():
    if not mongo_client:
        raise HTTPException(status_code=503, detail="mongo not configured")
    db = mongo_client[MONGO_DB]
    coll = db[MONGO_COLLECTION]
    return coll

# ---------- POST /orders ----------
@app.post("/orders")
async def create_order(order: OrderIn):
    coll = get_collection()
    doc = {"orderId": order.orderId, "ts": datetime.utcnow().isoformat() + "Z"}
    res = await coll.insert_one(doc)
    return {"inserted": True, "id": str(res.inserted_id)}

# ---------- GET /orders/count ----------
@app.get("/orders/count")
async def orders_count():
    coll = get_collection()
    count = await coll.count_documents({})
    return {"count": int(count)}

# Optional readiness endpoint (alias)
@app.get("/ready")
async def ready():
    return await healthz()