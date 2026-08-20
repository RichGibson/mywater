from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402

from db import init_app_db  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_app_db()
    yield


app = FastAPI(title="mywater", lifespan=lifespan)

from routers import reports  # noqa: E402

app.include_router(reports.router, prefix="/api")


@app.get("/")
def health():
    return {"status": "ok"}
