import os
import random
import logging
from flask import Flask, jsonify, request
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from pythonjsonlogger import jsonlogger

SERVICE_NAME = "auth-service"
JAEGER_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318") + "/v1/traces"
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

# Metrics
requests_total = Counter(
    "auth_requests_total", "Total auth requests", ["status"]
)
auth_duration = Histogram(
    "auth_duration_seconds", "Auth validation duration in seconds"
)


@app.route("/validate")
def validate():
    request_id = request.headers.get("X-Request-ID", "unknown")

    with tracer.start_as_current_span("auth-validate") as span:
        span.set_attribute("request.id", request_id)

        with auth_duration.time():
            # Simular validación: 90% éxito
            if random.random() < 0.9:
                requests_total.labels(status="200").inc()
                logger.info(
                    "Auth validation successful",
                    extra={"request_id": request_id, "user_id": 123},
                )
                return jsonify({"valid": True, "user_id": 123})
            else:
                requests_total.labels(status="401").inc()
                logger.warning(
                    "Auth validation failed - invalid token",
                    extra={"request_id": request_id},
                )
                return jsonify({"valid": False, "error": "Invalid token"}), 401


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "service": SERVICE_NAME})


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


if __name__ == "__main__":
    logger.info("Starting Auth Service", extra={"port": 5001})
    app.run(host="0.0.0.0", port=5001)
