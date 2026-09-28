from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["health"])


@router.get("/", include_in_schema=False)  # hidden from /docs
def root() -> RedirectResponse:
    # Visitors to the bare URL land on the interactive API docs instead of a 404
    return RedirectResponse("/docs")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
