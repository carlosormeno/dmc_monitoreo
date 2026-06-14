import os
import uuid
import time
import logging
import requests
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from pythonjsonlogger import jsonlogger

SERVICE_NAME = "api-gateway"
JAEGER_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318") + "/v1/traces"
AUTH_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:5001")
DATA_URL = os.getenv("DATA_SERVICE_URL", "http://data-service:5002")
LOG_FILE = f"/var/log/services/{SERVICE_NAME}.log"


def setup_logger():
    logger = logging.getLogger(SERVICE_NAME)
    logger.setLevel(logging.INFO)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"levelname": "level", "asctime": "timestamp"},
    )
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


logger = setup_logger()

# OpenTelemetry setup
resource = Resource(attributes={"service.name": SERVICE_NAME})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(endpoint=JAEGER_ENDPOINT)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(SERVICE_NAME)

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

# Rate limiting: 60 req/min globales, 30 req/min en /api/data por IP
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["60 per minute"],
    storage_uri="memory://",
)

# Metrics
requests_total = Counter(
    "gateway_requests_total", "Total requests", ["endpoint", "status"]
)
request_duration = Histogram(
    "gateway_request_duration_seconds", "Request duration in seconds", ["endpoint"]
)
active_connections = Gauge("gateway_active_connections", "Active connections")
rate_limited_total = Counter(
    "gateway_rate_limited_total", "Requests rechazados por rate limit", ["endpoint"]
)


@app.errorhandler(429)
def rate_limit_handler(e):
    endpoint = request.path
    rate_limited_total.labels(endpoint=endpoint).inc()
    requests_total.labels(endpoint=endpoint, status="429").inc()
    logger.warning(
        "Rate limit exceeded",
        extra={"endpoint": endpoint, "client_ip": get_remote_address()},
    )
    return jsonify({
        "error": "Too Many Requests",
        "message": "Límite: 30 requests/minuto por IP",
        "retry_after": "60s",
    }), 429


@app.before_request
def before_request():
    active_connections.inc()
    request.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.start_time = time.time()


@app.after_request
def after_request(response):
    active_connections.dec()
    return response


@app.route("/api/data")
@limiter.limit("30 per minute")
def get_data():
    request_id = getattr(request, "request_id", str(uuid.uuid4()))
    start = time.time()

    with tracer.start_as_current_span("api-gateway-get-data") as span:
        span.set_attribute("request.id", request_id)
        span.set_attribute("http.method", "GET")
        span.set_attribute("http.url", "/api/data")
        try:
            headers = {"X-Request-ID": request_id}

            with tracer.start_as_current_span("call-auth-service"):
                auth_resp = requests.get(
                    f"{AUTH_URL}/validate", headers=headers, timeout=2
                )

            if auth_resp.status_code != 200:
                duration = time.time() - start
                requests_total.labels(endpoint="/api/data", status="401").inc()
                request_duration.labels(endpoint="/api/data").observe(duration)
                logger.warning(
                    "Auth failed", extra={"request_id": request_id, "status": 401}
                )
                return jsonify({"error": "Unauthorized"}), 401

            with tracer.start_as_current_span("call-data-service"):
                data_resp = requests.get(
                    f"{DATA_URL}/data", headers=headers, timeout=2
                )

            duration = time.time() - start
            requests_total.labels(endpoint="/api/data", status="200").inc()
            request_duration.labels(endpoint="/api/data").observe(duration)
            logger.info(
                "Request served",
                extra={"request_id": request_id, "status": 200, "duration": duration},
            )
            return data_resp.json()

        except requests.exceptions.Timeout:
            duration = time.time() - start
            requests_total.labels(endpoint="/api/data", status="504").inc()
            request_duration.labels(endpoint="/api/data").observe(duration)
            logger.error(
                "Timeout calling downstream service",
                extra={"request_id": request_id},
            )
            return jsonify({"error": "Gateway Timeout"}), 504

        except Exception as e:
            duration = time.time() - start
            requests_total.labels(endpoint="/api/data", status="500").inc()
            request_duration.labels(endpoint="/api/data").observe(duration)
            logger.error(
                "Unhandled error",
                extra={"request_id": request_id, "error": str(e)},
            )
            return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "service": SERVICE_NAME})


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


if __name__ == "__main__":
    logger.info("Starting API Gateway", extra={"port": 5000, "rate_limit": "30/min"})
    app.run(host="0.0.0.0", port=5000)
