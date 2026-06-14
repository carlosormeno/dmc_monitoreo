import os
import time
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

SERVICE_NAME = "data-service"
JAEGER_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318") + "/v1/traces"
LOG_FILE = f"/var/log/services/{SERVICE_NAME}.log"

MOCK_DB = [
    {"id": 1, "name": "Producto Alpha", "price": 29.99},
    {"id": 2, "name": "Producto Beta", "price": 49.99},
    {"id": 3, "name": "Producto Gamma", "price": 19.99},
]


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
requests_total = Counter("data_requests_total", "Total data requests")
query_duration = Histogram(
    "data_query_duration_seconds", "Database query duration in seconds"
)


@app.route("/data")
def get_data():
    request_id = request.headers.get("X-Request-ID", "unknown")

    with tracer.start_as_current_span("data-service-query") as span:
        span.set_attribute("request.id", request_id)
        span.set_attribute("db.type", "mock")

        with tracer.start_as_current_span("database-query") as db_span:
            db_span.set_attribute("db.statement", "SELECT * FROM products")
            with query_duration.time():
                # Simular latencia de BD entre 100ms y 500ms
                time.sleep(random.uniform(0.1, 0.5))

        requests_total.inc()
        logger.info(
            "Data retrieved successfully",
            extra={"request_id": request_id, "records": len(MOCK_DB)},
        )
        return jsonify({"data": MOCK_DB, "count": len(MOCK_DB)})


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "service": SERVICE_NAME})


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


if __name__ == "__main__":
    logger.info("Starting Data Service", extra={"port": 5002})
    app.run(host="0.0.0.0", port=5002)
