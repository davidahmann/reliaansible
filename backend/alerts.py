"""
Alert manager for Relia OSS.

This module provides:
- Alert creation and management
- Alert levels (INFO, WARNING, CRITICAL)
- Alert types (SYSTEM, SECURITY, PERFORMANCE)
- Alert history
"""
import json
import uuid
import logging
import threading
import smtplib
import ssl
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional, Callable, Union
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from .config import settings

# Configure logger
logger = logging.getLogger(__name__)

class AlertLevel(str, Enum):
    """Alert severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

class AlertType(str, Enum):
    """Types of alerts."""
    SYSTEM = "SYSTEM"  # System health and status
    SECURITY = "SECURITY"  # Security-related alerts
    PERFORMANCE = "PERFORMANCE"  # Performance issues
    DATABASE = "DATABASE"  # Database-related alerts
    API = "API"  # API-related alerts
    LLM = "LLM"  # LLM service-related alerts
    MONITORING = "MONITORING"  # Monitoring system alerts
    USER = "USER"  # User-related alerts

class AlertManager:
    """Manage system alerts."""
    
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls):
        """Create a singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AlertManager, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance
    
    def _initialize(self):
        """Initialize the alert manager."""
        self.active_alerts: Dict[str, Dict[str, Any]] = {}
        self.alert_history: List[Dict[str, Any]] = []
        self.alert_handlers: Dict[str, List[Callable]] = {
            AlertLevel.INFO: [],
            AlertLevel.WARNING: [],
            AlertLevel.CRITICAL: [],
        }
        
        # Register default handlers
        self._register_default_handlers()
    
    def _register_default_handlers(self):
        """Register default alert handlers."""
        # Log all alerts
        self.register_handler(None, self._log_alert_handler)
        
        # Send email for critical alerts if email is configured
        if hasattr(settings, "EMAIL_ENABLED") and settings.EMAIL_ENABLED:
            self.register_handler(AlertLevel.CRITICAL, self._email_alert_handler)
    
    def register_handler(self, level: Optional[AlertLevel], handler: Callable):
        """Register an alert handler.
        
        Args:
            level: Alert level to handle, or None to handle all levels
            handler: Handler function with signature (alert: Dict[str, Any]) -> None
        """
        if level is None:
            # Register for all levels
            for lvl in AlertLevel:
                if handler not in self.alert_handlers[lvl]:
                    self.alert_handlers[lvl].append(handler)
        else:
            # Register for specific level
            if handler not in self.alert_handlers[level]:
                self.alert_handlers[level].append(handler)
    
    def unregister_handler(self, level: Optional[AlertLevel], handler: Callable):
        """Unregister an alert handler.
        
        Args:
            level: Alert level the handler was registered for, or None for all levels
            handler: Handler function to unregister
        """
        if level is None:
            # Unregister from all levels
            for lvl in AlertLevel:
                if handler in self.alert_handlers[lvl]:
                    self.alert_handlers[lvl].remove(handler)
        else:
            # Unregister from specific level
            if handler in self.alert_handlers[level]:
                self.alert_handlers[level].remove(handler)
    
    def add_alert(
        self, 
        level: Union[AlertLevel, str], 
        alert_type: Union[AlertType, str], 
        component: str,
        message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add a new alert.
        
        Args:
            level: Alert level (INFO, WARNING, CRITICAL)
            alert_type: Alert type
            component: Component that triggered the alert
            message: Alert message
            context: Additional context information
            
        Returns:
            Alert ID
        """
        # Standardize inputs
        if isinstance(level, str):
            level = AlertLevel(level)
        if isinstance(alert_type, str):
            alert_type = AlertType(alert_type)
        
        # Generate alert ID
        alert_id = str(uuid.uuid4())
        
        # Create alert object
        alert = {
            "id": alert_id,
            "level": level,
            "type": alert_type,
            "component": component,
            "message": message,
            "context": context or {},
            "created_at": datetime.utcnow().isoformat(),
            "acknowledged": False,
            "acknowledged_at": None,
            "acknowledged_by": None,
        }
        
        # Store in active alerts
        with self._lock:
            self.active_alerts[alert_id] = alert
            
            # Add to history
            self.alert_history.append(alert.copy())
            
            # Limit history size
            max_history = getattr(settings, "ALERT_HISTORY_SIZE", 1000)
            if len(self.alert_history) > max_history:
                self.alert_history = self.alert_history[-max_history:]
        
        # Trigger handlers
        self._trigger_handlers(alert)
        
        return alert_id
    
    def dismiss_alert(self, alert_id: str, user_id: str = "admin") -> bool:
        """Dismiss an active alert.
        
        Args:
            alert_id: ID of the alert to dismiss
            user_id: ID of the user dismissing the alert
            
        Returns:
            True if alert was dismissed, False if not found
        """
        with self._lock:
            if alert_id in self.active_alerts:
                # Update alert in both active and history
                self.active_alerts[alert_id]["acknowledged"] = True
                self.active_alerts[alert_id]["acknowledged_at"] = datetime.utcnow().isoformat()
                self.active_alerts[alert_id]["acknowledged_by"] = user_id
                
                # Find alert in history and update it
                for alert in self.alert_history:
                    if alert["id"] == alert_id:
                        alert["acknowledged"] = True
                        alert["acknowledged_at"] = datetime.utcnow().isoformat()
                        alert["acknowledged_by"] = user_id
                        break
                
                # Remove from active alerts
                dismissed_alert = self.active_alerts.pop(alert_id)
                
                # Log dismissal
                logger.info(
                    f"Alert dismissed: {dismissed_alert['level']} - {dismissed_alert['message']}",
                    extra={"alert_id": alert_id, "user_id": user_id}
                )
                
                return True
            
            return False
    
    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get all active (undismissed) alerts.
        
        Returns:
            List of active alerts
        """
        with self._lock:
            return list(self.active_alerts.values())
    
    def get_alert_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get alert history.
        
        Args:
            limit: Maximum number of alerts to return
            
        Returns:
            List of historical alerts
        """
        with self._lock:
            # Return most recent alerts first
            return sorted(
                self.alert_history,
                key=lambda a: a["created_at"],
                reverse=True
            )[:limit]
    
    def get_alert(self, alert_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific alert by ID.
        
        Args:
            alert_id: ID of the alert
            
        Returns:
            Alert object or None if not found
        """
        # Check active alerts first
        with self._lock:
            if alert_id in self.active_alerts:
                return self.active_alerts[alert_id]
            
            # Check history
            for alert in self.alert_history:
                if alert["id"] == alert_id:
                    return alert
            
            return None
    
    def _trigger_handlers(self, alert: Dict[str, Any]):
        """Trigger all registered handlers for an alert.
        
        Args:
            alert: Alert object
        """
        level = alert["level"]
        
        # Run handlers in a separate thread to avoid blocking
        def run_handlers():
            for handler in self.alert_handlers[level]:
                try:
                    handler(alert)
                except Exception as e:
                    logger.error(f"Error in alert handler: {e}", exc_info=True)
        
        # Start handler thread
        thread = threading.Thread(target=run_handlers)
        thread.daemon = True
        thread.start()
    
    def _log_alert_handler(self, alert: Dict[str, Any]):
        """Default handler that logs all alerts.
        
        Args:
            alert: Alert object
        """
        level_name = alert["level"]
        log_level = getattr(logging, str(level_name))
        
        # Create log message
        message = f"ALERT [{alert['type']}] {alert['component']}: {alert['message']}"
        
        # Add extra context for structured logging
        extra = {
            "alert_id": alert["id"],
            "alert_type": alert["type"],
            "component": alert["component"],
            "context": alert["context"]
        }
        
        # Log with appropriate level
        logger.log(log_level, message, extra=extra)
    
    def _email_alert_handler(self, alert: Dict[str, Any]):
        """Default handler that sends emails for critical alerts.
        
        Args:
            alert: Alert object
        """
        # Only send for critical alerts
        if alert["level"] != AlertLevel.CRITICAL:
            return
        
        # Check if email is configured
        if not hasattr(settings, "EMAIL_ENABLED") or not settings.EMAIL_ENABLED:
            return
        
        try:
            # Create email
            msg = MIMEMultipart()
            msg["Subject"] = f"CRITICAL ALERT: {alert['component']} - {alert['message'][:50]}"
            msg["From"] = settings.EMAIL_FROM
            msg["To"] = settings.EMAIL_TO
            
            # Create email body
            html = f"""
            <html>
            <body>
                <h2>CRITICAL ALERT from Relia</h2>
                <p><strong>Component:</strong> {alert['component']}</p>
                <p><strong>Type:</strong> {alert['type']}</p>
                <p><strong>Message:</strong> {alert['message']}</p>
                <p><strong>Time:</strong> {alert['created_at']}</p>
                <h3>Context:</h3>
                <pre>{json.dumps(alert['context'], indent=2)}</pre>
                <p>
                    <a href="{settings.BASE_URL}/dashboard/alerts">
                        View in Dashboard
                    </a>
                </p>
            </body>
            </html>
            """
            
            # Attach HTML part
            msg.attach(MIMEText(html, "html"))
            
            # Send email
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings.EMAIL_HOST, settings.EMAIL_PORT, context=context) as server:
                server.login(settings.EMAIL_USERNAME, settings.EMAIL_PASSWORD)
                server.sendmail(settings.EMAIL_FROM, settings.EMAIL_TO, msg.as_string())
            
            logger.info(f"Sent alert email for alert {alert['id']}")
        except Exception as e:
            logger.error(f"Failed to send alert email: {e}", exc_info=True)

# Create a function to get the alert manager singleton
_alert_manager = None

def get_alert_manager() -> AlertManager:
    """Get the alert manager singleton instance."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager