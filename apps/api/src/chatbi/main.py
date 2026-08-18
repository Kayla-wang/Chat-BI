from fastapi import FastAPI

from chatbi.api.routers import ALL_ROUTERS
from chatbi.errors import ApiError, api_error_handler

app = FastAPI(title="Chat-BI API", version="0.1.0")
app.add_exception_handler(ApiError, api_error_handler)
for _router in ALL_ROUTERS:
    app.include_router(_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
