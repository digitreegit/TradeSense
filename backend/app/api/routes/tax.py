"""Year-end CSV export from local compliance logs (authenticated user scope)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.deps import get_current_user_id
from app.services.tax_export_service import build_tax_csv_for_year
from app.services.user_runtime import _log_dir_for_user

router = APIRouter(prefix="/tax", tags=["tax"])


@router.get("/export/csv")
def export_tax_csv(
    year: int = Query(..., ge=2000, le=2100),
    user_id: int = Depends(get_current_user_id),
) -> Response:
    log_dir = _log_dir_for_user(user_id)
    csv_text = build_tax_csv_for_year(log_dir, year)
    body = csv_text.encode("utf-8")
    filename = f"tradesense-tax-{year}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
