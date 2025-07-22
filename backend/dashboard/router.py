"""Router for the monitoring dashboard."""
import csv
import json
import io
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Depends, HTTPException, status, Cookie
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..auth import role_required
from ..monitoring import get_metrics, HealthCheck, Component, SystemInfo
from .. import database
from ..config import settings
from ..alerts import AlertManager, AlertLevel, AlertType

# Set up templates and static files
DASHBOARD_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(DASHBOARD_DIR / "templates"))

# Create router
router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Create alert manager singleton
alert_manager = AlertManager()

# Helper for dashboard preferences
def get_dashboard_preferences(dashboard_preferences: Optional[str] = Cookie(None)) -> Dict[str, Any]:
    """Get dashboard preferences from cookie."""
    if not dashboard_preferences:
        return {
            "theme": "light",
            "refresh_interval": 0,  # 0 means no auto-refresh
            "default_view": "overview",
            "chart_type": "doughnut",
            "visible_panels": ["health", "metrics", "system", "requests"],
            "compact_mode": False
        }
    
    try:
        return json.loads(dashboard_preferences)
    except Exception:
        return {
            "theme": "light",
            "refresh_interval": 0,
            "default_view": "overview",
            "chart_type": "doughnut",
            "visible_panels": ["health", "metrics", "system", "requests"],
            "compact_mode": False
        }

@router.get("/", response_class=HTMLResponse, dependencies=[Depends(role_required("admin"))])
async def dashboard_home(
    request: Request,
    preferences: Dict[str, Any] = Depends(get_dashboard_preferences)
):
    """Main dashboard page."""
    # Get health status
    health = HealthCheck.check_health()
    
    # Get metrics
    metrics = get_metrics().get_metrics()
    
    # Format uptime
    uptime_seconds = metrics["uptime_seconds"]
    uptime = str(timedelta(seconds=int(uptime_seconds)))
    
    # Get system info
    system_info = SystemInfo.get_system_info()
    
    # Get active alerts
    active_alerts = alert_manager.get_active_alerts()
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "Relia Monitoring Dashboard",
            "health": health,
            "metrics": metrics,
            "uptime": uptime,
            "system_info": system_info,
            "settings": settings,
            "preferences": preferences,
            "alerts": active_alerts,
            "alert_count": len(active_alerts)
        }
    )

@router.get("/logs", response_class=HTMLResponse, dependencies=[Depends(role_required("admin"))])
async def view_logs(
    request: Request, 
    log_type: str = "application", 
    limit: int = 100,
    preferences: Dict[str, Any] = Depends(get_dashboard_preferences)
):
    """View application logs."""
    logs: List[Dict[str, Any]] = []
    
    # Load logs from database if enabled
    if settings.DB_ENABLED:
        if log_type == "application":
            logs = database.get_logs(limit=limit)
        elif log_type == "access":
            logs = database.get_access_logs(limit=limit)
        elif log_type == "telemetry":
            logs = database.get_telemetry(limit=limit)
    
    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "title": f"Relia {log_type.title()} Logs",
            "logs": logs,
            "log_type": log_type,
            "limit": limit,
            "preferences": preferences,
            "alerts": alert_manager.get_active_alerts(),
            "alert_count": len(alert_manager.get_active_alerts())
        }
    )

@router.get("/export/logs", dependencies=[Depends(role_required("admin"))])
async def export_logs(
    log_type: str = "application", 
    format: str = "csv",
    limit: int = 1000
):
    """Export logs to CSV or JSON format."""
    if not settings.DB_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is disabled"
        )
    
    # Get logs
    logs: List[Dict[str, Any]] = []
    if log_type == "application":
        logs = database.get_logs(limit=limit)
    elif log_type == "access":
        logs = database.get_access_logs(limit=limit)
    elif log_type == "telemetry":
        logs = database.get_telemetry(limit=limit)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Invalid log type: {log_type}"
        )
    
    # Get current timestamp for filename
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"relia_{log_type}_logs_{timestamp}"
    
    if format == "json":
        # Prepare JSON response
        content = json.dumps(logs, indent=2, default=str)
        
        return StreamingResponse(
            io.StringIO(content),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename}.json"
            }
        )
    elif format == "csv":
        # Create CSV file in memory
        output = io.StringIO()
        
        if logs:
            # Get field names from first log entry
            fieldnames = logs[0].keys()
            
            # Create CSV writer
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            
            # Write logs with special handling for nested objects
            for log in logs:
                # Process each log entry to handle nested dictionaries
                flat_log = {}
                for key, value in log.items():
                    if isinstance(value, (dict, list)):
                        flat_log[key] = json.dumps(value)
                    else:
                        flat_log[key] = value
                writer.writerow(flat_log)
        
        # Reset stream position
        output.seek(0)
        
        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}.csv"
            }
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Invalid format: {format}, must be 'csv' or 'json'"
        )

@router.get("/export/metrics", dependencies=[Depends(role_required("admin"))])
async def export_metrics(format: str = "json"):
    """Export metrics to JSON or CSV format."""
    # Get metrics
    metrics = get_metrics().get_metrics()
    
    # Get current timestamp for filename
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"relia_metrics_{timestamp}"
    
    if format == "json":
        # Prepare JSON response (convert non-serializable types to strings)
        content = json.dumps(metrics, indent=2, default=str)
        
        return StreamingResponse(
            io.StringIO(content),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename}.json"
            }
        )
    elif format == "csv":
        # Flatten metrics for CSV export
        output = io.StringIO()
        flat_metrics = []
        
        # Process system metrics
        for category, values in metrics["system"].items():
            if isinstance(values, dict):
                for key, value in values.items():
                    if not isinstance(value, dict):
                        flat_metrics.append({
                            "type": "system",
                            "category": category,
                            "name": key,
                            "value": value
                        })
        
        # Process app metrics
        for category, values in metrics["metrics"].items():
            if isinstance(values, dict):
                for key, value in values.items():
                    flat_metrics.append({
                        "type": "application",
                        "category": category,
                        "name": key,
                        "value": value
                    })
            else:
                flat_metrics.append({
                    "type": "application",
                    "category": None,
                    "name": category,
                    "value": values
                })
        
        # Add process metrics
        for key, value in metrics["process"].items():
            flat_metrics.append({
                "type": "process",
                "category": None,
                "name": key,
                "value": value
            })
        
        # Add general metrics
        flat_metrics.append({
            "type": "general",
            "category": None,
            "name": "uptime_seconds",
            "value": metrics["uptime_seconds"]
        })
        flat_metrics.append({
            "type": "general",
            "category": None,
            "name": "requests_per_minute",
            "value": metrics["requests_per_minute"]
        })
        
        # Write CSV
        if flat_metrics:
            writer = csv.DictWriter(output, fieldnames=["type", "category", "name", "value"])
            writer.writeheader()
            for metric in flat_metrics:
                writer.writerow(metric)
        
        # Reset stream position
        output.seek(0)
        
        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}.csv"
            }
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Invalid format: {format}, must be 'csv' or 'json'"
        )

@router.get("/metrics", response_class=HTMLResponse, dependencies=[Depends(role_required("admin"))])
async def view_metrics(
    request: Request,
    preferences: Dict[str, Any] = Depends(get_dashboard_preferences)
):
    """View application metrics dashboard."""
    metrics = get_metrics().get_metrics()
    
    # Get feedback stats if database is enabled
    feedback_stats = {}
    if settings.DB_ENABLED and hasattr(database, "get_feedback_stats"):
        feedback_stats = database.get_feedback_stats()
    
    # Get request stats from metrics
    request_stats = metrics["metrics"]["requests"]
    
    # Get LLM usage stats
    llm_stats = {}
    if settings.DB_ENABLED and settings.COLLECT_LLM_USAGE:
        llm_stats = database.get_llm_usage_stats()
    
    return templates.TemplateResponse(
        "metrics.html",
        {
            "request": request,
            "title": "Relia Metrics Dashboard",
            "metrics": metrics,
            "feedback_stats": feedback_stats,
            "request_stats": request_stats,
            "llm_stats": llm_stats,
            "preferences": preferences,
            "alerts": alert_manager.get_active_alerts(),
            "alert_count": len(alert_manager.get_active_alerts())
        }
    )

@router.get("/health", response_class=HTMLResponse, dependencies=[Depends(role_required("admin"))])
async def view_health(
    request: Request,
    preferences: Dict[str, Any] = Depends(get_dashboard_preferences)
):
    """View system health dashboard."""
    health = HealthCheck.check_health()
    
    return templates.TemplateResponse(
        "health.html",
        {
            "request": request,
            "title": "Relia Health Dashboard",
            "health": health,
            "component_keys": [c.value for c in Component],
            "preferences": preferences,
            "alerts": alert_manager.get_active_alerts(),
            "alert_count": len(alert_manager.get_active_alerts())
        }
    )

@router.get("/playbooks", response_class=HTMLResponse, dependencies=[Depends(role_required("admin"))])
async def view_playbooks(
    request: Request, 
    limit: int = 50,
    preferences: Dict[str, Any] = Depends(get_dashboard_preferences)
):
    """View generated playbooks."""
    playbooks = []
    if settings.DB_ENABLED and hasattr(database, "get_playbooks"):
        playbooks = database.get_playbooks(limit=limit)
    
    playbook_dir = settings.PLAYBOOK_DIR
    if playbook_dir.exists():
        # Collect files from playbook directory if database function not available
        if not playbooks:
            playbook_files = list(playbook_dir.glob("*.yml"))
            playbooks = [
                {
                    "id": f.stem,
                    "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    "size": f.stat().st_size,
                    "path": str(f),
                }
                for f in sorted(playbook_files, key=lambda x: x.stat().st_mtime, reverse=True)[:limit]
            ]
    
    return templates.TemplateResponse(
        "playbooks.html",
        {
            "request": request,
            "title": "Relia Generated Playbooks",
            "playbooks": playbooks,
            "limit": limit,
            "preferences": preferences,
            "alerts": alert_manager.get_active_alerts(),
            "alert_count": len(alert_manager.get_active_alerts())
        }
    )

@router.get("/alerts", response_class=HTMLResponse, dependencies=[Depends(role_required("admin"))])
async def view_alerts(
    request: Request,
    preferences: Dict[str, Any] = Depends(get_dashboard_preferences)
):
    """View system alerts."""
    active_alerts = alert_manager.get_active_alerts()
    alert_history = alert_manager.get_alert_history(limit=100)
    
    # Get current alert levels
    alert_counts = {
        AlertLevel.CRITICAL: 0,
        AlertLevel.WARNING: 0,
        AlertLevel.INFO: 0
    }
    
    for alert in active_alerts:
        alert_counts[alert["level"]] += 1
    
    return templates.TemplateResponse(
        "alerts.html",
        {
            "request": request,
            "title": "Relia System Alerts",
            "active_alerts": active_alerts,
            "alert_history": alert_history,
            "alert_counts": alert_counts,
            "alert_types": [t.value for t in AlertType],
            "alert_levels": [level.value for level in AlertLevel],
            "preferences": preferences,
            "alerts": active_alerts,
            "alert_count": len(active_alerts)
        }
    )

@router.post("/preferences", dependencies=[Depends(role_required("admin"))])
async def save_preferences(request: Request):
    """Save dashboard preferences."""
    # Parse form data
    form_data = await request.form()
    
    # Build preferences
    preferences = {
        "theme": form_data.get("theme", "light"),
        "refresh_interval": int(form_data.get("refresh_interval", "0")),
        "default_view": form_data.get("default_view", "overview"),
        "chart_type": form_data.get("chart_type", "doughnut"),
        "visible_panels": form_data.getlist("visible_panels") or ["health", "metrics", "system", "requests"],
        "compact_mode": form_data.get("compact_mode") == "on"
    }
    
    # Create response
    response = JSONResponse({"status": "success", "preferences": preferences})
    
    # Set cookie
    response.set_cookie(
        "dashboard_preferences",
        json.dumps(preferences),
        max_age=60*60*24*30,  # 30 days
        httponly=True,
        samesite="lax"
    )
    
    return response

@router.post("/alerts/dismiss/{alert_id}", dependencies=[Depends(role_required("admin"))])
async def dismiss_alert(alert_id: str):
    """Dismiss an alert."""
    success = alert_manager.dismiss_alert(alert_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with ID {alert_id} not found"
        )
    
    return {"status": "success", "message": f"Alert {alert_id} dismissed"}

@router.post("/alerts/test", dependencies=[Depends(role_required("admin"))])
async def create_test_alert(request: Request):
    """Create a test alert."""
    form_data = await request.form()
    
    level = form_data.get("level", "INFO")
    alert_type = form_data.get("type", "SYSTEM")
    component = form_data.get("component", "system")
    message = form_data.get("message", "Test alert message")
    
    alert_id = alert_manager.add_alert(
        level=level,
        alert_type=alert_type,
        component=component,
        message=message,
        context={"source": "manual", "user": "admin"}
    )
    
    return {"status": "success", "alert_id": alert_id}

@router.get("/preferences", response_class=HTMLResponse, dependencies=[Depends(role_required("admin"))])
async def view_preferences(request: Request, preferences: Dict[str, Any] = Depends(get_dashboard_preferences)):
    """View and edit dashboard preferences."""
    return templates.TemplateResponse(
        "preferences.html",
        {
            "request": request,
            "title": "Dashboard Preferences",
            "preferences": preferences,
            "alerts": alert_manager.get_active_alerts(),
            "alert_count": len(alert_manager.get_active_alerts())
        }
    )