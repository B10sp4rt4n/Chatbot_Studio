from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from db import verify_recordia_hash


app = FastAPI(title="Recordia Verification API", version="1.0.0")


class HashVerificationRequest(BaseModel):
    tenant_id: int = Field(..., ge=1)
    project_id: int = Field(..., ge=1)
    session_id: int = Field(..., ge=1)
    hash: str = Field(..., min_length=64, max_length=128)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/verify_hash")
def verify_hash(request: HashVerificationRequest):
    try:
        result = verify_recordia_hash(
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            session_id=request.session_id,
            recordia_hash=request.hash,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
