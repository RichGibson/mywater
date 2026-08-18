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


@app.get("/")
def health():
    return {"status": "ok"}
