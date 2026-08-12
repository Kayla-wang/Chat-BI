from fastapi import FastAPI

from chatbi.api.auth_router import router as auth_router
from chatbi.errors import ApiError, api_error_handler

app = FastAPI(title="Chat-BI API", version="0.1.0")
app.add_exception_handler(ApiError, api_error_handler)
app.include_router(auth_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
