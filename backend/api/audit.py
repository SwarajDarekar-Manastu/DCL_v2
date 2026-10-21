"""Read-only audit log routes for the Console AuditPage (file 08 §4.4). Owner: S3."""

from fastapi import APIRouter

router = APIRouter(prefix="/audit", tags=["audit"])
