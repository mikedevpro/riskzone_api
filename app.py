from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, constr, model_validator
from sqlalchemy import Column, Integer, String, DateTime, create_engine, desc
from sqlalchemy.orm import declarative_base, sessionmaker

# -----------------------------
# DB setup (SQLite)
# -----------------------------
DATABASE_URL = "sqlite:///./riskzone.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


class Score(Base):
    __tablename__ = "scores"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(16), nullable=False)
    score = Column(Integer, nullable=False, index=True)
    level = Column(Integer, nullable=False, default=1)
    character = Column(String(24), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


Base.metadata.create_all(bind=engine)

# -----------------------------
# API
# -----------------------------
app = FastAPI(title="Risk Zone Leaderboard API")

# CORS: allow your dev + prod frontends
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://risk-zone.vercel.app",
        # add your Vercel domain later, e.g. "https://risk-zone.vercel.app"
    ],
    allow_origin_regex=r"^https://.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/version")
def version():
    return {"version": "cors-1"}

# Very lightweight in-memory rate limiting per IP (good enough for demo)
# NOTE: resets when server restarts; for production use Redis or a gateway.
RATE = {}  # ip -> (window_start_iso, count)
WINDOW_SECONDS = 60
MAX_REQ_PER_WINDOW = 120


def rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc)
    bucket = RATE.get(ip)
    if not bucket:
        RATE[ip] = (now, 1)
        return
    window_start, count = bucket
    elapsed = (now - window_start).total_seconds()
    if elapsed > WINDOW_SECONDS:
        RATE[ip] = (now, 1)
        return
    if count >= MAX_REQ_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many requests. Try again shortly.")
    RATE[ip] = (window_start, count + 1)


class SubmitScoreIn(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=16) = Field(..., description="Player name")
    score: int = Field(..., ge=0, le=999999)
    level: int = Field(1, ge=1, le=999)
    character: Optional[constr(strip_whitespace=True, min_length=1, max_length=24)] = None

    @model_validator(mode="before")
    @classmethod
    def map_name_aliases(cls, data):
        if not isinstance(data, dict):
            return data
        if data.get("name"):
            return data

        for alias in ("playerName", "player_name", "player", "username"):
            alias_value = data.get(alias)
            if isinstance(alias_value, str) and alias_value.strip():
                data = {**data, "name": alias_value}
                break
        return data


class ScoreOut(BaseModel):
    name: str
    playerName: str
    score: int
    level: int
    character: Optional[str] = None
    created_at: str  # ISO

@app.get("/")
def root():
    return {"ok": True, "service": "riskzone-api"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/leaderboard", response_model=List[ScoreOut])
def get_leaderboard(limit: int = 10):
    limit = max(1, min(limit, 50))
    db = SessionLocal()
    try:
        rows = (
            db.query(Score)
            .order_by(desc(Score.score), desc(Score.level), desc(Score.created_at))
            .limit(limit)
            .all()
        )
        return [
            ScoreOut(
                name=r.name,
                playerName=r.name,
                score=r.score,
                level=r.level,
                character=r.character,
                created_at=r.created_at.isoformat(),
            )
            for r in rows
        ]
    finally:
        db.close()


@app.post("/score", response_model=List[ScoreOut])
def submit_score(payload: SubmitScoreIn, request: Request, limit: int = 10):
    rate_limit(request)

    # Simple anti-abuse: reject obviously fake huge jumps (optional; tweak as you like)
    if payload.score > 200000:
        raise HTTPException(status_code=400, detail="Score out of allowed range for demo.")

    db = SessionLocal()
    try:
        db.add(
            Score(
                name=payload.name,
                score=payload.score,
                level=payload.level,
                character=payload.character,
            )
        )
        db.commit()

        # Return updated top N
        limit = max(1, min(limit, 50))
        rows = (
            db.query(Score)
            .order_by(desc(Score.score), desc(Score.level), desc(Score.created_at))
            .limit(limit)
            .all()
        )
        return [
            ScoreOut(
                name=r.name,
                playerName=r.name,
                score=r.score,
                level=r.level,
                character=r.character,
                created_at=r.created_at.isoformat(),
            )
            for r in rows
        ]
    finally:
        db.close()
