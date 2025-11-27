from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os, json, logging
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from pathlib import Path

# ---------- Logging ----------
logger = logging.getLogger("demo_app")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(handler)

# ---------- Config ----------
MONGO_URI            = os.getenv("MONGO_URI")  # e.g. mongodb://user:pass@mongodb:27017/app?authSource=admin
MONGO_DB             = os.getenv("mongoDb", "app")
MONGO_COLLECTION     = os.getenv("mongoCollection", "orders")
TLS_CA_FILE          = os.getenv("MONGO_CA_FILE", "/etc/ssl/mongo/ca.pem")
TLS_CERT_FILE        = os.getenv("MONGO_CERT_FILE", "/etc/ssl/mongo/client.pem")  # NEW
TLS_ENABLED          = os.getenv("MONGO_TLS_ENABLED", "true").lower() == "true"

app = FastAPI()

mongo_client: AsyncIOMotorClient | None = None

@app.on_event("startup")
async def startup_event():
    global mongo_client

    tls_args = {}

    if TLS_ENABLED:
        paths = {
            "tlsCAFile": TLS_CA_FILE,
            "tlsCertificateKeyFile": TLS_CERT_FILE
        }

        for key, file in paths.items():
            if not Path(file).exists():
                logger.error(json.dumps({"msg": f"TLS file missing", "file": file}))
                raise RuntimeError(f"Missing TLS required file: {file}")

        tls_args = {
            "tls": True,
            "tlsAllowInvalidHostnames": True,
            "tlsCAFile": TLS_CA_FILE,
            "tlsCertificateKeyFile": TLS_CERT_FILE
        }

        logger.info(json.dumps({
            "msg": "TLS Enabled for MongoDB",
            "ca": TLS_CA_FILE,
            "client_cert": TLS_CERT_FILE
        }))
    else:
        logger.warning(json.dumps({"msg": "Running WITHOUT TLS"}))

    mongo_client = AsyncIOMotorClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000,
        **tls_args
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


@app.get("/healthz")
async def health():
    try:
        await mongo_client.admin.command("ping")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


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
    count = await get_collection().count_documents({})
    return {"count": count}


@app.get("/ready")
async def ready():
    return await health()
