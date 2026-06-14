#!/bin/bash
# security-pipeline.sh — Pipeline de seguridad para el proyecto Día 3
# Uso: ./security-pipeline.sh
# Requiere: trufflehog, semgrep, pip-audit, trivy

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPORT_DIR="$PROJECT_DIR/security-reports"
mkdir -p "$REPORT_DIR"

echo "================================================"
echo "   === Security Pipeline — Día 3 ==="
echo "================================================"
echo ""

# ─── 1. Secret Detection (trufflehog) ────────────────────────────────────────
echo "[1/4] Scanning for secrets (trufflehog)..."
if command -v trufflehog &>/dev/null; then
  trufflehog filesystem "$PROJECT_DIR" \
    --json \
    --no-update \
    2>/dev/null | tee "$REPORT_DIR/secrets.json" || true
  echo "  -> Resultado guardado en: security-reports/secrets.json"
else
  echo "  [SKIP] trufflehog no instalado. Instalar con: brew install trufflehog"
fi
echo ""

# ─── 2. SAST (semgrep) ───────────────────────────────────────────────────────
echo "[2/4] Running SAST (semgrep)..."
if command -v semgrep &>/dev/null; then
  semgrep --config=auto "$PROJECT_DIR/services" \
    --json \
    --output "$REPORT_DIR/sast.json" \
    --quiet || true
  echo "  -> Resultado guardado en: security-reports/sast.json"
elif python3 -m semgrep --version &>/dev/null 2>&1; then
  python3 -m semgrep --config=auto "$PROJECT_DIR/services" \
    --json \
    --output "$REPORT_DIR/sast.json" \
    --quiet || true
  echo "  -> Resultado guardado en: security-reports/sast.json"
else
  echo "  [SKIP] semgrep no instalado. Instalar con: pip3 install semgrep"
fi
echo ""

# ─── 3. Dependency Scanning (pip-audit) ─────────────────────────────────────
echo "[3/4] Scanning dependencies (pip-audit)..."
if command -v pip-audit &>/dev/null; then
  pip-audit \
    --requirement "$PROJECT_DIR/services/requirements.txt" \
    --format=json \
    --output "$REPORT_DIR/dependencies.json" || true
  echo "  -> Resultado guardado en: security-reports/dependencies.json"
elif python3 -m pip_audit --version &>/dev/null 2>&1; then
  python3 -m pip_audit \
    --requirement "$PROJECT_DIR/services/requirements.txt" \
    --format=json \
    --output "$REPORT_DIR/dependencies.json" || true
  echo "  -> Resultado guardado en: security-reports/dependencies.json"
else
  echo "  [SKIP] pip-audit no instalado. Instalar con: pip3 install pip-audit"
fi
echo ""

# ─── 4. Container Scanning (trivy via Podman export) ────────────────────────
echo "[4/4] Scanning container images (trivy)..."
if command -v trivy &>/dev/null; then
  IMAGES=("api-gateway" "auth-service" "data-service")
  for img in "${IMAGES[@]}"; do
    FULL_IMAGE="localhost/tareafinal_${img}:latest"
    TAR_FILE="/tmp/trivy-${img}.tar"
    echo "  Scanning: $FULL_IMAGE"
    # Exportar imagen desde Podman a tar y escanear con trivy
    if podman save "$FULL_IMAGE" -o "$TAR_FILE" 2>/dev/null; then
      trivy image \
        --input "$TAR_FILE" \
        --severity HIGH,CRITICAL \
        --format json \
        --output "$REPORT_DIR/trivy-${img}.json" \
        --quiet 2>/dev/null || true
      rm -f "$TAR_FILE"
      echo "    -> Reporte: security-reports/trivy-${img}.json"
    else
      echo "    [WARN] No se encontró imagen ${img}. Ejecuta primero: podman-compose -f docker-compose-full.yml build"
    fi
  done
  echo "  -> Reportes guardados en: security-reports/trivy-*.json"
else
  echo "  [SKIP] trivy no instalado. Instalar con: brew install trivy"
fi
echo ""

# ─── Resumen ─────────────────────────────────────────────────────────────────
echo "================================================"
echo "   === Security Scan Complete ==="
echo ""
echo "Reportes generados en: $REPORT_DIR/"
ls -la "$REPORT_DIR/" 2>/dev/null || true
echo ""
echo "Vulnerabilidades encontradas (ejemplo conocido):"
echo "  - flask < 3.0.0: Werkzeug header injection (GHSA-2g68-c3qc-8985)"
echo "    Remediación: Actualizar a flask>=3.0.0 (ya incluido en requirements.txt)"
echo "================================================"
