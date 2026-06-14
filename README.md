# Proyecto Final Día 3 — Sistema de Monitoreo Completo

Sistema de observabilidad completo para arquitectura de microservicios con métricas, logs, trazas y alertas.

## Arquitectura

```
API Gateway (5000) ──► Auth Service (5001)
        │
        └──────────► Data Service (5002)
```

**Stack de observabilidad:**
- Prometheus + Grafana → Métricas
- Loki + Promtail → Logs
- Jaeger → Trazas distribuidas
- Alertmanager → Alertas

## Requisitos

- Podman Desktop instalado y corriendo (Lo realicé con Podman puesto que es más ligero que Docker)
- podman-compose: `pip install podman-compose`

## Levantar el proyecto

```bash
cd tareaFinal

# Construir y levantar todos los servicios
podman-compose -f docker-compose-full.yml up -d --build

# Ver logs
podman-compose -f docker-compose-full.yml logs -f

# Detener
podman-compose -f docker-compose-full.yml down
```

## URLs de acceso

| Servicio       | URL                          |
|----------------|------------------------------|
| API Gateway    | http://localhost:8080/api/data |
| Auth Service   | http://localhost:5001/validate |
| Data Service   | http://localhost:5002/data     |
| Prometheus     | http://localhost:9090          |
| Grafana        | http://localhost:3000 (admin/admin) |
| Jaeger UI      | http://localhost:16686         |
| Loki           | http://localhost:3100          |
| Alertmanager   | http://localhost:9093          |

## Generar tráfico

```bash
while true; do
  # API Gateway → auth + data
  curl -s http://localhost:8080/api/data > /dev/null
  curl -s http://localhost:8080/health > /dev/null

  # Health checks directos
  curl -s http://localhost:5001/health > /dev/null
  curl -s http://localhost:5002/health > /dev/null

  echo "Requests enviados — $(date '+%H:%M:%S')"
  sleep 0.5
done
```

## Pipeline de Seguridad

```bash
chmod +x security-pipeline.sh
./security-pipeline.sh
```

Requiere: `trufflehog`, `semgrep`, `pip-audit`, `trivy`

```bash
brew install trufflehog trivy
pip install semgrep pip-audit
```

## Dashboards Grafana

Los dashboards se provisionan automáticamente al iniciar Grafana:

1. **Service Overview** — Golden Signals (Latency, Traffic, Errors, Saturation)
2. **Business Metrics** — Métricas por servicio, auth rate, query duration
3. **Security** — Auth failures, error rates, security score, logs de seguridad

## Estructura de archivos

```
tareaFinal/
├── services/
│   ├── api-gateway.py       # API Gateway (Flask + OTEL + Prometheus)
│   ├── auth-service.py      # Auth Service (validación 90% success)
│   ├── data-service.py      # Data Service (simula BD con latencia)
│   ├── requirements.txt     # Dependencias Python
│   └── Dockerfile
├── grafana/
│   └── provisioning/
│       ├── datasources/     # Prometheus, Loki, Jaeger
│       └── dashboards/      # 3 dashboards JSON
├── docker-compose-full.yml  # Stack completo
├── prometheus.yml           # Scrape configs (3 microservicios)
├── alert-rules.yml          # 3 recording rules + 5 alertas
├── alertmanager.yml         # Routing de notificaciones
├── loki-config.yml          # Config Loki
├── promtail-config.yml      # Colección de logs por volumen
├── security-pipeline.sh     # Pipeline CI/CD de seguridad
```

## Preguntas de Reflexión

1. **¿Cómo detectarías un problema de performance?**
   Yo lo detectaría usando el dashboard Service Overview: el mapa de calor ahí colocado, muestra la latencia acumulada, y la alerta `HighLatency` dispara cuando p95 > 500ms. Por otro lado, con Jaeger se puede ver qué span específico está lento (auth vs data).

2. **¿Qué métrica es más importante: latencia o error rate?**
   Depende del escenario. El "error rate" es más urgente (usuarios no pueden usar el servicio), pero tener una latencia alta puede derivar en timeouts que generen errores. Idealmente monitorear ambos como indican los Golden Signals ayudan.

3. **¿Cómo escalarías para 10,000 req/s?**
   Haría un escalamiento horizontal de los microservicios, pero consideraría colocar un balanceador, una BD del tipo redis para el caché de auth tokens, si se puede un service mesh (Istio) para gestionar el tráfico.

4. **¿Qué vulnerabilidades identificaste?**
   - Dependencias con CVEs conocidos (trivy encontró CRITICAL=2, HIGH=14 por imagen)
   - Tokens de auth simulados (sin validación real de JWT)
   - Sin TLS entre servicios internos (tráfico en texto plano)
   - Sin validación de headers de entrada
   - Rate limiting implementado (30 req/min) para mitigar abuso

5. **¿Cómo implementarías circuit breaker?**
   Podría usar la librería `pybreaker` en api-gateway.py para cada llamada downstream. Si auth-service falla N veces consecutivas, el circuito se abre y se retorna 503 directamente sin esperar timeout.
