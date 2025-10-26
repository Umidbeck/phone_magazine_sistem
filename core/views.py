# core/views.py - Health Check Endpoint
from django.http import JsonResponse
from django.db import connection
from django.core.cache import cache
import redis
import os


def health_check(request):
    """
    Health check endpoint for monitoring
    Returns status of database, cache, and application
    """
    status = {
        "status": "healthy",
        "database": "unknown",
        "cache": "unknown",
        "redis": "unknown"
    }

    http_status = 200

    # Check database
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        status["database"] = "healthy"
    except Exception as e:
        status["database"] = f"unhealthy: {str(e)}"
        status["status"] = "unhealthy"
        http_status = 503

    # Check cache
    try:
        cache.set("health_check", "ok", 10)
        if cache.get("health_check") == "ok":
            status["cache"] = "healthy"
        else:
            status["cache"] = "unhealthy"
            status["status"] = "unhealthy"
            http_status = 503
    except Exception as e:
        status["cache"] = f"unhealthy: {str(e)}"
        if os.getenv("USE_REDIS") == "True":
            status["status"] = "unhealthy"
            http_status = 503

    # Check Redis (if enabled)
    if os.getenv("USE_REDIS") == "True":
        try:
            redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/1"))
            redis_client.ping()
            status["redis"] = "healthy"
        except Exception as e:
            status["redis"] = f"unhealthy: {str(e)}"
            status["status"] = "unhealthy"
            http_status = 503
    else:
        status["redis"] = "not_configured"

    return JsonResponse(status, status=http_status)