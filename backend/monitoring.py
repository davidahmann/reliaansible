"""
Monitoring and health check utilities for the Relia backend.

This module provides functions for monitoring system health, checking service
status, and collecting metrics about system resources and application performance.
"""
import os
import logging
import platform
import time
import threading
import tempfile
import multiprocessing
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum
import psutil

from .config import settings
from .llm_adapter import get_client, LLMError
from . import database
from . import tasks

# Configure logger
logger = logging.getLogger(__name__)

class HealthStatus(str, Enum):
    """Health status for components."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

class Component(str, Enum):
    """Components to check for health."""
    SYSTEM = "system"
    DATABASE = "database"
    LLM = "llm"
    TASK_QUEUE = "task_queue"
    STORAGE = "storage"
    CACHE = "cache"

class SystemInfo:
    """System information collector."""
    
    @classmethod
    def get_system_info(cls) -> Dict[str, Any]:
        """Get basic system information."""
        cpu_count = multiprocessing.cpu_count()
        
        return {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu_count": cpu_count,
            "cpu_model": cls._get_cpu_model(),
            "memory_total": psutil.virtual_memory().total,
            "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
            "process_id": os.getpid(),
            "process_start_time": cls._get_process_start_time(),
            "environment": settings.ENV,
        }
    
    @classmethod
    def get_process_info(cls) -> Dict[str, Any]:
        """Get information about the current process."""
        process = psutil.Process()
        
        cpu_percent = process.cpu_percent(interval=0.1)
        memory_info = process.memory_info()
        
        return {
            "cpu_percent": cpu_percent,
            "memory_rss": memory_info.rss,  # Resident Set Size
            "memory_vms": memory_info.vms,  # Virtual Memory Size
            "threads": len(process.threads()),
            "open_files": len(process.open_files()),
            "connections": len(process.connections()),
            "uptime_seconds": time.time() - process.create_time(),
        }
    
    @classmethod
    def get_resource_usage(cls) -> Dict[str, Any]:
        """Get system resource usage."""
        return {
            "cpu": {
                "percent": psutil.cpu_percent(interval=0.1),
                "percent_per_cpu": psutil.cpu_percent(interval=0.1, percpu=True),
                "count": multiprocessing.cpu_count(),
            },
            "memory": {
                "total": psutil.virtual_memory().total,
                "available": psutil.virtual_memory().available,
                "percent": psutil.virtual_memory().percent,
                "used": psutil.virtual_memory().used,
                "free": psutil.virtual_memory().free,
            },
            "disk": cls._get_disk_usage(),
            "network": {
                "bytes_sent": psutil.net_io_counters().bytes_sent,
                "bytes_recv": psutil.net_io_counters().bytes_recv,
                "packets_sent": psutil.net_io_counters().packets_sent,
                "packets_recv": psutil.net_io_counters().packets_recv,
            },
        }
    
    @staticmethod
    def _get_cpu_model() -> str:
        """Get CPU model information."""
        try:
            if platform.system() == "Windows":
                return platform.processor()
            elif platform.system() == "Darwin":
                import subprocess
                output = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"]).decode("utf-8").strip()
                return output
            elif platform.system() == "Linux":
                with open("/proc/cpuinfo") as f:
                    for line in f:
                        if line.strip().startswith("model name"):
                            return line.split(":", 1)[1].strip()
            return "Unknown CPU"
        except Exception as e:
            logger.warning(f"Failed to get CPU model: {e}")
            return "Unknown CPU"
    
    @staticmethod
    def _get_process_start_time() -> str:
        """Get the start time of the current process."""
        try:
            process = psutil.Process()
            return datetime.fromtimestamp(process.create_time()).isoformat()
        except Exception as e:
            logger.warning(f"Failed to get process start time: {e}")
            return "Unknown"
    
    @staticmethod
    def _get_disk_usage() -> Dict[str, Any]:
        """Get disk usage for important directories."""
        result = {}
        
        # Application directory
        app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        app_usage = psutil.disk_usage(app_dir)
        result["app_directory"] = {
            "total": app_usage.total,
            "used": app_usage.used,
            "free": app_usage.free,
            "percent": app_usage.percent,
            "path": app_dir,
        }
        
        # Data directory
        if settings.DATA_DIR.exists():
            data_usage = psutil.disk_usage(str(settings.DATA_DIR))
            result["data_directory"] = {
                "total": data_usage.total,
                "used": data_usage.used,
                "free": data_usage.free,
                "percent": data_usage.percent,
                "path": str(settings.DATA_DIR),
            }
        
        # Playbook directory
        if settings.PLAYBOOK_DIR.exists():
            playbook_usage = psutil.disk_usage(str(settings.PLAYBOOK_DIR))
            result["playbook_directory"] = {
                "total": playbook_usage.total,
                "used": playbook_usage.used,
                "free": playbook_usage.free,
                "percent": playbook_usage.percent,
                "path": str(settings.PLAYBOOK_DIR),
            }
        
        # Temp directory
        temp_dir = tempfile.gettempdir()
        temp_usage = psutil.disk_usage(temp_dir)
        result["temp_directory"] = {
            "total": temp_usage.total,
            "used": temp_usage.used,
            "free": temp_usage.free,
            "percent": temp_usage.percent,
            "path": temp_dir,
        }
        
        return result

class HealthCheck:
    """Health check utilities."""
    
    # Cache for health check results
    _health_cache = {}
    _health_cache_lock = threading.RLock()
    _last_health_check = 0
    _health_check_ttl = 60  # seconds
    
    @classmethod
    def check_health(cls) -> Dict[str, Any]:
        """Run a comprehensive health check of all components.
        
        Uses a time-based cache to avoid performing expensive health checks too frequently.
        """
        # Check if we have a fresh cached result
        current_time = time.time()
        with cls._health_cache_lock:
            if cls._last_health_check > 0 and (current_time - cls._last_health_check) < cls._health_check_ttl:
                if 'health_result' in cls._health_cache:
                    # Update the timestamp in the cached result
                    cached_result = cls._health_cache['health_result'].copy()
                    cached_result['meta']['cache_hit'] = True
                    cached_result['meta']['cache_age'] = current_time - cls._last_health_check
                    return cached_result
        
        # Set up for parallel health check execution
        from concurrent.futures import ThreadPoolExecutor
        executor = ThreadPoolExecutor(max_workers=6)
        
        # Start all health checks in parallel
        futures = {
            Component.SYSTEM: executor.submit(cls.check_system_health),
            Component.DATABASE: executor.submit(cls.check_database_health),
            Component.LLM: executor.submit(cls.check_llm_health),
            Component.TASK_QUEUE: executor.submit(cls.check_task_queue_health),
            Component.STORAGE: executor.submit(cls.check_storage_health),
            Component.CACHE: executor.submit(cls.check_cache_health)
        }
        
        # Collect results as they complete
        results = {}
        for component, future in futures.items():
            try:
                results[component] = future.result()
            except Exception as e:
                logger.exception(f"Health check for {component} failed: {e}")
                results[component] = {
                    "status": HealthStatus.UNKNOWN,
                    "details": {"error": str(e)}
                }
        
        # Determine overall status
        overall_status = HealthStatus.HEALTHY
        component_statuses = [result["status"] for result in results.values()]
        
        if HealthStatus.UNHEALTHY in component_statuses:
            overall_status = HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in component_statuses:
            overall_status = HealthStatus.DEGRADED
        
        # Add meta information
        meta = {
            "timestamp": datetime.utcnow().isoformat(),
            "version": getattr(settings, "VERSION", "unknown"),
            "environment": settings.ENV,
            "cache_hit": False,
            "check_duration_ms": int((time.time() - current_time) * 1000)
        }
        
        health_result = {
            "status": overall_status,
            "components": results,
            "meta": meta,
        }
        
        # Cache the result
        with cls._health_cache_lock:
            cls._health_cache['health_result'] = health_result
            cls._last_health_check = current_time
        
        return health_result
    
    @classmethod
    def check_system_health(cls) -> Dict[str, Any]:
        """Check system health."""
        try:
            status = HealthStatus.HEALTHY
            details = {}
            
            # Check CPU usage
            cpu_percent = psutil.cpu_percent(interval=0.1)
            if cpu_percent > 90:
                status = HealthStatus.DEGRADED
                details["high_cpu_usage"] = cpu_percent
            
            # Check memory usage
            memory = psutil.virtual_memory()
            if memory.percent > 90:
                status = HealthStatus.DEGRADED
                details["high_memory_usage"] = memory.percent
            
            # Check disk space
            for disk_name, disk_info in SystemInfo._get_disk_usage().items():
                if disk_info["percent"] > 90:
                    status = HealthStatus.DEGRADED
                    details[f"high_disk_usage_{disk_name}"] = disk_info["percent"]
            
            return {
                "status": status,
                "details": details,
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
            }
        except Exception as e:
            logger.error(f"System health check failed: {e}")
            return {
                "status": HealthStatus.UNKNOWN,
                "details": {"error": str(e)},
            }
    
    @classmethod
    def check_database_health(cls) -> Dict[str, Any]:
        """Check database health."""
        if not settings.DB_ENABLED:
            return {
                "status": HealthStatus.UNKNOWN,
                "details": {"message": "Database is disabled"},
            }
        
        try:
            # Get a connection
            start_time = time.time()
            db = database.get_db()
            
            # Run a simple query
            cursor = db.execute("SELECT 1")
            result = cursor.fetchone()
            
            # Check that the query succeeded
            if result and result[0] == 1:
                duration_ms = (time.time() - start_time) * 1000
                
                # Check response time
                if duration_ms > 500:  # Slow response
                    return {
                        "status": HealthStatus.DEGRADED,
                        "details": {"slow_response_time": duration_ms},
                        "response_time_ms": duration_ms,
                    }
                else:
                    return {
                        "status": HealthStatus.HEALTHY,
                        "details": {},
                        "response_time_ms": duration_ms,
                    }
            else:
                return {
                    "status": HealthStatus.UNHEALTHY,
                    "details": {"unexpected_result": str(result)},
                }
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                "status": HealthStatus.UNHEALTHY,
                "details": {"error": str(e)},
            }
    
    @classmethod
    def check_llm_health(cls) -> Dict[str, Any]:
        """Check LLM service health."""
        try:
            # Get LLM client
            llm_client = get_client()
            
            # Send a minimal ping prompt
            start_time = time.time()
            llm_provider = getattr(llm_client, "model", "unknown")
            
            try:
                # We won't actually call the LLM API here to avoid costs
                # Instead, we'll just check if the client can be initialized
                duration_ms = (time.time() - start_time) * 1000
                
                return {
                    "status": HealthStatus.HEALTHY,
                    "details": {"provider": llm_provider},
                    "response_time_ms": duration_ms,
                }
            except LLMError as e:
                return {
                    "status": HealthStatus.UNHEALTHY,
                    "details": {"error": str(e), "provider": llm_provider},
                }
            
        except Exception as e:
            logger.error(f"LLM health check failed: {e}")
            return {
                "status": HealthStatus.UNHEALTHY,
                "details": {"error": str(e)},
            }
    
    @classmethod
    def check_task_queue_health(cls) -> Dict[str, Any]:
        """Check task queue health."""
        try:
            # Get task queue
            task_queue = tasks.get_task_queue()
            
            # Get queue stats
            active_tasks = len([t for t in task_queue.tasks.values() 
                               if t.status == tasks.TaskStatus.RUNNING])
            pending_tasks = len([t for t in task_queue.tasks.values() 
                                if t.status == tasks.TaskStatus.PENDING])
            total_tasks = len(task_queue.tasks)
            
            # Check if queue is overloaded
            if pending_tasks > settings.TASK_MAX_WORKERS * 10:
                return {
                    "status": HealthStatus.DEGRADED,
                    "details": {"high_pending_tasks": pending_tasks},
                    "active_tasks": active_tasks,
                    "pending_tasks": pending_tasks,
                    "total_tasks": total_tasks,
                }
            
            return {
                "status": HealthStatus.HEALTHY,
                "details": {},
                "active_tasks": active_tasks,
                "pending_tasks": pending_tasks,
                "total_tasks": total_tasks,
                "max_workers": settings.TASK_MAX_WORKERS,
            }
        except Exception as e:
            logger.error(f"Task queue health check failed: {e}")
            return {
                "status": HealthStatus.UNKNOWN,
                "details": {"error": str(e)},
            }
    
    @classmethod
    def check_storage_health(cls) -> Dict[str, Any]:
        """Check storage health."""
        try:
            status = HealthStatus.HEALTHY
            details = {}
            
            # Check if directories exist
            if not settings.DATA_DIR.exists():
                status = HealthStatus.DEGRADED
                details["data_dir_missing"] = str(settings.DATA_DIR)
            
            if not settings.PLAYBOOK_DIR.exists():
                status = HealthStatus.DEGRADED
                details["playbook_dir_missing"] = str(settings.PLAYBOOK_DIR)
            
            # Check disk space
            disk_usage = SystemInfo._get_disk_usage()
            
            # Check data directory space
            if "data_directory" in disk_usage and disk_usage["data_directory"]["percent"] > 90:
                status = HealthStatus.DEGRADED
                details["data_dir_low_space"] = disk_usage["data_directory"]["percent"]
            
            # Check playbook directory space
            if "playbook_directory" in disk_usage and disk_usage["playbook_directory"]["percent"] > 90:
                status = HealthStatus.DEGRADED
                details["playbook_dir_low_space"] = disk_usage["playbook_directory"]["percent"]
            
            # Check if playbooks are accessible
            sample_playbooks = list(settings.PLAYBOOK_DIR.glob("*.yml"))[:5]
            inaccessible_playbooks = [str(p) for p in sample_playbooks if not os.access(p, os.R_OK)]
            
            if inaccessible_playbooks:
                status = HealthStatus.DEGRADED
                details["inaccessible_playbooks"] = inaccessible_playbooks
            
            return {
                "status": status,
                "details": details,
                "data_dir": str(settings.DATA_DIR),
                "playbook_dir": str(settings.PLAYBOOK_DIR),
                "playbook_count": len(list(settings.PLAYBOOK_DIR.glob("*.yml"))),
            }
        except Exception as e:
            logger.error(f"Storage health check failed: {e}")
            return {
                "status": HealthStatus.UNKNOWN,
                "details": {"error": str(e)},
            }
    
    @classmethod
    def check_cache_health(cls) -> Dict[str, Any]:
        """Check cache health."""
        from . import cache
        
        try:
            # Get cache stats
            schema_stats = cache.schema_cache.stats()
            llm_stats = cache.llm_cache.stats()
            playbook_stats = cache.playbook_cache.stats()
            
            # Check memory usage of the process
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_percent = memory_info.rss / psutil.virtual_memory().total * 100
            
            # Check if memory usage is high and cache size is substantial
            total_cache_entries = schema_stats["size"] + llm_stats["size"] + playbook_stats["size"]
            
            status = HealthStatus.HEALTHY
            details = {}
            
            if memory_percent > 80 and total_cache_entries > 1000:
                status = HealthStatus.DEGRADED
                details["high_memory_usage"] = memory_percent
                details["large_cache_size"] = total_cache_entries
            
            return {
                "status": status,
                "details": details,
                "schema_cache_size": schema_stats["size"],
                "llm_cache_size": llm_stats["size"],
                "playbook_cache_size": playbook_stats["size"],
                "total_cache_entries": total_cache_entries,
            }
        except Exception as e:
            logger.error(f"Cache health check failed: {e}")
            return {
                "status": HealthStatus.UNKNOWN,
                "details": {"error": str(e)},
            }

class Metrics:
    """Application metrics collector."""
    
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Metrics, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance
    
    def _initialize(self):
        """Initialize the metrics collector."""
        self.start_time = time.time()
        self.metrics = {
            "requests": {
                "total": 0,
                "by_endpoint": {},
                "by_status": {},
            },
            "llm": {
                "calls": 0,
                "tokens": 0,
                "errors": 0,
                "cache_hits": 0,
                "cache_misses": 0,
            },
            "tasks": {
                "created": 0,
                "completed": 0,
                "failed": 0,
                "canceled": 0,
            },
            "playbooks": {
                "generated": 0,
                "linted": 0,
                "tested": 0,
            },
        }
    
    def record_request(self, endpoint: str, status_code: int):
        """Record an API request."""
        with self._lock:
            self.metrics["requests"]["total"] += 1
            
            # By endpoint
            if endpoint not in self.metrics["requests"]["by_endpoint"]:
                self.metrics["requests"]["by_endpoint"][endpoint] = 0
            self.metrics["requests"]["by_endpoint"][endpoint] += 1
            
            # By status
            status_key = str(status_code)
            if status_key not in self.metrics["requests"]["by_status"]:
                self.metrics["requests"]["by_status"][status_key] = 0
            self.metrics["requests"]["by_status"][status_key] += 1
    
    def record_llm_call(self, tokens: int = 0, is_cache_hit: bool = False, is_error: bool = False):
        """Record an LLM API call."""
        with self._lock:
            if not is_cache_hit:
                self.metrics["llm"]["calls"] += 1
                self.metrics["llm"]["tokens"] += tokens
            
            if is_error:
                self.metrics["llm"]["errors"] += 1
            
            if is_cache_hit:
                self.metrics["llm"]["cache_hits"] += 1
            else:
                self.metrics["llm"]["cache_misses"] += 1
    
    def record_task_event(self, event_type: str):
        """Record a task event."""
        with self._lock:
            if event_type in ["created", "completed", "failed", "canceled"]:
                self.metrics["tasks"][event_type] += 1
    
    def record_playbook_event(self, event_type: str):
        """Record a playbook event."""
        with self._lock:
            if event_type in ["generated", "linted", "tested"]:
                self.metrics["playbooks"][event_type] += 1
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics."""
        with self._lock:
            uptime_seconds = time.time() - self.start_time
            requests_per_minute = self.metrics["requests"]["total"] / (uptime_seconds / 60)
            
            result = {
                "uptime_seconds": uptime_seconds,
                "requests_per_minute": requests_per_minute,
                "metrics": self.metrics,
            }
            
            # Add system metrics
            result.update({
                "system": SystemInfo.get_resource_usage(),
                "process": SystemInfo.get_process_info(),
            })
            
            return result
    
    def reset_metrics(self):
        """Reset all metrics."""
        with self._lock:
            self._initialize()

# Global metrics instance
_metrics: Optional[Metrics] = None

def get_metrics() -> Metrics:
    """Get the global metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = Metrics()
    return _metrics