"""Team management and team productivity routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.core import (
    audit_log,
    check_machine_access as _check_machine_access,
    require_permission,
)
from database import db
from models import TeamCreateRequest, TeamMachineAssignRequest, TeamUpdateRequest

router = APIRouter()


@router.post("/api/teams")
async def create_team(
    request: Request,
    payload: TeamCreateRequest,
    user=Depends(require_permission("teams.manage")),
):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Team name is required")
    team = db.create_team(name=name, description=payload.description or "")
    audit_log(request, user, "team_created", "team", str(team.get("id")), {"name": name})
    return team


@router.get("/api/teams")
async def list_teams(
    response: Response,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    user=Depends(require_permission("teams.view")),
):
    data = db.get_teams(search=search, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(data.get("total", 0))
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"
    return data.get("items", [])


@router.put("/api/teams/{team_id}")
async def update_team(
    request: Request,
    team_id: str,
    payload: TeamUpdateRequest,
    user=Depends(require_permission("teams.manage")),
):
    if payload.name is None and payload.description is None:
        raise HTTPException(status_code=400, detail="No fields provided to update")
    updated = db.update_team(
        team_id,
        name=payload.name,
        description=payload.description,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Team not found")
    audit_log(request, user, "team_updated", "team", team_id)
    return updated


@router.delete("/api/teams/{team_id}")
async def delete_team(
    request: Request,
    team_id: str,
    user=Depends(require_permission("teams.manage")),
):
    deleted = db.delete_team(team_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Team not found")
    audit_log(request, user, "team_deleted", "team", team_id)
    return {"message": "Team deleted"}


@router.post("/api/teams/{team_id}/machines")
async def assign_machine_to_team(
    request: Request,
    team_id: str,
    payload: TeamMachineAssignRequest,
    user=Depends(require_permission("teams.manage")),
):
    machine_id = (payload.machine_id or "").strip()
    if not machine_id:
        raise HTTPException(status_code=400, detail="machine_id is required")
    ok = db.add_machine_to_team(team_id, machine_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Team or machine not found")
    audit_log(
        request,
        user,
        "team_machine_added",
        "team",
        team_id,
        {"machine_id": machine_id},
    )
    return {"message": "Machine assigned to team", "team_id": team_id, "machine_id": machine_id}


@router.get("/api/teams/{team_id}/machines")
async def list_team_machines(
    team_id: str,
    response: Response,
    search: str = "",
    status: str = "",
    limit: int = 50,
    offset: int = 0,
    start_date: str = "",
    end_date: str = "",
    user=Depends(require_permission("teams.view")),
):
    data = db.get_team_machines(
        team_id=team_id,
        search=search,
        status=status,
        limit=limit,
        offset=offset,
        start_date=start_date,
        end_date=end_date,
    )
    response.headers["X-Total-Count"] = str(data.get("total", 0))
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"
    return data.get("items", [])


@router.delete("/api/teams/{team_id}/machines/{machine_id}")
async def remove_machine_from_team(
    request: Request,
    team_id: str,
    machine_id: str,
    user=Depends(require_permission("teams.manage")),
):
    removed = db.remove_machine_from_team(team_id, machine_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Machine is not assigned to this team")
    audit_log(
        request,
        user,
        "team_machine_removed",
        "team",
        team_id,
        {"machine_id": machine_id},
    )
    return {"message": "Machine removed from team"}


@router.get("/api/machines/{machine_id}/productivity")
async def get_machine_productivity(
    machine_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user=Depends(require_permission("productivity.view")),
):
    _check_machine_access(user, machine_id)
    payload = db.get_machine_productivity(
        machine_id=machine_id,
        start_date=start_date or "",
        end_date=end_date or "",
    )
    if not payload:
        raise HTTPException(status_code=404, detail="Machine not found")
    return payload


@router.get("/api/teams/{team_id}/productivity")
async def get_team_productivity(
    team_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trend_days: int = 7,
    user=Depends(require_permission("teams.view")),
):
    payload = db.get_team_productivity(
        team_id=team_id,
        start_date=start_date or "",
        end_date=end_date or "",
        trend_days=trend_days,
    )
    if not payload:
        raise HTTPException(status_code=404, detail="Team not found")
    return payload
