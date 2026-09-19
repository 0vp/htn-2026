"""API entry point."""

from fastapi import FastAPI

app = FastAPI(title="HTN API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
