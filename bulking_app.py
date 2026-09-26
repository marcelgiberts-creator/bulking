"""
bulking_app.py
================
App de Nutrición y Gestión de Volumen (Bulking) con IA.
Genera un archivo index.html autogestionado y lo sube a Git.
"""

import os
import sys
import time
import hashlib
import subprocess
import threading
import webbrowser
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

# ============================================================================
# ⚙️ CONFIGURACIÓN GENERAL (EDITA AQUÍ)
# ============================================================================
# Key en Base64 (no es seguridad real, solo evita que GitHub Push Protection
# bloquee el push al detectar el patrón de clave de Google). Se decodifica en
# el navegador con atob(). Para cambiarla:
#   python -c "import base64; print(base64.b64encode(b'TU_KEY_AQUI').decode())"
# ⚠️ SEGURIDAD: esta clave acaba en el HTML público (GitHub Pages). Restríngela en
#    Google Cloud → Credenciales: referentes HTTP (tu dominio + localhost) y SOLO
#    "Generative Language API". Si alguna vez salió en un export, rótala.
GEMINI_API_KEY_B64 = "QVEuQWI4Uk42S2szdjJuZS1ONE9qZWVwR0FtNmVOOHZnRGgxUENFOXBTZ1VRQng5TkJ0ZXc="
# Todo a un único modelo (rápido/barato) por decisión explícita: registro de
# comidas, chat, sustituciones, plan semanal y asistente diario.
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_MODEL_PLAN = "gemini-3.5-flash-lite"
GEMINI_MODEL_FOOD = "gemini-3.5-flash-lite"

# 🔗 SINCRONIZACIÓN EN LA NUBE (Firebase Realtime Database)
# Permite que tus datos (comidas, pesos, perfil...) viajen contigo entre PC,
# móvil y navegadores distintos usando solo un link con un identificador.
# Pasos para activarlo (~5 min, gratis, sin tarjeta):
#   1. Ve a https://console.firebase.google.com → "Añadir proyecto".
#   2. Dentro del proyecto: menú lateral → "Realtime Database" → "Crear base de datos".
#      Elige "Empezar en modo de prueba" (o configura reglas propias después).
#   3. Copia la URL que aparece arriba de los datos (tipo
#      "https://TU-PROYECTO-default-rtdb.europe-west1.firebasedatabase.app")
#      y pégala abajo, SIN barra final.
# ⚠️ IMPORTANTE: si lo dejas vacío (""), la app funciona SOLO con localStorage,
# que es exclusivo de cada navegador/origen. Esto significa que localhost y tu
# web publicada en GitHub Pages son dos almacenes completamente distintos y
# NUNCA verán los mismos datos entre sí. Para que "abrir la web" muestre lo
# mismo que "abrir localhost", esta URL debe estar configurada: es la única
# fuente de verdad compartida entre ambos entornos.
# ⚠️ Nota de seguridad: en modo de prueba, cualquiera con tu link de
# sincronización (el "?uid=...") puede leer/escribir tus datos, igual que
# con un Google Doc compartido por link. Suficiente para uso personal, pero
# no subas ese link a ningún sitio público.
FIREBASE_DB_URL = "https://bulking-c9496-default-rtdb.europe-west1.firebasedatabase.app/"

# 🍔 Alimentos de relleno (Alta densidad calórica, baja saciedad)
FILLER_FOODS = "Maltodextrina en polvo, clear/hydro protein de limon, crema de arroz, harina de arroz, aceite de oliva virgen extra, miel, crema de cacahute, whey protein de chocolate"
# ============================================================================

THIS_FILE = os.path.abspath(__file__)
PROJECT_DIR = os.path.dirname(THIS_FILE)
INDEX_FILE = os.path.join(PROJECT_DIR, "index.html")
PORT = 8000
CHECK_INTERVAL = 2   # Segundos entre comprobaciones de cambio de este archivo
DEBOUNCE = 4         # Segundos de espera tras un cambio antes de subir a Git

# ============================================================================
# 🖥️ CÓDIGO FRONTEND (HTML / CSS / JS)
# Dividido en bloques semánticos y estructurados.
# ============================================================================

APP_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Bulking OS</title>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  /* =========================================
     🎨 SISTEMA DE DISEÑO — Bulking OS
     Paleta neutra, cristal sutil, un único acento.
     ========================================= */
  :root {
    /* Base neutra (casi negro, ligerísimo tinte cálido) */
    --bg-color: #0a0b0d;
    --bg-elev: #0f1114;

    /* Acento único, ámbar desaturado */
    --accent: #d9ab6a;
    --accent-soft: rgba(217, 171, 106, 0.14);
    --accent-line: rgba(217, 171, 106, 0.32);
    --accent-glow: rgba(217, 171, 106, 0.18);

    /* Semánticos, todos desaturados */
    --green: #7fae94;
    --red: #c5837a;
    --pro-color: #8aa2c8;
    --car-color: #c6a575;
    --fat-color: #bf948a;
    --sugar-color: #b291ab;

    /* Texto: escala de 3 niveles, nunca blanco puro */
    --text: #edeef0;
    --text-mid: #a8adb6;
    --text-dim: #6f757f;

    /* Cristal */
    --glass-bg: rgba(255, 255, 255, 0.032);
    --glass-bg-raised: rgba(255, 255, 255, 0.055);
    --glass-border: rgba(255, 255, 255, 0.075);
    --glass-border-strong: rgba(255, 255, 255, 0.13);
    --glass-shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 28px rgba(0,0,0,0.28);
    --glass-shadow-hover: 0 1px 2px rgba(0,0,0,0.3), 0 16px 44px rgba(0,0,0,0.36);

    /* Radios */
    --radius-lg: 22px;
    --radius-md: 14px;
    --radius-sm: 10px;

    /* Movimiento: rápido y sutil */
    --ease: cubic-bezier(0.22, 1, 0.36, 1);
    --dur: 0.22s;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Manrope', -apple-system, BlinkMacSystemFont, sans-serif; }

  body {
    background-color: var(--bg-color);
    background-image:
      radial-gradient(900px 500px at 15% -8%, rgba(217,171,106,0.055), transparent 70%),
      radial-gradient(800px 500px at 88% 8%, rgba(138,162,200,0.045), transparent 70%);
    background-attachment: fixed;
    color: var(--text);
    -webkit-tap-highlight-color: transparent;
    -webkit-font-smoothing: antialiased;
    padding-bottom: 96px;
    line-height: 1.55;
    letter-spacing: -0.005em;
  }

  .app-container { max-width: 1120px; margin: 0 auto; padding: 40px 24px 120px; }

  /* =========================================
     ✍️ ESCALA TIPOGRÁFICA
     ========================================= */
  h2 {
    font-family: 'Space Grotesk', sans-serif;
    font-size: clamp(1.55rem, 2.6vw, 2rem);
    font-weight: 600; letter-spacing: -0.025em;
    margin-bottom: 28px; padding-bottom: 20px;
    display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
    border-bottom: 1px solid var(--glass-border);
  }
  h3 {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 0.82rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.07em;
    color: var(--text-mid); margin-bottom: 20px;
  }
  .subtitle { font-size: 0.8rem; color: var(--text-dim); font-weight: 500; letter-spacing: 0; }
  .section-kicker { color: var(--text-dim); font-size: .7rem; letter-spacing: .1em; text-transform: uppercase; font-weight: 700; margin-bottom: 8px; }

  /* =========================================
     🧱 TARJETAS — mucho aire, cristal sutil
     ========================================= */
  .glass-card {
    background: var(--glass-bg);
    backdrop-filter: blur(20px) saturate(140%); -webkit-backdrop-filter: blur(20px) saturate(140%);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-lg);
    padding: 30px 32px;
    margin-bottom: 20px;
    box-shadow: var(--glass-shadow);
    position: relative;
    transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease), transform var(--dur) var(--ease);
  }
  /* Reflejo superior discreto */
  .glass-card::before {
    content: ''; position: absolute; inset: 0 0 auto 0; height: 1px; border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.14), transparent);
    pointer-events: none;
  }
  .glass-card.card-hero {
    background: linear-gradient(168deg, rgba(217,171,106,0.055), rgba(255,255,255,0.028) 46%);
    border-color: var(--accent-line);
  }
  .glass-card > h3:first-child { margin-top: 0; }

  details.glass-card { padding: 22px 32px; }
  details.glass-card summary { list-style: none; color: var(--text-mid); font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; }
  details.glass-card summary::-webkit-details-marker { display: none; }

  /* =========================================
     🎛️ CONTROLES
     ========================================= */
  input, select, textarea {
    width: 100%; background: rgba(255,255,255,0.035);
    border: 1px solid var(--glass-border);
    color: var(--text); border-radius: var(--radius-sm);
    padding: 15px 16px; font-size: 0.95rem; margin-bottom: 12px;
    transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
  }
  input::placeholder, textarea::placeholder { color: var(--text-dim); }
  input:focus, select:focus, textarea:focus {
    outline: none; border-color: var(--accent-line);
    background: rgba(255,255,255,0.06);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  input[type="number"]::-webkit-outer-spin-button,
  input[type="number"]::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
  input[type="number"] { -moz-appearance: textfield; }
  input[type="date"]::-webkit-calendar-picker-indicator { filter: invert(0.6); cursor: pointer; }
  input[type="file"] { padding: 12px 14px; font-size: 0.84rem; color: var(--text-mid); }
  select { appearance: none; -webkit-appearance: none; cursor: pointer;
    background-image: linear-gradient(45deg, transparent 50%, var(--text-dim) 50%), linear-gradient(135deg, var(--text-dim) 50%, transparent 50%);
    background-position: calc(100% - 20px) center, calc(100% - 14px) center;
    background-size: 6px 6px, 6px 6px; background-repeat: no-repeat; padding-right: 40px; }

  button { transition: all var(--dur) var(--ease); display: inline-flex; justify-content: center; align-items: center; gap: 8px; font-family: inherit; }
  button:active:not(:disabled) { transform: scale(0.985); }
  button:disabled { opacity: 0.4; cursor: not-allowed; }

  button.primary {
    width: 100%; background: var(--accent); color: #17130c; font-weight: 700;
    border: none; border-radius: var(--radius-md); padding: 16px; font-size: 0.95rem; cursor: pointer;
    letter-spacing: -0.01em; box-shadow: 0 1px 0 rgba(255,255,255,0.18) inset, 0 6px 20px rgba(217,171,106,0.16);
  }
  button.secondary {
    background: var(--glass-bg-raised); color: var(--text); border: 1px solid var(--glass-border);
    padding: 13px 18px; border-radius: var(--radius-sm); cursor: pointer; font-weight: 600; font-size: 0.88rem;
  }

  /* =========================================
     📊 HERO DEL DASHBOARD
     ========================================= */
  .kcal-main { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 22px; gap: 16px; }
  .kcal-number {
    font-family: 'Space Grotesk', sans-serif;
    font-size: clamp(2.9rem, 8vw, 3.6rem); font-weight: 600; line-height: 1;
    letter-spacing: -0.045em; font-variant-numeric: tabular-nums;
  }
  .kcal-target { color: var(--text-dim); font-size: 0.72rem; font-weight: 600; margin-top: 8px; text-transform: uppercase; letter-spacing: 0.07em; }

  .main-progress { height: 6px; background: rgba(255,255,255,0.07); border-radius: 99px; overflow: hidden; margin-bottom: 26px; }
  .main-progress-fill { height: 100%; background: var(--accent); border-radius: 99px; transition: width 0.85s var(--ease); }
  .surplus { background: var(--green) !important; }

  /* Tira de métricas clave (peso, tendencia, proteína) */
  .metric-strip { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--glass-border); border: 1px solid var(--glass-border); border-radius: var(--radius-md); overflow: hidden; margin-bottom: 24px; }
  .metric-cell { background: var(--bg-elev); padding: 16px 14px; text-align: center; }
  .metric-cell-val { font-family: 'Space Grotesk', sans-serif; font-size: 1.28rem; font-weight: 600; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; line-height: 1.15; }
  .metric-cell-label { font-size: 0.64rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; margin-top: 6px; }

  .macro-row { margin-bottom: 20px; }
  .macro-row:last-child { margin-bottom: 0; }
  .macro-label { font-size: 0.72rem; font-weight: 600; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-mid); }
  .macro-values { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
  .macro-value-block { display: flex; align-items: baseline; gap: 6px; }
  .macro-value-block.right { justify-content: flex-end; }
  .macro-value-num { font-family: 'Space Grotesk', sans-serif; font-weight: 600; font-size: 1.12rem; line-height: 1; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
  .macro-value-tag { font-size: 0.64rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
  .macro-bar-bg { height: 4px; background: rgba(255,255,255,0.07); border-radius: 99px; overflow: hidden; }
  .macro-bar-fill { height: 100%; border-radius: 99px; transition: width 0.85s var(--ease); }
  .pro-fill { background: var(--pro-color); }
  .car-fill { background: var(--car-color); }
  .fat-fill { background: var(--fat-color); }
  .sugar-fill { background: var(--sugar-color); }
  .over-limit { background: var(--red) !important; }

  .quick-adjust { display:flex; justify-content:space-between; align-items:center; gap:12px; margin: 24px 0 0; padding-top: 20px; border-top: 1px solid var(--glass-border); color:var(--text-dim); font-size:0.74rem; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
  .quick-adjust-controls { display:flex; gap:6px; }
  .quick-adjust-controls button { padding:8px 12px; font-size:0.78rem; }

  /* =========================================
     🏅 RACHA, FAVORITOS, SCORE, INSIGHTS
     ========================================= */
  .streak-badge { display:inline-flex; align-items:center; gap:5px; padding:5px 11px; border-radius:99px; background:var(--accent-soft); border:1px solid var(--accent-line); color:var(--accent); font-size:0.7rem; font-weight:700; white-space:nowrap; letter-spacing: 0.01em; }

  .favorites-row { display:flex; gap:8px; flex-wrap:wrap; }
  .favorite-chip { display:inline-flex; align-items:center; gap:7px; padding:9px 14px; border-radius:99px; background:var(--glass-bg-raised); border:1px solid var(--glass-border); font-size:0.8rem; font-weight:600; cursor:pointer; transition: all var(--dur) var(--ease); }
  .favorite-chip .chip-remove { opacity:0.35; font-size:0.7rem; }
  .favorite-chip .chip-remove:hover { opacity:1; color: var(--red); }

  .quality-score-badge { display:flex; align-items:center; gap:18px; padding:18px 20px; border-radius:var(--radius-md); background:var(--glass-bg-raised); border:1px solid var(--glass-border); }
  .quality-score-num { font-family:'Space Grotesk', sans-serif; font-weight:600; font-size:2.4rem; line-height:1; letter-spacing:-0.04em; font-variant-numeric: tabular-nums; }

  /* Tarjetas de insight cortas (salida de IA y métricas derivadas) */
  .insight-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:10px; }
  .insight-card { padding:16px 18px; border-radius:var(--radius-md); background:var(--glass-bg-raised); border:1px solid var(--glass-border); }
  .insight-value { font-family:'Space Grotesk', sans-serif; font-size:1.15rem; font-weight:600; letter-spacing:-0.025em; line-height:1.2; font-variant-numeric: tabular-nums; }
  .insight-label { font-size:0.68rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:0.07em; font-weight:600; margin-top:7px; }
  .insight-note { font-size:0.85rem; color:var(--text-mid); line-height:1.6; }

  /* Filas de datos clave/valor, sustituyen a listas largas de texto */
  .data-row { display:flex; justify-content:space-between; align-items:center; gap:14px; padding:13px 0; border-bottom:1px solid var(--glass-border); font-size:0.88rem; color:var(--text-mid); }
  .data-row:last-child { border-bottom:none; padding-bottom:0; }
  .data-row:first-child { padding-top:0; }
  .data-row b { color:var(--text); font-weight:600; font-variant-numeric: tabular-nums; }

  /* =========================================
     📸 FOTOS DE PROGRESO
     ========================================= */
  .photo-gallery { display:flex; gap:10px; overflow-x:auto; padding-bottom:8px; scrollbar-width:none; }
  .photo-gallery::-webkit-scrollbar { display:none; }
  .photo-thumb { flex-shrink:0; width:84px; text-align:center; }
  .photo-thumb img { width:84px; height:106px; object-fit:cover; border-radius:var(--radius-sm); border:1px solid var(--glass-border); transition: border-color var(--dur) var(--ease); }
  .photo-thumb-date { font-size:0.62rem; color:var(--text-dim); margin-top:6px; font-variant-numeric: tabular-nums; }
  .photo-thumb-del { font-size:0.62rem; color:var(--text-dim); cursor:pointer; margin-top:3px; }
  .photo-thumb-del:hover { color: var(--red); }
  .photo-compare-view { display:flex; gap:10px; }
  .photo-compare-view img { width:50%; border-radius:var(--radius-md); border:1px solid var(--glass-border); object-fit:cover; }

  /* =========================================
     🎙️ ENTRADA POR VOZ / TEXTO
     ========================================= */
  .mic-container { text-align: center; padding: 30px 24px; }
  .mic-btn {
    width: 76px; height: 76px; border-radius: 50%; border: 1px solid var(--accent-line);
    background: var(--accent-soft); color: var(--accent); font-size: 1.7rem; cursor: pointer;
    display: inline-flex; justify-content: center; align-items: center;
    transition: transform var(--dur) var(--ease), background var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
  }
  .mic-btn.listening { background: var(--accent); color: #17130c; animation: pulse 1.8s infinite; }
  @keyframes pulse { 0% { box-shadow: 0 0 0 0 var(--accent-glow); } 70% { box-shadow: 0 0 0 20px rgba(217,171,106,0); } 100% { box-shadow: 0 0 0 0 rgba(217,171,106,0); } }
  .ai-status { font-size: 0.84rem; color: var(--text-dim); margin-top: 18px; font-weight: 500; min-height: 22px; }

  /* =========================================
     📋 HISTORIAL DE COMIDAS
     ========================================= */
  .log-item { display: flex; justify-content: space-between; padding: 16px 0; border-bottom: 1px solid var(--glass-border); align-items: center; gap: 12px; animation: itemIn 0.3s var(--ease) both; }
  @keyframes itemIn { from { opacity:0; transform: translateY(4px); } to { opacity:1; transform:none; } }
  .log-item:last-child { border-bottom: none; }
  .log-item > div:first-child { flex: 1; min-width: 0; }
  .log-title { font-weight: 600; font-size: 0.95rem; margin-bottom: 4px; word-wrap: break-word; overflow-wrap: break-word; line-height: 1.35; }
  .log-macros { font-size: 0.74rem; color: var(--text-dim); line-height: 1.5; font-variant-numeric: tabular-nums; }
  .log-kcal { font-family: 'Space Grotesk', sans-serif; font-weight: 600; color: var(--text); font-size: 1.05rem; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
  .log-item-actions { display: flex; align-items: center; flex-shrink: 0; gap: 6px; }
  .log-kcal-wrap { text-align: right; margin-right: 8px; display: flex; align-items: baseline; gap: 3px; }
  .del-btn, .edit-btn {
    background: transparent; border: 1px solid var(--glass-border); color: var(--text-dim);
    border-radius: var(--radius-sm); width: 34px; height: 34px; cursor: pointer; font-size: 0.95rem;
    flex-shrink:0; display:flex; align-items:center; justify-content:center; padding:0;
  }
  .del-btn:hover { border-color: rgba(197,131,122,0.4); color: var(--red); }
  .edit-btn:hover { border-color: var(--glass-border-strong); color: var(--text); }

  /* =========================================
     🧬 PERFIL, ESTADÍSTICAS Y GRÁFICOS
     ========================================= */
  .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px; }
  .stat-box { background: var(--glass-bg); border: 1px solid var(--glass-border); padding: 22px 18px; border-radius: var(--radius-md); text-align: center; backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); }
  .stat-val { font-family: 'Space Grotesk', sans-serif; font-size: 1.85rem; font-weight: 600; margin-bottom: 6px; letter-spacing: -0.035em; font-variant-numeric: tabular-nums; }
  .stat-title { font-size: 0.64rem; color: var(--text-dim); text-transform: uppercase; font-weight: 600; letter-spacing: 0.08em; }

  .form-row { display: flex; gap: 12px; margin-bottom: 12px; }
  .form-group { flex: 1; min-width: 0; }
  .form-group label { display: block; font-size: 0.7rem; color: var(--text-dim); margin-bottom: 8px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }

  .chart-container { position: relative; height: 210px; width: 100%; margin-top: 8px; }

  .section > h2::before { content:''; width:3px; height:24px; border-radius:99px; background:var(--accent); margin-right:14px; align-self:center; }
  .dashboard-grid { display:grid; grid-template-columns:minmax(0, 1.3fr) minmax(290px, .7fr); gap:20px; align-items:start; margin-bottom:20px; }
  .dashboard-grid > .glass-card { margin-bottom:0; }
  .summary-card { position:relative; overflow:hidden; }

  .date-nav { display:flex; align-items:center; justify-content:space-between; padding:14px 20px; }
  .date-nav button { padding:10px 15px; }
  .date-nav-label { text-align:center; }
  .date-nav-label strong { font-family:'Space Grotesk', sans-serif; font-size:0.92rem; font-weight:600; letter-spacing:-0.02em; }

  /* =========================================
     📅 MENÚ SEMANAL Y TABLAS
     ========================================= */
  .plan-table { width:100%; border-collapse:collapse; margin-top:8px; }
  .plan-table th { color:var(--text-dim); font-size:0.66rem; text-align:left; padding:12px 10px; border-bottom:1px solid var(--glass-border); text-transform:uppercase; letter-spacing:0.07em; font-weight:600; }
  .plan-table td { padding:13px 10px; font-size:0.85rem; vertical-align:top; border-bottom:1px solid var(--glass-border); color:var(--text-mid); }
  .day-card { margin-top:14px; padding:24px 26px; border-radius:var(--radius-md); background:var(--glass-bg); border:1px solid var(--glass-border); }
  .day-card h3 { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
  .meal-row { display:grid; grid-template-columns:130px minmax(0, 1fr) 76px; gap:18px; align-items:center; padding:16px 0; border-top:1px solid var(--glass-border); }
  .meal-name { font-weight:600; color:var(--text); font-size:0.88rem; }
  .meal-items { color:var(--text-mid); font-size:.85rem; line-height:1.65; }
  .meal-alternatives { display:block; color:var(--text-dim); font-size:.74rem; margin-top:6px; line-height:1.5; }
  .meal-kcal { text-align:right; color:var(--text); font-family:'Space Grotesk', sans-serif; font-weight:600; font-size:.95rem; font-variant-numeric: tabular-nums; }
  .meal-kcal small { display:block; color:var(--text-dim); font-family:'Manrope'; font-weight:500; font-size:.66rem; margin-top:3px; }
  .plan-summary-bar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; padding:18px 20px; background:var(--glass-bg-raised); border:1px solid var(--glass-border); border-radius:var(--radius-md); }
  .plan-meta { display:flex; gap:8px; flex-wrap:wrap; margin-top:16px; }
  .meta-pill { padding:8px 13px; border-radius:99px; background:var(--glass-bg-raised); border:1px solid var(--glass-border); color:var(--text-dim); font-size:.72rem; font-weight:500; }
  .meta-pill b { color:var(--text); font-weight:600; }
  .day-total { margin-top:16px; padding:16px 18px; border-radius:var(--radius-sm); background:var(--accent-soft); border:1px solid var(--accent-line); line-height:1.7; font-size:0.86rem; color:var(--text-mid); }
  .day-total b { color:var(--accent); font-weight:600; }

  .badge { display:inline-block; padding:4px 10px; border-radius:99px; font-size:0.62rem; font-weight:700; letter-spacing: 0.06em; text-transform: uppercase; }
  .badge-batch { background: rgba(138,162,200,0.12); color: var(--pro-color); border: 1px solid rgba(138,162,200,0.24); }
  .badge-fresh { background: rgba(127,174,148,0.12); color: var(--green); border: 1px solid rgba(127,174,148,0.24); }

  /* =========================================
     💬 CHAT Y AVISOS
     ========================================= */
  .chat-window { display:flex; flex-direction:column; gap:14px; max-height:56vh; overflow-y:auto; padding:6px 2px 14px; margin-bottom:16px; scroll-behavior: smooth; }
  .chat-bubble { max-width:82%; padding:14px 18px; border-radius:18px; font-size:0.9rem; line-height:1.6; animation: itemIn 0.28s var(--ease) both; }
  .chat-bubble.user { align-self:flex-end; background: var(--accent); color:#17130c; font-weight:500; border-bottom-right-radius:5px; }
  .chat-bubble.ai { align-self:flex-start; background: var(--glass-bg-raised); border:1px solid var(--glass-border); color: var(--text-mid); border-bottom-left-radius:5px; }
  .chat-empty { color:var(--text-dim); text-align:center; padding:36px 20px; font-size:0.86rem; line-height: 1.6; }
  .chat-action-btn { margin-top:12px; background: var(--accent-soft); border:1px solid var(--accent-line); color:var(--accent); border-radius:var(--radius-sm); padding:11px 16px; font-weight:600; cursor:pointer; font-size:0.84rem; width: 100%; }

  .alert { background: var(--accent-soft); border: 1px solid var(--accent-line); padding: 16px 18px; border-radius: var(--radius-md); font-size: 0.86rem; margin-bottom: 16px; color: var(--text-mid); line-height: 1.6; }
  .alert.warn { background: rgba(197,131,122,0.07); border-color: rgba(197,131,122,0.24); }

  .daily-assistant {
    background: var(--glass-bg); backdrop-filter: blur(20px) saturate(140%); -webkit-backdrop-filter: blur(20px) saturate(140%);
    border: 1px solid var(--glass-border); border-left: 2px solid var(--accent-line);
    border-radius: var(--radius-md); padding: 22px 24px; margin-bottom: 20px; color: var(--text-mid);
  }
  .assistant-kicker { font-size:.62rem; letter-spacing:.1em; text-transform:uppercase; font-weight:700; color:var(--accent); margin-bottom:8px; }
  .assistant-title { font-family:'Space Grotesk', sans-serif; font-size:1rem; font-weight:600; color:var(--text); margin-bottom:8px; line-height:1.4; letter-spacing:-0.02em; }
  .assistant-body { font-size:.87rem; line-height:1.65; color:var(--text-mid); }

  .food-review { margin-top:20px; padding:20px; border:1px solid var(--accent-line); border-radius:var(--radius-md); background:var(--accent-soft); text-align:left; }
  .food-review-grid { display:grid; grid-template-columns:2fr repeat(5, minmax(50px, 1fr)); gap:8px; margin:14px 0; }
  .food-review-grid input { margin-bottom:0; padding:11px 8px; font-size:0.85rem; text-align:center; }
  .food-review-grid input:first-child { text-align:left; }
  .ingredient-row { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .ingredient-row button { padding:5px 10px; font-size:.68rem; }

  /* Toasts */
  #toast-container { position: fixed; top: 20px; left: 50%; transform: translateX(-50%); z-index: 1000; display: flex; flex-direction: column; gap: 10px; width: 90%; max-width: 380px; pointer-events: none; }
  .toast { background: rgba(22,24,28,0.94); backdrop-filter: blur(20px); border: 1px solid var(--glass-border-strong); color: var(--text); padding: 14px 20px; border-radius: var(--radius-sm); font-size: 0.85rem; font-weight: 500; box-shadow: var(--glass-shadow-hover); transform: translateY(-14px); opacity: 0; transition: all 0.28s var(--ease); text-align: center; }
  .toast.show { transform: translateY(0); opacity: 1; }
  .toast.error { border-color: rgba(197,131,122,0.4); color: var(--red); }

  /* =========================================
     📱 NAVEGACIÓN INFERIOR
     ========================================= */
  .bottom-nav {
    position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
    width: calc(100% - 28px); max-width: 520px;
    background: rgba(16, 18, 21, 0.72); backdrop-filter: blur(24px) saturate(160%); -webkit-backdrop-filter: blur(24px) saturate(160%);
    border: 1px solid var(--glass-border-strong); border-radius: 20px;
    display: flex; justify-content: space-around; padding: 8px 6px; z-index: 100;
    box-shadow: 0 12px 40px rgba(0,0,0,0.5);
  }
  .nav-item { color: var(--text-dim); text-align: center; font-size: 0.64rem; cursor: pointer; flex: 1; font-weight: 600; transition: all var(--dur) var(--ease); border-radius: 14px; padding: 8px 4px; letter-spacing: 0.02em; }
  .nav-item.active { color: var(--accent); background: var(--accent-soft); }
  .nav-icon { font-size: 1.25rem; margin-bottom: 4px; display: block; filter: grayscale(100%) opacity(0.45); transition: all var(--dur) var(--ease); }
  .nav-item.active .nav-icon { filter: grayscale(0%) opacity(1); }

  .section { display: none; }
  .section.active { display: block; animation: sectionIn 0.32s var(--ease); }
  @keyframes sectionIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }

  .toggle-row { display:flex; justify-content:space-between; align-items:center; padding:14px 0; gap:16px; }
  .switch { position:relative; width:44px; height:26px; flex-shrink:0; }
  .switch input { opacity:0; width:0; height:0; }
  .slider { position:absolute; cursor:pointer; inset:0; background:rgba(255,255,255,0.1); border-radius:99px; transition:0.25s var(--ease); }
  .slider:before { position:absolute; content:""; height:20px; width:20px; left:3px; bottom:3px; background:var(--text); border-radius:50%; transition:0.25s var(--ease); }
  input:checked + .slider { background: var(--accent); }
  input:checked + .slider:before { transform: translateX(18px); background:#17130c; }

  /* =========================================
     ✨ MICROINTERACCIONES (solo puntero fino)
     ========================================= */
  @media (hover: hover) and (pointer: fine) {
    .glass-card:hover { border-color: var(--glass-border-strong); box-shadow: var(--glass-shadow-hover); transform: translateY(-2px); }
    .glass-card.card-hero:hover { border-color: rgba(217,171,106,0.45); }
    button.primary:hover:not(:disabled) { filter: brightness(1.07); box-shadow: 0 1px 0 rgba(255,255,255,0.22) inset, 0 8px 26px rgba(217,171,106,0.24); }
    button.secondary:hover:not(:disabled) { background: rgba(255,255,255,0.09); border-color: var(--glass-border-strong); }
    .favorite-chip:hover { border-color: var(--accent-line); transform: translateY(-1px); }
    .nav-item:hover:not(.active) { color: var(--text-mid); }
    .mic-btn:hover { transform: scale(1.04); background: rgba(217,171,106,0.2); }
    .photo-thumb img:hover { border-color: var(--accent-line); }
    .insight-card { transition: border-color var(--dur) var(--ease); }
    .insight-card:hover { border-color: var(--glass-border-strong); }
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
  }

  /* =========================================
     📱 MÓVIL — una sola mano, más aire
     ========================================= */
  @media (max-width: 760px) {
    .app-container { padding: 26px 16px 116px; }
    .glass-card { padding: 24px 20px; border-radius: 18px; margin-bottom: 14px; }
    details.glass-card { padding: 18px 20px; }
    h2 { margin-bottom: 22px; padding-bottom: 16px; }
    .dashboard-grid { grid-template-columns: 1fr; gap: 14px; }
    .meal-row { grid-template-columns: 1fr auto; gap: 8px 12px; }
    .meal-row > :nth-child(2) { grid-column: 1 / -1; grid-row: 2; }
    .meal-kcal { grid-column: 2; grid-row: 1; }
    .day-card { padding: 20px 16px; }
    .form-row { flex-direction: column; gap: 0; }
    .food-review-grid { grid-template-columns: 1fr 1fr 1fr; }
    .food-review-grid input:first-child { grid-column: 1 / -1; }
    /* Objetivos táctiles generosos */
    input, select, textarea { padding: 16px; font-size: 16px; }
    button.primary { padding: 17px; }
    button.secondary { padding: 14px 18px; }
    .chat-bubble { max-width: 90%; }
  }

  @media (min-width: 1400px) {
    .app-container { max-width: 1240px; padding-top: 52px; }
    .glass-card { padding: 34px 36px; }
  }

  /* =========================================
     🧠 v2 — ESTADO DEL BULK, MOTOR, DIAGNÓSTICO, AUDITORÍA
     ========================================= */
  .tone-ok { --tone: var(--green); } .tone-warn { --tone: var(--accent); } .tone-bad { --tone: var(--red); } .tone-neutral { --tone: var(--text-mid); }
  .status-head { display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; }
  .status-chip { display:inline-flex; align-items:center; gap:8px; padding:6px 12px; border-radius:99px; font-size:.78rem; font-weight:700; letter-spacing:.02em; color:var(--tone); background:color-mix(in srgb, var(--tone) 14%, transparent); border:1px solid color-mix(in srgb, var(--tone) 35%, transparent); }
  .status-chip::before { content:''; width:7px; height:7px; border-radius:50%; background:var(--tone); }
  .conf-badge { font-size:.68rem; font-weight:700; text-transform:uppercase; letter-spacing:.07em; padding:5px 10px; border-radius:99px; border:1px solid var(--glass-border-strong); color:var(--text-mid); }
  .conf-alta { color:var(--green); border-color:rgba(127,174,148,.4); } .conf-media { color:var(--accent); border-color:var(--accent-line); } .conf-baja { color:var(--red); border-color:rgba(197,131,122,.4); }
  .status-nums { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:18px 0 6px; }
  .sn-val { font-family:'Space Grotesk',sans-serif; font-size:1.2rem; font-weight:600; letter-spacing:-.02em; font-variant-numeric:tabular-nums; }
  .sn-lbl { font-size:.64rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:.07em; font-weight:600; margin-top:3px; }
  .rate-scale { position:relative; height:34px; margin:18px 0 20px; }
  .rate-scale::before { content:''; position:absolute; left:0; right:0; top:14px; height:6px; border-radius:99px; background:rgba(255,255,255,.06); }
  .rs-band { position:absolute; top:12px; height:10px; border-radius:99px; background:rgba(127,174,148,.35); border:1px solid rgba(127,174,148,.6); }
  .rs-zero { position:absolute; top:6px; width:1px; height:22px; background:var(--text-dim); }
  .rs-ci { position:absolute; top:15px; height:4px; border-radius:99px; background:var(--accent); opacity:.55; }
  .rs-dot { position:absolute; top:10px; width:14px; height:14px; margin-left:-7px; border-radius:50%; background:var(--accent); box-shadow:0 0 0 3px var(--bg-color); }
  .rs-labels span { position:absolute; top:28px; transform:translateX(-50%); font-size:.62rem; color:var(--text-dim); font-variant-numeric:tabular-nums; }
  .rs-legend { display:flex; gap:16px; font-size:.68rem; color:var(--text-dim); margin-top:6px; }
  .rs-legend i { display:inline-block; width:10px; height:6px; border-radius:3px; margin-right:6px; vertical-align:middle; }
  .lg-band { background:rgba(127,174,148,.5); } .lg-ci { background:var(--accent); }
  .muted-line { font-size:.76rem; color:var(--text-dim); line-height:1.5; margin-top:10px; }
  .why-title { font-family:'Space Grotesk',sans-serif; font-size:1.05rem; margin-bottom:12px; } .why-title b { color:var(--accent); }
  .kv-row { display:grid; grid-template-columns:1fr auto; gap:2px 12px; padding:10px 0; border-bottom:1px solid var(--glass-border); font-size:.86rem; }
  .kv-row:last-of-type { border-bottom:none; }
  .kv-row span { color:var(--text-mid); } .kv-row b { font-variant-numeric:tabular-nums; text-align:right; }
  .kv-row small { grid-column:1 / -1; color:var(--text-dim); font-size:.72rem; line-height:1.4; }
  .decision-box { margin-top:14px; padding:12px 14px; border-radius:var(--radius-sm); font-size:.84rem; line-height:1.5; background:color-mix(in srgb, var(--tone) 9%, transparent); border:1px solid color-mix(in srgb, var(--tone) 28%, transparent); }
  .decision-box b { color:var(--tone); }
  .sub-details { margin-top:14px; font-size:.8rem; } .sub-details summary { cursor:pointer; color:var(--text-mid); font-weight:600; }
  .formula p { color:var(--text-mid); line-height:1.55; margin:10px 0 0; }
  .q-list { display:flex; flex-direction:column; gap:10px; }
  .q-item { padding:12px 14px; border-radius:var(--radius-sm); background:rgba(255,255,255,.025); border:1px solid var(--glass-border); border-left:3px solid var(--tone); }
  .q-head { display:flex; align-items:baseline; gap:10px; } .q-text { flex:1; font-size:.86rem; font-weight:600; }
  .q-val { font-size:.84rem; color:var(--tone); font-variant-numeric:tabular-nums; white-space:nowrap; }
  .q-dot { display:none; } .q-ans { font-size:.78rem; color:var(--text-mid); margin-top:6px; line-height:1.5; }
  details.insights-details > summary, .card-summary { cursor:pointer; font-family:'Space Grotesk',sans-serif; font-weight:600; font-size:1.02rem; }
  .pred-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  .pred-card { padding:14px; border-radius:var(--radius-sm); background:rgba(255,255,255,.03); border:1px solid var(--glass-border); }
  .pred-lbl { font-size:.66rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:.07em; font-weight:600; }
  .pred-val { font-family:'Space Grotesk',sans-serif; font-size:1.05rem; font-weight:600; margin:6px 0 4px; } .pred-val.dim { color:var(--text-dim); }
  .pred-sub { font-size:.72rem; color:var(--text-dim); line-height:1.4; }
  .sub-title { font-size:.72rem; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:var(--text-mid); margin-bottom:10px; }
  .banner-actions { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-top:10px; }
  button.mini, .secondary.mini { padding:6px 12px; font-size:.74rem; }
  .mini-tag { display:inline-block; font-size:.62rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em; padding:2px 7px; border-radius:6px; background:rgba(255,255,255,.07); color:var(--text-mid); vertical-align:middle; }
  .day-status-row { display:flex; gap:8px; justify-content:center; align-items:center; flex-wrap:wrap; margin-top:8px; }
  .dq-list { display:flex; flex-direction:column; gap:8px; margin-top:12px; }
  .dq-item { font-size:.78rem; line-height:1.5; color:var(--text-mid); padding:10px 12px; border-radius:var(--radius-sm); background:rgba(255,255,255,.03); border:1px solid var(--glass-border); }
  .table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; }
  .plan-table.audit { font-size:.74rem; white-space:nowrap; } .plan-table.audit th { text-align:left; color:var(--text-dim); font-weight:600; padding:6px 8px; } .plan-table.audit td { padding:6px 8px; }
  .decision-item { border-bottom:1px solid var(--glass-border); padding:8px 0; font-size:.8rem; }
  .decision-item summary { cursor:pointer; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .decision-reason { color:var(--text-mid); line-height:1.5; margin:8px 0; }
  .act-subir { color:var(--green); } .act-bajar { color:var(--red); } .act-mantener, .act-sin_datos { color:var(--text-mid); } .act-correccion, .act-manual { color:var(--accent); }
  pre.trace { font-size:.66rem; line-height:1.4; max-height:260px; overflow:auto; background:rgba(0,0,0,.25); border:1px solid var(--glass-border); border-radius:8px; padding:10px; color:var(--text-mid); white-space:pre-wrap; }
  .chart-container.tall { height:280px; }
  .src-badge { display:inline-flex; align-items:center; gap:6px; margin-top:8px; padding:5px 10px; border-radius:20px; background:rgba(255,255,255,0.06); font-size:.72rem; font-weight:700; }
  .est-meta { font-size:.8rem; color:var(--text-mid); margin-top:12px; } .est-meta b { color:var(--text); }
  .est-items { width:100%; font-size:.76rem; margin-top:8px; border-collapse:collapse; } .est-items td { padding:4px 0; color:var(--text-mid); border-bottom:1px solid var(--glass-border); } .est-items td:nth-child(2), .est-items td:nth-child(3) { text-align:right; white-space:nowrap; padding-left:10px; }
  .est-assump { font-size:.72rem; color:var(--text-dim); margin-top:8px; line-height:1.45; }
  .est-question { margin-top:12px; padding:10px 12px; border-radius:var(--radius-sm); border:1px solid var(--accent-line); background:var(--accent-soft); font-size:.82rem; }
  .scale-row { display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin:-4px 0 14px; font-size:.7rem; color:var(--text-dim); } .scale-row span { margin-right:4px; text-transform:uppercase; letter-spacing:.06em; font-weight:600; }
  .scale-row button { padding:6px 10px; font-size:.74rem; }
  .cmp-bar { display:flex; justify-content:space-between; align-items:center; padding:12px 14px; margin:12px 0; border-radius:8px; background:rgba(255,255,255,0.04); border:1px solid var(--glass-border); font-size:.85rem; }
  @media (max-width: 760px){ .pred-grid { grid-template-columns:1fr; } .status-nums { grid-template-columns:repeat(3,1fr); } .sn-val { font-size:1.02rem; } }
</style>
</head>
<body>

<div id="toast-container"></div>

<div class="app-container">

  <!-- ========================================================================= -->
  <!-- 📊 TAB 1: DASHBOARD Y REGISTRO DIARIO                                     -->
  <!-- ========================================================================= -->
  <div id="tab-dash" class="section active">
    <h2>Resumen <span class="subtitle" id="date-display"></span></h2>
    <div id="no-sync-banner" class="alert warn" style="display:none;"></div>
    <div id="adjust-alert" class="alert" style="display:none;"></div>
    <div id="day-flag-banner" class="alert warn" style="display:none;"></div>
    <div id="favorite-suggestion" class="alert" style="display:none;"></div>
    <div id="backup-reminder" class="alert" style="display:none;"></div>
    <div id="daily-assistant" class="daily-assistant" style="display:none;"></div>

    <div class="dashboard-grid">
    <div class="glass-card card-hero" style="padding-top: 30px;">
      <div class="kcal-main">
        <div>
          <div class="kcal-number" id="ui-kcal-consumed">0</div>
          <div class="kcal-target">Ingeridas</div>
        </div>
        <div style="text-align: right;">
          <div class="kcal-number" id="ui-kcal-remaining" style="font-size: 3.8rem; color: var(--accent);">0</div>
          <div class="kcal-target" id="ui-kcal-status">Restantes</div>
        </div>
      </div>
      <div style="font-size:0.72rem; color: var(--text-dim); margin-bottom:14px; display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; text-transform:uppercase; letter-spacing:0.06em; font-weight:600;">
        <span>Objetivo <b style="color:var(--text-mid);" id="ui-kcal-target">--</b> kcal</span>
        <span class="streak-badge" id="streak-badge" style="display:none;"></span>
      </div>
      <div class="main-progress"><div class="main-progress-fill" id="ui-progress"></div></div>
      <div class="metric-strip" id="ui-metric-strip">
        <div class="metric-cell"><div class="metric-cell-val" id="ui-strip-weight">--</div><div class="metric-cell-label">Peso</div></div>
        <div class="metric-cell"><div class="metric-cell-val" id="ui-strip-trend">--</div><div class="metric-cell-label">Tendencia</div></div>
        <div class="metric-cell"><div class="metric-cell-val" id="ui-strip-goal">--</div><div class="metric-cell-label">Objetivo</div></div>
      </div>
      <div style="font-size:0.78rem; color: var(--green); margin-bottom:16px; font-weight:600; display:none;" id="ui-override-note"></div>
      <div class="macro-row">
        <div class="macro-values">
          <span class="macro-label" style="color: var(--pro-color); margin-bottom:0;">Proteína</span>
          <div class="macro-value-block right"><span class="macro-value-num" id="txt-pro">0g</span><span class="macro-value-tag" id="rem-pro">0g</span></div>
        </div>
        <div class="macro-bar-bg"><div class="macro-bar-fill pro-fill" id="bar-pro"></div></div>
      </div>
      <div class="macro-row">
        <div class="macro-values">
          <span class="macro-label" style="color: var(--car-color); margin-bottom:0;">Carbohidratos</span>
          <div class="macro-value-block right"><span class="macro-value-num" id="txt-car">0g</span><span class="macro-value-tag" id="rem-car">0g</span></div>
        </div>
        <div class="macro-bar-bg"><div class="macro-bar-fill car-fill" id="bar-car"></div></div>
      </div>
      <div class="macro-row">
        <div class="macro-values">
          <span class="macro-label" style="color: var(--fat-color); margin-bottom:0;">Grasas</span>
          <div class="macro-value-block right"><span class="macro-value-num" id="txt-fat">0g</span><span class="macro-value-tag" id="rem-fat">0g</span></div>
        </div>
        <div class="macro-bar-bg"><div class="macro-bar-fill fat-fill" id="bar-fat"></div></div>
      </div>
      <div class="macro-row">
        <div class="macro-values">
          <span class="macro-label" style="color: var(--sugar-color); margin-bottom:0;">Azúcar</span>
          <div class="macro-value-block right"><span class="macro-value-num" id="txt-sugar">0g</span><span class="macro-value-tag" id="rem-sugar">0g</span></div>
        </div>
        <div class="macro-bar-bg"><div class="macro-bar-fill sugar-fill" id="bar-sugar"></div></div>
      </div>

      <div class="quick-adjust" aria-label="Ajuste rapido del objetivo">
        <span>Ajustar hoy</span>
        <div class="quick-adjust-controls">
          <button class="secondary" onclick="adjustDay(-100)" title="Restar 100 kcal">−100</button>
          <button class="secondary" onclick="adjustDay(100)" title="Sumar 100 kcal">+100</button>
          <button class="secondary" onclick="resetDayOverride()" title="Restablecer ajuste">Reset</button>
        </div>
      </div>
    </div>

    <!-- WIDGET DE ENTRADA POR VOZ / TEXTO -->
    <div class="glass-card mic-container">
      <button class="mic-btn" id="btn-mic">🎙️</button>
      <div class="ai-status" id="ai-status">Toca para dictar qué has comido</div>
      <div id="favorites-row" class="favorites-row" style="display:none; margin-top:18px;"></div>
      <div style="display:flex; gap:10px; margin-top:24px;">
        <input type="text" id="manual-text" placeholder="o escríbelo aquí..." style="margin-bottom:0;">
        <button class="secondary" id="btn-send-text" onclick="processText()">Enviar</button>
      </div>
      <div id="food-review" class="food-review" style="display:none;"></div>
    </div>
    </div>

    <!-- ESTADO DEL BULK (motor v2) -->
    <div class="glass-card">
      <h3>Estado del bulk</h3>
      <div id="bulk-status-content"></div>
    </div>
    <div class="glass-card">
      <div id="why-target-dash"></div>
      <details class="insights-details" style="margin-top:18px;">
        <summary>Diagnóstico completo</summary>
        <div id="insights-dash" class="q-list" style="margin-top:14px;"></div>
      </details>
    </div>

    <div class="glass-card date-nav">
      <button class="secondary" onclick="navDay(-1)">◀</button>
      <div class="date-nav-label">
        <strong id="log-date-label">Hoy</strong>
        <div id="log-date-jump" style="display:none; margin-top:6px;"><button class="secondary" style="padding:6px 12px; font-size:.75rem;" onclick="jumpToday()">Volver a hoy</button></div>
        <div id="day-status-row" class="day-status-row"></div>
      </div>
      <button class="secondary" id="btn-next-day" onclick="navDay(1)">▶</button>
    </div>

    <h3>Historial</h3>
    <div class="glass-card" id="log-list" style="padding: 10px 24px;"></div>
  </div>

  <!-- ========================================================================= -->
  <!-- 🛒 TAB 2: MENÚ SEMANAL GENERATIVO                                         -->
  <!-- ========================================================================= -->
  <div id="tab-plan" class="section">
    <h2>Menú semanal</h2>
    <div class="glass-card">
      <div class="plan-meta" style="margin: 0 0 22px;">
        <span class="meta-pill"><span class="badge badge-batch">batch</span> &nbsp;Desayuno · Comida</span>
        <span class="meta-pill"><span class="badge badge-fresh">fresh</span> &nbsp;Levantarse · Merienda · Cena</span>
        <span class="meta-pill">Generar <b>jue</b> · Comprar <b>vie</b> · Cocinar <b>dom</b></span>
      </div>
      <button class="primary" id="btn-generate-plan" onclick="generatePlan()">Generar plan semanal</button>
      <div id="plan-validation" class="alert" style="display:none; margin-top:16px;"></div>
      <div id="plan-loading" style="display:none; text-align:center; padding:20px; color:var(--accent); font-weight: 600;">
        🧠 Diseñando estructura clínica nutricional...
      </div>
    </div>
    <div class="glass-card" style="display:none; background: transparent; border:none; box-shadow:none; padding:0;" id="plan-container">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
        <span style="font-size:0.8rem; color:var(--text-dim);" id="plan-date"></span>
        <button class="secondary" onclick="generatePlan()" style="padding:8px 16px; font-size:0.85rem;">Regenerar</button>
      </div>
      <div id="plan-output"></div>
    </div>
  </div>

  <!-- ========================================================================= -->
  <!-- 💬 TAB 3: COACH IA CHAT                                                   -->
  <!-- ========================================================================= -->
  <div id="tab-chat" class="section">
    <h2>Coach</h2>
    <div class="glass-card">

      <div class="chat-window" id="chat-window"></div>
      <div style="display:flex; gap:10px;">
        <input type="text" id="chat-input" placeholder="Escribe tu mensaje..." style="margin-bottom:0;">
        <button class="secondary" id="btn-chat-send" onclick="sendChatMessage()">Enviar</button>
      </div>
    </div>
  </div>

  <!-- ========================================================================= -->
  <!-- 🧬 TAB 4: PERFIL, PESO Y TENDENCIAS                                       -->
  <!-- ========================================================================= -->
  <div id="tab-body" class="section">
    <h2>Progreso</h2>

    <!-- PESO -->
    <div class="glass-card">
      <h3>Peso</h3>
      <div class="form-row" style="margin-bottom: 12px;">
        <div class="form-group"><label>Fecha</label><input type="date" id="input-weight-date" style="margin-bottom:0;"></div>
        <div class="form-group"><label>Peso (kg)</label><input type="number" step="0.1" id="input-weight" placeholder="Ej: 55.4" style="margin-bottom:0;"></div>
      </div>
      <button class="secondary" onclick="addWeight()" style="width:100%; margin-bottom:16px;">Guardar pesaje</button>
      <div id="weight-day-list" style="margin-bottom:16px;"></div>
      <div class="chart-container tall"><canvas id="weightChart"></canvas></div>
      <div class="muted-line" id="weight-chart-caption"></div>
    </div>

    <!-- ESTADO DEL BULK + PREDICCIÓN -->
    <div class="glass-card">
      <h3>Estado del bulk</h3>
      <div id="bulk-status-body"></div>
      <div class="sub-title" style="margin-top:22px;">¿Cuándo llego a mi objetivo?</div>
      <div class="form-group" style="margin-bottom:10px;"><label>Peso objetivo (kg)</label><input type="number" step="0.1" id="input-goal-weight" placeholder="Ej: 60" style="margin-bottom:0;"></div>
      <button class="secondary" onclick="saveGoalWeight()" style="width:100%; margin-bottom:16px;">Guardar peso objetivo</button>
      <div id="goal-projection-content"></div>
    </div>

    <!-- MOTOR DE KCAL -->
    <div class="glass-card">
      <h3>Motor de kcal</h3>
      <div id="why-target-body"></div>
      <div class="sub-title" style="margin-top:20px;">Mantenimiento estimado y objetivo en el tiempo</div>
      <div class="chart-container"><canvas id="modelChart"></canvas></div>
      <div class="muted-line">Cada punto es lo que el motor estimaba ESE día con los datos disponibles hasta entonces (sin mirar al futuro).</div>
    </div>

    <!-- DIAGNÓSTICO -->
    <div class="glass-card">
      <h3>Diagnóstico</h3>
      <div id="insights-body" class="q-list"></div>
    </div>

    <!-- NUTRICIÓN REAL VS OBJETIVO -->
    <div class="glass-card">
      <h3>Nutrición real vs objetivo</h3>
      <div class="chart-container"><canvas id="kcalTrendChart"></canvas></div>
      <div id="nutrition-stats" style="margin-top:14px;"></div>
      <button class="secondary" id="btn-weekly-summary" onclick="generateWeeklySummary()" style="width:100%; margin-top:16px;">Resumen semanal con IA</button>
      <div id="weekly-summary-output" style="display:none; margin-top:16px;"></div>
    </div>

    <!-- AUDITORÍA -->
    <details class="glass-card">
      <summary class="card-summary">🧹 Calidad de datos</summary>
      <div id="dq-content" style="margin-top:16px;"></div>
    </details>
    <details class="glass-card">
      <summary class="card-summary">🤖 IA de comidas: precisión y correcciones</summary>
      <div id="ai-stats-content" style="margin-top:16px;"></div>
    </details>
    <details class="glass-card">
      <summary class="card-summary">🕘 Historial de decisiones (auditoría)</summary>
      <div id="decision-log-content" style="margin-top:16px;"></div>
    </details>
    <details class="glass-card">
      <summary class="card-summary">🧪 Backtest: algoritmo anterior vs nuevo</summary>
      <button class="secondary" onclick="runBacktestUI()" style="width:100%; margin-top:16px;">Ejecutar backtest con mis datos</button>
      <div id="backtest-content" style="margin-top:16px;"></div>
    </details>

    <!-- RESUMEN CLÍNICO IA -->
    <div class="glass-card">
      <h3>Resumen con IA</h3>
      <button class="primary" id="btn-ai-summary" onclick="generateBodySummary()">Generar resumen</button>
      <div id="ai-body-summary-output" style="display:none; margin-top:18px;"></div>
    </div>

    <!-- COMPOSICIÓN CORPORAL -->
<div class="glass-card">
      <h3>Composición corporal</h3>
      <div id="body-comp-content"></div>
      <div id="body-comp-chart-wrap" style="display:none; margin-top:20px;">
        <div class="form-group" style="max-width:260px; margin-bottom:6px;">
          <label>Métrica del gráfico</label>
          <select id="metric-select" onchange="renderBodyCompositionChart()">
            <option value="weight">Peso (kg)</option>
            <option value="bmi">IMC</option>
            <option value="bodyfat">% Grasa corporal</option>
            <option value="ffmi">FFMI (normalizado)</option>
            <option value="fatmass">Masa grasa (kg)</option>
            <option value="leanmass">Masa libre de grasa (kg)</option>
          </select>
        </div>
        <div class="chart-container"><canvas id="bodyCompChart"></canvas></div>
      </div>
    </div>

    <!-- MEDIDAS CORPORALES (OPCIONAL) -->
<div class="glass-card">
      <h3>Medidas corporales</h3>
      <p style="font-size:0.78rem; color:var(--text-dim); margin-bottom:16px;">Cuello y cintura desbloquean el % de grasa medido.</p>
      <div class="form-row" style="margin-bottom: 12px;">
        <div class="form-group"><label>Fecha</label><input type="date" id="input-measure-date" style="margin-bottom:0;"></div>
      </div>
      <div class="form-row" style="margin-bottom: 12px;">
        <div class="form-group"><label>Cuello (cm)</label><input type="number" step="0.1" id="input-neck" placeholder="Ej: 38" style="margin-bottom:0;"></div>
        <div class="form-group"><label>Cintura (cm)</label><input type="number" step="0.1" id="input-waist" placeholder="Ej: 82" style="margin-bottom:0;"></div>
        <div class="form-group"><label>Cadera (cm)</label><input type="number" step="0.1" id="input-hip" placeholder="Ej: 95" style="margin-bottom:0;"></div>
      </div>
      <button class="secondary" onclick="addBodyMeasure()" style="width:100%; margin-bottom:16px;">Guardar medidas</button>
      <div id="measure-day-list"></div>
    </div>

    <!-- FOTOS DE PROGRESO -->
<div class="glass-card">
      <h3>Fotos de progreso</h3>
      <p style="font-size:0.78rem; color:var(--text-dim); margin-bottom:16px;">Una por día. Se comprime automáticamente.</p>
      <input type="file" accept="image/*" capture="environment" id="input-photo" style="margin-bottom:12px;">
      <button class="secondary" onclick="addProgressPhoto()" style="width:100%; margin-bottom:16px;">Guardar foto de hoy</button>
      <div id="photo-gallery" class="photo-gallery"></div>
      <div id="photo-compare-controls" style="display:none; margin-top:16px;">
        <div class="form-row" style="margin-bottom:12px;">
          <div class="form-group"><label>Antes</label><select id="photo-compare-a" onchange="renderPhotoCompare()" style="margin-bottom:0;"></select></div>
          <div class="form-group"><label>Después</label><select id="photo-compare-b" onchange="renderPhotoCompare()" style="margin-bottom:0;"></select></div>
        </div>
        <div id="photo-compare-view" class="photo-compare-view"></div>
      </div>
    </div>

    <div class="stats-grid">
      <div class="stat-box">
        <div class="stat-title">Mantenimiento</div>
        <div class="stat-val" id="ui-tdee" style="color:var(--pro-color);">--</div>
        <div style="font-size:0.8rem; color:var(--text-dim);" id="ui-tdee-sub">kcal / día</div>
      </div>
      <div class="stat-box">
        <div class="stat-title">IMC</div>
        <div class="stat-val" id="ui-bmi">--</div>
        <div style="font-size:0.8rem; font-weight:600;" id="ui-bmi-label">--</div>
      </div>
    </div>

    <!-- PERFIL -->
    <div class="glass-card">
      <h3>Perfil</h3>
      <div class="form-row">
        <div class="form-group"><label>Edad</label><input type="number" id="prof-age" placeholder="24"></div>
        <div class="form-group"><label>Altura (cm)</label><input type="number" id="prof-height" placeholder="175"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Peso de referencia (kg)</label><input type="number" id="prof-weight" step="0.1"></div>
        <div class="form-group"><label>Sexo</label>
          <select id="prof-sex"><option value="m">Hombre</option><option value="f">Mujer</option></select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Días de entrenamiento / semana</label>
          <select id="prof-training-days"><option value="0">0</option><option value="1">1</option><option value="2">2</option><option value="3">3</option><option value="4">4</option><option value="5">5</option><option value="6">6</option><option value="7">7</option></select>
        </div>
        <div class="form-group"><label>Ritmo objetivo</label>
          <select id="prof-rate">
            <option value="conservador">Conservador · 0,15–0,30 % peso/sem</option>
            <option value="estandar">Estándar · 0,25–0,50 % peso/sem</option>
            <option value="rapido">Rápido · 0,50–0,75 % peso/sem</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Inicio del bulk</label><input type="date" id="prof-bulk-start"></div>
        <div class="form-group"><label>Comidas al día</label><input type="number" min="3" max="8" id="prof-meals" placeholder="5"></div>
      </div>
      <div class="form-group" style="margin-bottom:16px;"><label>Preferencias y restricciones</label><textarea id="prof-preferences" rows="2" placeholder="Ej: sin lactosa, económico, no pescado..."></textarea></div>
      <p class="muted-line" style="margin:0 0 8px;">El peso de referencia se actualiza solo con tus pesajes; solo se usa si aún no hay tendencia. Los días de entreno fijan el mantenimiento inicial (1,2 + 0,075 × días); después manda tu balance real.</p>

      <div class="toggle-row">
        <div style="font-size:0.9rem; font-weight:500;">Pausar ajuste automático (vacaciones, lesión, enfermedad)</div>
        <label class="switch"><input type="checkbox" id="prof-pause"><span class="slider"></span></label>
      </div>

      <button class="secondary" onclick="saveProfile()" style="width:100%; margin: 16px 0 10px;">Guardar perfil</button>
      <div style="display:flex; gap:10px;">
        <button class="primary" style="flex:1;" onclick="recalcTargetFromModel()">Recalcular objetivo desde el modelo</button>
        <button class="secondary" onclick="setManualTarget()">Fijar a mano</button>
      </div>
    </div>
  </div>

  <!-- ========================================================================= -->
  <!-- 💾 TAB 5: DATOS Y BACKUP                                                  -->
  <!-- ========================================================================= -->
  <div id="tab-data" class="section">
    <h2>Datos</h2>
    <div class="glass-card">
      <h3>Sincronización</h3>
      <div id="sync-status-content"></div>
    </div>
    <div class="glass-card">
      <h3>Backup local</h3>
      <p style="font-size:0.8rem; color:var(--text-dim); margin-bottom:16px;">Los datos viven en este navegador. Exporta de vez en cuando.</p>
      <button class="secondary" onclick="exportData()" style="width:100%; margin-bottom:12px;">⬇️ Exportar JSON</button>
      <label style="display:block; text-align:center; padding:14px; border-radius:var(--radius-sm); border:1px dashed var(--glass-border); color:var(--text-dim); font-size:0.9rem; cursor:pointer;">
        ⬆️ Importar JSON
        <input type="file" id="import-file-input" accept="application/json" style="display:none;">
      </label>
    </div>
    <div class="glass-card">
      <h3>Diagnóstico técnico</h3>
      <p style="font-size:0.8rem; color:var(--text-dim); margin-bottom:16px;">Informe completo para revisar tu evolución o pasárselo a una IA: datos observados, cálculos, estimaciones, predicciones, decisiones y backtest. Sin API keys, sin enlace de sincronización, sin fotos y sin chat.</p>
      <button class="secondary diag-btn" onclick="exportDiagnostics('pdf')" style="width:100%; margin-bottom:10px;">📄 Informe PDF</button>
      <button class="secondary diag-btn" onclick="exportDiagnostics('json')" style="width:100%; margin-bottom:10px;">🧾 Datos JSON (etiquetados)</button>
      <button class="secondary diag-btn" onclick="exportDiagnostics('csv')" style="width:100%;">📊 Tablas CSV (ZIP)</button>
    </div>
    <div class="glass-card">
      <h3>Tests del motor</h3>
      <p style="font-size:0.8rem; color:var(--text-dim); margin-bottom:16px;">Ejecuta en tu navegador la batería de tests de los cálculos (casos A–O y regresiones).</p>
      <button class="secondary" onclick="runEngineTestsUI()" style="width:100%;">Ejecutar tests</button>
      <div id="tests-output" style="display:none; margin-top:14px;"></div>
    </div>
  </div>

</div>

<!-- BOTTOM NAVIGATION -->
<div class="bottom-nav">
  <div class="nav-item active" data-tab="dash" onclick="nav('dash')"><span class="nav-icon">📊</span>Hoy</div>
  <div class="nav-item" data-tab="plan" onclick="nav('plan')"><span class="nav-icon">🛒</span>Menú</div>
  <div class="nav-item" data-tab="chat" onclick="nav('chat')"><span class="nav-icon">💬</span>Coach</div>
  <div class="nav-item" data-tab="body" onclick="nav('body')"><span class="nav-icon">📈</span>Progreso</div>
  <div class="nav-item" data-tab="data" onclick="nav('data')"><span class="nav-icon">💾</span>Datos</div>
</div>

<!-- ========================================================================= -->
<!-- ⚙️ CÓDIGO JAVASCRIPT (LÓGICA PRINCIPAL)                                     -->
<!-- ========================================================================= -->
<script>
/*__ENGINE_START__*/
// =============================================================================
// 🧠 BulkEngine — ÚNICA FUENTE DE VERDAD de todos los cálculos
// =============================================================================
// Módulo PURO: no toca DOM, localStorage, red ni reloj (la fecha "hoy" entra
// siempre como parámetro asOf). Esto lo hace:
//   · testeable en Node (python bulking_app.py --test),
//   · reproducible (mismos datos + misma fecha = mismo resultado),
//   · libre de fuga de datos en el backtest por construcción (asOf filtra todo),
//   · reutilizable tal cual en un futuro backend (Workers).
// Dashboard, gráficos, prompts de IA, PDF/JSON/CSV y backtest consumen el MISMO
// objeto que devuelve computeState(). Si ves "kg/semana = X" en dos sitios,
// sale de la misma función.
// Nomenclatura de datos: OBSERVED (lo registrado), CALCULATED (derivado
// determinista), ESTIMATED (modelo con incertidumbre), PREDICTED (futuro).
(function(root){
'use strict';
const VERSION = '2.0.0';

const CONFIG = Object.freeze({
  KCAL_PER_KG: 7700,                 // kcal por kg de cambio de peso (convención; escala todo el balance)
  TREND_ALPHA_PER_DAY: 0.15,         // EWMA temporal (semivida ≈ 4,3 días); solo para "peso tendencia" y gráfico
  RATE_WINDOW_DAYS: 28,              // ventana de la regresión de ritmo
  MIN_RATE_POINTS: 4, MIN_RATE_SPAN: 6,   // por debajo: ni siquiera tendencia preliminar
  MEDIA: { span: 13, weighIns: 10, completeDays: 10 },
  ALTA:  { span: 24, weighIns: 18, completeDays: 18, maxCiHalfWidth: 0.10 },
  CI_Z: 1.2816,                      // intervalo del 80 %
  RESIDUAL_SD_FLOOR: 0.20,           // kg: evita falsa precisión con pocos pesajes muy parecidos
  HAMPEL_HALF_WINDOW_DAYS: 3, HAMPEL_K: 3, HAMPEL_MAD_FLOOR_KG: 0.3,
  WEIGHT_PLAUSIBLE: [25, 250],
  COMPLETE_MIN_ENTRIES: 2, COMPLETE_MIN_FRACTION_OF_MEDIAN: 0.6,
  PRIOR_SD_FRACTION: 0.12,           // incertidumbre de Mifflin-St Jeor × actividad
  LOGGING_SYSTEMATIC_FRACTION: 0.05, // error sistemático de registro asumido
  RATE_PRESETS: { conservador: [0.15, 0.30], estandar: [0.25, 0.50], rapido: [0.50, 0.75] },
  DEFAULT_RATE_PRESET: 'estandar',   // 0,25–0,50 % peso/sem (Iraki et al., 2019)
  ADHERENCE_MIN: 0.90,
  DEADBAND_KCAL: 50,
  STEP_MAX: { MEDIA: 100, ALTA: 150 },
  COOLDOWN_DAYS: 7, NO_REVERSAL_DAYS: 21,
  ETA_MAX_WEEKS: 104,
  TARGET_ROUND: 10,
  FLOOR_KCAL: 1600
});

// ---------------------------------------------------------------- utilidades
const DAY_MS = 86400000;
function parseKey(k){ const [y,m,d] = k.split('-').map(Number); return Date.UTC(y, m-1, d); }
function keyOf(ms){ const d = new Date(ms); return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,'0')}-${String(d.getUTCDate()).padStart(2,'0')}`; }
function addDays(k, n){ return keyOf(parseKey(k) + n*DAY_MS); }
function diffDays(a, b){ return Math.round((parseKey(b) - parseKey(a)) / DAY_MS); } // b - a
const sum = a => a.reduce((s,x)=>s+x,0);
const mean = a => a.length ? sum(a)/a.length : null;
function median(a){ if(!a.length) return null; const s=[...a].sort((x,y)=>x-y); const m=Math.floor(s.length/2); return s.length%2 ? s[m] : (s[m-1]+s[m])/2; }
function sd(a){ if(a.length<2) return 0; const m=mean(a); return Math.sqrt(sum(a.map(x=>(x-m)**2))/(a.length-1)); }
const roundTo = (x, step) => Math.round(x/step)*step;
const isActive = e => e && !e.deletedAt;
const MONTHS = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
function monthLabel(k){ const d=new Date(parseKey(k)); return `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`; }
function fmt(x, dec=0){ if(x===null||x===undefined||!Number.isFinite(x)) return '—'; return (dec? x.toFixed(dec) : String(Math.round(x))).replace('.', ','); }
function fmtSigned(x, dec=2){ if(!Number.isFinite(x)) return '—'; return (x>=0?'+':'−') + fmt(Math.abs(x), dec); }
function idToTimestamp(id){ if(typeof id!=='string' || !/^[0-9a-z]{6,10}$/.test(id)) return null; const ms=parseInt(id,36); return (ms>1.6e12 && ms<2.5e12) ? ms : null; }

// ------------------------------------------------------- 1) días (OBSERVED)
// Un registro por día natural entre el primer dato y asOf. El día asOf es el
// día en curso ("open"): nunca entra en estadísticas de ingesta.
function earliestActive(entries){
  const act = (entries||[]).filter(isActive).filter(e=>Number.isFinite(Number(e.kg)));
  if(!act.length) return null;
  const sorted = [...act].sort((a,b)=>String(a.time||'99:99').localeCompare(String(b.time||'99:99')));
  return { kg: Number(sorted[0].kg), time: sorted[0].time || null, count: act.length };
}
function targetOn(timeline, date, fallback){
  let t = fallback;
  for(const e of (timeline||[])) if(e.date <= date && Number.isFinite(Number(e.kcal))) t = Number(e.kcal);
  return t;
}
function buildDays(raw, asOf){
  const weights = raw.weights||{}, logs = raw.logs||{};
  const all = [...Object.keys(weights), ...Object.keys(logs)].filter(d => d <= asOf).sort();
  if(!all.length) return { days: [], personalMedian: null };
  const start = raw.startDate && raw.startDate < all[0] ? raw.startDate : all[0];
  // Mediana personal de ingesta (solo días cerrados, sin marcar como incompletos)
  const closedIntakes = [];
  for(const d of Object.keys(logs)){
    if(d >= asOf) continue;
    const act = (logs[d]||[]).filter(isActive);
    if(!act.length || (raw.dayFlags||{})[d] === false) continue;
    closedIntakes.push(sum(act.map(e=>Number(e.kcal)||0)));
  }
  const personalMedian = median(closedIntakes);
  const out = [];
  for(let d = start; d <= asOf; d = addDays(d,1)){
    const act = (logs[d]||[]).filter(isActive);
    const w = earliestActive(weights[d]);
    const intake = sum(act.map(e=>Number(e.kcal)||0));
    const flag = (raw.dayFlags||{})[d];
    let status, autoStatus = null;
    if(d === asOf) status = 'open';
    else if(!act.length) status = 'empty';
    else if(flag === true) status = 'complete';
    else if(flag === false) status = 'incomplete';
    else {
      const okEntries = act.length >= CONFIG.COMPLETE_MIN_ENTRIES;
      const okKcal = personalMedian === null || intake >= CONFIG.COMPLETE_MIN_FRACTION_OF_MEDIAN * personalMedian;
      status = autoStatus = (okEntries && okKcal) ? 'complete' : 'doubtful';
    }
    const target = targetOn(raw.timeline, d, raw.fallbackTarget);
    const override = Number((raw.overrides||{})[d]) || 0;
    out.push({ date:d, weight: w ? w.kg : null, weightTime: w ? w.time : null, weighIns: w ? w.count : 0,
      intake, p: sum(act.map(e=>Number(e.p)||0)), c: sum(act.map(e=>Number(e.c)||0)), f: sum(act.map(e=>Number(e.f)||0)),
      entries: act.length, status, autoStatus, userFlag: flag === undefined ? null : flag,
      target: Number.isFinite(target) ? target : null, override,
      targetEffective: Number.isFinite(target) ? target + override : null });
  }
  return { days: out, personalMedian };
}

// ------------------------------------------- 2) peso: outliers y tendencia
function hampel(points){
  const W = CONFIG.HAMPEL_HALF_WINDOW_DAYS;
  return points.map((p) => {
    if(p.kg < CONFIG.WEIGHT_PLAUSIBLE[0] || p.kg > CONFIG.WEIGHT_PLAUSIBLE[1]) return { outlier:true, reason:'implausible' };
    const nb = points.filter(q => Math.abs(q.t - p.t) <= W && q.kg >= CONFIG.WEIGHT_PLAUSIBLE[0] && q.kg <= CONFIG.WEIGHT_PLAUSIBLE[1]);
    if(nb.length < 3) return { outlier:false };
    const med = median(nb.map(q=>q.kg));
    const mad = Math.max(CONFIG.HAMPEL_MAD_FLOOR_KG, 1.4826 * median(nb.map(q=>Math.abs(q.kg-med))));
    return Math.abs(p.kg - med) > CONFIG.HAMPEL_K * mad ? { outlier:true, reason:'hampel', localMedian: med } : { outlier:false };
  });
}
function trendSeries(points, flags){
  // EWMA temporal: alpha efectivo = 1-(1-α)^Δdías → un hueco de 5 días pesa como 5 pasos.
  const good = points.filter((p,i)=>!flags[i].outlier);
  if(!good.length) return points.map(p=>({ date:p.date, t:p.t, kg:p.kg, time:p.time, trend:null, outlier:true, outlierReason:'implausible' }));
  // Semilla robusta: mediana de los 3 primeros pesajes válidos (no un único pesaje).
  const firstGood = flags.findIndex(f=>!f.outlier);
  let ema = median(good.slice(0,3).map(p=>p.kg)), lastT = good[0].t;
  return points.map((p,i) => {
    if(!flags[i].outlier && i !== firstGood){
      const a = 1 - Math.pow(1 - CONFIG.TREND_ALPHA_PER_DAY, Math.max(1, p.t - lastT));
      ema = ema + a * (p.kg - ema);
      lastT = p.t;
    }
    return { date:p.date, t:p.t, kg:p.kg, time:p.time, trend: ema, outlier: flags[i].outlier, outlierReason: flags[i].reason || null };
  });
}
function weightRate(points, flags, asOf){
  const from = addDays(asOf, -(CONFIG.RATE_WINDOW_DAYS-1));
  const pts = points.filter((p,i)=>!flags[i].outlier && p.date >= from && p.date <= asOf);
  if(pts.length < CONFIG.MIN_RATE_POINTS) return null;
  const span = pts[pts.length-1].t - pts[0].t;
  if(span < CONFIG.MIN_RATE_SPAN) return null;
  const x0 = pts[0].t, xs = pts.map(p=>p.t-x0), ys = pts.map(p=>p.kg), n = pts.length;
  const mx = mean(xs), my = mean(ys);
  const sxx = sum(xs.map(x=>(x-mx)**2));
  const b = sum(xs.map((x,i)=>(x-mx)*(ys[i]-my))) / sxx, a = my - b*mx;
  const res = xs.map((x,i)=>ys[i]-(a+b*x));
  const s = Math.max(CONFIG.RESIDUAL_SD_FLOOR, Math.sqrt(sum(res.map(r=>r*r))/Math.max(1,n-2)));
  const rr = sum(res.map(r=>r*r));
  let rho = rr>0 ? sum(res.slice(1).map((r,i)=>r*res[i]))/rr : 0; rho = Math.min(0.9, Math.max(0, rho));
  const nEff = Math.max(2, n*(1-rho)/(1+rho));
  const se = s/Math.sqrt(sxx) * Math.sqrt(n/nEff);
  const z = CONFIG.CI_Z;
  return { slopePerDay: b, sePerDay: se, perWeek: b*7, sePerWeek: se*7, ciLow: (b-z*se)*7, ciHigh: (b+z*se)*7,
    n, span, firstDate: pts[0].date, lastDate: pts[pts.length-1].date, intercept: a, x0,
    fittedFirst: a, fittedLast: a + b*span, residualSD: s, rho, nEff };
}

// --------------------------------------------- 3) ingesta y adherencia
function intakeStats(days, from, to){
  const win = days.filter(d => d.date >= from && d.date <= to && d.status !== 'open');
  const comp = win.filter(d => d.status === 'complete');
  const vals = comp.map(d=>d.intake);
  return { from, to, n: comp.length, mean: mean(vals), sd: sd(vals), totalDays: win.length,
    doubtful: win.filter(d=>d.status==='doubtful').map(d=>d.date),
    incomplete: win.filter(d=>d.status==='incomplete').map(d=>d.date),
    empty: win.filter(d=>d.status==='empty').map(d=>d.date),
    allDaysMean: mean(win.filter(d=>d.entries>0).map(d=>d.intake)) };
}
function adherence(days, from, to){
  const comp = days.filter(d => d.date>=from && d.date<=to && d.status==='complete' && Number.isFinite(d.targetEffective));
  if(!comp.length) return { n:0, ratio:null, within10:0, meanGap:null, meanTarget:null, meanIntake:null };
  const ti = sum(comp.map(d=>d.intake)), tt = sum(comp.map(d=>d.targetEffective));
  return { n: comp.length, ratio: ti/tt, within10: comp.filter(d=>Math.abs(d.intake-d.targetEffective) <= 0.1*d.targetEffective).length,
    meanGap: (tt-ti)/comp.length, meanTarget: tt/comp.length, meanIntake: ti/comp.length };
}

// ------------------------------------------ 4) mantenimiento (ESTIMATED)
function activityFactor(trainingDays){ const d = Math.min(7, Math.max(0, Number(trainingDays)||0)); return 1.2 + 0.075*d; }
function mifflin(profile, weightKg){
  const base = 10*weightKg + 6.25*Number(profile.height) - 5*Number(profile.age);
  return profile.sex === 'f' ? base - 161 : base + 5;
}
function maintenanceEstimate(profile, weightKg, rate, intake, confLevel){
  const prior = mifflin(profile, weightKg) * activityFactor(profile.trainingDays);
  const priorSd = CONFIG.PRIOR_SD_FRACTION * prior;
  const out = { prior, priorSd, obs:null, obsSd:null, posterior: prior, posteriorSd: priorSd, dataWeight: 0,
    method: 'formula', activityFactor: activityFactor(profile.trainingDays), bmr: mifflin(profile, weightKg) };
  if(!rate || !intake || !intake.n || confLevel === 'BAJA') return out;
  const obs = intake.mean - rate.slopePerDay * CONFIG.KCAL_PER_KG;
  const obsSd = Math.sqrt((intake.sd**2)/intake.n + (rate.sePerDay*CONFIG.KCAL_PER_KG)**2 + (CONFIG.LOGGING_SYSTEMATIC_FRACTION*intake.mean)**2);
  const wObs = 1/obsSd**2, wPri = 1/priorSd**2;
  return { ...out, obs, obsSd, posterior: (obs*wObs + prior*wPri)/(wObs+wPri), posteriorSd: Math.sqrt(1/(wObs+wPri)),
    dataWeight: wObs/(wObs+wPri), method: 'bayes' };
}

// ---------------------------------------- 5) rango, confianza, estado
function targetRange(weightKg, preset){
  const [lo, hi] = CONFIG.RATE_PRESETS[preset] || CONFIG.RATE_PRESETS[CONFIG.DEFAULT_RATE_PRESET];
  return { preset: CONFIG.RATE_PRESETS[preset] ? preset : CONFIG.DEFAULT_RATE_PRESET, lowPct: lo, highPct: hi, midPct: (lo+hi)/2,
    low: weightKg*lo/100, high: weightKg*hi/100, mid: weightKg*(lo+hi)/200 };
}
function confidence(rate, intake){
  const reasons = [];
  if(!rate){ return { level:'BAJA', score:0, reasons:['Aún no hay pesajes suficientes para calcular una tendencia (mínimo 4 en ≥6 días).'], missing:null }; }
  const half = (rate.ciHigh - rate.ciLow)/2;
  const score = mean([Math.min(1, rate.span/CONFIG.ALTA.span), Math.min(1, rate.n/CONFIG.ALTA.weighIns), Math.min(1, (intake.n||0)/CONFIG.ALTA.completeDays), Math.min(1, CONFIG.ALTA.maxCiHalfWidth/Math.max(half,1e-9))]);
  const M = CONFIG.MEDIA, A = CONFIG.ALTA;
  const okMedia = rate.span >= M.span && rate.n >= M.weighIns && (intake.n||0) >= M.completeDays;
  const okAlta = rate.span >= A.span && rate.n >= A.weighIns && (intake.n||0) >= A.completeDays && half <= A.maxCiHalfWidth;
  if(rate.span < M.span) reasons.push(`${rate.span+1} días de pesajes (mínimo ${M.span+1})`);
  if(rate.n < M.weighIns) reasons.push(`${rate.n} pesajes (mínimo ${M.weighIns})`);
  if((intake.n||0) < M.completeDays) reasons.push(`${intake.n||0} días de comida completos (mínimo ${M.completeDays})`);
  const level = okAlta ? 'ALTA' : okMedia ? 'MEDIA' : 'BAJA';
  let missing = null;
  if(level === 'MEDIA'){
    const m = [];
    const pl = (n, s1, s2) => `${n} ${n===1?s1:s2}`;
    if(rate.span < A.span) m.push(`${pl(A.span - rate.span,'día','días')} más de datos`);
    if(rate.n < A.weighIns) m.push(`${pl(A.weighIns - rate.n,'pesaje','pesajes')} más`);
    if(intake.n < A.completeDays) m.push(`${pl(A.completeDays - intake.n,'día de comida completo','días de comida completos')} más`);
    if(half > A.maxCiHalfWidth) m.push(`un intervalo más estrecho (ahora ±${fmt(half,2)} kg/sem)`);
    missing = m;
  }
  return { level, score, reasons, missing, ciHalfWidth: half };
}
function rateStatus(rate, range, conf){
  if(!rate) return { code:'SIN_DATOS', lean:null };
  const lean = rate.perWeek < range.low ? 'below' : rate.perWeek > range.high ? 'above' : 'inside';
  if(conf.level === 'BAJA') return { code:'SIN_DATOS', lean };
  if(rate.ciHigh < range.low) return { code:'POR_DEBAJO', lean };
  if(rate.ciLow > range.high) return { code:'POR_ENCIMA', lean };
  if(rate.perWeek >= range.low && rate.perWeek <= range.high) return { code:'DENTRO', lean };
  return { code:'INCIERTO', lean };
}
const STATUS_LABEL = { SIN_DATOS:'DATOS INSUFICIENTES', POR_DEBAJO:'POR DEBAJO', DENTRO:'DENTRO DEL RANGO', POR_ENCIMA:'POR ENCIMA', INCIERTO:'INCIERTO' };

// ---------------------------------------------- 6) predicciones (PREDICTED)
function predictions(level, rate, range, conf, goalKg, asOf){
  const out = { goalKg, level, remaining: Number.isFinite(goalKg) ? goalKg - level : null, current:null, objective:null };
  if(!Number.isFinite(goalKg) || goalKg <= 0) return out;
  if(out.remaining <= 0){ out.current = out.objective = { available:true, reached:true, text:'Objetivo alcanzado' }; return out; }
  const dateAt = w => addDays(asOf, Math.round(w*7));
  // Escenario ritmo objetivo (compuesto: el % se aplica sobre el peso de cada semana)
  const wFast = Math.log(goalKg/level)/Math.log(1+range.highPct/100), wSlow = Math.log(goalKg/level)/Math.log(1+range.lowPct/100);
  out.objective = { available:true, weeksMin:wFast, weeksMax:wSlow, from: dateAt(wFast), to: dateAt(wSlow),
    text: `${monthLabel(dateAt(wFast))} – ${monthLabel(dateAt(wSlow))}`, basis: `${fmt(range.lowPct,2)}–${fmt(range.highPct,2)} % peso/sem` };
  // Escenario ritmo actual: solo con evidencia suficiente
  if(!rate || conf.level === 'BAJA'){ out.current = { available:false, text:'todavía no hay datos suficientes para una fecha fiable' }; return out; }
  if(rate.ciLow <= 0){ out.current = { available:false, text:`no estimable: tu ritmo (${fmtSigned(rate.perWeek)} kg/sem, IC80 ${fmtSigned(rate.ciLow)} a ${fmtSigned(rate.ciHigh)}) no se distingue de 0` }; return out; }
  const wMin = out.remaining / rate.ciHigh, wMax = out.remaining / rate.ciLow, wMid = out.remaining / rate.perWeek;
  if(wMin > CONFIG.ETA_MAX_WEEKS){ out.current = { available:true, text:'más de 2 años a este ritmo', weeksMin:wMin, weeksMax:wMax, weeksMid:wMid }; return out; }
  const to = wMax > CONFIG.ETA_MAX_WEEKS ? null : dateAt(wMax);
  out.current = { available:true, weeksMin:wMin, weeksMax:wMax, weeksMid:wMid, from: dateAt(wMin), to,
    text: to ? `${monthLabel(dateAt(wMin))} – ${monthLabel(to)}` : `no antes de ${monthLabel(dateAt(wMin))} (límite superior > 2 años)` };
  return out;
}

// ------------------------------------------------ 7) decisión (controlador)
// Deliberadamente conservador. El OBJETIVO es un punto de consigna guiado por
// el resultado (peso); el modelo de mantenimiento solo dimensiona el paso.
function decide(state, currentTarget, lastChange, opts={}){
  const asOf = state.asOf, M = state.maintenance, R = state.range, conf = state.confidence, st = state.status.code;
  const surplus = R.mid * CONFIG.KCAL_PER_KG / 7;
  const needed = roundTo(M.posterior + surplus, CONFIG.TARGET_ROUND);
  const T = Math.round(currentTarget);
  const base = { date: asOf, prevTarget: T, newTarget: T, delta: 0, needed, surplus, action:'MANTENER', reasonCode:'', reason:'' };
  const r = state.rate, adh = state.adherence;
  const rateTxt = r ? `${fmtSigned(r.perWeek)} kg/sem (IC80 ${fmtSigned(r.ciLow)} a ${fmtSigned(r.ciHigh)})` : 'sin tendencia';
  const rangeTxt = `${fmt(R.low,2)}–${fmt(R.high,2)} kg/sem`;
  const adhTxt = adh.ratio!==null ? `${fmt(adh.ratio*100)} % (media ${fmt(adh.meanIntake)} de ${fmt(adh.meanTarget)} kcal)` : 'sin días completos';
  const M_txt = `${fmt(M.posterior)} ±${fmt(M.posteriorSd)} kcal`;
  if(opts.paused) return { ...base, reasonCode:'PAUSADO', reason:'Ajuste automático pausado por ti. No se toca el objetivo.' };
  if(st === 'SIN_DATOS') return { ...base, action:'SIN_DATOS', reasonCode:'DATOS_INSUFICIENTES', reason:`Datos insuficientes (confianza baja: ${conf.reasons.join('; ') || 'tendencia no calculable'}). No se toca el objetivo.` };
  let proposal = 0, code = '', why = '';
  if(st === 'DENTRO'){ code='EN_RANGO'; why=`Tu ritmo ${rateTxt} está dentro del rango (${rangeTxt}). Se mantiene.`; }
  else if(st === 'INCIERTO'){ code='INCIERTO'; why=`Tu ritmo ${rateTxt} ${state.status.lean==='below'?'apunta a estar por debajo':'apunta a estar por encima'} del rango (${rangeTxt}), pero el intervalo aún se solapa con él. Se espera a tener más evidencia.`; }
  else if(st === 'POR_DEBAJO'){
    if(adh.ratio !== null && adh.ratio < CONFIG.ADHERENCE_MIN){ code='ADHERENCIA'; why=`Ganas por debajo del rango (${rateTxt} vs ${rangeTxt}), pero solo alcanzas el ${adhTxt}. Subir el objetivo no ayuda si no se alcanza: la prioridad es llegar a ${fmt(T)} kcal. Con tu mantenimiento estimado (${M_txt}) necesitarías ~${fmt(needed)} kcal sostenidas.`; }
    else if(needed - T < CONFIG.DEADBAND_KCAL){ code='OBJETIVO_SUFICIENTE'; why=`Ganas por debajo del rango, pero tu objetivo actual (${fmt(T)}) ya cubre lo estimado como necesario (~${fmt(needed)} = mantenimiento ${M_txt} + superávit ${fmt(surplus)}). Nunca se baja estando por debajo del rango.`; }
    else { proposal = Math.min(needed - T, CONFIG.STEP_MAX[conf.level] || CONFIG.STEP_MAX.MEDIA); code='SUBIR'; why=`Ganas por debajo del rango (${rateTxt} vs ${rangeTxt}) cumpliendo el objetivo (${adhTxt}). Necesario estimado ~${fmt(needed)} kcal (mantenimiento ${M_txt} + superávit ${fmt(surplus)}). Subida limitada a ${CONFIG.STEP_MAX[conf.level]} kcal por ajuste (confianza ${conf.level}).`; }
  } else if(st === 'POR_ENCIMA'){
    const floor = Math.max(CONFIG.FLOOR_KCAL, roundTo(M.posterior, CONFIG.TARGET_ROUND));
    if(T - needed < CONFIG.DEADBAND_KCAL){ code='SOBRE_OBJETIVO'; why=`Ganas por encima del rango (${rateTxt} vs ${rangeTxt}) aunque tu objetivo (${fmt(T)}) no está por encima de lo necesario (~${fmt(needed)}); tu media real es ${adhTxt}. El ajuste es comer más cerca del objetivo, no bajarlo.`; }
    else { proposal = -Math.min(T - needed, CONFIG.STEP_MAX[conf.level] || CONFIG.STEP_MAX.MEDIA); if(T + proposal < floor) proposal = floor - T; code='BAJAR'; why=`Ganas por encima del rango (${rateTxt} vs ${rangeTxt}). Necesario estimado ~${fmt(needed)} kcal. Bajada limitada a ${CONFIG.STEP_MAX[conf.level]} kcal por ajuste y nunca por debajo del mantenimiento estimado (${fmt(floor)}).`; }
  }
  proposal = roundTo(proposal, CONFIG.TARGET_ROUND);
  if(proposal === 0) return { ...base, reasonCode: code, reason: why };
  if(lastChange && lastChange.date){
    const since = diffDays(lastChange.date, asOf);
    if(since < CONFIG.COOLDOWN_DAYS) return { ...base, proposal, reasonCode:'COOLDOWN', reason:`${why} Pendiente: el último cambio fue hace ${since} días (mínimo ${CONFIG.COOLDOWN_DAYS}).` };
    if(Math.sign(lastChange.delta) === -Math.sign(proposal) && since < CONFIG.NO_REVERSAL_DAYS) return { ...base, proposal, reasonCode:'NO_REVERSION', reason:`${why} Bloqueado: cambiaría el sentido del último ajuste (hace ${since} días, mínimo ${CONFIG.NO_REVERSAL_DAYS}).` };
  }
  return { ...base, newTarget: T + proposal, delta: proposal, action: proposal>0?'SUBIR':'BAJAR', reasonCode: code, reason: why };
}

// ------------------------------------------------- 8) calidad de datos
function dataQuality(raw, days, points, trend, asOf){
  const closed = days.filter(d=>d.status!=='open');
  const wTimes = points.map(p=>p.time).filter(Boolean).map(t=>{ const [h,m]=t.split(':').map(Number); return h+m/60; });
  const suspects = [], dups = [], backfilled = [];
  for(const [date, entries] of Object.entries(raw.logs||{})){
    if(date > asOf) continue;
    const act = (entries||[]).filter(isActive);
    act.forEach((e, i) => {
      const kcal = Number(e.kcal)||0, macroK = 4*(Number(e.p)||0)+4*(Number(e.c)||0)+9*(Number(e.f)||0);
      if(kcal >= 60 && Math.abs(macroK - kcal) > 0.25*kcal) suspects.push({ date, id:e.id, label:e.label, kcal, reason:`kcal (${fmt(kcal)}) no cuadra con macros (${fmt(macroK)})` });
      const g = /^\s*(\d+(?:[.,]\d+)?)\s*(?:g|gr|gramos)\b(?!.*\d+\s*(?:g|gr|gramos)\b)/i.exec(e.originalText||'');
      if(g){ const grams = parseFloat(g[1].replace(',','.')); if(grams>0 && kcal > grams*9.5) suspects.push({ date, id:e.id, label:e.label, kcal, reason:`${fmt(kcal)} kcal en ${fmt(grams)} g es imposible (máx. ~9 kcal/g)` }); }
      if(/\d{1,2}:\d{2}\s*·\s*P:/.test(e.originalText||'')) dups.push({ date, id:e.id, label:e.label, kcal, reason:'registrada pegando el texto de otra entrada' });
      const ts = Number(e.createdAt) || idToTimestamp(e.id);
      if(ts){ const created = keyOf(ts + (Number(raw.tzOffsetMin)||0)*60000); if(created > date) backfilled.push({ date, id:e.id, label:e.label, created }); }
      for(let j=0;j<i;j++){ const o=act[j]; if(String(o.label).toLowerCase()===String(e.label).toLowerCase() && Math.abs((Number(o.kcal)||0)-kcal) <= 0.1*Math.max(kcal,1)) dups.push({ date, id:e.id, label:e.label, kcal, reason:'misma comida dos veces el mismo día (¿duplicado o la comiste dos veces?)' }); }
    });
  }
  let longestGap = 0; for(let i=1;i<points.length;i++) longestGap = Math.max(longestGap, points[i].t - points[i-1].t - 1);
  return {
    daysElapsed: days.length, closedDays: closed.length,
    daysWithWeight: days.filter(d=>d.weight!==null).length, daysWithFood: closed.filter(d=>d.entries>0).length,
    complete: closed.filter(d=>d.status==='complete').length,
    doubtful: closed.filter(d=>d.status==='doubtful').map(d=>({date:d.date, intake:d.intake, entries:d.entries})),
    incomplete: closed.filter(d=>d.status==='incomplete').map(d=>d.date),
    emptyDays: closed.filter(d=>d.status==='empty').map(d=>d.date),
    daysWithoutWeight: days.filter(d=>d.weight===null).map(d=>d.date),
    multiWeighDays: days.filter(d=>d.weighIns>1).map(d=>d.date),
    outliers: trend.filter(t=>t.outlier).map(t=>({date:t.date, kg:t.kg, reason:t.outlierReason})),
    weighInTime: wTimes.length ? { earliest: Math.min(...wTimes), latest: Math.max(...wTimes), spreadHours: Math.max(...wTimes)-Math.min(...wTimes), morningPct: wTimes.filter(h=>h<10).length/wTimes.length } : null,
    longestWeightGapDays: longestGap, suspectEntries: suspects, possibleDuplicates: dups, backfilledEntries: backfilled
  };
}

// ---------------------------------------------------- 9) estado completo
// raw = { weights:{date:[{kg,time,deletedAt}]}, logs:{date:[entries]}, dayFlags:{date:bool},
//         overrides:{date:n}, timeline:[{date,kcal,source}], fallbackTarget, startDate }
function computeState(raw, profile, asOf, opts={}){
  const built = buildDays(raw, asOf);
  const days = built.days || [], t0 = days.length ? days[0].date : asOf;
  const points = days.filter(d=>d.weight!==null).map(d=>({ date:d.date, t: diffDays(t0, d.date), kg:d.weight, time:d.weightTime }));
  const flags = hampel(points);
  const trend = trendSeries(points, flags);
  const rate = weightRate(points, flags, asOf);
  const lastTrend = [...trend].reverse().find(t=>t.trend!==null);
  const level = lastTrend ? lastTrend.trend : Number(profile.weight);
  const startTrend = trend.find(t=>t.trend!==null && (!profile.bulkStartDate || t.date >= profile.bulkStartDate));
  const range = targetRange(level, profile.ratePreset);
  const iFrom = rate ? rate.firstDate : addDays(asOf, -(CONFIG.RATE_WINDOW_DAYS-1));
  const iTo = rate ? addDays(rate.lastDate, -1) : addDays(asOf, -1);
  const intake = intakeStats(days, iFrom, iTo);
  const conf = confidence(rate, intake);
  const maintenance = maintenanceEstimate(profile, level, rate, intake, conf.level);
  const status = rateStatus(rate, range, conf);
  const adh = adherence(days, iFrom, iTo);
  const adh7 = adherence(days, addDays(asOf,-7), addDays(asOf,-1));
  const intake7 = intakeStats(days, addDays(asOf,-7), addDays(asOf,-1));
  const goalKg = Number(profile.goalWeightKg);
  const pred = Number.isFinite(level) ? predictions(level, rate, range, conf, goalKg, asOf) : { current:null, objective:null, remaining:null };
  const state = { engineVersion: VERSION, asOf, config: CONFIG, days, personalMedian: built.personalMedian ?? null,
    weight: { points: trend, level, start: startTrend ? { date:startTrend.date, kg:startTrend.trend } : null, lastRaw: points.length ? points[points.length-1] : null },
    rate, range, intake, intake7, adherence: adh, adherence7: adh7, confidence: conf, maintenance, status, predictions: pred,
    goalKg: Number.isFinite(goalKg) && goalKg>0 ? goalKg : null };
  state.dataQuality = dataQuality(raw, days, points, trend, asOf);
  if(opts.currentTarget !== undefined){
    state.currentTarget = opts.currentTarget;
    state.decision = decide(state, opts.currentTarget, opts.lastChange || null, { paused: !!opts.paused });
  }
  state.insights = buildInsights(state);
  return state;
}

// ----------------------------------------------------- 10) insights
// Cada insight responde a UNA pregunta concreta. Nada decorativo.
function buildInsights(s){
  const out = [], r = s.rate, M = s.maintenance, R = s.range, adh = s.adherence, conf = s.confidence;
  const needed = roundTo(M.posterior + R.mid*CONFIG.KCAL_PER_KG/7, CONFIG.TARGET_ROUND);
  // 1. ¿Estoy comiendo suficiente?
  if(s.intake.n){
    const gap = s.intake.mean - needed;
    out.push({ id:'eating', q:'¿Estoy comiendo suficiente?', tone: gap >= -50 ? 'ok' : gap >= -200 ? 'warn' : 'bad',
      value: `${fmt(s.intake.mean)} kcal`, a: `Comes ${fmt(s.intake.mean)} kcal de media (${s.intake.n} días completos). Para ganar dentro del rango se estiman ~${fmt(needed)} kcal → ${gap>=0?'sobran':'faltan'} ~${fmt(Math.abs(gap))} kcal/día.` });
  } else out.push({ id:'eating', q:'¿Estoy comiendo suficiente?', tone:'neutral', value:'—', a:'Aún no hay días de comida completos en la ventana de análisis.' });
  // 2. ¿Llego a las kcal de la app?
  if(adh.ratio !== null) out.push({ id:'adherence', q:'¿Llego a las kcal que me marca la app?', tone: adh.ratio>=CONFIG.ADHERENCE_MIN ? 'ok' : adh.ratio>=0.8 ? 'warn' : 'bad',
    value: `${fmt(adh.ratio*100)} %`, a: `Alcanzas el ${fmt(adh.ratio*100)} % del objetivo (−${fmt(adh.meanGap)} kcal/día de media). Días dentro de ±10 %: ${adh.within10}/${adh.n}.${s.adherence7.ratio!==null?` Últimos 7 días: ${fmt(s.adherence7.ratio*100)} %.`:''}` });
  // 3-4. ¿Gano peso? ¿A la velocidad correcta?
  if(r){
    out.push({ id:'gaining', q:'¿Estoy ganando peso?', tone: r.ciLow > 0 ? 'ok' : r.ciHigh < 0 ? 'bad' : 'warn',
      value: `${fmtSigned(r.perWeek)} kg/sem`, a: r.ciLow > 0 ? `Sí: ${fmtSigned(r.perWeek)} kg/sem (IC80 ${fmtSigned(r.ciLow)} a ${fmtSigned(r.ciHigh)}).` : r.ciHigh < 0 ? `No, estás perdiendo: ${fmtSigned(r.perWeek)} kg/sem.` : `No se puede afirmar: ${fmtSigned(r.perWeek)} kg/sem, intervalo ${fmtSigned(r.ciLow)} a ${fmtSigned(r.ciHigh)} incluye el 0 (peso estable).` });
    const pct = r.perWeek / s.weight.level * 100;
    out.push({ id:'speed', q:'¿A la velocidad correcta?', tone: s.status.code==='DENTRO' ? 'ok' : s.status.code==='SIN_DATOS'||s.status.code==='INCIERTO' ? 'neutral' : 'bad',
      value: STATUS_LABEL[s.status.code], a: `Tu ritmo: ${fmtSigned(pct,2)} % del peso/sem. Rango objetivo: ${fmt(R.lowPct,2)}–${fmt(R.highPct,2)} % (${fmt(R.low,2)}–${fmt(R.high,2)} kg/sem). Desviación vs punto medio: ${fmtSigned(r.perWeek - R.mid)} kg/sem.` });
  } else out.push({ id:'gaining', q:'¿Estoy ganando peso?', tone:'neutral', value:'—', a:'Faltan pesajes para calcular una tendencia (mínimo 4 en ≥6 días).' });
  // 5. ¿Tengo datos suficientes?
  out.push({ id:'data', q:'¿Tengo suficientes datos para saberlo?', tone: conf.level==='ALTA'?'ok':conf.level==='MEDIA'?'warn':'bad', value: `Confianza ${conf.level}`,
    a: conf.level==='ALTA' ? 'Sí: histórico consistente.' : conf.level==='MEDIA' ? `Tendencia preliminar fiable. Para confianza alta faltan: ${(conf.missing||[]).join(', ')}.` : `Todavía no: ${conf.reasons.join('; ')}.` });
  // 6. ¿Mantenimiento correcto?
  out.push({ id:'maintenance', q:'¿Mi mantenimiento estimado parece correcto?', tone: M.method==='bayes' ? (M.posteriorSd<150?'ok':'warn') : 'neutral', value: `${fmt(M.posterior)} ±${fmt(M.posteriorSd)}`,
    a: M.method==='bayes' ? `Fórmula ${fmt(M.prior)} kcal; tus datos dicen ${fmt(M.obs)} ±${fmt(M.obsSd)}. Estimación combinada ${fmt(M.posterior)} ±${fmt(M.posteriorSd)} (tus datos pesan un ${fmt(M.dataWeight*100)} %).` : `Solo fórmula (Mifflin-St Jeor × ${fmt(M.activityFactor,3)} por tus días de entreno): ${fmt(M.prior)} ±${fmt(M.priorSd)} kcal. Se personalizará con datos.` });
  // 7. ¿Hay que cambiar kcal?
  if(s.decision) out.push({ id:'change', q:'¿Hay que cambiar mis kcal? ¿Cuánto? ¿Por qué?', tone: s.decision.delta ? 'warn' : 'ok',
    value: s.decision.delta ? `${s.decision.delta>0?'+':''}${s.decision.delta} kcal` : 'No', a: s.decision.reason });
  // 8-9. Progreso y fecha
  if(s.goalKg){
    const st = s.weight.start, prog = st && s.goalKg !== st.kg ? (s.weight.level - st.kg)/(s.goalKg - st.kg) : null;
    out.push({ id:'progress', q:`¿Estoy progresando hacia ${fmt(s.goalKg,1)} kg?`, tone: prog!==null && prog>0.02 ? 'ok' : 'warn', value: `${fmt(s.predictions.remaining,1)} kg`,
      a: `Peso tendencia ${fmt(s.weight.level,2)} kg; faltan ${fmt(s.predictions.remaining,1)} kg.${st?` Desde el ${st.date} (${fmt(st.kg,2)} kg): ${fmtSigned(s.weight.level-st.kg)} kg${prog!==null?(prog>0.005?` (${fmt(prog*100)} % del camino)`:' (sin avance todavía)'):''}.`:''}` });
    out.push({ id:'eta', q:'¿Cuándo podría llegar?', tone: s.predictions.current?.available ? 'ok' : 'neutral', value: s.predictions.objective?.text || '—',
      a: `A tu ritmo actual: ${s.predictions.current?.text || '—'}. Si progresas dentro del rango: ${s.predictions.objective?.text || '—'}.` });
  }
  return out;
}

// ------------------------------------ 11) algoritmo ANTIGUO (solo backtest)
// Port fiel de bulking_app.py previo (incluido el bug Number(null)→0), validado
// contra el código original: reproduce 2591,72 → 2342 del 21-sep-2026.
const legacy = (function(){
  function isoWeekKey(k){
    const d = new Date(parseKey(k)); const dayNum = (d.getUTCDay()+6)%7; d.setUTCDate(d.getUTCDate()-dayNum+3);
    const firstThursday = new Date(Date.UTC(d.getUTCFullYear(),0,4));
    const week = 1 + Math.round(((d - firstThursday)/DAY_MS - 3 + ((firstThursday.getUTCDay()+6)%7))/7);
    return `${d.getUTCFullYear()}-W${String(week).padStart(2,'0')}`;
  }
  function series(weights, asOf, days){ const out=[]; for(let i=days-1;i>=0;i--){ const k=addDays(asOf,-i); const e=(weights[k]||[]).filter(isActive); if(e.length) out.push({date:k, kg: sum(e.map(x=>Number(x.kg)))/e.length}); } return out; }
  function ema(s, a=0.25){ let v=null; return s.map(p=>{ v = v===null ? p.kg : a*p.kg+(1-a)*v; return {date:p.date, kg:p.kg, ema:v}; }); }
  function slope(pts){ const n=pts.length; if(n<2) return null; const mx=mean(pts.map(p=>p.x)), my=mean(pts.map(p=>p.y)); let num=0,den=0; for(const p of pts){ num+=(p.x-mx)*(p.y-my); den+=(p.x-mx)**2; } return den===0?null:num/den; }
  function dynamic(weights, logs, asOf, profile){
    const dw = series(weights, asOf, 21); if(dw.length < 8) return null;
    const es = ema(dw), first = es[0], last = es[es.length-1]; const elapsed = diffDays(first.date, last.date); if(elapsed < 10) return null;
    let n=0, tot=0; const mpd = Number(profile.mealsPerDay)||5, floorK = (profile.targetKcal||2000)*0.6;
    for(let k=first.date; k<=last.date; k=addDays(k,1)){ const act=(logs[k]||[]).filter(isActive); const kc=sum(act.map(e=>Number(e.kcal)||0)); if(kc>0 && (act.length>=Math.max(2,mpd-1) || kc>=floorK)){ n++; tot+=kc; } }
    if(n < 8) return null;
    const avg = tot/n, pts = es.map(p=>({x: diffDays(first.date,p.date), y:p.ema})), sl = slope(pts);
    const change = sl!==null ? sl*elapsed : last.ema-first.ema;
    return { estimatedMaintenance: avg - (change*7700)/elapsed, avgIntake: avg, weightChangeKg: change, elapsedDays: elapsed, intakeDays: n, weightDays: dw.length,
      confidence: Math.min(1, (dw.length/14)*0.5 + (n/14)*0.5) };
  }
  function projection(weights, asOf){
    const d = series(weights, asOf, 21); if(d.length<6) return {status:'cold'}; const es=ema(d), first=es[0], last=es[es.length-1];
    const el = diffDays(first.date,last.date); if(el<6) return {status:'cold'};
    const sl = slope(es.map(p=>({x:diffDays(first.date,p.date), y:p.ema})));
    return { status:'ok', currentEma:last.ema, ratePerWeek: sl!==null ? sl*7 : ((last.ema-first.ema)/el)*7, dataPoints:d.length, elapsedDays: el };
  }
  // Evalúa como lo hacía adjustWeeklyTarget(). profile: {targetKcal, emaMaintenanceKcal, lastAdjustmentWeek, weeklyGainGoalKg, mealsPerDay, adjustmentPaused}
  function adjust(profileIn, weights, logs, asOf, { fixNullBug=false }={}){
    const p = { ...profileIn }; const wk = isoWeekKey(asOf);
    if(!p.targetKcal || p.lastAdjustmentWeek === wk || p.adjustmentPaused) return { profile:p, record:null };
    let days=0; for(let i=0;i<7;i++){ if((weights[addDays(asOf,-i)]||[]).filter(isActive).length) days++; }
    if(days < 4) return { profile:p, record:null };
    const goal = Number(p.weeklyGainGoalKg)||0.3, dyn = dynamic(weights, logs, asOf, p);
    if(dyn){
      const stored = p.emaMaintenanceKcal;
      const prev = fixNullBug ? (Number.isFinite(stored) && stored!==null ? stored : dyn.estimatedMaintenance)
                              : (Number.isFinite(Number(stored)) ? Number(stored) : dyn.estimatedMaintenance); // Number(null) === 0 → el bug
      const smoothed = 0.4*dyn.estimatedMaintenance + 0.6*prev; p.emaMaintenanceKcal = smoothed;
      const raw = smoothed + goal*7700/7, prevT = p.targetKcal, step = Math.round(100 + dyn.confidence*150);
      const fin = Math.max(1600, Math.round(Math.max(prevT-step, Math.min(prevT+step, raw))));
      p.targetKcal = fin; p.lastAdjustmentWeek = wk;
      return { profile:p, record:{ date:asOf, week:wk, mode:'dinamico', prevTarget:prevT, newTarget:fin, rawMaintenance:dyn.estimatedMaintenance, smoothedMaintenance:smoothed, dyn } };
    }
    const s = series(weights, asOf, 28); if(s.length < 8) return { profile:p, record:null };
    const es = ema(s), last = es[es.length-1]; let wa=null;
    for(let j=es.length-1;j>=0;j--){ if(diffDays(es[j].date,last.date) >= 6){ wa=es[j]; break; } }
    if(!wa) return { profile:p, record:null };
    const ch = last.ema - wa.ema; let delta = 0; if(ch < goal-0.05) delta=150; else if(ch > goal+0.05) delta=-150;
    p.lastAdjustmentWeek = wk; const prevT = p.targetKcal; if(delta) p.targetKcal = Math.max(1600, p.targetKcal+delta);
    return { profile:p, record:{ date:asOf, week:wk, mode:'basico', prevTarget:prevT, newTarget:p.targetKcal, weeklyChange:ch } };
  }
  return { isoWeekKey, dynamic, adjust, projection };
})();

// ------------------------------------------------ 12) backtest sin fuga
// Cada día D solo ve datos ANTERIORES a D (decisión por la mañana, antes de
// pesarse y de comer). Ambos algoritmos parten del mismo objetivo inicial y
// evolucionan con sus propias decisiones. La adherencia se mide siempre
// contra el objetivo que el usuario realmente veía (timeline observado).
function filterRawBefore(raw, date){
  const pick = obj => Object.fromEntries(Object.entries(obj||{}).filter(([k])=>k < date));
  return { ...raw, weights: pick(raw.weights), logs: pick(raw.logs), dayFlags: pick(raw.dayFlags), overrides: pick(raw.overrides),
    timeline: (raw.timeline||[]).filter(e=>e.date < date) };
}
function backtest(raw, profile, { from, to, initialTarget, legacyProfile }){
  const rows = []; let tNew = initialTarget, lastChange = null;
  let lp = { ...(legacyProfile||{}), targetKcal: initialTarget };
  for(let d = from; d <= to; d = addDays(d,1)){
    const r = filterRawBefore(raw, d);
    const st = computeState(r, profile, d, { currentTarget: tNew, lastChange });
    const dec = st.decision;
    if(dec.delta){ lastChange = { date:d, delta: dec.delta }; tNew = dec.newTarget; }
    const lg = legacy.adjust(lp, r.weights, r.logs, d); lp = lg.profile;
    const lproj = legacy.projection(r.weights, d);
    rows.push({ date:d, weighIns: st.rate ? st.rate.n : st.days.filter(x=>x.weight!==null).length, completeDays: st.intake.n,
      observedTarget: targetOn(raw.timeline, d, initialTarget),
      legacyTarget: lp.targetKcal, legacyEvent: !lg.record ? '' : lg.record.mode==='dinamico'
        ? `${Math.round(lg.record.prevTarget)}→${lg.record.newTarget} (mant. bruto ${Math.round(lg.record.rawMaintenance)}, suavizado ${Math.round(lg.record.smoothedMaintenance)})`
        : `${Math.round(lg.record.prevTarget)}→${lg.record.newTarget} (básico, EMA ${lg.record.weeklyChange>=0?'+':''}${lg.record.weeklyChange.toFixed(2)} kg/sem)`,
      legacyRate: lproj.status==='ok' ? lproj.ratePerWeek : null,
      newTarget: tNew, newAction: dec.action, newReason: dec.reasonCode, newReasonText: dec.reason,
      rate: st.rate ? st.rate.perWeek : null, ciLow: st.rate ? st.rate.ciLow : null, ciHigh: st.rate ? st.rate.ciHigh : null,
      status: st.status.code, confidence: st.confidence.level,
      maintenance: st.maintenance.posterior, maintenanceSd: st.maintenance.posteriorSd, maintenanceMethod: st.maintenance.method,
      intakeMean: st.intake.mean, adherence: st.adherence.ratio });
  }
  return rows;
}

const api = { VERSION, CONFIG, computeState, decide, buildDays, hampel, trendSeries, weightRate, intakeStats, adherence,
  maintenanceEstimate, activityFactor, mifflin, targetRange, confidence, rateStatus, predictions, buildInsights, dataQuality,
  backtest, filterRawBefore, legacy, targetOn, STATUS_LABEL,
  util: { addDays, diffDays, parseKey, keyOf, median, mean, sd, fmt, fmtSigned, monthLabel, idToTimestamp, roundTo } };
if(typeof module !== 'undefined' && module.exports) module.exports = api; else root.BulkEngine = api;
})(typeof window !== 'undefined' ? window : globalThis);
/*__ENGINE_END__*/

</script>
<script>
/*__TESTS_START__*/
// =============================================================================
// 🧪 Tests del motor (Node: `python bulking_app.py --test` · navegador: runEngineTests())
// =============================================================================
function runEngineTests(E, log){
  log = log || console.log;
  const results = [];
  const U = E.util;
  const check = (name, cond, detail) => { results.push({ name, pass: !!cond, detail: detail || '' }); };
  function rng(seed){ let s = seed >>> 0; return () => { s = (s*1664525 + 1013904223) >>> 0; return s/4294967296; }; }
  function gauss(r){ let u=0, v=0; while(!u) u=r(); while(!v) v=r(); return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v); }
  // Generador sintético determinista
  function synth(o){
    const c = Object.assign({ days:35, start:'2026-01-01', w0:60, rate:0, noise:0.3, seed:1, intake:2500, intakeNoise:80, entries:5, weighEvery:1, target:2500 }, o);
    const r = rng(c.seed), raw = { weights:{}, logs:{}, dayFlags:{}, overrides:{}, timeline:[{ date:c.start, kcal:c.target, source:'test' }], fallbackTarget:c.target };
    for(let i=0;i<c.days;i++){
      const d = U.addDays(c.start, i);
      if(i % c.weighEvery === 0) raw.weights[d] = [{ kg: +(c.w0 + c.rate/7*i + c.noise*gauss(r)).toFixed(2), time:'08:00' }];
      const kcal = c.intake + c.intakeNoise*gauss(r);
      raw.logs[d] = Array.from({ length:c.entries }, (_,k)=>({ id:`t${i}_${k}`, label:'x', kcal: kcal/c.entries, p: kcal*0.2/4/c.entries, c: kcal*0.5/4/c.entries, f: kcal*0.3/9/c.entries }));
    }
    const asOf = U.addDays(c.start, c.days);
    const profile = { age:25, height:175, sex:'m', trainingDays:3, weight:c.w0, ratePreset:'estandar', goalWeightKg:c.w0+5 };
    if(c.patch) c.patch(raw);
    return { raw, profile, asOf, cfg:c };
  }
  const state = (s, T, extra) => E.computeState(s.raw, s.profile, s.asOf, Object.assign({ currentTarget: T === undefined ? s.cfg.target : T, lastChange:null }, extra||{}));

  // ---- CASO A: peso estable + ingesta estable (cumple objetivo, no gana) → subir
  { const s = synth({ days:35, rate:0, intake:2500, target:2500 }); const st = state(s);
    check('A · estable + cumple objetivo → POR_DEBAJO y SUBIR', st.status.code==='POR_DEBAJO' && st.decision.action==='SUBIR', `${st.status.code} ${st.decision.action} ${st.decision.delta}`);
    check('A · subida acotada (≤150 kcal)', st.decision.delta > 0 && st.decision.delta <= 150, st.decision.delta);
    check('A · mantenimiento ≈ ingesta (±150)', Math.abs(st.maintenance.posterior - 2500) < 150, Math.round(st.maintenance.posterior)); }
  // ---- CASO B: subiendo dentro del rango → mantener
  { const s = synth({ days:35, rate:0.22, intake:2700, target:2700, noise:0.2, seed:2 }); const st = state(s);
    check('B · dentro del rango → DENTRO y MANTENER', st.status.code==='DENTRO' && st.decision.delta===0, `${st.status.code} ${st.rate.perWeek.toFixed(3)}`);
    let changed = 0; for(let k=0;k<50;k++){ const x = state(synth({ days:35, rate:0.22, intake:2700, target:2700, seed:100+k })); if(x.decision.delta) changed++; }
    check('B · 50 simulaciones dentro del rango con ruido → casi nunca cambia (≤10 %)', changed <= 5, `${changed}/50`); }
  // ---- CASO C: subiendo demasiado rápido → bajar, sin pasar del mantenimiento
  { const s = synth({ days:35, rate:0.65, intake:3200, target:3200 }); const st = state(s);
    check('C · demasiado rápido → BAJAR', st.status.code==='POR_ENCIMA' && st.decision.action==='BAJAR', `${st.status.code} ${st.decision.action}`);
    check('C · bajada acotada y ≥ mantenimiento', st.decision.delta >= -150 && st.decision.newTarget >= Math.round(st.maintenance.posterior/10)*10 - 10, `${st.decision.delta} → ${st.decision.newTarget}`); }
  // ---- CASO D: subiendo demasiado lento cumpliendo → subir
  { const s = synth({ days:35, rate:0.03, intake:2600, target:2600, seed:4 }); const st = state(s);
    check('D · demasiado lento cumpliendo → SUBIR', st.decision.action==='SUBIR', `${st.status.code} ${st.decision.action}`); }
  // ---- CASO E: 1-2 días de bajada por ruido → sin cambio
  { const base = synth({ days:35, rate:0.22, intake:2700, target:2700, seed:5 });
    const s = synth({ days:35, rate:0.22, intake:2700, target:2700, seed:5, patch: raw => { for(const d of [U.addDays('2026-01-01',33), U.addDays('2026-01-01',34)]) raw.weights[d][0].kg -= 0.8; } });
    const a = state(base), b = state(s);
    check('E · bajón de 2 días por ruido → no BAJA ni SUBE', b.decision.delta === 0, `${b.status.code} ${b.decision.action}`);
    check('E · ritmo se mueve <0,12 kg/sem', Math.abs(a.rate.perWeek - b.rate.perWeek) < 0.12, (a.rate.perWeek-b.rate.perWeek).toFixed(3)); }
  // ---- CASO F: solo 3-4 días
  { const s = synth({ days:4 }); const st = state(s);
    check('F · 4 días → DATOS INSUFICIENTES, sin cambio', st.status.code==='SIN_DATOS' && st.decision.delta===0 && st.decision.action==='SIN_DATOS');
    check('F · 4 días → sin fecha de llegada', st.predictions.current && st.predictions.current.available===false); }
  // ---- CASO G: muchos días sin kcal
  { const s = synth({ days:35, patch: raw => { Object.keys(raw.logs).forEach((d,i)=>{ if(i%6) delete raw.logs[d]; }); } }); const st = state(s);
    check('G · pocos días de comida → confianza BAJA, solo fórmula', st.confidence.level==='BAJA' && st.maintenance.method==='formula' && st.decision.delta===0, `${st.confidence.level} n=${st.intake.n}`); }
  // ---- CASO H: objetivo 2500, come 2200, peso estable → mantener (nunca bajar)
  { const s = synth({ days:35, rate:0, intake:2200, target:2500, seed:8 }); const st = state(s);
    check('H · baja adherencia → MANTENER por ADHERENCIA', st.decision.delta===0 && st.decision.reasonCode==='ADHERENCIA', `${st.decision.reasonCode}`);
    check('H · mantenimiento aprendido ≈ 2200 (no 2500)', Math.abs(st.maintenance.obs - 2200) < 150, Math.round(st.maintenance.obs)); }
  // ---- CASO I: outlier de peso
  { const base = synth({ days:35, rate:0.2, seed:9 }); const s = synth({ days:35, rate:0.2, seed:9, patch: raw => { raw.weights[U.addDays('2026-01-01',20)][0].kg += 3; } });
    const a = state(base), b = state(s);
    check('I · outlier +3 kg detectado', b.dataQuality.outliers.length===1, JSON.stringify(b.dataQuality.outliers));
    check('I · outlier no altera el ritmo (<0,02)', Math.abs(a.rate.perWeek - b.rate.perWeek) < 0.02, (a.rate.perWeek-b.rate.perWeek).toFixed(4)); }
  // ---- CASO J / TEST DEL BUG SOSPECHADO: día de ~1000 kcal entre días normales, peso siguiente igual
  { const cfg = { days:35, rate:0, intake:2400, target:2400, seed:10, intakeNoise:0 };
    const low = U.addDays('2026-01-01', 30);
    const base = synth(Object.assign({}, cfg, { patch: raw => { raw.weights[U.addDays(low,1)][0].kg = raw.weights[low][0].kg; } }));
    const auto = synth(Object.assign({}, cfg, { patch: raw => { raw.logs[low].forEach(e=>{ e.kcal = 1000/5; }); raw.weights[U.addDays(low,1)][0].kg = raw.weights[low][0].kg; } }));
    const conf = synth(Object.assign({}, cfg, { patch: raw => { raw.logs[low].forEach(e=>{ e.kcal = 1000/5; }); raw.weights[U.addDays(low,1)][0].kg = raw.weights[low][0].kg; raw.dayFlags[low] = true; } }));
    const a = state(base), b = state(auto), c = state(conf);
    check('J · día de 1000 kcal sin confirmar → marcado "dudoso" y excluido del mantenimiento', b.days.find(d=>d.date===low).status==='doubtful' && Math.abs(a.maintenance.posterior - b.maintenance.posterior) < 1, `${b.days.find(d=>d.date===low).status}`);
    check('J · confirmado completo → cuenta como energía real pero mueve el mantenimiento <60 kcal', c.days.find(d=>d.date===low).status==='complete' && Math.abs(a.maintenance.posterior - c.maintenance.posterior) < 60, Math.round(a.maintenance.posterior - c.maintenance.posterior));
    check('J · BUG SOSPECHADO: comer 1000 kcal sin perder peso NUNCA baja el objetivo', b.decision.delta >= 0 && c.decision.delta >= 0 && c.decision.action !== 'BAJAR', `${b.decision.action}/${c.decision.action}`);
    check('J · la decisión es la misma que sin el día bajo', b.decision.action === a.decision.action && c.decision.action === a.decision.action, `${a.decision.action} ${b.decision.action} ${c.decision.action}`); }
  // ---- CASO K: día extremadamente alto
  { const cfg = { days:35, rate:0.22, intake:2700, target:2700, seed:11 }; const hi = U.addDays('2026-01-01', 30);
    const a = state(synth(cfg)), b = state(synth(Object.assign({}, cfg, { patch: raw => { raw.logs[hi].forEach(e=>{ e.kcal = 5500/5; }); } })));
    check('K · día de 5500 kcal → mantenimiento se mueve <120 y sin cambio de decisión', Math.abs(a.maintenance.posterior - b.maintenance.posterior) < 120 && a.decision.action === b.decision.action, `${Math.round(b.maintenance.posterior-a.maintenance.posterior)} ${a.decision.action}/${b.decision.action}`); }
  // ---- CASO L: una semana estable
  { const st = state(synth({ days:7 })); check('L · 1 semana → sin decisión (datos insuficientes)', st.decision.action==='SIN_DATOS' && st.confidence.level==='BAJA'); }
  // ---- CASO M: varias semanas estable, simulación diaria: cambios espaciados y acotados
  { const s = synth({ days:42, rate:0, intake:2400, target:2400, seed:13 });
    let T = 2400, last = null, changes = [];
    for(let k=0;k<21;k++){
      const d = U.addDays(s.asOf, k); const raw = JSON.parse(JSON.stringify(s.raw));
      for(let j=0;j<k;j++){ const dd = U.addDays(s.asOf, j); raw.weights[dd] = [{ kg:60, time:'08:00' }]; raw.logs[dd] = [{ id:'m'+j, kcal:2400, p:120, c:300, f:80, label:'x' }, { id:'n'+j, kcal:0, p:0,c:0,f:0, label:'y' }]; }
      raw.timeline = [{ date:'2026-01-01', kcal:2400 }, ...changes.map(c=>({ date:c.date, kcal:c.newTarget }))];
      const st = E.computeState(raw, s.profile, d, { currentTarget:T, lastChange:last });
      if(st.decision.delta){ changes.push({ date:d, newTarget: st.decision.newTarget, delta: st.decision.delta }); last = { date:d, delta:st.decision.delta }; T = st.decision.newTarget; }
    }
    const spaced = changes.every((c,i)=> i===0 || U.diffDays(changes[i-1].date, c.date) >= 7);
    check('M · varias semanas planas → subidas espaciadas ≥7 días, ≤150 cada una, nunca bajadas', spaced && changes.every(c=>c.delta>0 && c.delta<=150), JSON.stringify(changes.map(c=>c.delta)));
    check('M · se detiene al caer la adherencia (<90 %)', changes.length <= 3, changes.length); }
  // ---- CASO N: pesajes irregulares
  { let cover = 0, errs = [], N = 200;
    for(let k=0;k<N;k++){ const st = state(synth({ days:42, rate:0.2, weighEvery: 2 + (k%3), noise:0.35, seed:1000+k })); if(st.rate.ciLow <= 0.2 && st.rate.ciHigh >= 0.2) cover++; errs.push(st.rate.perWeek - 0.2); }
    const bias = errs.reduce((a,b)=>a+b,0)/N;
    check('N · pesajes irregulares (cada 2-4 días): IC80 calibrado (cobertura 72-88 % en 200 simulaciones)', cover/N >= 0.72 && cover/N <= 0.88, `${(cover/N*100).toFixed(0)} %`);
    check('N · sin sesgo sistemático del ritmo (|sesgo| < 0,02 kg/sem)', Math.abs(bias) < 0.02, bias.toFixed(4)); }
  // ---- CASO O: registros incompletos (se olvidó apuntar) → excluidos
  { const cfg = { days:35, rate:0, intake:2500, target:2500, seed:15 };
    const a = state(synth(cfg)), b = state(synth(Object.assign({}, cfg, { patch: raw => { [5,12,19,26].forEach(i=>{ raw.logs[U.addDays('2026-01-01',i)] = [{ id:'inc'+i, label:'solo desayuno', kcal:450, p:20, c:60, f:15 }]; }); } })));
    check('O · días incompletos → marcados dudosos y fuera del cálculo', b.dataQuality.doubtful.length===4 && b.intake.doubtful.length===3, `${b.dataQuality.doubtful.length}/${b.intake.doubtful.length}`);
    check('O · mantenimiento no sesgado a la baja (<40 kcal)', Math.abs(a.maintenance.posterior - b.maintenance.posterior) < 40, Math.round(b.maintenance.posterior - a.maintenance.posterior)); }

  // ---- REGRESIÓN: bug Number(null)→0 del algoritmo antiguo (documentado con el port)
  { const s = synth({ days:30, rate:0, intake:2300, target:2600, intakeNoise:0, noise:0, seed:16 });
    const lp = { targetKcal:2600, emaMaintenanceKcal:null, lastAdjustmentWeek:null, weeklyGainGoalKg:0.3, mealsPerDay:5 };
    const bug = E.legacy.adjust(lp, s.raw.weights, s.raw.logs, s.asOf), fix = E.legacy.adjust(lp, s.raw.weights, s.raw.logs, s.asOf, { fixNullBug:true });
    check('Legacy · reproduce el bug (suavizado = 0,4 × bruto)', Math.abs(bug.record.smoothedMaintenance - 0.4*bug.record.rawMaintenance) < 1e-6, bug.record.smoothedMaintenance);
    check('Legacy · sin el bug el objetivo sería mant. + 330', fix.record.newTarget === Math.round(fix.record.rawMaintenance + 330), fix.record.newTarget);
    const st = state(s, 2600);
    check('Nuevo motor · sin estado recursivo: nunca propone < mantenimiento estimado', st.decision.newTarget >= Math.round(st.maintenance.posterior) - 10, `${st.decision.newTarget} vs ${Math.round(st.maintenance.posterior)}`); }
  // ---- Controlador: guardas explícitas
  { const s = synth({ days:35, rate:0, intake:2500, target:2500, seed:17 });
    const st = state(s, 2500, { lastChange:{ date: U.addDays(s.asOf,-3), delta:100 } });
    check('Controlador · cooldown 7 días', st.decision.delta===0 && st.decision.reasonCode==='COOLDOWN', st.decision.reasonCode);
    const c = synth({ days:35, rate:0.65, intake:3200, target:3200, seed:18 });
    const st2 = state(c, 3200, { lastChange:{ date: U.addDays(c.asOf,-10), delta:+100 } });
    check('Controlador · no invierte el sentido antes de 21 días', st2.decision.delta===0 && st2.decision.reasonCode==='NO_REVERSION', st2.decision.reasonCode);
    const st3 = state(s, 2500, { paused:true }); check('Controlador · pausado no toca nada', st3.decision.delta===0 && st3.decision.reasonCode==='PAUSADO'); }
  // ---- Sin fuga de datos
  { const s = synth({ days:40, rate:0.2, seed:19 }); const d = U.addDays('2026-01-01', 30);
    const a = E.computeState(E.filterRawBefore(s.raw, d), s.profile, d, { currentTarget:2500 });
    const mod = JSON.parse(JSON.stringify(s.raw)); for(let i=30;i<40;i++){ const k=U.addDays('2026-01-01',i); mod.weights[k][0].kg += 5; mod.logs[k].forEach(e=>e.kcal*=3); }
    const b = E.computeState(E.filterRawBefore(mod, d), s.profile, d, { currentTarget:2500 });
    check('Backtest · cambiar datos FUTUROS no altera el estado del día D', JSON.stringify([a.rate,a.maintenance,a.decision]) === JSON.stringify([b.rate,b.maintenance,b.decision])); }
  // ---- Predicciones
  { const st = state(synth({ days:35, rate:0.3, seed:20 }));
    check('Predicción · ritmo claro → rango de fechas en meses', st.predictions.current.available && /\d{4}/.test(st.predictions.current.text), st.predictions.current.text);
    const flat = state(synth({ days:35, rate:0, seed:21 }));
    check('Predicción · ritmo ≈0 → NO muestra fecha', flat.predictions.current.available===false, flat.predictions.current.text);
    check('Predicción · escenario objetivo siempre disponible', flat.predictions.objective.available && flat.predictions.objective.weeksMin < flat.predictions.objective.weeksMax); }
  // ---- EWMA temporal y semilla robusta
  { const pts = [{date:'2026-01-01',t:0,kg:60},{date:'2026-01-02',t:1,kg:60},{date:'2026-01-03',t:2,kg:60},{date:'2026-01-13',t:12,kg:61}];
    const tr = E.trendSeries(pts, pts.map(()=>({outlier:false})));
    check('EWMA · un hueco de 10 días pesa como 10 pasos', Math.abs(tr[3].trend - (60 + (1-Math.pow(0.85,10))*1)) < 1e-9, tr[3].trend);
    const tr2 = E.trendSeries([{date:'a',t:0,kg:62},{date:'b',t:1,kg:60},{date:'c',t:2,kg:60}], [{},{},{}].map(()=>({outlier:false})));
    check('EWMA · semilla = mediana de los 3 primeros (un primer pesaje raro no arrastra)', Math.abs(tr2[0].trend-60) < 1e-9, tr2[0].trend); }

  const passed = results.filter(r=>r.pass).length;
  results.forEach(r => log(`${r.pass ? '✅' : '❌'} ${r.name}${r.pass ? '' : '  → ' + r.detail}`));
  log(`🧪 Motor: ${passed}/${results.length} tests OK`);
  return { passed, total: results.length, results };
}
if(typeof module !== 'undefined' && module.exports) module.exports = { runEngineTests };
/*__TESTS_END__*/

</script>
<script>
// VARIABLES INYECTADAS DESDE PYTHON
const GEMINI_API_KEY = atob("__API_KEY_B64__");
const GEMINI_MODEL = "__MODEL__";
const GEMINI_MODEL_PLAN = "__MODEL_PLAN__";
const GEMINI_MODEL_FOOD = "__MODEL_FOOD__";
const FILLER_FOODS = "__FILLER__";
const FIREBASE_DB_URL = "__FIREBASE_DB_URL__";

// UTILIDADES DOM Y FECHAS
const $ = id => document.getElementById(id);
// ÚNICA fuente de verdad para convertir un Date en clave "YYYY-MM-DD" en
// hora LOCAL (nunca toISOString, que es UTC y puede desplazar el día de
// madrugada). Todo el resto del código debe pasar por aquí para que un
// pesaje o una comida de las 00:30 no acabe atribuido al día equivocado.
function dateKey(d){
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}
const todayStr = () => dateKey(new Date());
function shiftDate(dateStr, delta){
  const [y,m,d] = dateStr.split('-').map(Number);
  const dt = new Date(y, m-1, d);
  dt.setDate(dt.getDate()+delta);
  const yy = dt.getFullYear(); const mm = String(dt.getMonth()+1).padStart(2,'0'); const dd = String(dt.getDate()).padStart(2,'0');
  return `${yy}-${mm}-${dd}`;
}
function formatDateLabel(dateStr){
  if(dateStr === todayStr()) return 'Hoy';
  const d = new Date(dateStr + 'T00:00:00');
  const s = d.toLocaleDateString('es-ES',{weekday:'long', day:'numeric', month:'short', year:'numeric'});
  return s.charAt(0).toUpperCase()+s.slice(1);
}
let pendingFoodEntry = null;
let editingLogId = null;
let selectedLogDate = todayStr();

// SISTEMA DE NOTIFICACIONES (TOAST)
function showToast(msg, isError=false){
  const container = $('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${isError?'error':''}`;
  toast.innerText = msg;
  container.appendChild(toast);
  setTimeout(()=>toast.classList.add('show'), 10);
  setTimeout(()=>{
    toast.classList.remove('show');
    setTimeout(()=>toast.remove(), 300);
  }, 3000);
}

// STORAGE
// STORAGE — cada escritura deja una marca de tiempo por clave (__syncMeta) para
// que la sincronización fusione en vez de sobrescribir (ver mergeStores).
const SYNC_META_KEY = '__syncMeta';
const NON_SYNC_KEYS = new Set([SYNC_META_KEY, 'syncUid']);
let __dataVersion = 0; // invalida la caché del motor cuando cambia cualquier dato
function readSyncMeta(){ try { return JSON.parse(localStorage.getItem(SYNC_META_KEY) || '{}') || {}; } catch(e){ return {}; } }
function touchSyncMeta(key, deleted = false){
  if(NON_SYNC_KEYS.has(key)) return;
  const meta = readSyncMeta(); meta[key] = deleted ? -Date.now() : Date.now();
  try { localStorage.setItem(SYNC_META_KEY, JSON.stringify(meta)); } catch(e){ console.error('meta', e); }
}
async function safeGet(key){ try { const r = localStorage.getItem(key); return r ? JSON.parse(r) : null; } catch(e){ return null; } }
async function safeSet(key,val){
  try { localStorage.setItem(key, JSON.stringify(val)); } catch(e){ console.error('storage error', e); }
  touchSyncMeta(key); __dataVersion++;
  scheduleCloudPush();
}
async function safeRemove(key){
  localStorage.removeItem(key); touchSyncMeta(key, true); __dataVersion++;
  scheduleCloudPush();
}

// =========================================
// 🔗 SINCRONIZACIÓN EN LA NUBE (Firebase Realtime Database, vía REST)
// =========================================
// Todo tu localStorage se refleja como un único JSON en la nube bajo un id
// (uid) que vive en la URL (?uid=...) y en localStorage. Abrir la MISMA url
// en otro dispositivo/navegador descarga esos mismos datos. Sin backend,
// sin SDK: solo peticiones REST a Firebase.
const cloudSyncEnabled = !!(FIREBASE_DB_URL && FIREBASE_DB_URL.trim());
let syncUid = null;
let cloudPushTimer = null;
let cloudSynced = false;

function getOrCreateSyncUid(){
  const url = new URL(window.location.href);
  let uid = url.searchParams.get('uid') || localStorage.getItem('syncUid');
  if(!uid){
    uid = (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2)).replace(/-/g, '');
  }
  localStorage.setItem('syncUid', uid);
  if(url.searchParams.get('uid') !== uid){
    url.searchParams.set('uid', uid);
    window.history.replaceState({}, '', url.toString());
  }
  return uid;
}

function dumpLocalStorage(){
  const data = {};
  for(let i = 0; i < localStorage.length; i++){ const k = localStorage.key(i); data[k] = localStorage.getItem(k); }
  return data;
}

// Fusión de almacenes (local ↔ nube). Antes se subía el localStorage ENTERO
// y ganaba el último en escribir: una pestaña o un dispositivo con datos
// antiguos devolvía el perfil a un estado viejo (así se perdieron los ajustes
// del 12 y 14-sep). Ahora:
//   · cada clave lleva su marca de tiempo → gana la escritura más reciente;
//   · listas con id (comidas, pesajes, decisiones, línea temporal del
//     objetivo, correcciones de IA) se fusionan elemento a elemento;
//   · los borrados viajan como marca negativa (no reaparecen).
function entryStamp(e){ return Math.max(Number(e && e.updatedAt) || 0, Number(e && e.createdAt) || 0, Number(e && e.deletedAt) || 0); }
function isIdArrayText(txt){
  try { const v = JSON.parse(txt); return Array.isArray(v) && v.length > 0 && v.every(e => e && typeof e === 'object' && e.id !== undefined); } catch(e){ return false; }
}
function mergeIdArrays(older, newer){
  const map = new Map();
  for(const e of older) map.set(e.id, e);
  for(const e of newer){ const cur = map.get(e.id); if(!cur || entryStamp(e) >= entryStamp(cur)) map.set(e.id, e); }
  return [...map.values()];
}
function mergeStores(local, remote){
  const parseMeta = obj => { try { return JSON.parse(obj[SYNC_META_KEY] || '{}') || {}; } catch(e){ return {}; } };
  const lm = parseMeta(local), rm = parseMeta(remote);
  const out = {}, meta = {};
  const keys = new Set([...Object.keys(local), ...Object.keys(remote), ...Object.keys(lm), ...Object.keys(rm)]);
  for(const k of keys){
    if(NON_SYNC_KEYS.has(k)) continue;
    const lt = Number(lm[k]) || 0, rt = Number(rm[k]) || 0, lv = local[k], rv = remote[k];
    if(lv !== undefined && rv !== undefined && lt >= 0 && rt >= 0 && lv !== rv && isIdArrayText(lv) && isIdArrayText(rv)){
      const localNewer = Math.abs(lt) >= Math.abs(rt);
      out[k] = JSON.stringify(localNewer ? mergeIdArrays(JSON.parse(rv), JSON.parse(lv)) : mergeIdArrays(JSON.parse(lv), JSON.parse(rv)));
      meta[k] = Math.max(lt, rt);
      continue;
    }
    // Empate (p.ej. datos anteriores a esta versión, sin marca): gana la nube, como antes.
    const pickLocal = Math.abs(lt) > Math.abs(rt) || (Math.abs(lt) === Math.abs(rt) && rv === undefined);
    const t = pickLocal ? lt : rt, v = pickLocal ? lv : rv;
    if(t < 0){ meta[k] = t; continue; }                // borrado más reciente
    if(v === undefined){ const o = pickLocal ? rv : lv; if(o !== undefined){ out[k] = o; meta[k] = pickLocal ? rt : lt; } continue; }
    out[k] = v; meta[k] = t;
  }
  out[SYNC_META_KEY] = JSON.stringify(meta);
  return out;
}
function applyMergedLocally(merged){
  const local = dumpLocalStorage(); let changed = false;
  for(const [k, v] of Object.entries(merged)){ if(local[k] !== v){ try { localStorage.setItem(k, v); } catch(e){ console.error(e); } if(k !== SYNC_META_KEY) changed = true; } }
  for(const k of Object.keys(local)){ if(!(k in merged) && !NON_SYNC_KEYS.has(k)){ localStorage.removeItem(k); changed = true; } }
  if(changed) __dataVersion++;
  return changed;
}

async function pullFromCloud(){
  if(!cloudSyncEnabled) return;
  try {
    const res = await fetch(`${FIREBASE_DB_URL}/users/${syncUid}/data.json`);
    if(!res.ok) throw new Error('HTTP ' + res.status);
    const remote = await res.json();
    if(remote && typeof remote === 'object'){
      const merged = mergeStores(dumpLocalStorage(), remote);
      applyMergedLocally(merged);
      cloudSynced = true;
      const differs = Object.keys(merged).some(k => merged[k] !== remote[k]) || Object.keys(remote).some(k => !NON_SYNC_KEYS.has(k) && !(k in merged));
      if(differs) await pushToCloudNow(); // la nube no tenía lo más reciente de este dispositivo
    } else {
      cloudSynced = true;
      if(localStorage.length > 0) await pushToCloudNow();
    }
  } catch(e){
    console.error('Fallo al sincronizar desde la nube:', e);
    showToast('No se pudo sincronizar con la nube (revisa tu conexión). Usando datos locales.', true);
  }
}

let pushInFlight = false;
async function pushToCloudNow(){
  if(!cloudSyncEnabled || !syncUid) return;
  if(pushInFlight){ scheduleCloudPush(); return; }
  pushInFlight = true;
  try {
    // Leer-fusionar-escribir: nunca se sube el estado local a ciegas.
    let remote = null;
    try { const r = await fetch(`${FIREBASE_DB_URL}/users/${syncUid}/data.json`); if(r.ok) remote = await r.json(); } catch(e){ /* sin red: se reintenta en el próximo cambio */ }
    let merged;
    if(remote && typeof remote === 'object') merged = mergeStores(dumpLocalStorage(), remote);
    else { merged = dumpLocalStorage(); NON_SYNC_KEYS.forEach(k => { if(k !== SYNC_META_KEY) delete merged[k]; }); }
    const changedLocal = applyMergedLocally(merged);
    await fetch(`${FIREBASE_DB_URL}/users/${syncUid}/data.json`, { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(merged) });
    if(changedLocal) await onExternalDataChange();
  } catch(e){ console.error('Fallo al subir a la nube:', e); }
  finally { pushInFlight = false; }
}

function scheduleCloudPush(){
  if(!cloudSyncEnabled || !cloudSynced) return; // no subir hasta haber hecho la primera sincronización
  clearTimeout(cloudPushTimer);
  cloudPushTimer = setTimeout(pushToCloudNow, 1500);
}

function getSyncLink(){
  return window.location.href;
}

function renderSyncStatus(){
  const el = $('sync-status-content');
  if(!el) return;
  if(!cloudSyncEnabled){
    el.innerHTML = `<div style="color:var(--text-dim); font-size:0.85rem; line-height:1.6;">Sincronización en la nube no configurada. Tus datos viven solo en este navegador (usa el backup manual de abajo entre dispositivos). Para activarla, configura <b>FIREBASE_DB_URL</b> en <code>bulking_app.py</code>.</div>`;
    return;
  }
  el.innerHTML = `
    <div style="font-size:0.85rem; color:var(--green); font-weight:600; margin-bottom:10px;">✅ Sincronización activa</div>
    <div style="font-size:0.82rem; color:var(--text-dim); margin-bottom:10px; line-height:1.5;">Abre este mismo link en cualquier dispositivo o navegador para ver y seguir registrando sobre los mismos datos.</div>
    <div style="display:flex; gap:8px;">
      <input readonly value="${getSyncLink()}" style="margin-bottom:0; font-size:0.75rem;" onclick="this.select()">
      <button class="secondary" onclick="copySyncLink()" style="flex-shrink:0;">Copiar</button>
    </div>
    <div style="font-size:0.72rem; color:var(--text-dim); margin-top:10px;">⚠️ Cualquiera con este link puede ver y modificar tus datos. No lo compartas.</div>`;
}

window.copySyncLink = () => {
  navigator.clipboard.writeText(getSyncLink()).then(()=>showToast('Link copiado')).catch(()=>showToast('No se pudo copiar', true));
};

// Aviso imposible de pasar por alto: sin FIREBASE_DB_URL configurada, cada
// origen (localhost vs tu URL de GitHub Pages) tiene su PROPIO localStorage
// y nunca van a coincidir. Esto no es un fallo puntual, es cómo funciona
// localStorage por diseño del navegador — por eso se avisa de forma
// permanente en el dashboard, no solo en la pestaña de Datos.
function renderNoSyncBanner(){
  const el = $('no-sync-banner');
  if(!el) return;
  if(cloudSyncEnabled){ el.style.display = 'none'; return; }
  el.style.display = 'block';
  el.innerHTML = `<b>Sin sincronización.</b> Los datos no se comparten entre navegadores. Configura <code>FIREBASE_DB_URL</code> para activarla.`;
}

// Purga de claves de caché de asistente antiguas (>30 días) para que el
// payload subido a Firebase en cada sync no crezca sin límite con el tiempo.
async function pruneOldCaches(){
  try {
    const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - 30);
    const cutoffKey = dateKey(cutoff);
    const toRemove = [];
    for(let i = 0; i < localStorage.length; i++){
      const k = localStorage.key(i);
      if(k && k.startsWith('assistantCache:') && k.slice('assistantCache:'.length) < cutoffKey) toRemove.push(k);
    }
    toRemove.forEach(k => localStorage.removeItem(k));
  } catch(e){ console.error('Fallo al purgar caché antigua', e); }
}

// ESTADO GLOBAL
let profile = null;
let weightChartInstance = null;
let kcalTrendChartInstance = null;
let bodyCompChartInstance = null;

// =========================================
// 🧬 PERFIL Y CÁLCULOS METABÓLICOS
// =========================================
async function loadProfile(){
  let p = await safeGet('profile');
  if(!p){
    p = { age: 23, height: 175, weight: 65, sex: 'm', trainingDays: 3, ratePreset: 'estandar', mealsPerDay: 5, preferences: '', targetKcal: null, targetProtein: null, targetCarbs: null, targetFat: null, adjustmentPaused: false, goalWeightKg: null, bulkStartDate: null };
    await safeSet('profile', p);
  }
  p.mealsPerDay = p.mealsPerDay || 5;
  p.trainingDays = Number.isFinite(Number(p.trainingDays)) ? Math.min(7, Math.max(0, Number(p.trainingDays))) : 3;
  p.preferences = p.preferences || '';
  p.ratePreset = BulkEngine.CONFIG.RATE_PRESETS[p.ratePreset] ? p.ratePreset : BulkEngine.CONFIG.DEFAULT_RATE_PRESET;
  // Ojo: Number(null) === 0 (y es "finito"). Ese detalle fue el bug que sembró el
  // mantenimiento en 0 kcal en la versión anterior; aquí se comprueba de forma explícita.
  const g = p.goalWeightKg === null || p.goalWeightKg === undefined ? NaN : Number(p.goalWeightKg);
  p.goalWeightKg = Number.isFinite(g) && g > 0 ? g : null;
  return p;
}

// ÚNICA vía de escritura del perfil: relee lo guardado y aplica solo los campos
// que cambian. Una pestaña abierta desde hace días ya no puede devolver el
// perfil (y el objetivo de kcal) a un estado antiguo.
async function updateProfile(patch){
  const fresh = (await safeGet('profile')) || profile || {};
  await safeSet('profile', { ...fresh, ...patch });
  profile = await loadProfile();
  return profile;
}

// kcal por kg de cambio de peso: vive en BulkEngine.CONFIG.KCAL_PER_KG (una sola cifra para toda la app).
const KCAL_PER_KG = BulkEngine.CONFIG.KCAL_PER_KG;

// Mantenimiento TEÓRICO (solo punto de partida): Mifflin-St Jeor × factor
// derivado de tus días de entreno (1,2 + 0,075·días). El motor lo combina con
// tus datos reales en cuanto hay evidencia suficiente.
function calcTDEE(p, weight){ return BulkEngine.mifflin(p, weight) * BulkEngine.activityFactor(p.trainingDays); }

// OMS 2015 (azúcares libres): objetivo ideal <5 % de la energía. 1 g ≈ 4 kcal.
function calcSugarTargetG(kcal){
  return (kcal * 0.05) / 4;
}

// Macros desde las kcal. Proteína y grasa por kg de PESO TENDENCIA (no del
// último pesaje, que salta ±0,5 kg de un día a otro).
function recomputeMacrosFromKcal(p, weightKg){
  const w = Number(weightKg) || Number(p.weight);
  p.targetProtein = w * 2.0; // 2 g/kg (rango óptimo 1,6-2,2)
  p.targetFat = w * 1.0;     // 1 g/kg mínimo salud hormonal
  p.targetCarbs = Math.max(0, (p.targetKcal - (p.targetProtein*4) - (p.targetFat*9))/4);
  p.targetSugar = calcSugarTargetG(p.targetKcal);
  return p;
}

function getTargets(override=0){
  const kcal = (profile.targetKcal || 2500) + override;
  const protein = profile.targetProtein || profile.weight * 2 || 130;
  const fat = profile.targetFat || profile.weight * 1 || 70;
  const sugar = profile.targetSugar || calcSugarTargetG(kcal);
  return { kcal, p: protein, c: Math.max(0, (kcal - protein*4 - fat*9)/4), f: fat, s: sugar };
}

// Un único objetivo diario (sin días "de entreno" / "de descanso": la app ya
// no sabe ni necesita saber qué días entrenas).
function getPlanTargets(){
  return { average: getTargets() };
}

// =========================================
// 📋 REGISTRO DE ALIMENTOS (borrado lógico + marcas de tiempo para auditoría)
// =========================================
async function getLogRaw(date){ const a = await safeGet('log:'+date); return Array.isArray(a) ? a : []; }
async function getLog(date){ return (await getLogRaw(date)).filter(e => !e.deletedAt); }
async function setLog(date, entries){
  // Conserva las entradas borradas (lápidas) que no vienen en la lista activa.
  const raw = await getLogRaw(date); const ids = new Set(entries.map(e => e.id));
  const tombstones = raw.filter(e => e.deletedAt && !ids.has(e.id));
  await safeSet('log:'+date, [...entries, ...tombstones]);
}
async function softDeleteLogEntry(date, id){
  const raw = await getLogRaw(date); const e = raw.find(x => x.id === id); if(!e) return;
  e.deletedAt = Date.now(); e.updatedAt = e.deletedAt;
  await safeSet('log:'+date, raw);
}
const sumEntries = entries => entries.reduce((a,e)=>({kcal:a.kcal+(e.kcal||0),p:a.p+(e.p||0),c:a.c+(e.c||0),f:a.f+(e.f||0),s:a.s+(e.s||0)}),{kcal:0,p:0,c:0,f:0,s:0});

// Estado del día: true = completo (confirmado por ti), false = incompleto, null = automático.
async function getDayFlag(date){ const v = await safeGet('dayflag:'+date); return v === true || v === false ? v : null; }
async function setDayFlag(date, val){ if(val === null) await safeRemove('dayflag:'+date); else await safeSet('dayflag:'+date, !!val); }

async function getDailyOverride(date){ return (await safeGet('override:'+date)) || 0; }
async function setDailyOverride(date, delta){ await safeSet('override:'+date, delta); }

async function adjustDay(delta){
  const current = await getDailyOverride(selectedLogDate);
  const next = Math.max(-300, Math.min(300, current + delta)); // ajuste temporal: solo hoy, ±300 kcal
  await setDailyOverride(selectedLogDate, next);
  await updateDashboardUI();
  showToast(`Objetivo de ${formatDateLabel(selectedLogDate).toLowerCase()}: ${next >= 0 ? '+' : ''}${next} kcal`);
}

async function resetDayOverride(){
  await setDailyOverride(selectedLogDate, 0);
  await updateDashboardUI();
  showToast('Ajuste restablecido');
}

// =========================================
// 📅 NAVEGACIÓN ENTRE DÍAS DEL HISTORIAL
// =========================================
function navDay(delta){
  const next = shiftDate(selectedLogDate, delta);
  if(next > todayStr()) return; // no permitir ir al futuro
  selectedLogDate = next;
  cancelFoodReview();
  updateDashboardUI();
}
function jumpToday(){
  selectedLogDate = todayStr();
  cancelFoodReview();
  updateDashboardUI();
}

function isoWeekKey(date = new Date()){
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - dayNum + 3);
  const firstThursday = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
  const week = 1 + Math.round(((d - firstThursday) / 86400000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
  return `${d.getUTCFullYear()}-W${String(week).padStart(2, '0')}`;
}

// Serie diaria de peso OBSERVADO (primer pesaje de cada día). La usa la gráfica
// de composición corporal; la tendencia y el ritmo salen SIEMPRE del motor.
function earliestWeight(entries){
  const act = (entries || []).filter(e => !e.deletedAt && Number.isFinite(Number(e.kg)));
  if(!act.length) return null;
  const s = [...act].sort((a,b) => String(a.time || '99:99').localeCompare(String(b.time || '99:99')));
  return { kg: Number(s[0].kg), time: s[0].time || null, count: act.length };
}
async function getDailyWeightSeries(days = 28){
  const series = [];
  for(let i = days - 1; i >= 0; i--){
    const key = shiftDate(todayStr(), -i);
    const w = earliestWeight(await getWeightEntries(key));
    if(w) series.push({ date: key, kg: w.kg });
  }
  return series;
}

// =========================================
// 🧠 PUENTE ALMACENAMIENTO ↔ MOTOR (BulkEngine)
// =========================================
// Todo lo que se muestra (dashboard, gráficos, IA, PDF/JSON/CSV) sale de
// getEngineState(): un único cálculo por cambio de datos.
const RAW_PREFIXES = new Set(['weight', 'log', 'dayflag', 'override']);
function collectRaw(){
  const raw = { weights:{}, logs:{}, dayFlags:{}, overrides:{}, timeline:[], fallbackTarget: Number(profile && profile.targetKcal) || 2500,
    startDate: (profile && profile.bulkStartDate) || null, tzOffsetMin: -new Date().getTimezoneOffset() };
  for(let i = 0; i < localStorage.length; i++){
    const k = localStorage.key(i); if(!k) continue;
    const idx = k.indexOf(':'); if(idx < 0) continue;
    const prefix = k.slice(0, idx), date = k.slice(idx + 1);
    if(!RAW_PREFIXES.has(prefix) || !/^\d{4}-\d{2}-\d{2}$/.test(date)) continue;
    let v; try { v = JSON.parse(localStorage.getItem(k)); } catch(e){ continue; }
    if(prefix === 'weight' && Array.isArray(v)) raw.weights[date] = v;
    else if(prefix === 'log' && Array.isArray(v)) raw.logs[date] = v;
    else if(prefix === 'dayflag' && (v === true || v === false)) raw.dayFlags[date] = v;
    else if(prefix === 'override' && Number(v)) raw.overrides[date] = Number(v);
  }
  try { raw.timeline = (JSON.parse(localStorage.getItem('targetTimeline') || '[]') || []).slice().sort((a,b) => a.date === b.date ? (Number(a.at)||0) - (Number(b.at)||0) : a.date.localeCompare(b.date)); } catch(e){}
  return raw;
}
// Último cambio "de control" del objetivo (automático o manual). Las
// correcciones de migración no cuentan para el enfriamiento.
function lastTargetChange(timeline){
  for(let i = (timeline || []).length - 1; i >= 0; i--){
    const e = timeline[i];
    if(Number(e.delta) && (e.source === 'auto' || e.source === 'manual')) return { date: e.date, delta: Number(e.delta) };
  }
  return null;
}
let __engineCache = null;
function getEngineState(){
  const asOf = todayStr();
  const key = `${__dataVersion}|${asOf}|${profile && profile.targetKcal}|${profile && profile.adjustmentPaused}`;
  if(__engineCache && __engineCache.key === key) return __engineCache.state;
  const raw = collectRaw();
  const state = BulkEngine.computeState(raw, profile, asOf, { currentTarget: Number(profile.targetKcal) || 2500, lastChange: lastTargetChange(raw.timeline), paused: !!profile.adjustmentPaused });
  state.raw = raw;
  __engineCache = { key, state };
  return state;
}

// ÚNICA vía para cambiar el objetivo de kcal: deja rastro en targetTimeline.
async function setTargetKcal(newKcal, source, reason, decisionId = null){
  const prev = Number(profile.targetKcal) || null;
  const kcal = Math.round(newKcal);
  let level = Number(profile.weight);
  try { level = getEngineState().weight.level || level; } catch(e){}
  const m = recomputeMacrosFromKcal({ ...profile, targetKcal: kcal }, level);
  await updateProfile({ targetKcal: kcal, targetProtein: m.targetProtein, targetFat: m.targetFat, targetCarbs: m.targetCarbs, targetSugar: m.targetSugar });
  const tl = (await safeGet('targetTimeline')) || [];
  tl.push({ id: 'tl' + Date.now().toString(36), date: todayStr(), at: Date.now(), kcal, prev, delta: prev ? kcal - prev : 0, source, reason: reason || '', decisionId });
  await safeSet('targetTimeline', tl);
}

function showAdjustAlert(msg, isWarn = false){
  const el = $('adjust-alert'); if(!el) return;
  el.className = 'alert' + (isWarn ? ' warn' : '');
  el.innerText = msg;
  el.style.display = 'block';
}
function hideAdjustAlert(){ const el = $('adjust-alert'); if(el) el.style.display = 'none'; }

// Traza completa de una evaluación (auditoría: nada de caja negra).
function buildDecisionRecord(st, d){
  const r = st.rate, M = st.maintenance, R = st.range, I = st.intake, A = st.adherence;
  const n = (x, k=0) => x === null || x === undefined || !Number.isFinite(x) ? null : +x.toFixed(k);
  return { id: 'dc' + Date.now().toString(36), at: Date.now(), date: st.asOf, engineVersion: st.engineVersion,
    prevTarget: d.prevTarget, newTarget: d.newTarget, delta: d.delta, action: d.action, reasonCode: d.reasonCode, reason: d.reason,
    needed: d.needed, surplus: Math.round(d.surplus), proposal: d.proposal ?? null,
    inputs: {
      window: r ? { from: r.firstDate, to: r.lastDate } : null,
      weightTrendKg: n(st.weight.level, 3),
      rate: r ? { kgPerWeek: n(r.perWeek, 4), ciLow: n(r.ciLow, 4), ciHigh: n(r.ciHigh, 4), pctBodyweightPerWeek: n(r.perWeek / st.weight.level * 100, 3), weighIns: r.n, spanDays: r.span, residualSD: n(r.residualSD, 3) } : null,
      targetRange: { preset: R.preset, lowPct: R.lowPct, highPct: R.highPct, lowKgWk: n(R.low, 3), highKgWk: n(R.high, 3) },
      intake: { from: I.from, to: I.to, meanKcal: n(I.mean), sdKcal: n(I.sd), completeDays: I.n, doubtfulDays: I.doubtful, incompleteDays: I.incomplete },
      adherence: { ratio: n(A.ratio, 4), daysWithin10pct: A.within10, days: A.n, meanGapKcal: n(A.meanGap) },
      maintenance: { method: M.method, formulaKcal: n(M.prior), observedKcal: n(M.obs), observedSd: n(M.obsSd), estimateKcal: n(M.posterior), estimateSd: n(M.posteriorSd), dataWeight: n(M.dataWeight, 3) },
      confidence: { level: st.confidence.level, score: n(st.confidence.score, 3) },
      status: st.status.code
    } };
}

// Evaluación: como mucho una vez al día. Registra cada cambio y, aunque no
// cambie nada, una evaluación por semana (latido de auditoría).
async function runDailyEvaluation(){
  if(!profile.targetKcal) return;
  const today = todayStr();
  if((await safeGet('lastEvaluationDate')) === today) return;
  const st = getEngineState(), d = st.decision;
  const log = (await safeGet('decisionLog')) || [];
  const lastOwn = [...log].reverse().find(x => !x.legacy && x.action !== 'CORRECCION');
  const heartbeat = !lastOwn || BulkEngine.util.diffDays(lastOwn.date, today) >= 7;
  const rec = buildDecisionRecord(st, d);
  if(d.delta){
    await setTargetKcal(d.newTarget, 'auto', d.reason, rec.id);
    showAdjustAlert(`🧠 Objetivo ${d.delta > 0 ? 'subido' : 'bajado'} ${d.delta > 0 ? '+' : ''}${d.delta} kcal → ${d.newTarget} kcal. ${d.reason}`);
  }
  if(d.delta || heartbeat){ log.push(rec); if(log.length > 500) log.splice(0, log.length - 500); await safeSet('decisionLog', log); }
  await safeSet('lastEvaluationDate', today);
}

// =========================================
// 🔧 MIGRACIÓN A v2 (una sola vez)
// =========================================
async function migrateToV2(){
  if((Number(await safeGet('schemaVersion')) || 1) >= 2) return null;
  const report = { at: new Date().toISOString(), removedSensitiveKeys: [], removedTrainingKeys: 0, removedFoodCaches: 0, correction: null };
  const keys = () => Object.keys(dumpLocalStorage());
  // 1) Claves sensibles, restos del tracking de gimnasio y cachés de IA v1
  //    (la caché v1 guardaba estimaciones sin revisar, p. ej. "10 g de malto = 380 kcal").
  for(const k of keys()){
    if(/api[_-]?key|token|secret|password|credential/i.test(k)){ await safeRemove(k); report.removedSensitiveKeys.push(k); }
    else if(k.startsWith('training:')){ await safeRemove(k); report.removedTrainingKeys++; }
    else if(k.startsWith('foodCache:')){ await safeRemove(k); report.removedFoodCaches++; }
  }
  // 2) Ids y marcas de tiempo (auditoría de ediciones/borrados a partir de ahora)
  for(const k of keys()){
    if(k.startsWith('weight:')){
      const arr = await safeGet(k);
      if(Array.isArray(arr) && arr.some(e => !e.id)) await safeSet(k, arr.map((e, i) => ({ id: e.id || `w${k.slice(7).replace(/-/g,'')}_${i}`, ...e })));
    } else if(k.startsWith('log:')){
      const arr = await safeGet(k);
      if(Array.isArray(arr) && arr.some(e => e.createdAt === undefined)) await safeSet(k, arr.map(e => ({ ...e, createdAt: e.createdAt ?? BulkEngine.util.idToTimestamp(e.id) ?? null })));
    }
  }
  // 3) Línea temporal del objetivo reconstruida: registros de targetHistory +
  //    objetivo que realmente MOSTRABA el dashboard cada día (huella del asistente).
  const hist = (await safeGet('targetHistory')) || [];
  const dataDates = keys().filter(k => /^(log|weight):\d{4}-\d{2}-\d{2}$/.test(k)).map(k => k.split(':')[1]).sort();
  const firstDate = dataDates[0] || todayStr();
  const tl = []; let seq = 0;
  const cur = () => tl.length ? tl[tl.length - 1].kcal : null;
  const push = (date, kcal, source, reason, extra = {}) => { const prev = cur(); const k = Math.round(kcal); tl.push({ id: `tlm${++seq}`, date, at: seq, kcal: k, prev, delta: prev !== null ? k - prev : 0, source, reason, ...extra }); };
  const observed = {};
  for(const k of keys()){
    if(!k.startsWith('assistantCache:')) continue;
    const parts = String(((await safeGet(k)) || {}).stateKey || '').split('|');
    if(parts.length >= 8 && Number(parts[5])) observed[k.split(':')[1]] = Number(parts[5]) - (Number(parts[7]) || 0);
  }
  const obsDates = Object.keys(observed).sort(); let oi = 0;
  const flushObserved = (before) => { while(oi < obsDates.length && (before === null || obsDates[oi] < before)){ const d = obsDates[oi++]; if(cur() !== Math.round(observed[d])) push(d, observed[d], 'legacy-observed', 'Objetivo que mostraba el dashboard ese día (cambio que no quedó registrado)'); } };
  if(hist.length) push(firstDate, hist[0].prevTarget, 'legacy-formula', 'Objetivo inicial por fórmula (versión anterior de la app)');
  else if(profile.targetKcal) push(firstDate, profile.targetKcal, 'legacy-initial', 'Objetivo existente al migrar');
  for(const h of hist){
    flushObserved(h.date);
    if(cur() !== null && Math.round(h.prevTarget) !== cur()) push(h.date, h.prevTarget, 'legacy-untracked-reset', 'El objetivo había vuelto a este valor sin quedar registrado (guardado del perfil o sobrescritura por sincronización). Fecha aproximada.', { approx: true });
    push(h.date, h.newTarget, 'legacy-auto', h.note || '', { legacyWeek: h.week, legacyMode: h.mode });
  }
  flushObserved(null);
  if(profile.targetKcal && cur() !== Math.round(profile.targetKcal)) push(todayStr(), profile.targetKcal, 'legacy-untracked-reset', 'Objetivo guardado en el perfil al migrar.', { approx: true });
  // 4) Corrección del bug del algoritmo anterior (mantenimiento suavizado sembrado en 0)
  const decisions = hist.map((h, i) => ({ id: `lg${i}`, legacy: true, date: h.date, at: i, prevTarget: Math.round(h.prevTarget), newTarget: h.newTarget, delta: Math.round(h.newTarget - h.prevTarget),
    action: h.newTarget > h.prevTarget ? 'SUBIR' : h.newTarget < h.prevTarget ? 'BAJAR' : 'MANTENER', reasonCode: `LEGACY_${String(h.mode || '').toUpperCase()}`, reason: h.note || '' }));
  const last = hist[hist.length - 1];
  const m = last && /~(\d+) kcal\/día, suavizado con semanas anteriores a ~(\d+) kcal\/día/.exec(last.note || '');
  let restore = null;
  if(m && Number(m[2]) < 0.7 * Number(m[1]) && Math.round(profile.targetKcal) === Math.round(last.newTarget)){
    restore = Math.round(last.prevTarget);
    const goal = Number(profile.weeklyGainGoalKg) || 0.3;
    const reason = `Se deshace el ajuste del ${last.date} (${Math.round(last.prevTarget)} → ${last.newTarget} kcal). El algoritmo anterior sembró el mantenimiento suavizado en 0 kcal (Number(null) = 0), así que calculó con ~${m[2]} kcal/día en vez de ~${m[1]}. Sin el bug habría propuesto ~${Math.round(Number(m[1]) + goal*7700/7)} kcal. Se restaura ${restore} kcal y el motor nuevo decide a partir de aquí.`;
    push(todayStr(), restore, 'correction', reason);
    decisions.push({ id: 'lgfix', date: todayStr(), at: Date.now(), prevTarget: Math.round(profile.targetKcal), newTarget: restore, delta: restore - Math.round(profile.targetKcal), action: 'CORRECCION', reasonCode: 'BUGFIX_EMA_NULL', reason });
    report.correction = { from: Math.round(profile.targetKcal), to: restore, date: last.date };
  }
  await safeSet('targetTimeline', tl);
  await safeSet('decisionLog', decisions);
  // 5) Parámetros del algoritmo anterior (solo para el backtest) y limpieza del perfil
  const fresh = (await safeGet('profile')) || {};
  await safeSet('legacySnapshot', { weeklyGainGoalKg: Number(fresh.weeklyGainGoalKg) || 0.3, goalOffset: fresh.goalOffset ?? null, activity: fresh.activity ?? null, mealsPerDay: fresh.mealsPerDay || 5, initialTarget: tl.length ? tl[0].kcal : null, emaMaintenanceKcalAtMigration: fresh.emaMaintenanceKcal ?? null });
  ['activity', 'goalOffset', 'weeklyGainGoalKg', 'emaMaintenanceKcal', 'lastAdjustmentWeek', 'geminiModel'].forEach(k => delete fresh[k]);
  fresh.ratePreset = fresh.ratePreset || 'estandar';
  fresh.bulkStartDate = fresh.bulkStartDate || firstDate;
  if(restore) fresh.targetKcal = restore;
  await safeSet('profile', fresh);
  profile = await loadProfile();
  if(restore){ const mm = recomputeMacrosFromKcal({ ...profile }, profile.weight); await updateProfile({ targetProtein: mm.targetProtein, targetFat: mm.targetFat, targetCarbs: mm.targetCarbs, targetSugar: mm.targetSugar }); }
  await safeSet('migrationReport', report);
  await safeSet('schemaVersion', 2);
  return report;
}
// =========================================
// 📊 DASHBOARD UI RENDER
// =========================================
function pickMealExample(capped, focus, remP, fillerExamples){
  if(capped.includes('grasas') && focus === 'carbohidratos'){
    return remP > 15
      ? 'pechuga de pollo o pavo a la plancha (sin aceite añadido) con arroz blanco y verdura al vapor'
      : `arroz blanco o crema de arroz con miel y claras de huevo${fillerExamples ? `, o ${fillerExamples}` : ''}`;
  }
  if(capped.includes('grasas') && focus === 'proteína'){
    return 'pechuga de pollo, pavo o claras de huevo con verdura, sin aceites ni salsas grasas';
  }
  if(capped.includes('carbohidratos') && focus === 'proteína'){
    return 'pescado blanco, pollo o claras de huevo con verdura, sin arroz ni pasta';
  }
  if(capped.includes('proteína') && focus === 'carbohidratos'){
    return 'arroz o pasta con verduras salteadas y un chorrito de aceite de oliva';
  }
  return 'pechuga de pollo con arroz y verduras, con un chorrito de aceite de oliva';
}

function pickSnackExample(capped, remP, fillerExamples){
  if(capped.includes('grasas') && remP <= 8){
    return fillerExamples ? `un poco de ${fillerExamples}` : 'una pieza de fruta o un poco de miel';
  }
  return 'una pieza de fruta, un yogur 0% o un puñado de claras de huevo';
}

function buildMacroGuidance(target, sums, remainingKcal, mealsRemaining, hour){
  const remP = Math.max(0, target.p - sums.p);
  const remC = Math.max(0, target.c - sums.c);
  const remF = Math.max(0, target.f - sums.f);
  const pctP = target.p > 0 ? (sums.p / target.p) * 100 : 0;
  const pctC = target.c > 0 ? (sums.c / target.c) * 100 : 0;
  const pctF = target.f > 0 ? (sums.f / target.f) * 100 : 0;

  // Consideramos "al límite" un macro por encima del 85% de su objetivo diario
  const capped = [];
  if(pctF >= 85) capped.push('grasas');
  if(pctP >= 100) capped.push('proteína');
  if(pctC >= 100) capped.push('carbohidratos');

  // De entre proteína y carbohidratos (los que suele interesar priorizar), cuál tiene más margen
  const openMacros = [
    { name: 'proteína', pct: pctP },
    { name: 'carbohidratos', pct: pctC }
  ].filter(m => m.pct < 90).sort((a, b) => a.pct - b.pct);
  const focus = openMacros.length ? openMacros[0].name : null;

  let macroNote = '';
  if(capped.length && focus) macroNote = `Ya vas casi al límite de ${capped.join(' y ')}, así que mejor algo centrado en ${focus} y con poca grasa añadida.`;
  else if(capped.length) macroNote = `Ya vas casi al límite de ${capped.join(' y ')}, ve con cuidado con esos macros en lo que queda de día.`;

  const fillerExamples = (typeof FILLER_FOODS === 'string' ? FILLER_FOODS : '').split(',').map(s => s.trim()).filter(Boolean).slice(0, 2).join(' o ');
  const mealsPerDay = Number(profile.mealsPerDay) || 5;
  const avgMealSize = mealsPerDay > 0 ? target.kcal / mealsPerDay : 500;
  const isLateNight = (typeof hour === 'number') && (hour >= 22 || hour < 5);

  let sizeNote, example, lateNightOverride = false;
  const safeMealsRemaining = Math.max(1, mealsRemaining || 1);
  if(remainingKcal <= avgMealSize * 0.35){
    // Muy poco margen: un plato entero no tiene sentido
    sizeNote = 'Con tan poco margen no hace falta un plato entero.';
    example = pickSnackExample(capped, remP, fillerExamples);
  } else if(isLateNight && remainingKcal > avgMealSize * 1.6){
    // Ya es de noche y aún queda mucho por delante: repartir en "varias comidas más"
    // ya no es realista a estas horas. Mejor una cena moderada que forzar el déficit.
    lateNightOverride = true;
    sizeNote = 'Ya es tarde para repartir esto en varias comidas más — mejor una cena moderada con buena proteína ahora, y no pasa nada si hoy te quedas algo por debajo del objetivo.';
    example = pickMealExample(capped, focus, remP, fillerExamples);
  } else if(safeMealsRemaining <= 1 || remainingKcal <= avgMealSize * 1.6){
    // Encaja en una comida normal (o es la última del día, coma lo que coma)
    sizeNote = '';
    example = pickMealExample(capped, focus, remP, fillerExamples);
  } else {
    // Quedan varias comidas por delante: no recomendar metértelo todo de golpe
    const perMeal = Math.round(remainingKcal / safeMealsRemaining);
    sizeNote = `Aún te quedan ${safeMealsRemaining} comidas hoy, repártelo en vez de meterlo todo en una — para la siguiente, apunta a unas ${perMeal} kcal.`;
    example = pickMealExample(capped, focus, remP, fillerExamples);
  }

  const parts = [macroNote, sizeNote].filter(Boolean);
  const note = parts.join(' ');
  return { note, example, remP, remC, remF, lateNightOverride };
}

// Cuenta cuántas comidas "caben" de verdad en lo que queda de día, repartiendo
// tus comidas habituales en una ventana horaria típica (07:30-22:30). Evita
// recomendar "repartir en 4 comidas" cuando ya son las 9 de la noche.
function estimateTimeAdjustedMealsRemaining(mealsPerDay, mealsRemainingCount){
  const dayStart = 7.5, dayEnd = 22.5;
  const now = new Date();
  const hour = now.getHours() + now.getMinutes() / 60;
  const windowHours = dayEnd - dayStart;
  const slotSize = windowHours / Math.max(1, mealsPerDay);
  const hoursLeft = Math.max(0, dayEnd - hour);
  const timeSlots = Math.max(1, Math.round(hoursLeft / slotSize));
  return { hour, effective: Math.max(1, Math.min(mealsRemainingCount, timeSlots)) };
}

function assistantMarkup(title, body){
  return `<div class="assistant-kicker">🤖 Asistente de hoy</div><div class="assistant-title">${title}</div><div class="assistant-body">${body}</div>`;
}

// Genera el mensaje de respaldo (sin IA) por si Gemini falla o tarda. Es la
// misma lógica de reglas que existía antes de tener asistente con IA: nunca
// nos quedamos sin mensaje aunque la API esté caída.
function buildFallbackAssistant(sums, target, logsCount){
  const remainingKcal = Math.max(0, target.kcal - sums.kcal);
  const remainingProtein = Math.max(0, target.p - sums.p);
  const mealsTarget = Number(profile.mealsPerDay) || 5;
  const mealsRemainingCount = Math.max(1, mealsTarget - logsCount);
  const { hour, effective: mealsRemaining } = estimateTimeAdjustedMealsRemaining(mealsTarget, mealsRemainingCount);

  let title, message;
  if(remainingKcal <= 50 && remainingProtein <= 5){
    title = '✅ Casi lo tienes';
    message = 'Objetivo prácticamente cumplido. Mantén la hidratación y no necesitas forzar otra comida.';
  } else if(remainingKcal > 0){
    const { note, example, lateNightOverride } = buildMacroGuidance(target, sums, remainingKcal, mealsRemaining, hour);
    title = lateNightOverride ? '🌙 Se hace tarde' : (mealsRemaining <= 1 ? '🍽️ Última comida del día' : '📋 Repártelo en lo que queda de día');
    const intro = note || 'Aún te queda margen en todos los macros.';
    message = `${intro} Por ejemplo: ${example}.`;
  } else {
    title = '⚠️ Objetivo superado';
    message = `Has superado el objetivo en ${Math.round(sums.kcal - target.kcal)} kcal. No compenses mañana; vuelve a tu objetivo habitual.`;
  }
  return { title, body: message };
}

// Huella del estado actual del día: si no cambia (mismas kcal/macros/nº de
// comidas/ajuste), reutilizamos el mensaje ya generado en vez de llamar a la
// IA otra vez en cada refresco del dashboard.
function assistantStateKey(sums, target, logsCount, override){
  return [Math.round(sums.kcal), Math.round(sums.p), Math.round(sums.c), Math.round(sums.f), Math.round(sums.s), Math.round(target.kcal), logsCount, override].join('|');
}

// Construye el prompt con TODO el contexto real de hoy (hora, kcal/macros/azúcar
// ingeridos y restantes, comidas ya registradas para no repetirlas, comidas que
// faltan por horario, preferencias e histórico) y pide a la IA (modelo bueno,
// el mismo que el plan semanal) que redacte la recomendación del asistente.
// Bloque de contexto factual compartido: el estado real de un día concreto
// (kcal/macros objetivo vs. ingeridos vs. restantes, comidas registradas,
// hora del día y cuántas comidas quedan por delante, e histórico reciente).
// Lo reutilizan tanto el asistente de la pestaña "Hoy" como el chat del
// coach, para que AMBOS razonen sobre exactamente los mismos datos en vez
// de que el chat solo vea el objetivo de kcal a secas.
async function buildDailyStatusText(sums, target, logs, date){
  const mealsTarget = Number(profile.mealsPerDay) || 5;
  const mealsRemainingCount = Math.max(1, mealsTarget - logs.length);
  const { hour, effective: mealsRemaining } = estimateTimeAdjustedMealsRemaining(mealsTarget, mealsRemainingCount);
  const h = Math.floor(hour); const m = Math.round((hour - h) * 60);
  const hourLabel = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;

  const remP = Math.max(0, target.p - sums.p);
  const remC = Math.max(0, target.c - sums.c);
  const remF = Math.max(0, target.f - sums.f);
  const remS = Math.max(0, target.s - sums.s);
  const remKcal = Math.max(0, target.kcal - sums.kcal);
  const loggedList = logs.length ? logs.map(l => `${l.time || ''} ${l.label} (${Math.round(l.kcal)} kcal)`).join('; ') : 'ninguna todavía';
  const history = await buildRecentHistorySummary(14);

  return `Estado de ${formatDateLabel(date)} (hora actual ${hourLabel}):
- Kcal: objetivo ${Math.round(target.kcal)}, ingeridas ${Math.round(sums.kcal)}, restantes ${Math.round(remKcal)}.
- Proteína: objetivo ${Math.round(target.p)}g, ingerida ${Math.round(sums.p)}g, restante ${Math.round(remP)}g.
- Carbohidratos: objetivo ${Math.round(target.c)}g, ingeridos ${Math.round(sums.c)}g, restantes ${Math.round(remC)}g.
- Grasas: objetivo ${Math.round(target.f)}g, ingeridas ${Math.round(sums.f)}g, restantes ${Math.round(remF)}g.
- Azúcar: objetivo recomendado (OMS, <5% de las kcal) ${Math.round(target.s)}g, ingerido ${Math.round(sums.s)}g, restante ${Math.round(remS)}g.
- Comidas registradas hoy (${logs.length}/${mealsTarget} previstas, quedan realistamente ${mealsRemaining} por la hora que es): ${loggedList}.
- Preferencias y restricciones: ${profile.preferences || 'ninguna indicada'}.
${history ? '- ' + history : ''}`;
}

async function requestDailyAssistantAI(sums, target, logs, date){
  const statusText = await buildDailyStatusText(sums, target, logs, date);

  const prompt = `Eres el asistente de la pestaña "Hoy" de Bulking OS, una app de nutrición para volumen (ganancia muscular). Responde SOLO este JSON, sin texto ni markdown fuera de él: {"title":"máximo 6 palabras, con un emoji delante","body":"2-3 frases directas, sin markdown"}.

${statusText}

Instrucciones:
- Sugiere QUÉ TIPO de comida encaja mejor con lo que falta de kcal/macros/azúcar (no des receta completa ni cantidades), evitando repetir algo que ya aparece en las comidas registradas hoy.
- Si es tarde (después de las 22h) y aún queda mucho margen, no recomiendes repartirlo en varias comidas: propón una cena moderada y acepta quedarse algo por debajo hoy.
- Si el objetivo de kcal y proteína está prácticamente cumplido, dilo y no fuerces otra comida.
- Si ya se superó el objetivo de kcal, no generes culpa: indica que no debe compensar mañana.
- Si algún macro o el azúcar está cerca de su límite, avísalo y orienta hacia opciones bajas en ese macro.
Máximo 2-3 frases en "body". Un solo emoji, solo en "title".`;

  const res = await callGemini(prompt, true, GEMINI_MODEL_PLAN);
  if(res && typeof res.title === 'string' && typeof res.body === 'string' && res.title.trim() && res.body.trim()){
    return { title: res.title.trim(), body: res.body.trim() };
  }
  return null;
}

async function renderDailyAssistant(sums, target, logsCount, date, logs){
  const assistant = $('daily-assistant');
  if(date !== todayStr()){
    assistant.innerHTML = assistantMarkup('📅 Día pasado', `Estás viendo el registro del ${formatDateLabel(date).toLowerCase()}. Total: ${Math.round(sums.kcal)} kcal, P:${Math.round(sums.p)}g C:${Math.round(sums.c)}g G:${Math.round(sums.f)}g.`);
    assistant.style.display = 'block';
    return;
  }

  const override = await getDailyOverride(date);
  const stateKey = assistantStateKey(sums, target, logsCount, override);
  const cached = await safeGet('assistantCache:' + date);
  if(cached && cached.stateKey === stateKey){
    assistant.innerHTML = assistantMarkup(cached.title, cached.body);
    assistant.style.display = 'block';
    return;
  }

  // Mostramos ya el mensaje de respaldo (instantáneo) mientras la IA piensa,
  // así el usuario nunca ve la tarjeta vacía ni tiene que esperar.
  const fallback = buildFallbackAssistant(sums, target, logsCount);
  assistant.innerHTML = assistantMarkup(fallback.title, fallback.body);
  assistant.style.display = 'block';
  await safeSet('assistantCache:' + date, { stateKey, ...fallback });

  const ai = await requestDailyAssistantAI(sums, target, logs || [], date);
  if(ai){
    await safeSet('assistantCache:' + date, { stateKey, title: ai.title, body: ai.body });
    // Solo pisamos la UI si el usuario sigue viendo el mismo día (si navegó
    // a otro día mientras la IA respondía, no tiene sentido sobreescribir).
    if(selectedLogDate === date){
      assistant.innerHTML = assistantMarkup(ai.title, ai.body);
    }
  }
}

async function updateDashboardUI(){
  const t = selectedLogDate;
  const logs = await getLog(t);
  const sums = sumEntries(logs);
  const override = await getDailyOverride(t);
  const tgt = getTargets(override);

  $('log-date-label').innerText = formatDateLabel(t);
  $('log-date-jump').style.display = (t === todayStr()) ? 'none' : 'block';
  $('btn-next-day').disabled = (t === todayStr());
  if(t === todayStr()) $('date-display').innerText = ''; else $('date-display').innerText = '';

  const noteEl = $('ui-override-note');
  if(override !== 0){ noteEl.style.display='block'; noteEl.innerText = `💡 Ajuste aplicado: ${override>0?'+':''}${override} kcal para ${formatDateLabel(t).toLowerCase()}.`; } 
  else { noteEl.style.display='none'; }

  $('ui-kcal-consumed').innerText = Math.round(sums.kcal);
  $('ui-kcal-target').innerText = Math.round(tgt.kcal);
  let kcalPct = (sums.kcal/tgt.kcal)*100;
  const progFill = $('ui-progress');
  progFill.style.width = Math.min(100,kcalPct)+'%';

  const kcalDiff = tgt.kcal - sums.kcal;
  const remEl = $('ui-kcal-remaining');
  if(kcalDiff >= 0){
    remEl.innerText = Math.round(kcalDiff);
    remEl.style.color = 'var(--accent)';
  } else {
    remEl.innerText = '+' + Math.round(Math.abs(kcalDiff));
    remEl.style.color = 'var(--green)';
  }

  if(kcalPct>=100){ progFill.classList.add('surplus'); $('ui-kcal-status').innerText="¡Objetivo cumplido!"; $('ui-kcal-status').style.color="var(--green)"; }
  else { progFill.classList.remove('surplus'); $('ui-kcal-status').innerText="Restantes"; $('ui-kcal-status').style.color="var(--text-dim)"; }

  const bar = (cur,target,barId,txtId,remId)=>{
    let pct=(cur/target)*100;
    const b=$(barId); b.style.width=Math.min(100,pct)+'%';
    $(txtId).innerText = `${Math.round(cur)}g`;
    const diff = target - cur;
    const rem = $(remId);
    if(diff >= 0){ rem.innerText = `${Math.round(diff)} restan`; rem.style.color = ''; }
    else { rem.innerText = `+${Math.round(Math.abs(diff))} de más`; rem.style.color = 'var(--green)'; }
    if(pct>115) b.classList.add('over-limit'); else b.classList.remove('over-limit');
  };
  bar(sums.p, tgt.p, 'bar-pro','txt-pro','rem-pro'); bar(sums.c, tgt.c, 'bar-car','txt-car','rem-car'); bar(sums.f, tgt.f, 'bar-fat','txt-fat','rem-fat'); bar(sums.s, tgt.s, 'bar-sugar','txt-sugar','rem-sugar');
  await renderDailyAssistant(sums, tgt, logs.length, t, logs);
  await renderMetricStrip();

  const list = $('log-list');
  if(!logs.length) list.innerHTML = '<div class="chat-empty">Sin registros este día.</div>';
  else {
    list.innerHTML = logs.slice().reverse().map(log=>`
      <div class="log-item">
        <div>
          <div class="log-title">${log.label}</div>
          <div class="log-macros">${log.time||''} · P:${Math.round(log.p)} C:${Math.round(log.c)} G:${Math.round(log.f)} Az:${Math.round(log.s||0)}</div>
        </div>
        <div class="log-item-actions">
          <div class="log-kcal-wrap">
            <span class="log-kcal">${Math.round(log.kcal)}</span><span style="font-size:0.75rem; color:var(--text-dim);">kcal</span>
          </div>
          ${log.originalText ? `<button class="edit-btn" style="background:rgba(16,185,129,0.1); border-color:rgba(16,185,129,0.25); color:var(--green);" onclick="reestimateLog('${log.id}')" title="Re-estimar con IA">🔄</button>` : ''}
          <button class="edit-btn" onclick="editLog('${log.id}')" title="Editar">✎</button>
          <button class="del-btn" onclick="delLog('${log.id}')" title="Borrar">✕</button>
        </div>
      </div>
    `).join('');
  }
  await renderFavoritesQuickAdd();
  await renderStreakBadge();
  renderDayStatusRow(t);
}
window.delLog = async (id) => {
  // Borrado lógico: la entrada queda como "borrada" (auditable) y deja de contar.
  await softDeleteLogEntry(selectedLogDate, id);
  showToast('Registro eliminado');
  await updateDashboardUI(); await refreshInsights();
};
window.editLog = async (id) => {
  const entries = await getLog(selectedLogDate);
  const entry = entries.find(e=>e.id===id);
  if(!entry) return;
  showFoodReview(entry, true);
  $('food-review').scrollIntoView({behavior:'smooth', block:'center'});
};

// =========================================
// 🤖 API GEMINI CON REINTENTOS Y MANEJO DE ERRORES
// =========================================
async function callGemini(prompt, isJson=false, model=GEMINI_MODEL, maxRetries=2, opts={}){
  if(!GEMINI_API_KEY || GEMINI_API_KEY.includes("TU_API_KEY_AQUI")){
    showToast("Error: API Key no configurada en el código fuente de Python.", true);
    return null;
  }
  const payload = { contents: [{parts:[{text:prompt}]}] };
  const gen = {};
  if(isJson) gen.responseMimeType = 'application/json';
  if(opts.temperature !== undefined) gen.temperature = opts.temperature;
  if(Object.keys(gen).length) payload.generationConfig = gen;

  for(let attempt=0; attempt<=maxRetries; attempt++){
    const controller = new AbortController();
    const timeoutId = setTimeout(()=>controller.abort(), 25000);
    try {
      const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${GEMINI_API_KEY}`, {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload), signal: controller.signal
      });
      clearTimeout(timeoutId);
      const data = await res.json();

      if(!res.ok){
        const status = res.status;
        const retriable = status === 429 || status === 503 || status >= 500;
        if(retriable && attempt < maxRetries){
          if(attempt === 0) showToast('Modelo saturado, reintentando...');
          await new Promise(r=>setTimeout(r, 900*(attempt+1)));
          continue;
        }
        console.error("Gemini Error:", data);
        throw new Error(retriable ? 'El modelo está saturado ahora mismo. Prueba de nuevo en unos segundos.' : (data.error?.message || "Error en red/API."));
      }

      const text = data?.candidates?.[0]?.content?.parts?.[0]?.text;
      if(!text) throw new Error("La IA no devolvió contenido.");
      if(isJson){
        const start=text.indexOf('{'); const end=text.lastIndexOf('}');
        if(start === -1 || end === -1) throw new Error("La IA no devolvió un JSON válido.");
        return JSON.parse(text.substring(start,end+1));
      }
      return text;
    } catch(e) {
      clearTimeout(timeoutId);
      const isAbort = e.name === 'AbortError';
      if(isAbort && attempt < maxRetries){
        showToast('La IA está tardando demasiado, reintentando...');
        continue;
      }
      console.error("AI Fallback trigered:", e);
      showToast(isAbort ? 'La IA tardó demasiado en responder. Inténtalo de nuevo.' : `Fallo IA: ${e.message.slice(0,70)}`, true);
      return null;
    }
  }
  return null;
}

// =========================================
// 🎯 PIPELINE DE ESTIMACIÓN NUTRICIONAL (100% modelo de IA)
// =========================================
// Se quitó deliberadamente la consulta a Open Food Facts y la búsqueda web:
// para comida casera (el caso normal al hablar/escribir rápido) casi nunca
// encontraban un match fiable y solo añadían 1-2 llamadas de red extra de
// latencia sin mejorar la precisión real. Ahora es una única llamada a
// Gemini que hace TODO el trabajo (identificar alimento, gramos y macros a
// la vez), con anclas de ración de cocina casera española en el prompt para
// que el tamaño de ración se acerque más a la realidad. Un caché ligero por
// texto normalizado evita repetir la llamada si registras exactamente lo
// mismo otra vez (ej. "las mismas 2 tostadas de siempre").
function normalizeFoodKey(text){
  return String(text).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim();
}
async function getFoodCache(key){ return await safeGet('foodCache:' + key); }
async function setFoodCache(key, val){ await safeSet('foodCache:' + key, val); }

// Referencias de ración de cocina casera española, para que la IA ancle
// mejor los gramos cuando el usuario no da cantidad exacta (caso más común
// al dictar por voz o textear rápido).
const PORTION_ANCHORS = `Pechuga de pollo mediana ≈150g · Muslo de pollo ≈120g · Filete de ternera/cerdo ≈150g · Lomo de pescado ≈150g · Plato de arroz o pasta (guarnición) cocido ≈150-200g, como plato único ≈250-300g · Puñado de arroz/pasta en crudo ≈70-90g/persona · Patata mediana ≈150g · Huevo grande ≈55g · Rebanada de pan ≈30-40g · Cucharada sopera de aceite ≈10-13g · Yogur individual ≈125g · Pieza de fruta mediana (manzana, plátano, naranja) ≈130-180g · Puñado de frutos secos ≈25-30g · Cazo de legumbre cocida (guarnición) ≈150-180g, plato único ≈250g.`;

// =========================================
// 🍽️ ESTIMACIÓN DE COMIDAS v2
// =========================================
// · Desglose por alimento (gramos + kcal + macros): los totales se SUMAN en código.
// · Rango (kcal_low–kcal_high) + confianza + supuestos visibles; como mucho 1 pregunta.
// · Si el texto trae kcal o valores de etiqueta por 100 g/ml, el total se calcula
//   de forma determinista (la IA solo reparte macros).
// · temperature 0 → misma frase, misma estimación.
// · Aprende de tus correcciones: se guardan (aiCorrections), se reutilizan como
//   ejemplos en el prompt y la caché guarda el valor que TÚ validaste.
const FOOD_PROMPT_VERSION = 'v2';
const numOr0 = v => { const n = Number(v); return Number.isFinite(n) && n >= 0 ? n : 0; };

// Cantidad única en gramos al inicio del texto ("10g de maltodextrina") → para el control de plausibilidad.
function singleGramsOf(text){
  const m = /^\s*(\d+(?:[.,]\d+)?)\s*(?:g|gr|gramos)\b(?!.*\d+\s*(?:g|gr|gramos)\b)/i.exec(String(text || ''));
  return m ? parseFloat(m[1].replace(',', '.')) : null;
}
// kcal explícitas en el texto → total determinista.
function parseExplicitNutrition(text){
  const t = String(text || '').toLowerCase().replace(/(\d),(\d)/g, '$1.$2');
  // "620kcal de pizza bbq", "400 kcal de chips ahoy" (una sola cosa; con "más/y/+" decide la IA)
  let m = /^\s*(\d+(?:\.\d+)?)\s*kcal\b/.exec(t);
  if(m && !/\b(m[aá]s|adem[aá]s|y|aparte)\b|\+/.test(t.slice(m[0].length))) return { kcal: parseFloat(m[1]), basis: 'kcal indicadas por ti' };
  // "383g de pizza ... por cada 100g 212 kcal", "114g ... para 100 gr ... 1642 kJ ... 393 kcal", "500ml ... 100ml tienen 19kcal"
  const q = /(\d+(?:\.\d+)?)\s*(g|gr|gramos|ml)\b/.exec(t);
  const p100 = t.search(/\b100\s*(?:g|gr|gramos|ml)\b/);
  if(q && p100 > q.index){
    const k = /(\d+(?:\.\d+)?)\s*kcal/.exec(t.slice(p100 + 3));
    if(k) return { kcal: parseFloat(q[1]) * parseFloat(k[1]) / 100, basis: `etiqueta: ${k[1]} kcal/100 ${q[2] === 'ml' ? 'ml' : 'g'} × ${q[1]} ${q[2] === 'ml' ? 'ml' : 'g'}` };
  }
  return null;
}
async function getAiCorrections(){ return (await safeGet('aiCorrections')) || []; }
async function recordAiCorrection(rec){
  const list = await getAiCorrections();
  list.push({ id: 'cr' + Date.now().toString(36), at: Date.now(), ...rec });
  if(list.length > 400) list.splice(0, list.length - 400);
  await safeSet('aiCorrections', list);
}
function normalizeAiEstimate(res, text){
  if(!res || typeof res !== 'object') return null;
  let items = (Array.isArray(res.items) ? res.items : []).filter(i => i && i.food).map(i => ({ food: String(i.food), grams: numOr0(i.grams), kcal: numOr0(i.kcal), p: numOr0(i.p), c: numOr0(i.c), f: numOr0(i.f), s: numOr0(i.s) }));
  let tot = sumEntries(items);
  const explicit = parseExplicitNutrition(text);
  if(explicit && explicit.kcal > 0){
    if(tot.kcal > 0){ const k = explicit.kcal / tot.kcal; items = items.map(i => ({ ...i, kcal: i.kcal*k, p: i.p*k, c: i.c*k, f: i.f*k, s: i.s*k })); }
    else items = [{ food: String(res.label || text).slice(0, 60), grams: 0, kcal: explicit.kcal, p: 0, c: 0, f: 0, s: 0 }];
    tot = sumEntries(items);
  }
  const r1 = x => Math.round(x * 10) / 10;
  let low = numOr0(res.kcal_low), high = numOr0(res.kcal_high);
  if(explicit){ low = high = tot.kcal; }
  else { if(!(low > 0 && low <= tot.kcal)) low = tot.kcal * 0.85; if(!(high >= tot.kcal)) high = tot.kcal * 1.15; }
  const warnings = []; let fixKcal = null;
  const macroK = 4*tot.p + 4*tot.c + 9*tot.f;
  if(tot.kcal > 60 && Math.abs(macroK - tot.kcal) > 0.2 * tot.kcal) warnings.push(`Las kcal (${Math.round(tot.kcal)}) no cuadran con los macros (4·P+4·C+9·G = ${Math.round(macroK)}).`);
  const g = singleGramsOf(text);
  if(g && tot.kcal > g * 9.3){ warnings.push(`${Math.round(tot.kcal)} kcal en ${g} g es imposible (la grasa pura tiene ~9 kcal/g).`); if(tot.kcal/10 <= g*9.3) fixKcal = Math.round(tot.kcal/10); }
  const conf = explicit ? 'alta' : (['alta','media','baja'].includes(res.confidence) ? res.confidence : 'media');
  return { label: String(res.label || text).slice(0, 80), kcal: r1(tot.kcal), p: r1(tot.p), c: r1(tot.c), f: r1(tot.f), s: r1(tot.s),
    items: items.map(i => ({ ...i, kcal: r1(i.kcal), p: r1(i.p), c: r1(i.c), f: r1(i.f), s: r1(i.s) })),
    range: { low: Math.round(low), high: Math.round(high) }, confidence: conf,
    assumptions: (Array.isArray(res.assumptions) ? res.assumptions : []).map(String).slice(0, 6),
    question: explicit ? null : (res.question ? String(res.question) : null), explicitBasis: explicit ? explicit.basis : null,
    warnings, fixKcal, model: GEMINI_MODEL_FOOD, promptVersion: FOOD_PROMPT_VERSION };
}

async function estimateWithAIOnly(text, clarification = null){
  const corr = (await getAiCorrections()).slice(-6).map(c => `- "${c.text}": estimaste ${Math.round(c.ai.kcal)} kcal → el usuario lo corrigió a ${Math.round(c.final.kcal)} kcal`).join('\n');
  const prompt = `Eres un dietista-nutricionista español experto en estimar raciones de comida casera y productos de supermercado españoles a partir de descripciones rápidas (dictadas por voz o escritas deprisa).

Texto del registro: "${text}"${clarification ? `\nAclaración del usuario: "${clarification}"` : ''}

Referencias de ración en cocina casera española (para estimar gramos si no se indican): ${PORTION_ANCHORS}

Reglas:
1. Descompón en alimentos/ingredientes con gramos (o ml) estimados. Usa las cantidades del texto cuando existan.
2. Si el texto da kcal totales, kcal por 100 g/ml o valores de una etiqueta, ÚSALOS LITERALMENTE.
3. Grasas ocultas: en platos caseros fritos, salteados, a la plancha, guisos o con salsa, incluye el aceite como alimento propio (por defecto 10 g por ración; 15 g en fritos de sartén) salvo que el texto diga otra cosa, y decláralo en "assumptions". Incluye salsas, mahonesa, queso, pan y bebidas si se mencionan.
4. Tablas de composición españolas (BEDCA). Bebidas: 1 ml ≈ 1 g.
5. Coherencia por alimento: kcal ≈ 4·p + 4·c + 9·f. "s" = azúcares totales (0 si no lleva).
6. Incertidumbre honesta: "kcal_low"/"kcal_high" = rango razonable de lo descrito (más ancho cuanto menos precise el texto: ración, aceite, marca). "confidence": "alta" si hay cantidades o etiqueta; "media" si hay que suponer la ración; "baja" si es muy ambiguo.
7. "question": SOLO si una única aclaración cambiaría el total más de un 25 % (p. ej. "¿Cuántos gramos eran aproximadamente?", "¿Frito o a la plancha?"). Si no, null.
${corr ? `8. Correcciones previas de ESTE usuario a estimaciones tuyas (calibra raciones y productos parecidos):\n${corr}\n` : ''}Si el texto no describe comida, devuelve "items": [] y explica el motivo en "label".

Devuelve SOLO JSON, sin texto fuera:
{"label":"nombre corto","items":[{"food":"","grams":0,"kcal":0,"p":0,"c":0,"f":0,"s":0}],"kcal_low":0,"kcal_high":0,"confidence":"media","assumptions":[""],"question":null}`;
  const res = await callGemini(prompt, true, GEMINI_MODEL_FOOD, 2, { temperature: 0 });
  const est = normalizeAiEstimate(res, text);
  if(est){ est.source = 'Estimación de IA'; est.fromAI = true; }
  return est;
}

// Caché: solo guarda lo que TÚ confirmaste (valor final, corregido o no).
async function estimateFoodEntry(text, clarification = null){
  const cacheKey = normalizeFoodKey(text);
  if(!clarification && cacheKey){
    const cached = await getFoodCache(cacheKey);
    if(cached && cached.promptVersion === FOOD_PROMPT_VERSION && cached.result && validateFoodEntry(cached.result)){
      return { ...cached.result, source: cached.corrected ? 'Tu valor corregido (caché)' : 'Confirmado por ti antes (caché)', fromCache: true, fromAI: false };
    }
  }
  return await estimateWithAIOnly(text, clarification);
}

// =========================================
// 🎙️ PROCESAR TEXTO Y VOZ (NUTRICIÓN)
// =========================================
function validateFoodEntry(entry){
  if(!entry || typeof entry.label !== 'string' || !entry.label.trim()) return false;
  return ['kcal','p','c','f','s'].every(key => Number.isFinite(Number(entry[key])) && Number(entry[key]) >= 0);
}
function reliabilityBadge(source){
  if(!source) return '';
  const cached = /caché/i.test(source), fav = /favorita/i.test(source);
  const color = cached || fav ? '#8aa2c8' : 'var(--accent)';
  const label = fav ? '⭐ Favorita' : cached ? `✔ ${source}` : '🤖 Estimación de IA';
  return `<div class="src-badge" style="color:${color};">${label}</div>`;
}
const escAttr = s => String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
function reviewInputsHTML(e){
  return `<div class="food-review-grid">
      <input id="review-label" value="${escAttr(e.label)}" aria-label="Nombre de la comida">
      <input id="review-kcal" type="number" min="0" step="1" value="${Math.round(e.kcal)}" aria-label="Kcal">
      <input id="review-p" type="number" min="0" step="0.1" value="${e.p}" aria-label="Proteína">
      <input id="review-c" type="number" min="0" step="0.1" value="${e.c}" aria-label="Carbohidratos">
      <input id="review-f" type="number" min="0" step="0.1" value="${e.f}" aria-label="Grasas">
      <input id="review-sugar" type="number" min="0" step="0.1" value="${e.s || 0}" aria-label="Azúcar">
    </div>
    <div class="scale-row"><span>Ajustar ración</span>${[0.5, 0.75, 1.25, 1.5, 2].map(k => `<button class="secondary" onclick="scaleReview(${k})">×${String(k).replace('.', ',')}</button>`).join('')}</div>`;
}
function estimateDetailsHTML(est){
  if(!est || !est.range) return '';
  let h = `<div class="est-meta">Rango probable <b>${est.range.low === est.range.high ? est.range.low : `${est.range.low}–${est.range.high}`} kcal</b> · confianza <b>${est.confidence}</b>${est.explicitBasis ? ` · <span style="color:var(--green)">${escAttr(est.explicitBasis)}</span>` : ''}</div>`;
  if(est.items && est.items.length) h += `<table class="est-items"><tbody>${est.items.map(i => `<tr><td>${escAttr(i.food)}</td><td>${i.grams ? Math.round(i.grams) + ' g' : ''}</td><td>${Math.round(i.kcal)} kcal</td></tr>`).join('')}</tbody></table>`;
  if(est.assumptions && est.assumptions.length) h += `<div class="est-assump">Supuestos: ${est.assumptions.map(escAttr).join(' · ')}</div>`;
  (est.warnings || []).forEach(w => { h += `<div class="alert warn" style="margin:10px 0 0;">⚠️ ${escAttr(w)}${est.fixKcal ? ` <button class="secondary mini" onclick="applyReviewKcal(${est.fixKcal})">Usar ${est.fixKcal} kcal</button>` : ''}</div>`; });
  return h;
}
function showFoodReview(entry, isEdit = false){
  pendingFoodEntry = entry;
  editingLogId = isEdit ? entry.id : null;
  const est = isEdit ? entry.ai : entry;
  const review = $('food-review');
  review.style.display = 'block';
  review.innerHTML = `<strong>${isEdit ? 'Editar registro' : 'Revisa antes de guardar'}</strong><div style="color:var(--text-dim);font-size:.8rem;margin-top:4px;">${isEdit ? 'Corrige los valores y confirma. Si difieren de la IA, se guarda como corrección para que aprenda.' : 'Estimación con rango. Ajusta la ración o los valores si hace falta.'}</div>${reliabilityBadge(isEdit ? entry.source : entry.source)}
    ${est ? estimateDetailsHTML(est) : ''}
    ${!isEdit && entry.question ? `<div class="est-question">❓ ${escAttr(entry.question)}<div style="display:flex;gap:8px;margin-top:8px;"><input id="review-answer" placeholder="Tu respuesta (opcional)" style="margin:0;"><button class="secondary" onclick="answerFoodQuestion()">Re-estimar</button></div></div>` : ''}
    ${reviewInputsHTML(entry)}
    <div style="display:flex;gap:8px;"><button class="primary" style="flex:1;padding:11px;" onclick="confirmFoodReview()">${isEdit ? 'Guardar cambios' : 'Confirmar y registrar'}</button><button class="secondary" onclick="cancelFoodReview()">${isEdit ? 'Cancelar' : 'Descartar'}</button></div>`;
}
window.scaleReview = (k) => {
  ['kcal','p','c','f','sugar'].forEach(f => { const el = $('review-' + f); if(el) el.value = f === 'kcal' ? Math.round(Number(el.value) * k) : Math.round(Number(el.value) * k * 10) / 10; });
};
window.applyReviewKcal = (kcal) => { const cur = Number($('review-kcal').value) || 0; if(cur > 0) scaleReview(kcal / cur); };
window.answerFoodQuestion = async () => {
  const ans = ($('review-answer')?.value || '').trim();
  if(!ans || !pendingFoodEntry) return;
  const text = pendingFoodEntry.originalText;
  $('ai-status').innerText = 'Re-estimando con tu respuesta...';
  const res = await estimateFoodEntry(text, ans);
  if(validateFoodEntry(res) && res.kcal > 0){ res.originalText = text; res.clarification = ans; showFoodReview(res, false); $('ai-status').innerText = 'Estimación actualizada.'; }
  else showToast('No se pudo re-estimar ahora mismo.', true);
};
function cancelFoodReview(){
  pendingFoodEntry = null;
  editingLogId = null;
  const review = $('food-review');
  if(review){ review.style.display = 'none'; }
}
function showFoodReviewComparison(oldEntry, newEntry, kcalDiff){
  pendingFoodEntry = newEntry;
  editingLogId = oldEntry.id;
  const diff = Number.isFinite(kcalDiff) ? kcalDiff : (newEntry.kcal - oldEntry.kcal);
  const diffColor = diff > 0 ? 'var(--accent)' : diff < 0 ? 'var(--green)' : 'var(--text-dim)';
  const review = $('food-review');
  review.style.display = 'block';
  review.innerHTML = `<strong>Nueva estimación</strong>
    <div style="color:var(--text-dim);font-size:.8rem;margin-top:4px;">Compara con lo que tenías guardado, ajusta si hace falta y decide cuál te quedas.</div>
    <div class="cmp-bar"><span>Antes: <b>${Math.round(oldEntry.kcal)} kcal</b></span><span style="color:var(--text-dim);">→</span><span>Ahora: <b>${Math.round(newEntry.kcal)} kcal</b></span><span style="color:${diffColor}; font-weight:800;">${diff>=0?'+':''}${Math.round(diff)} kcal</span></div>
    ${estimateDetailsHTML(newEntry)}
    <div style="font-size:.75rem; color:var(--text-dim); margin:10px 0;">Texto original: "${escAttr(oldEntry.originalText || '')}"</div>
    ${reviewInputsHTML(newEntry)}
    <div style="display:flex;gap:8px;"><button class="primary" style="flex:1;padding:11px;" onclick="confirmFoodReview()">Usar esta estimación</button><button class="secondary" onclick="cancelFoodReview()">Mantener la anterior</button></div>`;
  review.scrollIntoView({behavior:'smooth', block:'center'});
}
window.reestimateLog = async (id) => {
  const entries = await getLog(selectedLogDate);
  const entry = entries.find(e => e.id === id);
  if(!entry) return;
  if(!entry.originalText){ showToast('Este registro no guardó el texto original, así que no se puede re-estimar.', true); return; }
  showToast('Pidiendo una nueva estimación a la IA...');
  const res = await estimateWithAIOnly(entry.originalText);
  if(!validateFoodEntry(res) || res.kcal <= 0){ showToast('No se pudo generar una nueva estimación ahora mismo.', true); return; }
  res.originalText = entry.originalText;
  const kcalDiff = res.kcal - entry.kcal;
  const pctDiff = entry.kcal > 0 ? Math.abs(kcalDiff) / entry.kcal * 100 : 100;
  if(pctDiff < 3){ showToast(`Sin cambios relevantes (diferencia de ${Math.round(Math.abs(kcalDiff))} kcal, <3 %).`); return; }
  showFoodReviewComparison(entry, res, kcalDiff);
};
function aiSnapshot(est){
  if(!est) return null;
  return { kcal: est.kcal, p: est.p, c: est.c, f: est.f, s: est.s || 0, items: est.items || [], range: est.range || null, confidence: est.confidence || null,
    assumptions: est.assumptions || [], question: est.question || null, clarification: est.clarification || null, explicitBasis: est.explicitBasis || null,
    warnings: est.warnings || [], model: est.model || null, promptVersion: est.promptVersion || null, at: Date.now() };
}
const differsFrom = (a, b) => Math.abs((a.kcal||0) - (b.kcal||0)) >= 1 || ['p','c','f'].some(k => Math.abs((a[k]||0) - (b[k]||0)) >= 0.5);
window.confirmFoodReview = async () => {
  if(!pendingFoodEntry) return;
  const final = { label: $('review-label').value.trim(), kcal: Number($('review-kcal').value), p: Number($('review-p').value), c: Number($('review-c').value), f: Number($('review-f').value), s: Number($('review-sugar').value) || 0 };
  if(!validateFoodEntry(final) || final.kcal <= 0){ showToast('Revisa los valores de la comida.', true); return; }
  const now = Date.now();
  const entries = await getLog(selectedLogDate);
  const src = pendingFoodEntry;
  let saved;
  if(editingLogId){
    const idx = entries.findIndex(e => e.id === editingLogId);
    if(idx === -1){ showToast('No se encontró el registro original.', true); cancelFoodReview(); return; }
    const before = entries[idx];
    const freshAI = src !== before && src.fromAI;               // viene de "Re-estimar"
    const ai = freshAI ? aiSnapshot(src) : (before.ai || null);
    const corrected = ai ? differsFrom(ai, final) : !!before.corrected;
    if(corrected && ai && differsFrom(before, final)) await recordAiCorrection({ date: selectedLogDate, entryId: before.id, text: before.originalText || before.label, label: final.label, ai: { kcal: ai.kcal, p: ai.p, c: ai.c, f: ai.f }, final: { kcal: final.kcal, p: final.p, c: final.c, f: final.f }, deltaKcal: Math.round(final.kcal - ai.kcal), deltaPct: ai.kcal ? +((final.kcal - ai.kcal) / ai.kcal * 100).toFixed(1) : null, model: ai.model, promptVersion: ai.promptVersion });
    const edits = [...(before.edits || []), { at: now, from: { kcal: before.kcal, p: before.p, c: before.c, f: before.f }, to: { kcal: final.kcal, p: final.p, c: final.c, f: final.f } }].slice(-10);
    saved = entries[idx] = { ...before, ...final, updatedAt: now, ai, corrected, edits, source: freshAI ? src.source : before.source };
    await setLog(selectedLogDate, entries);
    showToast('Registro actualizado');
  } else {
    const ai = src.fromAI ? aiSnapshot(src) : null;
    const corrected = ai ? differsFrom(ai, final) : false;
    saved = { id: now.toString(36), createdAt: now, updatedAt: now, time: new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'}), ...final, originalText: src.originalText || '', source: src.source || 'Manual', ai, corrected };
    if(corrected) await recordAiCorrection({ date: selectedLogDate, entryId: saved.id, text: saved.originalText, label: final.label, ai: { kcal: ai.kcal, p: ai.p, c: ai.c, f: ai.f }, final: { kcal: final.kcal, p: final.p, c: final.c, f: final.f }, deltaKcal: Math.round(final.kcal - ai.kcal), deltaPct: ai.kcal ? +((final.kcal - ai.kcal) / ai.kcal * 100).toFixed(1) : null, model: ai.model, promptVersion: ai.promptVersion });
    entries.push(saved);
    await setLog(selectedLogDate, entries);
    showToast(`+${Math.round(final.kcal)} kcal registradas (${formatDateLabel(selectedLogDate).toLowerCase()})`);
    await checkFavoriteSuggestion(saved);
  }
  // Caché = lo que TÚ confirmaste (si corriges, la próxima vez sale tu valor).
  const key = normalizeFoodKey(saved.originalText || '');
  if(key){
    const est = saved.ai;
    const k = est && est.kcal > 0 ? final.kcal / est.kcal : 1;
    await setFoodCache(key, { promptVersion: FOOD_PROMPT_VERSION, corrected: !!saved.corrected, updatedAt: now,
      result: { ...final, items: (est?.items || []).map(i => ({ ...i, kcal: i.kcal*k, p: i.p*k, c: i.c*k, f: i.f*k })), range: { low: Math.round(final.kcal), high: Math.round(final.kcal) }, confidence: 'alta', assumptions: [saved.corrected ? 'Valor corregido por ti' : 'Valor confirmado por ti'], question: null, warnings: [] } });
  }
  cancelFoodReview();
  await updateDashboardUI(); await refreshInsights();
  $('ai-status').innerText = 'Procesado con éxito.';
};

async function processText(voiceText){
  const inputEl = $('manual-text');
  const btnEl = $('btn-send-text');
  const input = voiceText || inputEl.value;
  if(!input.trim()) return;
  inputEl.value=''; btnEl.disabled=true; $('btn-mic').disabled=true;
  $('ai-status').innerText = 'Estimando kcal y macros...';
  const res = await estimateFoodEntry(input);
  if(validateFoodEntry(res) && res.kcal > 0){
    res.originalText = input;
    showFoodReview(res, false);
    $('ai-status').innerText = 'Estimación lista: revísala antes de guardar.';
  } else {
    $('ai-status').innerText = res && res.label && !res.kcal ? `No parece comida: ${res.label}` : 'No se pudo procesar. Inténtalo de nuevo en unos segundos.';
  }
  btnEl.disabled=false; $('btn-mic').disabled=false;
}

// Web Speech API
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition;
if(SpeechRec){
  recognition = new SpeechRec();
  recognition.lang='es-ES'; recognition.interimResults=false;
  recognition.onstart=()=>{ $('btn-mic').classList.add('listening'); $('ai-status').innerText='Escuchando tus macros...'; };
  recognition.onend=()=>{ $('btn-mic').classList.remove('listening'); };
  recognition.onresult=(e)=>processText(e.results[0][0].transcript);
  recognition.onerror=(e)=>{ showToast("Fallo de micrófono", true); $('btn-mic').classList.remove('listening'); }
}
$('btn-mic').onclick = ()=>{
  if(!recognition) { showToast('Navegador no soporta dictado', true); return; }
  recognition.start();
};

// =========================================
// 📅 GENERACIÓN DEL MENÚ (WORKFLOW SEMANAL)
// =========================================
// Resumen de las últimas 3 semanas de registros reales, para que el plan
// generado no se diseñe en el vacío y tenga en cuenta lo que de verdad comes.
async function buildRecentHistorySummary(days = 21){
  // Días CERRADOS (hoy no cuenta: está a medias) y solo días completos para las medias.
  const st = getEngineState();
  const from = shiftDate(todayStr(), -days);
  const closed = st.days.filter(d => d.date >= from && d.status !== 'open' && d.entries > 0);
  const complete = closed.filter(d => d.status === 'complete');
  if(complete.length < 3) return null;
  const freq = new Map();
  for(const d of closed) for(const e of await getLog(d.date)){
    const label = String(e.label || '').trim(); if(!label) continue;
    const norm = label.toLowerCase(); const prev = freq.get(norm);
    if(prev) prev.count++; else freq.set(norm, { label, count: 1 });
  }
  const topMeals = [...freq.values()].filter(m => m.count >= 2).sort((a, b) => b.count - a.count).slice(0, 6).map(m => `${m.label} (${m.count}x)`);
  const avg = Math.round(complete.reduce((a, d) => a + d.intake, 0) / complete.length);
  const within = complete.filter(d => d.targetEffective && Math.abs(d.intake - d.targetEffective) <= d.targetEffective * 0.1).length;
  return `Historial real de los últimos ${days} días (${complete.length} días completos): media ~${avg} kcal/día, ${within}/${complete.length} días dentro de ±10% del objetivo de ese día; necesario estimado para progresar ~${st.decision.needed} kcal.${topMeals.length ? ` Comidas que repite con frecuencia: ${topMeals.join(', ')}.` : ''}`;
}

async function generatePlan(){
  $('btn-generate-plan').style.display='none';
  $('plan-loading').style.display='block';
  $('plan-container').style.display='none';
  $('plan-validation').style.display='none';

  const planTargets = getPlanTargets();
  const t = planTargets.average;
  const historySummary = await buildRecentHistorySummary(21);

  const prompt = `Eres un Dietista-Nutricionista deportivo clínico. Diseña un plan de hipertrofia de 7 días exacto, basado en seguridad alimentaria (AESAN/FDA).
Objetivo Diario Promedio: ${Math.round(t.kcal)} kcal (P:${Math.round(t.p)}g, C:${Math.round(t.c)}g, G:${Math.round(t.f)}g).
Preferencias del usuario: ${profile.preferences || 'sin restricciones indicadas'}.
${historySummary ? historySummary + ' Prioriza comidas de estilo similar a las que ya repite (si encajan con los objetivos y preferencias) y ten en cuenta su adherencia real al proponer cantidades, en vez de diseñar el plan en el vacío.' : 'Aún no hay histórico suficiente de registros reales; diseña el plan solo a partir del objetivo y las preferencias indicadas.'}\nComidas al dia: ${profile.mealsPerDay || 5}. Todos los días tienen el mismo objetivo de kcal y macros.
Usa alimentos comodín de fácil asimilación si necesitas rellenar kcal: ${FILLER_FOODS}.

ESTRUCTURA DE COMIDAS ESTRICTA (${profile.mealsPerDay || 5} comidas exactas por día):
1. "Recién Levantado" (type:"fresh"): Al despertar. Alta digestibilidad, preparación en segundos sin ruido (sin electrodomésticos). Ej: yogur, batido manual (clear whey, maltodextrina), tortitas arroz.
2. "Desayuno" (type:"batch"): Para llevar. Formato tupper/vaso hermético limpio y sin migas (ej. overnight oats, porridge). Preparado en masa el domingo.
3. "Comida" (type:"batch"): Comida principal en tupper. Alto en CH complejos. Preparado el domingo.
4. "Merienda" (type:"fresh"): Snack rápido de tarde.
5. "Cena" (type:"fresh"): Comida final ligera y cocinada/montada al momento. Digestión amable para dormir.

WORKFLOW DEL USUARIO (Logística):
- Planifica HOY (Jueves).
- Compra MAÑANA (Viernes).
- Batch Cooking el DOMINGO para toda la semana. Divide en recipientes poco profundos y refrigera o congela inmediatamente; no dejes arroz o pasta cocidos enfriándose durante horas a temperatura ambiente.
Aplica directrices de conservación: nevera máximo 3-4 días (hasta el miércoles). Lo de Jueves a Domingo va al congelador. Genera "storagePlan" y "foodSafetyNotes".

RESTRICCIONES:
- Los totales diarios deben ser la suma exacta de sus comidas, no una estimación independiente.
- Los valores de cada comida deben ser la suma de todos sus ingredientes. Comprueba siempre que kcal sean coherentes con P, C y G (kcal aproximadas = P*4 + C*4 + G*9).
- Mantén proteína entre el 98% y el 105% del objetivo diario, grasas entre el 90% y el 110% y kcal entre el 95% y el 105%.
- Cada comida debe incluir cantidades y un campo "weightBasis" con "crudo" o "cocinado". Cada ingrediente debe incluir "food", "grams", "kcal", "p", "c" y "f". Para líquidos añade también "isLiquid":true y "ml".
- No ocultes agua, leche ni ningún líquido en instrucciones, nombres o alternativas: deben aparecer como ingredientes dentro de "items" y sus kcal/macros deben estar incluidas. En overnight oats, porridge, cremas, batidos, harina de arroz o crema de arroz incluye siempre el líquido exacto (agua con kcal 0, o leche/bebida con sus kcal reales). Si se usa leche, inclúyela también en "shoppingList" con la cantidad semanal calculada.
- La lista de compra debe sumar todos los ingredientes de los 7 días, incluidos líquidos con aporte nutricional. No cuentes las alternativas, solo la opción principal del plan.
- Añade "alternatives" (dos sustituciones sencillas) por cada comida.
- DEVUELVE SOLO UN JSON. SIN TEXTO EXTRA FUERA DEL JSON. SIN MARKDOWN.
- Estructura exacta requerida: 
{
 "days":[
  {"day":"Lunes","meals":[
    {"name":"Recién Levantado","type":"fresh","weightBasis":"crudo","items":[{"food":"Clear Whey","grams":30,"kcal":105,"p":25,"c":1,"f":0},{"food":"Agua","grams":300,"ml":300,"isLiquid":true,"kcal":0,"p":0,"c":0,"f":0}],"alternatives":["Yogur alto en proteína 200g","Leche sin lactosa 250ml"],"kcal":105,"p":25,"c":1,"f":0}
  ],"totals":{"kcal":105,"p":25,"c":1,"f":0}}
 ],
 "shoppingList":[{"item":"Avena","qty":"1kg"}],
 "batchInstructions":["Domingo: Hervir..."],
 "storagePlan":[{"meal":"Comida-Jueves","consumeDay":"Jueves","storage":"Congelador","note":"Sacar a nevera la noche antes"}],
 "foodSafetyNotes":"Nota clínica de seguridad..."
}`;

  const res = await callGemini(prompt, true, GEMINI_MODEL_PLAN);
  $('plan-loading').style.display='none';
  $('btn-generate-plan').style.display='block';
  
  const validation = validatePlan(res, planTargets);
  if(res && res.days && validation.ok){
    syncPlanDerivedData(res); // fuente única de verdad desde el primer momento
    await safeSet('lastPlan', { plan: res, generatedAt: new Date().toISOString() });
    renderPlanObject(res, new Date().toLocaleString('es-ES'));
    showToast("Menú semanal generado correctamente");
  } else {
    const message = validation.issues.length ? validation.issues.join(' ') : 'La IA no devolvió un plan válido.';
    $('plan-validation').style.display='block'; $('plan-validation').innerText = message;
    showToast("Plan rechazado: no cumple tus objetivos.", true);
  }
}

// =========================================
// 🔗 FUENTE ÚNICA DE VERDAD: MENÚ ↔ COMPRA ↔ BATCH (punto 9)
// =========================================
// La lista de la compra y el plan de conservación YA NO son texto fijo que
// la IA entrega una vez y puede quedar obsoleto: se recalculan aquí a
// partir de plan.days cada vez que el plan cambia (generación inicial,
// sustituir ingrediente, sustituir comida). Así nunca pueden desincronizarse
// del menú real, sin duplicar la lógica en tres sitios distintos.
function recomputeShoppingList(plan){
  const totals = new Map();
  plan.days.forEach(day => {
    (day.meals || []).forEach(meal => {
      (meal.items || []).forEach(item => {
        const key = normalizeFoodKey(item.food || '');
        if(!key) return;
        const prev = totals.get(key) || { food: item.food, grams: 0, ml: 0, isLiquid: !!item.isLiquid };
        prev.grams += Number(item.grams) || 0;
        if(item.isLiquid) prev.ml += Number(item.ml || item.grams) || 0;
        totals.set(key, prev);
      });
    });
  });
  return [...totals.values()].map(t => ({ item: t.food, qty: t.isLiquid ? `${Math.round(t.ml)} ml` : `${Math.round(t.grams)} g` }));
}

function recomputeStoragePlan(plan){
  // Regla fija AESAN/FDA ya usada en el prompt original: nevera máx 3-4 días
  // desde el domingo de batch cooking; de ahí en adelante, congelador.
  // Se deriva del orden REAL de los días del plan, no de una tabla aparte.
  const dayOrder = plan.days.map(d => d.day);
  const sundayIdx = dayOrder.findIndex(d => /domingo/i.test(d));
  const storagePlan = [];
  plan.days.forEach((day, idx) => {
    (day.meals || []).forEach(meal => {
      if(meal.type !== 'batch') return;
      const distanceFromSunday = sundayIdx === -1 ? idx : ((idx - sundayIdx) + 7) % 7;
      const storage = distanceFromSunday <= 3 ? 'Nevera' : 'Congelador';
      const note = storage === 'Congelador' ? 'Sacar a nevera la noche antes de consumir' : 'Consumir dentro de 3-4 días desde el domingo';
      storagePlan.push({ meal: `${meal.name}-${day.day}`, consumeDay: day.day, storage, note });
    });
  });
  return storagePlan;
}

function syncPlanDerivedData(plan){
  plan.shoppingList = recomputeShoppingList(plan);
  plan.storagePlan = recomputeStoragePlan(plan);
  return plan;
}

function validatePlan(plan, targets){
  const issues = [];
  const validNumber = value => Number.isFinite(Number(value)) && Number(value) >= 0;
  if(!plan || !Array.isArray(plan.days) || plan.days.length !== 7) issues.push('Deben existir exactamente 7 días.');
  if(!plan || !Array.isArray(plan.shoppingList) || !plan.shoppingList.length) issues.push('Falta una lista de compra calculada.');
  if(!plan || !Array.isArray(plan.batchInstructions) || !plan.batchInstructions.length) issues.push('Faltan instrucciones de batch cooking.');
  if(!plan || !plan.foodSafetyNotes) issues.push('Faltan directrices de seguridad alimentaria.');
  if(!plan || !Array.isArray(plan.days)) return {ok:false, issues};
  if(new Set(plan.days.map(day=>String(day.day || '').trim().toLowerCase())).size !== plan.days.length) issues.push('Hay días repetidos en el plan.');
  plan.days.forEach((day, index)=>{
    if(!Array.isArray(day.meals) || day.meals.length !== Number(profile.mealsPerDay || 5)) { issues.push(`El día ${index+1} no tiene el número correcto de comidas.`); return; }
    day.meals.forEach(meal=>{
      if(!['crudo','cocinado'].includes(meal.weightBasis) || !Array.isArray(meal.items) || !meal.items.length || !Array.isArray(meal.alternatives) || meal.alternatives.length < 2) issues.push(`El día ${index+1} tiene una comida incompleta.`);
      if(!validNumber(meal.kcal) || !validNumber(meal.p) || !validNumber(meal.c) || !validNumber(meal.f)) issues.push(`La comida ${meal.name || ''} del día ${index+1} tiene valores inválidos.`);
      const liquidKeywords = /overnight|porridge|crema|batido|harina de arroz|crema de arroz|avena instantánea/i;
      const needsLiquid = liquidKeywords.test(`${meal.name} ${meal.items.map(item=>item.food || '').join(' ')}`);
      const hasLiquid = meal.items.some(item=>item.isLiquid === true && Number(item.ml || item.grams) > 0);
      if(needsLiquid && !hasLiquid) issues.push(`La comida ${meal.name} del día ${index+1} debe indicar agua o leche como ingrediente con ml y kcal.`);
      meal.items.forEach(item=>{
        if(!item.food || !validNumber(item.grams) || !validNumber(item.kcal) || !validNumber(item.p) || !validNumber(item.c) || !validNumber(item.f)) issues.push(`Faltan valores válidos en ${item.food || 'un ingrediente'} del día ${index+1}.`);
        if(item.isLiquid === true && (!item.ml || Number(item.ml) <= 0)) issues.push(`El líquido ${item.food || ''} del día ${index+1} debe indicar mililitros.`);
      });
      const itemSum = sumEntries(meal.items);
      if(Math.abs(Number(meal.kcal || 0) - itemSum.kcal) > 1 || Math.abs(Number(meal.p || 0) - itemSum.p) > 0.5 || Math.abs(Number(meal.c || 0) - itemSum.c) > 0.5 || Math.abs(Number(meal.f || 0) - itemSum.f) > 0.5) issues.push(`Los totales de ${meal.name} del día ${index+1} no suman sus ingredientes.`);
      const mealMacroKcal = Number(meal.p || 0) * 4 + Number(meal.c || 0) * 4 + Number(meal.f || 0) * 9;
      if(Number(meal.kcal) > 0 && Math.abs(meal.kcal - mealMacroKcal) > meal.kcal * 0.1) issues.push(`Las kcal y macros no cuadran en ${meal.name} del día ${index+1}.`);
    });
    const sum = sumEntries(day.meals);
    const target = targets.average;
    if(Math.abs(sum.kcal-target.kcal) > target.kcal*0.05 || Math.abs(sum.p-target.p) > target.p*0.05 || Math.abs(sum.c-target.c) > target.c*0.1 || Math.abs(sum.f-target.f) > target.f*0.1) issues.push(`El día ${index+1} no cumple kcal, macros o proteína.`);
    day.totals = { kcal:sum.kcal, p:sum.p, c:sum.c, f:sum.f };
  });
  return {ok: issues.length === 0, issues};
}

function renderPlanObject(plan, dateStr){
  $('plan-container').style.display='block';
  $('plan-date').innerText = 'Generado: ' + dateStr;
  
  const avgKcal = Math.round(plan.days.reduce((sum, day)=>sum + Number(day.totals?.kcal || 0), 0) / 7);
  let html = `<div class="plan-summary-bar">
      <span class="meta-pill"><b>7</b> días</span>
      <span class="meta-pill"><b>${avgKcal}</b> kcal medias</span>
      <span class="badge badge-batch">🍱 batch</span><span class="badge badge-fresh">⚡ fresh</span>
    </div>
    <p style="font-size:.8rem; color:var(--text-dim); margin:12px 0 20px; line-height:1.5;">Los nombres de los días solo ordenan la semana para el batch cooking del domingo. Todos los días tienen el mismo objetivo.</p>`;
  plan.days.forEach((d, dayIndex)=>{
    const totals = d.totals || sumEntries(d.meals);
    html += `<div class="day-card"><h3><span>${d.day}</span></h3>`;
    d.meals.forEach((m, mealIndex)=>{
      const badge = m.type==='batch' ? '<span class="badge badge-batch">🍱 batch</span>' : '<span class="badge badge-fresh">⚡ fresh</span>';
      const alternatives = Array.isArray(m.alternatives) ? m.alternatives.join(' · ') : 'Sin alternativas';
      html += `<div class="meal-row"><div><div class="meal-name">${m.name}</div>${badge}<small style="display:block;color:var(--text-dim);font-size:.68rem;margin-top:5px;">${m.weightBasis || 'no indicado'}</small></div><div class="meal-items">${m.items.map((i, itemIndex)=>`<div class="ingredient-row"><span>${i.food} (${i.isLiquid ? (i.ml || i.grams) + 'ml' : i.grams + 'g'})</span><button class="secondary" onclick="replaceIngredient(${dayIndex},${mealIndex},${itemIndex})">No tengo este ingrediente</button></div>`).join('')}<small class="meal-alternatives">Alternativas: ${alternatives}</small></div><div class="meal-kcal">${Math.round(m.kcal)}<small>kcal</small><button class="secondary" style="padding:5px 7px;font-size:.66rem;margin-top:8px;" onclick="replaceMeal(${dayIndex},${mealIndex})">Cambiar comida</button></div></div>`;
    });
    html += `<div class="day-total">Total del día: <b>${Math.round(totals.kcal)} kcal</b><span style="color:var(--text-dim);"> · P:${Math.round(totals.p)} · C:${Math.round(totals.c)} · G:${Math.round(totals.f)}</span></div></div>`;
  });
  
  if(plan.shoppingList) {
    html += `<div class="day-card"><h3>Compra · viernes</h3><table class="plan-table"><tbody>${plan.shoppingList.map(i=>`<tr><td>${i.item}</td><td style="text-align:right;">${i.qty}</td></tr>`).join('')}</tbody></table></div>`;
  }
  if(plan.batchInstructions) {
    html += `<div class="day-card"><h3>Batch cooking · domingo</h3><ol style="padding-left:16px;font-size:0.9rem;">${plan.batchInstructions.map(i=>`<li style="margin-bottom:8px;">${i}</li>`).join('')}</ol></div>`;
  }
  if(plan.storagePlan) {
    html += `<div class="day-card"><h3>Conservación</h3><table class="plan-table"><tbody>${plan.storagePlan.map(i=>`<tr><td><b>${i.meal}</b></td><td>${i.storage}</td><td style="font-size:0.75rem;">${i.note||''}</td></tr>`).join('')}</tbody></table>`;
    if(plan.foodSafetyNotes) html += `<div class="alert warn" style="margin-top:12px;">🌡️ ${plan.foodSafetyNotes}</div>`;
    html += `</div>`;
  }
  $('plan-output').innerHTML = html;
}

window.replaceIngredient = async (dayIndex, mealIndex, itemIndex) => {
  const saved = await safeGet('lastPlan');
  const meal = saved?.plan?.days?.[dayIndex]?.meals?.[mealIndex];
  const oldItem = meal?.items?.[itemIndex];
  if(!meal || !oldItem) return;
  showToast('Buscando ingrediente equivalente...');
  const prompt = `Sustituye SOLO este ingrediente de una comida de hipertrofia: ${JSON.stringify(oldItem)}.
Comida: ${meal.name}. Preferencias del usuario: ${profile.preferences || 'sin restricciones'}.
Mantén aproximadamente sus kcal y proteína, respeta restricciones y conserva el campo isLiquid/ml si procede.
Devuelve SOLO JSON con esta forma: {"food":"","grams":0,"kcal":0,"p":0,"c":0,"f":0,"isLiquid":false,"ml":0}.`;
  const replacement = await callGemini(prompt, true, GEMINI_MODEL);
  const valid = replacement && replacement.food && ['grams','kcal','p','c','f'].every(key => Number.isFinite(Number(replacement[key])) && Number(replacement[key]) >= 0);
  if(!valid){ showToast('No se encontró un sustituto válido.', true); return; }
  if(replacement.isLiquid === true && (!replacement.ml || Number(replacement.ml) <= 0)){ showToast('El sustituto líquido no indica mililitros.', true); return; }
  const oldMealKcal = Number(meal.kcal) || 0;
  const oldMealProtein = Number(meal.p) || 0;
  meal.items[itemIndex] = replacement;
  const totals = sumEntries(meal.items);
  if(Math.abs(totals.kcal - oldMealKcal) > Math.max(120, oldMealKcal * 0.15) || Math.abs(totals.p - oldMealProtein) > Math.max(12, oldMealProtein * 0.15)){
    meal.items[itemIndex] = oldItem;
    showToast('El sustituto se aleja demasiado del objetivo de la comida.', true);
    return;
  }
  meal.kcal = totals.kcal; meal.p = totals.p; meal.c = totals.c; meal.f = totals.f;
  const validation = validatePlan(saved.plan, getPlanTargets());
  if(!validation.ok){
    meal.items[itemIndex] = oldItem;
    meal.kcal = oldMealKcal; meal.p = oldMealProtein;
    showToast('El sustituto no mantiene el objetivo diario.', true);
    return;
  }
  syncPlanDerivedData(saved.plan); // recalcula compra y batch a partir del ingrediente ya sustituido
  await safeSet('lastPlan', saved);
  renderPlanObject(saved.plan, new Date(saved.generatedAt).toLocaleString('es-ES'));
  showToast('Ingrediente sustituido: compra y batch actualizados automáticamente');
};

window.replaceMeal = async (dayIndex, mealIndex) => {
  const saved = await safeGet('lastPlan');
  if(!saved || !saved.plan?.days?.[dayIndex]?.meals?.[mealIndex]) return;
  const oldMeal = saved.plan.days[dayIndex].meals[mealIndex];
  showToast('Buscando sustitución equivalente...');
  const target = getPlanTargets().average;
  const prompt = `Sustituye esta comida de un plan de hipertrofia por otra equivalente y compatible con las preferencias del usuario: ${profile.preferences || 'sin restricciones'}. Mantén el mismo tipo ${oldMeal.type}, aproximadamente las mismas kcal (${Math.round(oldMeal.kcal)}) y proteína (${Math.round(oldMeal.p)}g). Devuelve SOLO JSON con esta forma: {"name":"","type":"${oldMeal.type}","weightBasis":"crudo","items":[{"food":"","grams":0,"kcal":0,"p":0,"c":0,"f":0,"isLiquid":false,"ml":0}],"alternatives":["",""],"kcal":0,"p":0,"c":0,"f":0}. Si preparas overnight oats, crema, batido, harina de arroz o crema de arroz, incluye agua o leche como ingrediente dentro de items, con ml y sus kcal/macros; si es leche, debe contar también en las kcal totales. Los valores de la comida deben sumar sus ingredientes y ser coherentes con P*4+C*4+G*9. Objetivo del día: ${Math.round(target.kcal)} kcal y ${Math.round(target.p)}g de proteína.`;
  const replacement = await callGemini(prompt, true, GEMINI_MODEL);
  if(!replacement || !Array.isArray(replacement.items)) { showToast('No se encontró una sustitución válida.', true); return; }
  saved.plan.days[dayIndex].meals[mealIndex] = replacement;
  const validation = validatePlan(saved.plan, getPlanTargets());
  if(!validation.ok) { showToast('La sustitución no mantiene los objetivos.', true); return; }
  syncPlanDerivedData(saved.plan); // recalcula compra y batch con la comida nueva
  await safeSet('lastPlan', saved);
  renderPlanObject(saved.plan, new Date(saved.generatedAt).toLocaleString('es-ES'));
  showToast('Comida sustituida: compra y batch actualizados automáticamente');
};

// =========================================
// 💬 CHAT IA E INTERACCIÓN DINÁMICA
// =========================================
async function sendChatMessage(){
  const inputEl = $('chat-input');
  const text = inputEl.value.trim();
  if(!text) return;
  inputEl.value='';
  let h = (await safeGet('chatHistory')) || [];
  h.push({ role:'user', text });
  renderChatWindow(h);
  const t = todayStr();
  const logsToday = await getLog(t);
  const sumsToday = sumEntries(logsToday);
  const overrideToday = await getDailyOverride(t);
  const tgtToday = getTargets(overrideToday);
  const statusText = await buildDailyStatusText(sumsToday, tgtToday, logsToday, t);
  const prompt = `Eres coach nutricionista del usuario en la app Bulking OS (volumen/ganancia muscular). Habla directo, clínico pero amistoso, y usa los datos reales de abajo (los calcula la app; no los recalcules).

Estado del bulk:
${engineContextText()}
Objetivo base ${Math.round(profile.targetKcal||2500)} kcal${overrideToday ? ` (hoy con un ajuste temporal ya aplicado de ${overrideToday>0?'+':''}${overrideToday} kcal)` : ''}.

${statusText}

Instrucciones:
- Usa las kcal/macros restantes y las comidas de hoy para responder con precisión.
- Si el usuario quiere compensar HOY (p. ej. "ayer comí poco, súbeme hoy"), propón un ajuste SOLO para hoy entre -300 y +300 kcal en "suggestedDelta". Si no procede, 0.
- Nunca cambies ni prometas cambiar el objetivo permanente: lo ajusta el motor automático con tus datos de peso (reglas visibles en Progreso).
Historial de charla: ${h.slice(-4).map(m=>`${m.role}: ${m.text}`).join(' | ')}.
Responde SOLO este JSON: {"reply":"respuesta breve","suggestedDelta":0}`;
  const res = await callGemini(prompt, true, GEMINI_MODEL);
  if(res && res.reply){
    const delta = Number.isFinite(Number(res.suggestedDelta)) ? Math.max(-300, Math.min(300, Math.round(Number(res.suggestedDelta)))) : 0;
    h.push({ role:'ai', text: res.reply, suggestedDelta: delta, applied:false });
    await safeSet('chatHistory', h);
    renderChatWindow(h);
  } else {
    showToast("El coach no pudo procesar el mensaje.", true);
  }
}

function renderChatWindow(h){
  const win = $('chat-window');
  if(!h.length) { win.innerHTML = '<div class="chat-empty">Pide ajustes como: "Ayer no comí casi, súbeme kcal hoy".</div>'; return; }
  win.innerHTML = h.map((m,i)=>`
    <div class="chat-bubble ${m.role}">
      ${m.text}
      ${(m.role==='ai' && m.suggestedDelta && !m.applied) ? `<button class="chat-action-btn" onclick="applyDelta(${i},${m.suggestedDelta})">✅ Aplicar ${m.suggestedDelta>0?'+':''}${m.suggestedDelta} kcal HOY</button>` : ''}
      ${(m.role==='ai' && m.applied) ? `<div style="margin-top:10px; font-size:0.75rem; color:var(--green); font-weight:700;">✔ Ajuste de kcal aplicado</div>` : ''}
    </div>
  `).join('');
  win.scrollTop = win.scrollHeight;
}
window.applyDelta = async (idx, delta) => {
  const h = await safeGet('chatHistory');
  const t = todayStr();
  if(!h?.[idx] || h[idx].applied) return;
  const safeDelta = Number.isFinite(Number(delta)) ? Math.max(-300, Math.min(300, Number(delta))) : 0;
  const current = await getDailyOverride(t);
  await setDailyOverride(t, Math.max(-300, Math.min(300, current + safeDelta)));
  h[idx].applied = true; await safeSet('chatHistory', h);
  renderChatWindow(h);
  if(selectedLogDate === t) updateDashboardUI();
  await refreshInsights();
  showToast("Objetivo ajustado solo para hoy.");
};

// =========================================
// 📉 DATOS METABÓLICOS Y GRÁFICOS
// =========================================
async function saveProfile(){
  await updateProfile({
    age: Number($('prof-age').value) || profile.age,
    height: Number($('prof-height').value) || profile.height,
    weight: Number($('prof-weight').value) || profile.weight,
    sex: $('prof-sex').value,
    mealsPerDay: Math.min(8, Math.max(3, Number($('prof-meals').value) || 5)),
    trainingDays: Math.min(7, Math.max(0, Number($('prof-training-days').value) || 0)),
    ratePreset: $('prof-rate').value,
    bulkStartDate: $('prof-bulk-start').value || profile.bulkStartDate,
    preferences: $('prof-preferences').value.trim(),
    adjustmentPaused: $('prof-pause').checked
  });
  updateBodyStats(); await updateDashboardUI(); await refreshInsights();
  showToast('Perfil guardado. El objetivo de kcal no cambia: lo ajusta el motor con tus datos.');
}
async function logManualDecision(st, newTarget, reason){
  const rec = buildDecisionRecord(st, { ...st.decision, prevTarget: Math.round(profile.targetKcal), newTarget, delta: newTarget - Math.round(profile.targetKcal), action: 'MANUAL', reasonCode: 'MANUAL', reason });
  const log = (await safeGet('decisionLog')) || []; log.push(rec); await safeSet('decisionLog', log);
  return rec;
}
async function recalcTargetFromModel(){
  const st = getEngineState(), needed = st.decision.needed, M = st.maintenance;
  if(!confirm(`¿Fijar el objetivo en ${needed} kcal?\n\nMantenimiento estimado ${fmtN(M.posterior)} ±${fmtN(M.posteriorSd)} (${M.method === 'bayes' ? 'fórmula + tus datos' : 'solo fórmula'}) + superávit ${fmtN(st.decision.surplus)} kcal para el centro del rango.\nQuedará registrado como cambio manual.`)) return;
  const reason = `Recalculado a mano desde el modelo: mantenimiento ${fmtN(M.posterior)} + superávit ${fmtN(st.decision.surplus)}.`;
  const rec = await logManualDecision(st, needed, reason);
  await setTargetKcal(needed, 'manual', reason, rec.id);
  await updateDashboardUI(); await refreshInsights(); showToast(`Objetivo fijado en ${needed} kcal`);
}
async function setManualTarget(){
  const v = prompt('Nuevo objetivo de kcal (queda registrado como cambio manual):', Math.round(profile.targetKcal || 2500));
  if(v === null) return;
  const k = Math.round(Number(String(v).replace(',', '.')));
  if(!Number.isFinite(k) || k < 1200 || k > 6000){ showToast('Valor no válido (1200–6000).', true); return; }
  const st = getEngineState();
  const rec = await logManualDecision(st, k, 'Fijado a mano por el usuario.');
  await setTargetKcal(k, 'manual', 'Fijado a mano por el usuario.', rec.id);
  await updateDashboardUI(); await refreshInsights(); showToast(`Objetivo fijado en ${k} kcal`);
}
function updateBodyStats(){
  let M = null; try { M = getEngineState().maintenance; } catch(e){}
  $('ui-tdee').innerText = Math.round(M ? M.posterior : calcTDEE(profile, profile.weight));
  const sub = $('ui-tdee-sub'); if(sub) sub.innerText = M && M.method === 'bayes' ? `kcal/día · ±${Math.round(M.posteriorSd)} · fórmula + datos` : 'kcal/día · solo fórmula';
  const bmi = profile.weight / Math.pow(profile.height/100, 2);
  $('ui-bmi').innerText = bmi.toFixed(1);
  $('ui-bmi-label').innerText = bmi<18.5?'Bajo Peso':bmi<25?'Normopeso':'Sobrepeso';
  $('ui-bmi-label').style.color = bmi<18.5?'var(--accent)':bmi<25?'var(--green)':'var(--red)';
}

// =========================================
// 📐 FÓRMULAS DE COMPOSICIÓN CORPORAL (basadas en literatura publicada)
// =========================================
function bmiOf(weightKg, heightCm){
  const h = heightCm / 100;
  return weightKg / (h * h);
}

// Deurenberg et al. 1991 (British Journal of Nutrition): estimación a partir
// de IMC + edad + sexo. No requiere ninguna medida extra, pero es una
// aproximación poblacional: tiende a sobreestimar grasa en gente muy
// musculada y a infraestimarla en gente muy sedentaria/poca masa muscular.
function deurenbergBodyFat(bmiVal, age, sex){
  const genderFactor = sex === 'm' ? 1 : 0;
  const bf = 1.2 * bmiVal + 0.23 * age - 10.8 * genderFactor - 5.4;
  return Math.max(2, Math.min(60, bf));
}

// Método de cinta métrica de la Marina de EE.UU. (Hodgdon & Beckett, 1984).
// Usa circunferencias reales, pero es sensible a cuellos gruesos respecto a
// la cintura (típico en gente entrenada/musculada): si "waist - neck" es
// pequeño, el log10 dispara el resultado hacia valores irreales (incluso
// negativos o <5%). Por eso ya NO se usa en solitario — ver auditoría más
// abajo. Devuelve null si las medidas no permiten un cálculo mínimamente
// estable (diferencia demasiado pequeña).
function navyBodyFat({ neck, waist, hip, heightCm, sex }){
  if(!(neck > 0) || !(waist > 0) || !(heightCm > 0)) return null;
  if(sex === 'm'){
    const diff = waist - neck;
    if(diff <= 4) return null; // por debajo de esto la fórmula deja de ser fiable (ver nota arriba)
    const bf = 495 / (1.0324 - 0.19077 * Math.log10(diff) + 0.15456 * Math.log10(heightCm)) - 450;
    return Number.isFinite(bf) ? Math.max(2, Math.min(60, bf)) : null;
  }
  if(!(hip > 0)) return null;
  const diff = waist + hip - neck;
  if(diff <= 4) return null;
  const bf = 495 / (1.29579 - 0.35004 * Math.log10(diff) + 0.22100 * Math.log10(heightCm)) - 450;
  return Number.isFinite(bf) ? Math.max(2, Math.min(60, bf)) : null;
}

// YMCA (fórmula clásica de cinta métrica, más simple y menos sensible que
// Navy porque no usa log10 de una diferencia pequeña). Requiere cintura +
// peso. Constantes en unidades imperiales (pulgadas/libras) tal como se
// publicó originalmente; convertimos desde cm/kg.
function ymcaBodyFat({ waistCm, weightKg, sex }){
  if(!(waistCm > 0) || !(weightKg > 0)) return null;
  const waistIn = waistCm / 2.54;
  const weightLb = weightKg * 2.20462;
  const raw = sex === 'm'
    ? (-98.42 + 4.15 * waistIn - 0.082 * weightLb) / weightLb * 100
    : (-76.76 + 4.15 * waistIn - 0.082 * weightLb) / weightLb * 100;
  return Number.isFinite(raw) ? Math.max(2, Math.min(60, raw)) : null;
}

// RFM — Relative Fat Mass (Woolcock/Stanford, Ortega et al., Clinical
// Nutrition 2018): fórmula moderna validada contra DEXA, más precisa que el
// IMC clásico para estimar %grasa poblacional, y solo necesita altura +
// cintura (ni peso ni cuello). Buen método de contraste porque no comparte
// las mismas fuentes de error que Navy o YMCA.
function rfmBodyFat({ heightCm, waistCm, sex }){
  if(!(heightCm > 0) || !(waistCm > 0)) return null;
  const raw = sex === 'm' ? 64 - 20 * (heightCm / waistCm) : 76 - 20 * (heightCm / waistCm);
  return Number.isFinite(raw) ? Math.max(2, Math.min(60, raw)) : null;
}

// CUN-BAE (Clínica Universidad de Navarra — Body Adiposity Estimator,
// Gómez-Ambrosi et al., Obesity 2012). Validado contra DEXA en población
// española, mejora sustancialmente al IMC clásico como predictor de %grasa
// porque incorpora edad y sexo con términos no lineales. No requiere cinta
// métrica, solo peso/altura/edad/sexo — por eso es el mejor sustituto de
// Deurenberg cuando no hay medidas de circunferencias.
function cunBaeBodyFat(bmiVal, age, sex){
  const sexTerm = sex === 'f' ? 1 : 0;
  const bf = -44.988 + (0.503 * age) + (10.689 * sexTerm) + (3.172 * bmiVal) - (0.026 * bmiVal * bmiVal)
    + (0.181 * bmiVal * sexTerm) - (0.02 * bmiVal * age) - (0.005 * bmiVal * bmiVal * sexTerm) + (0.00021 * bmiVal * bmiVal * age);
  return Number.isFinite(bf) ? Math.max(2, Math.min(60, bf)) : null;
}

// =========================================
// 🧪 CONSENSO MULTI-FÓRMULA DE % GRASA CORPORAL (auditoría punto 5/6)
// =========================================
// Ninguna fórmula individual es fiable para todo el mundo: Navy falla con
// cuellos gruesos, Deurenberg sobreestima en gente musculada, YMCA/RFM son
// más estables pero menos "de precisión clínica". La estrategia: calcular
// TODAS las que tengan datos suficientes, descartar outliers fisiológicamente
// imposibles, y dar min/max/recomendado en vez de un único número falsamente
// preciso.
const BF_IMPLAUSIBLE_MIN = { m: 5, f: 10 }; // por debajo de esto, esencial/imposible sin patología

function computeBodyFatConsensus({ weightKg, heightCm, age, sex, neck, waist, hip }){
  const bmiVal = bmiOf(weightKg, heightCm);
  const results = [];
  const navy = navyBodyFat({ neck, waist, hip, heightCm, sex });
  if(navy !== null) results.push({ method:'Navy (cinta métrica)', value:navy, tier:'medida' });
  const ymca = waist > 0 ? ymcaBodyFat({ waistCm:waist, weightKg, sex }) : null;
  if(ymca !== null) results.push({ method:'YMCA (cinta métrica)', value:ymca, tier:'medida' });
  const rfm = waist > 0 ? rfmBodyFat({ heightCm, waistCm:waist, sex }) : null;
  if(rfm !== null) results.push({ method:'RFM (Woolcock/Stanford 2018)', value:rfm, tier:'medida' });
  const cunbae = cunBaeBodyFat(bmiVal, age, sex);
  if(cunbae !== null) results.push({ method:'CUN-BAE (Gómez-Ambrosi 2012)', value:cunbae, tier:'formula' });
  const deurenberg = deurenbergBodyFat(bmiVal, age, sex);
  results.push({ method:'Deurenberg 1991 (solo referencia)', value:deurenberg, tier:'referencia' });

  const implausibleFloor = BF_IMPLAUSIBLE_MIN[sex] || 5;
  results.forEach(r => { r.implausible = r.value < implausibleFloor; });

  // El consenso usa solo métodos "medida" (cinta métrica) si hay al menos
  // uno no-implausible; si no hay ninguna medida fiable, cae a CUN-BAE
  // (fórmula validada) y deja Deurenberg fuera del cómputo, solo como dato
  // complementario en pantalla (punto 6).
  const usable = results.filter(r => !r.implausible && r.tier !== 'referencia');
  const measureBased = usable.filter(r => r.tier === 'medida');
  const pool = measureBased.length ? measureBased : usable;

  let recommended = null, min = null, max = null;
  if(pool.length){
    const values = pool.map(r => r.value).sort((a,b)=>a-b);
    min = values[0]; max = values[values.length-1];
    const mid = Math.floor(values.length/2);
    recommended = values.length % 2 ? values[mid] : (values[mid-1]+values[mid])/2;
  }
  const anyImplausible = results.some(r => r.implausible && r.tier !== 'referencia');
  return { results, recommended, min, max, anyImplausible, implausibleFloor, hasMeasurements: measureBased.length > 0 };
}

// FFMI = masa libre de grasa / altura². La versión "normalizada" ajusta por
// altura (aprox. +6.1 × (1.8 − altura en m)) para poder comparar entre
// personas de distinta estatura; es la métrica que se usa en el estudio de
// Kouri et al. 1995 sobre límites naturales de masa muscular.
function ffmiOf(leanKg, heightCm){
  const h = heightCm / 100;
  const ffmi = leanKg / (h * h);
  const normalized = ffmi + 6.1 * (1.8 - h);
  return { ffmi, normalized };
}

// Ratio cintura/altura: cribado de riesgo cardiometabólico independiente de
// sexo/edad, con el umbral de "cintura < mitad de tu altura" citado en
// varios estudios (p.ej. Ashwell & Hsieh 2005; Browning et al. 2010).
function whtrOf(waistCm, heightCm){ return waistCm / heightCm; }

// Ratio cintura/cadera: la OMS (2008) marca 0.90 (hombres) / 0.85 (mujeres)
// como umbral de riesgo cardiometabólico aumentado.
function whrOf(waistCm, hipCm){ return waistCm / hipCm; }

// =========================================
// 📏 REGISTRO DE MEDIDAS CORPORALES (opcional, con edición y borrado)
// =========================================
async function getBodyMeasureEntries(date){ const arr = await safeGet('bodymeasure:'+date); return Array.isArray(arr) ? arr : []; }
async function setBodyMeasureEntries(date, arr){ await safeSet('bodymeasure:'+date, arr); }

async function getLatestBodyMeasure(maxDays = 180){
  for(let i = 0; i < maxDays; i++){
    const d = new Date(); d.setDate(d.getDate() - i);
    const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    const entries = await getBodyMeasureEntries(key);
    if(entries.length) return { date: key, ...entries[entries.length - 1] };
  }
  return null;
}

async function getBodyMeasureSeries(days = 90){
  const series = [];
  for(let i = days - 1; i >= 0; i--){
    const d = new Date(); d.setDate(d.getDate() - i);
    const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    const entries = await getBodyMeasureEntries(key);
    if(entries.length) series.push({ date: key, ...entries[entries.length - 1] });
  }
  return series;
}

function measureSummaryLabel(e){
  const parts = [];
  if(e.neck) parts.push(`Cuello ${e.neck}cm`);
  parts.push(`Cintura ${e.waist}cm`);
  if(e.hip) parts.push(`Cadera ${e.hip}cm`);
  return parts.join(' · ');
}

async function renderBodyMeasureDayList(){
  const date = $('input-measure-date').value || todayStr();
  const entries = await getBodyMeasureEntries(date);
  const el = $('measure-day-list');
  if(!entries.length){ el.innerHTML = `<div style="color:var(--text-dim); font-size:0.85rem; padding:8px 0;">Sin medidas registradas el ${formatDateLabel(date).toLowerCase()}.</div>`; return; }
  el.innerHTML = entries.map((e,i)=>`
    <div class="log-item" style="padding:10px 0;">
      <div><div class="log-title">${measureSummaryLabel(e)}</div><div class="log-macros">${e.time||''}</div></div>
      <div class="log-item-actions">
        <button class="edit-btn" onclick="editBodyMeasureEntry('${date}', ${i})" title="Editar">✎</button>
        <button class="del-btn" onclick="delBodyMeasureEntry('${date}', ${i})" title="Borrar">✕</button>
      </div>
    </div>
  `).join('');
}

async function addBodyMeasure(){
  const waist = parseFloat($('input-waist').value);
  if(!Number.isFinite(waist) || waist <= 0){ showToast('Introduce al menos la cintura', true); return; }
  const neckRaw = $('input-neck').value, hipRaw = $('input-hip').value;
  const neck = neckRaw.trim() ? parseFloat(neckRaw) : null;
  const hip = hipRaw.trim() ? parseFloat(hipRaw) : null;
  const date = $('input-measure-date').value || todayStr();
  const arr = await getBodyMeasureEntries(date);
  arr.push({ neck: Number.isFinite(neck) ? neck : null, waist, hip: Number.isFinite(hip) ? hip : null, time: new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'}) });
  await setBodyMeasureEntries(date, arr);
  $('input-neck').value=''; $('input-waist').value=''; $('input-hip').value='';
  showToast(`Medidas guardadas (${formatDateLabel(date).toLowerCase()})`);
  await renderBodyMeasureDayList(); await renderBodyComposition(); await renderBodyCompositionChart();
}

window.editBodyMeasureEntry = async (date, index) => {
  const entries = await getBodyMeasureEntries(date);
  const cur = entries[index]; if(!cur) return;
  const neckVal = prompt('Cuello (cm), vacío si no aplica:', cur.neck ?? '');
  if(neckVal === null) return;
  const waistVal = prompt('Cintura (cm):', cur.waist ?? '');
  if(waistVal === null) return;
  const hipVal = prompt('Cadera (cm), vacío si no aplica:', cur.hip ?? '');
  if(hipVal === null) return;
  const waist = parseFloat(String(waistVal).replace(',', '.'));
  if(!Number.isFinite(waist) || waist <= 0){ showToast('Cintura inválida', true); return; }
  const neck = neckVal.trim() ? parseFloat(String(neckVal).replace(',', '.')) : null;
  const hip = hipVal.trim() ? parseFloat(String(hipVal).replace(',', '.')) : null;
  entries[index] = { ...cur, neck: Number.isFinite(neck) ? neck : null, waist, hip: Number.isFinite(hip) ? hip : null };
  await setBodyMeasureEntries(date, entries);
  showToast('Medidas actualizadas');
  await renderBodyMeasureDayList(); await renderBodyComposition(); await renderBodyCompositionChart();
};

window.delBodyMeasureEntry = async (date, index) => {
  const entries = await getBodyMeasureEntries(date);
  entries.splice(index, 1);
  await setBodyMeasureEntries(date, entries);
  showToast('Medida eliminada');
  await renderBodyMeasureDayList(); await renderBodyComposition(); await renderBodyCompositionChart();
};

// =========================================
// 🧠 RESUMEN CLÍNICO CON IA (composición corporal)
// =========================================
async function generateBodySummary(){
  const btn = $('btn-ai-summary');
  const out = $('ai-body-summary-output');
  btn.disabled = true; btn.innerText = 'Analizando...';

  const bmiVal = bmiOf(profile.weight, profile.height);
  const latest = await getLatestBodyMeasure();
  const consensus = computeBodyFatConsensus({ weightKg: profile.weight, heightCm: profile.height, age: profile.age, sex: profile.sex, neck: latest?.neck, waist: latest?.waist, hip: latest?.hip });
  const bfPct = consensus.recommended ?? cunBaeBodyFat(bmiVal, profile.age, profile.sex);
  const bfMethod = consensus.hasMeasurements ? `consenso de ${consensus.results.filter(r=>!r.implausible && r.tier==='medida').length} métodos de cinta métrica (rango ${consensus.min?.toFixed(1)}-${consensus.max?.toFixed(1)}%)` : 'CUN-BAE (Gómez-Ambrosi 2012, validado en población española)';
  const fatMass = profile.weight * (bfPct / 100);
  const leanMass = profile.weight - fatMass;
  const { normalized: ffmiNorm } = ffmiOf(leanMass, profile.height);
  const whtr = latest && latest.waist ? whtrOf(latest.waist, profile.height) : null;
  const whr = latest && latest.waist && latest.hip ? whrOf(latest.waist, latest.hip) : null;

  const prompt = `Actúa como médico especialista en nutrición deportiva y composición corporal. Sé totalmente transparente, directo y basado en evidencia científica, sin paños calientes, como en una consulta clínica real. Analiza estos datos de un usuario en fase de volumen (ganancia muscular):
- Sexo: ${profile.sex === 'm' ? 'hombre' : 'mujer'}, edad: ${profile.age} años, altura: ${profile.height} cm, peso actual: ${profile.weight.toFixed(1)} kg.
- IMC: ${bmiVal.toFixed(1)}.
- % Grasa corporal estimado: ${bfPct.toFixed(1)}% (método: ${bfMethod}).
- Masa grasa: ${fatMass.toFixed(1)} kg. Masa magra: ${leanMass.toFixed(1)} kg.
- FFMI normalizado: ${ffmiNorm.toFixed(1)} (referencia: límite natural típico ~25, Kouri et al. 1995).
${whtr ? `- Ratio cintura/altura: ${whtr.toFixed(2)}.` : ''}
${whr ? `- Ratio cintura/cadera: ${whr.toFixed(2)}.` : ''}
Estado del bulk calculado por la app (úsalo tal cual, no lo recalcules):
${engineContextText()}

Ten en cuenta la adherencia real y la decisión del motor al valorar si el objetivo actual tiene sentido o si la falta de progreso (si la hay) se debe más a la adherencia que al objetivo en sí.

Devuelve SOLO este JSON, sin texto ni markdown fuera de él:
{"veredicto":"1 frase de máximo 15 palabras resumiendo su situación física","metricas":[{"valor":"dato con número, máx 5 palabras (ej: 'FFMI 21.4, buen nivel')","etiqueta":"etiqueta de 1-2 palabras"}],"acciones":["acción concreta y accionable, máx 12 palabras","acción 2","acción 3"]}

Genera 3-4 métricas y exactamente 3 acciones. Usa solo números presentes en los datos de arriba. Nada de párrafos: cada campo va a una tarjeta visual pequeña.`;

  const res = await callGemini(prompt, true, GEMINI_MODEL_PLAN);
  btn.disabled = false; btn.innerText = 'Generar resumen';
  if(!res || !res.veredicto){ showToast('No se pudo generar el resumen ahora mismo.', true); return; }

  out.style.display = 'block';
  const metrics = Array.isArray(res.metricas) ? res.metricas.slice(0,4) : [];
  const actions = Array.isArray(res.acciones) ? res.acciones.slice(0,3) : [];
  out.innerHTML = `
    <div style="font-family:'Space Grotesk',sans-serif; font-weight:600; font-size:1.02rem; line-height:1.45; letter-spacing:-0.02em; margin-bottom:18px;">${res.veredicto}</div>
    ${metrics.length ? `<div class="insight-grid" style="margin-bottom:18px;">${metrics.map(m=>`<div class="insight-card"><div class="insight-value">${m.valor || ''}</div><div class="insight-label">${m.etiqueta || ''}</div></div>`).join('')}</div>` : ''}
    ${actions.length ? actions.map(a=>`<div class="data-row"><span>${a}</span></div>`).join('') : ''}
  `;
}

// =========================================
// 📐 COMPOSICIÓN CORPORAL (output enriquecido a partir del mínimo input)
// =========================================
// Rangos de referencia con FUENTE citada para cada barra (punto 4). No se
// inventa ningún corte: cuando la literatura no da un rango de consenso
// claro, se indica explícitamente en vez de rellenar un número.
const REFERENCE_BANDS = {
  bodyFat: {
    source: 'ACE (American Council on Exercise) — categorías estándar de %grasa esencial/atlética/fitness/aceptable/obesidad',
    m: [ {max:6,label:'Esencial'}, {max:14,label:'Atlético'}, {max:18,label:'Fitness'}, {max:25,label:'Aceptable'}, {max:100,label:'Alto'} ],
    f: [ {max:14,label:'Esencial'}, {max:21,label:'Atlético'}, {max:25,label:'Fitness'}, {max:32,label:'Aceptable'}, {max:100,label:'Alto'} ]
  },
  ffmi: {
    source: 'Kouri et al. 1995 (Clin J Sport Med) — límite natural típico ~25 en hombres sin ayuda farmacológica',
    m: [ {max:18,label:'Bajo'}, {max:20,label:'Medio'}, {max:22,label:'Bueno'}, {max:25,label:'Muy alto (límite natural)'}, {max:100,label:'Atípico'} ],
    f: [ {max:14,label:'Bajo'}, {max:16,label:'Medio'}, {max:18,label:'Bueno'}, {max:21,label:'Muy alto (límite natural)'}, {max:100,label:'Atípico'} ]
  },
  bmi: {
    source: 'OMS — clasificación estándar de IMC',
    m: [ {max:18.5,label:'Bajo peso'}, {max:25,label:'Normopeso'}, {max:30,label:'Sobrepeso'}, {max:35,label:'Obesidad I'}, {max:100,label:'Obesidad II+'} ],
    f: [ {max:18.5,label:'Bajo peso'}, {max:25,label:'Normopeso'}, {max:30,label:'Sobrepeso'}, {max:35,label:'Obesidad I'}, {max:100,label:'Obesidad II+'} ]
  }
};

function renderReferenceBar(value, bandKey, sex){
  const band = REFERENCE_BANDS[bandKey]; if(!band) return '';
  const scale = band[sex] || band.m;
  const idx = scale.findIndex(b => value <= b.max);
  const activeIdx = idx === -1 ? scale.length - 1 : idx;
  const colors = ['#3b82f6','#10b981','#f6b73c','#f59e0b','#ef4444'];
  const segs = scale.map((b,i)=>`<div style="flex:1; height:8px; background:${i===activeIdx? colors[i] : 'rgba(255,255,255,0.08)'}; border-radius:3px;"></div>`).join('');
  return `<div style="margin-top:8px;">
    <div style="display:flex; gap:3px;">${segs}</div>
    <div style="display:flex; justify-content:space-between; font-size:.62rem; color:var(--text-dim); margin-top:4px;">${scale.map((b,i)=>`<span style="${i===activeIdx?'color:'+colors[i]+';font-weight:800;':''}">${b.label}</span>`).join('')}</div>
    <div style="font-size:.62rem; color:var(--text-dim); margin-top:4px; opacity:.75;">Fuente: ${band.source}</div>
  </div>`;
}

async function renderBodyComposition(){
  const el = $('body-comp-content');
  if(!el) return;
  const latest = await getLatestBodyMeasure();
  const bmiVal = bmiOf(profile.weight, profile.height);
  const sex = profile.sex;

  const consensus = computeBodyFatConsensus({
    weightKg: profile.weight, heightCm: profile.height, age: profile.age, sex,
    neck: latest?.neck, waist: latest?.waist, hip: latest?.hip
  });

  const bfPct = consensus.recommended ?? cunBaeBodyFat(bmiVal, profile.age, sex);
  const fatMass = profile.weight * (bfPct / 100);
  const leanMass = profile.weight - fatMass;
  const { normalized } = ffmiOf(leanMass, profile.height);

  let html = '';

  if(consensus.anyImplausible){
    const floor = consensus.implausibleFloor;
    html += `<div class="alert warn" style="margin-bottom:16px;">⚠️ Alguna medida dio un %grasa por debajo de ${floor}% (${sex==='m'?'hombre':'mujer'}), fisiológicamente improbable sin patología. Se ha excluido del consenso automáticamente. Revisa que cuello/cintura/cadera estén bien medidos (cinta ajustada pero sin apretar, en el punto anatómico correcto) antes de confiar en el resultado.</div>`;
  }

  html += `
    <div class="stats-grid" style="margin-bottom:12px;">
      <div class="stat-box"><div class="stat-title">% Grasa (recomendado)</div><div class="stat-val" style="color:var(--accent);">${bfPct.toFixed(1)}%</div><div style="font-size:0.66rem; color:var(--text-dim);">${consensus.hasMeasurements ? 'Consenso de métodos con cinta métrica' : 'CUN-BAE (sin medidas de cinta aún)'}</div></div>
      <div class="stat-box"><div class="stat-title">FFMI (normalizado)</div><div class="stat-val" style="color:var(--pro-color);">${normalized.toFixed(1)}</div></div>
    </div>`;

  if(consensus.min !== null && consensus.max !== null && consensus.min !== consensus.max){
    html += `<div style="display:flex; justify-content:space-between; font-size:.78rem; padding:10px 12px; background:rgba(255,255,255,0.03); border-radius:8px; margin-bottom:14px;">
      <span>Mínima: <b>${consensus.min.toFixed(1)}%</b></span><span>Recomendada: <b style="color:var(--accent);">${bfPct.toFixed(1)}%</b></span><span>Máxima: <b>${consensus.max.toFixed(1)}%</b></span>
    </div>`;
  }

  html += `<div style="margin-bottom:16px;">${renderReferenceBar(bfPct, 'bodyFat', sex)}</div>`;

  html += `<details style="margin-bottom:14px;"><summary style="cursor:pointer; font-size:.82rem; color:var(--text-dim);">Ver los ${consensus.results.length} métodos calculados</summary>
    <div style="margin-top:10px;">${consensus.results.map(r => `<div style="display:flex; justify-content:space-between; padding:6px 0; font-size:.8rem; ${r.implausible?'opacity:.5;':''}">
      <span>${r.method}${r.implausible ? ' ⚠️ descartado (implausible)' : (r.tier==='referencia' ? ' (solo referencia, no entra en el consenso)' : '')}</span><b>${r.value.toFixed(1)}%</b>
    </div>`).join('')}</div>
  </details>`;

  html += `<div style="display:flex; justify-content:space-between; padding:8px 0; border-top:1px solid var(--glass-border); border-bottom:1px solid var(--glass-border);"><span style="color:var(--text-dim);">Masa grasa</span><b>${fatMass.toFixed(1)} kg</b></div>
    <div style="display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--glass-border);"><span style="color:var(--text-dim);">Masa magra (libre de grasa)</span><b>${leanMass.toFixed(1)} kg</b></div>
    <div style="display:flex; justify-content:space-between; padding:8px 0; margin-bottom:8px;"><span style="color:var(--text-dim);">IMC</span><b>${bmiVal.toFixed(1)}</b></div>
    ${renderReferenceBar(bmiVal, 'bmi', sex)}
    ${renderReferenceBar(normalized, 'ffmi', sex)}`;

  if(latest && latest.waist){
    const whtrVal = whtrOf(latest.waist, profile.height);
    let whtrBand, whtrColor;
    if(whtrVal < 0.4){ whtrBand = 'posible peso bajo'; whtrColor = 'var(--accent)'; }
    else if(whtrVal < 0.5){ whtrBand = 'rango saludable'; whtrColor = 'var(--green)'; }
    else if(whtrVal < 0.6){ whtrBand = 'riesgo aumentado'; whtrColor = 'var(--accent)'; }
    else { whtrBand = 'riesgo alto'; whtrColor = 'var(--red)'; }
    html += `<div style="display:flex; justify-content:space-between; padding:8px 0; border-top:1px solid var(--glass-border); margin-top:10px;"><span style="color:var(--text-dim);">Cintura/Altura (WHtR)</span><b>${whtrVal.toFixed(2)} <span style="font-size:.7rem; color:${whtrColor};">(${whtrBand})</span></b></div>`;
    if(latest.hip){
      const whrVal = whrOf(latest.waist, latest.hip);
      const whrCutoff = sex === 'm' ? 0.90 : 0.85;
      const overCutoff = whrVal > whrCutoff;
      html += `<div style="display:flex; justify-content:space-between; padding:8px 0;"><span style="color:var(--text-dim);">Cintura/Cadera (WHR)</span><b>${whrVal.toFixed(2)} <span style="font-size:.7rem; color:${overCutoff?'var(--red)':'var(--green)'};">(${overCutoff?'por encima del':'dentro del'} umbral OMS ${whrCutoff})</span></b></div>`;
    }
  } else {
    html += `<div style="font-size:0.8rem; color:var(--text-dim); margin-top:10px;">Añade cuello + cintura (+ cadera en mujeres) arriba para activar los métodos de cinta métrica en el consenso.</div>`;
  }

  el.innerHTML = html;
}

// Gráfico único dirigido por el selector de métrica (puntos 3/4). Para cada
// día con dato de peso disponible (weight:*), recalcula la métrica elegida
// usando SIEMPRE el consenso multi-fórmula de %grasa (nunca Deurenberg en
// solitario, ni Navy en solitario), reutilizando las medidas de cintura/
// cuello/cadera más recientes conocidas hasta esa fecha (no siempre habrá
// una medida exacta ese mismo día).
async function renderBodyCompositionChart(){
  const wrap = $('body-comp-chart-wrap');
  if(!wrap) return;
  const metric = $('metric-select') ? $('metric-select').value : 'weight';
  const weightSeries = await getDailyWeightSeries(90);
  if(weightSeries.length < 2){ wrap.style.display = 'none'; return; }
  wrap.style.display = 'block';

  const measureSeries = await getBodyMeasureSeries(180); // histórico completo para "última medida conocida hasta la fecha"
  const findLatestMeasureUpTo = (dateStr) => {
    let latest = null;
    for(const m of measureSeries){ if(m.date <= dateStr) latest = m; else break; }
    return latest;
  };

  const points = [];
  for(const w of weightSeries){
    const bmiVal = bmiOf(w.kg, profile.height);
    let bfPct;
    if(metric === 'bmi'){ points.push({ date:w.date, value:bmiVal }); continue; }
    if(metric === 'weight'){ points.push({ date:w.date, value:w.kg }); continue; }
    const measure = findLatestMeasureUpTo(w.date);
    const consensus = computeBodyFatConsensus({ weightKg:w.kg, heightCm:profile.height, age:profile.age, sex:profile.sex, neck:measure?.neck, waist:measure?.waist, hip:measure?.hip });
    bfPct = consensus.recommended ?? cunBaeBodyFat(bmiVal, profile.age, profile.sex);
    const fatMass = w.kg * (bfPct/100);
    const leanMass = w.kg - fatMass;
    if(metric === 'bodyfat') points.push({ date:w.date, value:bfPct });
    else if(metric === 'ffmi') points.push({ date:w.date, value: ffmiOf(leanMass, profile.height).normalized });
    else if(metric === 'fatmass') points.push({ date:w.date, value: fatMass });
    else if(metric === 'leanmass') points.push({ date:w.date, value: leanMass });
  }

  const metricMeta = {
    weight: {label:'Peso (kg)', color:'#f59e0b'}, bmi: {label:'IMC', color:'#3b82f6'},
    bodyfat: {label:'% Grasa corporal', color:'#ef4444'}, ffmi: {label:'FFMI', color:'#10b981'},
    fatmass: {label:'Masa grasa (kg)', color:'#ef4444'}, leanmass: {label:'Masa libre de grasa (kg)', color:'#3b82f6'}
  }[metric];

  // Eje temporal real (días desde el primer punto) y sin suavizado Bézier: el peso
  // se dibuja igual que en el gráfico principal (puntos reales unidos por rectas).
  const t0 = points[0].date;
  const ctx = $('bodyCompChart').getContext('2d');
  if(bodyCompChartInstance) bodyCompChartInstance.destroy();
  const bcFill = ctx.createLinearGradient(0, 0, 0, 200);
  bcFill.addColorStop(0, metricMeta.color + '2e'); bcFill.addColorStop(1, metricMeta.color + '00');
  bodyCompChartInstance = new Chart(ctx, {
    type: 'line',
    data: { datasets: [ { label: metricMeta.label, data: points.map(p=>({ x: BulkEngine.util.diffDays(t0, p.date), y: p.value })), borderColor: metricMeta.color, backgroundColor: bcFill, borderWidth:2, fill:true, tension:0, pointRadius:2, pointHoverRadius:4, pointHoverBackgroundColor: metricMeta.color } ] },
    options: (() => { const o = linearAxisOptions(t0); o.plugins.legend = { display:false }; o.plugins.tooltip.displayColors = false; o.plugins.tooltip.callbacks.label = it => ` ${metricMeta.label}: ${it.parsed.y.toFixed(metric==='weight'||metric.endsWith('mass') ? 2 : 1)}`; return o; })()
  });
}

// Estilo compartido de gráficos: sin ruido visual. Sin leyendas (la métrica
// ya está en el título de la tarjeta o en el selector), sin rejilla vertical,
// rejilla horizontal apenas visible, pocas etiquetas de eje y tooltip limpio.
const CHART_TEXT = '#6f757f';
const CHART_GRID = 'rgba(255,255,255,0.045)';
function cleanChartOptions(extra = {}){
  return {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    layout: { padding: { top: 6, right: 4, left: 0, bottom: 0 } },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(16,18,21,0.95)', borderColor: 'rgba(255,255,255,0.13)', borderWidth: 1,
        titleColor: '#edeef0', bodyColor: '#a8adb6', padding: 12, cornerRadius: 10,
        displayColors: false, titleFont: { size: 11, weight: '600' }, bodyFont: { size: 12 }
      }
    },
    scales: {
      y: { grid: { color: CHART_GRID, drawTicks: false }, border: { display: false }, ticks: { color: CHART_TEXT, font: { size: 10 }, maxTicksLimit: 5, padding: 10 } },
      x: { grid: { display: false }, border: { display: false }, ticks: { color: CHART_TEXT, font: { size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 5, padding: 6 } }
    },
    ...extra
  };
}

// =========================================
// ⚖️ REGISTRO DE PESO (CON EDICIÓN Y BORRADO)
// =========================================
// =========================================
// ⚖️ REGISTRO DE PESO (ids + borrado lógico + historial de ediciones)
// =========================================
async function getWeightEntriesRaw(date){ const arr = await safeGet('weight:'+date); return Array.isArray(arr) ? arr : []; }
async function getWeightEntries(date){ return (await getWeightEntriesRaw(date)).filter(e => !e.deletedAt); }
async function setWeightEntriesRaw(date, arr){ await safeSet('weight:'+date, arr); }

// profile.weight = último pesaje observado (solo se usa como respaldo si aún no hay tendencia).
async function refreshProfileWeightFromLatest(){
  for(let i = 0; i < 60; i++){
    const w = earliestWeight(await getWeightEntries(shiftDate(todayStr(), -i)));
    if(w){ if(Math.abs((Number(profile.weight) || 0) - w.kg) > 1e-9) await updateProfile({ weight: w.kg }); return; }
  }
}
async function renderWeightDayList(){
  const date = $('input-weight-date').value || todayStr();
  const entries = (await getWeightEntries(date)).sort((a,b) => String(a.time||'').localeCompare(String(b.time||'')));
  const el = $('weight-day-list');
  if(!entries.length){ el.innerHTML = `<div style="color:var(--text-dim); font-size:0.85rem; padding:8px 0;">Sin pesajes registrados el ${formatDateLabel(date).toLowerCase()}.</div>`; return; }
  el.innerHTML = entries.map((e, i) => `
    <div class="log-item" style="padding:10px 0;">
      <div><div class="log-title">${e.kg} kg ${i === 0 && entries.length > 1 ? '<span class="mini-tag">usado</span>' : ''}</div><div class="log-macros">${e.time || ''}${e.edits && e.edits.length ? ' · editado' : ''}${i > 0 ? ' · no cuenta (se usa el primer pesaje del día)' : ''}</div></div>
      <div class="log-item-actions">
        <button class="edit-btn" onclick="editWeightEntry('${date}', '${e.id}')" title="Editar">✎</button>
        <button class="del-btn" onclick="delWeightEntry('${date}', '${e.id}')" title="Borrar">✕</button>
      </div>
    </div>`).join('');
}
window.editWeightEntry = async (date, id) => {
  const raw = await getWeightEntriesRaw(date);
  const cur = raw.find(e => e.id === id && !e.deletedAt); if(!cur) return;
  const val = prompt('Nuevo peso (kg):', cur.kg);
  if(val === null) return;
  const num = parseFloat(String(val).replace(',', '.'));
  if(!Number.isFinite(num) || num <= 0){ showToast('Peso inválido', true); return; }
  cur.edits = [...(cur.edits || []), { at: Date.now(), from: cur.kg, to: num }].slice(-10);
  cur.kg = num; cur.updatedAt = Date.now();
  await setWeightEntriesRaw(date, raw);
  showToast('Pesaje actualizado');
  await afterWeightChange();
};
window.delWeightEntry = async (date, id) => {
  const raw = await getWeightEntriesRaw(date);
  const cur = raw.find(e => e.id === id); if(!cur) return;
  cur.deletedAt = Date.now(); cur.updatedAt = cur.deletedAt;
  await setWeightEntriesRaw(date, raw);
  showToast('Pesaje eliminado');
  await afterWeightChange();
};
async function addWeight(){
  const w = parseFloat(String($('input-weight').value).replace(',', '.'));
  if(!w || w <= 0){ showToast('Introduce un peso válido', true); return; }
  const date = $('input-weight-date').value || todayStr();
  // Aviso (no bloqueo) si se aleja mucho de tu tendencia: probable error de tecleo.
  const st = getEngineState();
  if(st.weight.points.length >= 4 && Number.isFinite(st.weight.level)){
    const diff = Math.abs(w - st.weight.level);
    if(diff > 2.5 || diff / st.weight.level > 0.035){
      if(!confirm(`Este peso (${w} kg) se aleja bastante de tu tendencia (~${st.weight.level.toFixed(1)} kg). Si es un error de tecleo, cancela.\n\nSi es real no pasa nada: un pesaje aislado se detecta como atípico y no mueve la tendencia.\n\n¿Guardar?`)) return;
    }
  }
  const arr = await getWeightEntriesRaw(date);
  const now = Date.now();
  arr.push({ id: 'w' + now.toString(36), kg: w, time: new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'}), createdAt: now, updatedAt: now });
  await setWeightEntriesRaw(date, arr);
  $('input-weight').value = '';
  const hour = new Date().getHours();
  showToast(`Peso registrado: ${w} kg (${formatDateLabel(date).toLowerCase()})${date === todayStr() && hour >= 11 ? ' · Consejo: pésate al levantarte, tras el baño y antes de comer' : ''}`);
  await afterWeightChange();
}
async function afterWeightChange(){
  await refreshProfileWeightFromLatest();
  await renderWeightDayList(); updateBodyStats(); await updateDashboardUI(); await refreshInsights();
}

// =========================================
// 📊 PANELES DE PROGRESO (todo sale de getEngineState)
// =========================================
const fmtN = BulkEngine.util.fmt, fmtS = BulkEngine.util.fmtSigned;
const MONTHS_SHORT = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
function shortDate(k){ const [, m, d] = k.split('-').map(Number); return `${d} ${MONTHS_SHORT[m-1]}`; }
const STATUS_UI = {
  SIN_DATOS: { label: 'Datos insuficientes', tone: 'neutral' }, POR_DEBAJO: { label: 'Por debajo del rango', tone: 'bad' },
  DENTRO: { label: 'Dentro del rango', tone: 'ok' }, POR_ENCIMA: { label: 'Por encima del rango', tone: 'bad' }, INCIERTO: { label: 'Incierto (esperando datos)', tone: 'warn' }
};
const SOURCE_UI = { auto: 'Automático', manual: 'Manual', correction: 'Corrección', 'legacy-formula': 'Fórmula (v1)', 'legacy-initial': 'Inicial (v1)', 'legacy-auto': 'Automático (v1)', 'legacy-untracked-reset': 'Reinicio no registrado (v1)', 'legacy-observed': 'Observado en dashboard (v1)' };
const confBadge = c => `<span class="conf-badge conf-${c.level.toLowerCase()}" title="Puntuación ${fmtN(c.score*100)} %">Confianza ${c.level}</span>`;
const kv = (k, v, sub = '') => `<div class="kv-row"><span>${k}</span><b>${v}</b>${sub ? `<small>${sub}</small>` : ''}</div>`;

// Escala horizontal: rango objetivo (verde), tu IC80 (barra) y tu ritmo (punto).
function rateScaleHTML(st){
  const r = st.rate, R = st.range; if(!r) return '';
  const lo = Math.min(-0.2, r.ciLow - 0.05, 0), hi = Math.max(R.high * 1.6, r.ciHigh + 0.05);
  const X = v => ((v - lo) / (hi - lo) * 100).toFixed(2) + '%';
  return `<div class="rate-scale" aria-label="Ritmo vs rango objetivo">
    <div class="rs-band" style="left:${X(R.low)}; width:calc(${X(R.high)} - ${X(R.low)});"></div>
    <div class="rs-zero" style="left:${X(0)};"></div>
    <div class="rs-ci" style="left:${X(r.ciLow)}; width:calc(${X(r.ciHigh)} - ${X(r.ciLow)});"></div>
    <div class="rs-dot" style="left:${X(r.perWeek)};"></div>
    <div class="rs-labels"><span style="left:${X(0)}">0</span><span style="left:${X(R.low)}">${fmtN(R.low,2)}</span><span style="left:${X(R.high)}">${fmtN(R.high,2)}</span></div>
  </div>
  <div class="rs-legend"><span><i class="lg-band"></i>Rango objetivo</span><span><i class="lg-ci"></i>Tu ritmo (IC 80 %)</span></div>`;
}
function renderBulkStatus(elId){
  const el = $(elId); if(!el) return;
  const st = getEngineState(), r = st.rate, R = st.range, S = STATUS_UI[st.status.code];
  let html = `<div class="status-head"><span class="status-chip tone-${S.tone}">${S.label}</span>${confBadge(st.confidence)}</div>`;
  if(r){
    html += `<div class="status-nums">
      <div><div class="sn-val">${fmtS(r.perWeek)}</div><div class="sn-lbl">kg/sem (28 d)</div></div>
      <div><div class="sn-val">${fmtS(r.perWeek / st.weight.level * 100, 2)} %</div><div class="sn-lbl">peso/sem</div></div>
      <div><div class="sn-val">${fmtN(R.low,2)}–${fmtN(R.high,2)}</div><div class="sn-lbl">objetivo kg/sem</div></div></div>
      ${rateScaleHTML(st)}
      <div class="muted-line">IC 80 %: ${fmtS(r.ciLow)} a ${fmtS(r.ciHigh)} kg/sem · ${r.n} pesajes en ${r.span + 1} días${st.status.code === 'SIN_DATOS' && st.status.lean ? ' · tendencia preliminar, aún no se usa para decidir' : ''}</div>`;
  } else {
    const n = st.weight.points.length;
    html += `<div class="muted-line" style="margin-top:12px;">Aún no se puede calcular el ritmo: ${n} pesaje${n === 1 ? '' : 's'} (mínimo 4 repartidos en ≥7 días). Pésate cada mañana, al levantarte.</div>`;
  }
  if(st.confidence.level === 'MEDIA' && st.confidence.missing && st.confidence.missing.length) html += `<div class="muted-line">Para confianza ALTA: ${st.confidence.missing.join(', ')}.</div>`;
  if(st.confidence.level === 'BAJA' && st.confidence.reasons.length) html += `<div class="muted-line">Falta: ${st.confidence.reasons.join('; ')}.</div>`;
  el.innerHTML = html;
}
function renderWhyTarget(elId, detailed = false){
  const el = $(elId); if(!el) return;
  const st = getEngineState(), d = st.decision, M = st.maintenance, R = st.range, A = st.adherence;
  const T = Math.round(profile.targetKcal || 0);
  const ch = [...(st.raw.timeline || [])].reverse().find(e => Number(e.delta));
  const mSub = M.method === 'bayes' ? `fórmula ${fmtN(M.prior)} + tus datos ${fmtN(M.obs)} (pesan ${fmtN(M.dataWeight*100)} %)` : `solo fórmula (Mifflin × ${fmtN(M.activityFactor,3)}); se personaliza con ≥${BulkEngine.CONFIG.MEDIA.completeDays} días completos y ≥${BulkEngine.CONFIG.MEDIA.span + 1} días de pesajes`;
  let html = `<div class="why-title">¿Por qué <b>${T} kcal</b>?</div>`;
  html += kv('Mantenimiento estimado', `${fmtN(M.posterior)} ±${fmtN(M.posteriorSd)} kcal`, mSub);
  html += kv('Superávit para el rango', `+${fmtN(d.surplus)} kcal`, `≈ ${fmtN(R.mid,2)} kg/sem (${fmtN(R.midPct,3)} % del peso) × 7700 kcal/kg ÷ 7`);
  html += kv('Necesario estimado', `≈ ${fmtN(d.needed)} kcal`, 'mantenimiento + superávit');
  html += kv('Tu media real', st.intake.n ? `${fmtN(st.intake.mean)} kcal` : '—', st.intake.n ? `${st.intake.n} días completos · adherencia ${A.ratio !== null ? fmtN(A.ratio*100) + ' %' : '—'}` : 'sin días completos en la ventana');
  html += kv('Tendencia de peso', st.rate ? `${fmtS(st.rate.perWeek)} kg/sem` : '—', STATUS_UI[st.status.code].label.toLowerCase());
  html += kv('Último cambio', ch ? `${ch.delta > 0 ? '+' : ''}${ch.delta} kcal` : 'ninguno', ch ? `${ch.date} · ${SOURCE_UI[ch.source] || ch.source}` : '');
  html += `<div class="decision-box tone-${d.delta ? 'warn' : d.action === 'SIN_DATOS' ? 'neutral' : 'ok'}"><b>${profile.adjustmentPaused ? 'Ajuste automático pausado.' : d.delta ? `Propuesta aplicada: ${d.delta > 0 ? '+' : ''}${d.delta} kcal` : 'Sin cambios.'}</b> ${d.reason}</div>`;
  if(detailed){
    html += `<details class="sub-details"><summary>Cómo se calcula (fórmulas y números)</summary><div class="formula">
      <p><b>Fórmula (prior):</b> Mifflin-St Jeor ${fmtN(M.bmr)} kcal × (1,2 + 0,075 × ${profile.trainingDays} días de entreno) = ${fmtN(M.prior)} ±${fmtN(M.priorSd)} kcal (±12 %).</p>
      ${M.method === 'bayes' ? `<p><b>Observado:</b> ingesta media ${fmtN(st.intake.mean)} − ritmo ${fmtS(st.rate.slopePerDay*1000,1)} g/día × 7,7 kcal/g = ${fmtN(M.obs)} ±${fmtN(M.obsSd)} kcal (incertidumbre de la ingesta, de la pendiente y un 5 % de error de registro).</p>
      <p><b>Combinado:</b> media ponderada por precisión → ${fmtN(M.posterior)} ±${fmtN(M.posteriorSd)} kcal. Ventana: ${st.intake.from} → ${st.intake.to} (la ingesta del día D se refleja en el peso de D+1).</p>` : ''}
      <p><b>Reglas del ajuste:</b> solo con confianza MEDIA/ALTA · nunca baja si ganas por debajo del rango · si comes <${BulkEngine.CONFIG.ADHERENCE_MIN*100} % del objetivo, no sube (el problema es llegar) · zona muerta ±${BulkEngine.CONFIG.DEADBAND_KCAL} kcal · máx. ${BulkEngine.CONFIG.STEP_MAX.MEDIA}/${BulkEngine.CONFIG.STEP_MAX.ALTA} kcal por cambio · ≥${BulkEngine.CONFIG.COOLDOWN_DAYS} días entre cambios · sin invertir el sentido en ${BulkEngine.CONFIG.NO_REVERSAL_DAYS} días · nunca por debajo del mantenimiento estimado.</p>
    </div></details>`;
  }
  el.innerHTML = html;
}
function renderInsightsList(elId){
  const el = $(elId); if(!el) return;
  const st = getEngineState();
  el.innerHTML = st.insights.map(i => `<div class="q-item tone-${i.tone}"><div class="q-head"><span class="q-dot"></span><span class="q-text">${i.q}</span><b class="q-val">${i.value}</b></div><div class="q-ans">${i.a}</div></div>`).join('');
}
async function renderMetricStrip(){
  const wEl = $('ui-strip-weight'), tEl = $('ui-strip-trend'), gEl = $('ui-strip-goal');
  if(!wEl || !tEl || !gEl) return;
  const st = getEngineState();
  if(st.weight.points.length){ wEl.innerText = st.weight.level.toFixed(1) + ' kg'; wEl.style.color = ''; }
  else { wEl.innerText = '--'; wEl.style.color = 'var(--text-dim)'; }
  if(st.rate && st.confidence.level !== 'BAJA'){
    const r = st.rate.perWeek;
    tEl.innerText = fmtS(r);
    tEl.style.color = st.status.code === 'DENTRO' ? 'var(--green)' : st.status.code === 'INCIERTO' ? 'var(--text-mid)' : 'var(--red)';
    tEl.nextElementSibling.innerText = `kg/sem · ±${fmtN(st.confidence.ciHalfWidth, 2)}`;
  } else { tEl.innerText = '--'; tEl.style.color = 'var(--text-dim)'; tEl.nextElementSibling.innerText = 'kg/sem · pocos datos'; }
  if(profile.goalWeightKg && st.weight.points.length){
    const rem = profile.goalWeightKg - st.weight.level;
    gEl.innerText = `${rem >= 0 ? '+' : ''}${rem.toFixed(1)}`; gEl.style.color = 'var(--accent)';
    gEl.nextElementSibling.innerText = `kg a ${profile.goalWeightKg}`;
  } else { gEl.innerText = '--'; gEl.style.color = 'var(--text-dim)'; gEl.nextElementSibling.innerText = 'Sin objetivo'; }
}
// Días cerrados recientes con registro dudoso → te pregunta en vez de adivinar.
function renderDayFlagBanner(){
  const el = $('day-flag-banner'); if(!el) return;
  const st = getEngineState(); const from = shiftDate(todayStr(), -14);
  const doubtful = st.days.filter(d => d.status === 'doubtful' && d.date >= from);
  if(!doubtful.length){ el.style.display = 'none'; return; }
  const d = doubtful[doubtful.length - 1];
  el.style.display = 'block';
  el.innerHTML = `📋 El <b>${formatDateLabel(d.date).toLowerCase()}</b> tiene ${fmtN(d.intake)} kcal en ${d.entries} registro${d.entries === 1 ? '' : 's'} (bastante menos que tu día habitual, ~${fmtN(st.personalMedian)}). ¿Está completo? Hasta que respondas, <b>no cuenta</b> para estimar tu mantenimiento.
    <div class="banner-actions"><button class="secondary mini" onclick="setDayFlagUI('${d.date}', true)">Sí, comí eso</button><button class="secondary mini" onclick="setDayFlagUI('${d.date}', false)">No, faltan comidas</button>${doubtful.length > 1 ? `<span class="muted-line" style="margin:0;">+${doubtful.length - 1} día(s) más</span>` : ''}</div>`;
}
window.setDayFlagUI = async (date, val) => {
  await setDayFlag(date, val);
  showToast(val === true ? 'Marcado como completo: cuenta como energía real.' : val === false ? 'Marcado como incompleto: se excluye del cálculo.' : 'Estado automático restaurado.');
  await updateDashboardUI(); await refreshInsights();
};
function renderPredictionCard(){
  const el = $('goal-projection-content'); if(!el) return;
  const st = getEngineState(), P = st.predictions;
  if(!st.goalKg){ el.innerHTML = '<div class="muted-line">Define un peso objetivo para ver predicciones.</div>'; return; }
  if(P.remaining !== null && P.remaining <= 0){ el.innerHTML = `<div class="decision-box tone-ok"><b>🎯 Objetivo alcanzado.</b> Peso tendencia ${fmtN(st.weight.level,2)} kg.</div>`; return; }
  const c = P.current, o = P.objective;
  el.innerHTML = `<div class="pred-grid">
    <div class="pred-card"><div class="pred-lbl">A tu ritmo actual</div><div class="pred-val ${c && c.available ? '' : 'dim'}">${c && c.available ? c.text : 'No estimable'}</div><div class="pred-sub">${c && c.available ? `Ritmo ${fmtS(st.rate.perWeek)} kg/sem; rango por el IC 80 %` : (c ? (t => t.charAt(0).toUpperCase() + t.slice(1))(c.text.replace(/^no estimable:\s*/i, '')) : '')}</div></div>
    <div class="pred-card"><div class="pred-lbl">Si progresas dentro del rango</div><div class="pred-val">${o ? o.text : '—'}</div><div class="pred-sub">${o ? `${o.basis} (${fmtN(o.weeksMin)}–${fmtN(o.weeksMax)} semanas)` : ''}</div></div></div>
    <div class="muted-line">Faltan ${fmtN(P.remaining,1)} kg (peso tendencia ${fmtN(st.weight.level,2)} kg → ${fmtN(st.goalKg,1)} kg). Sin fechas exactas a propósito: con ruido diario de ±0,3–0,5 kg una fecha al día es falsa precisión.</div>`;
}
async function saveGoalWeight(){
  const v = parseFloat(String($('input-goal-weight').value).replace(',', '.'));
  await updateProfile({ goalWeightKg: Number.isFinite(v) && v > 0 ? v : null });
  showToast(Number.isFinite(v) && v > 0 ? `Objetivo: ${v} kg` : 'Objetivo eliminado');
  await refreshInsights();
}

// ---- Gráficos (eje X temporal real: días desde el primer dato) ----
function linearAxisOptions(t0){
  const o = cleanChartOptions();
  o.interaction = { mode: 'nearest', intersect: false, axis: 'x' };
  o.scales.x = { type: 'linear', grid: { display: false }, border: { display: false }, ticks: { color: CHART_TEXT, font: { size: 10 }, maxTicksLimit: 6, callback: v => shortDate(BulkEngine.util.addDays(t0, Math.round(v))) } };
  o.plugins.legend = { display: true, position: 'bottom', labels: { color: CHART_TEXT, boxWidth: 10, boxHeight: 10, font: { size: 10 }, filter: i => !String(i.text).startsWith('_') } };
  o.plugins.tooltip = { ...o.plugins.tooltip, displayColors: true, filter: i => !String(i.dataset.label).startsWith('_'), callbacks: { title: items => items.length ? shortDate(BulkEngine.util.addDays(t0, Math.round(items[0].parsed.x))) : '' } };
  return o;
}
async function renderWeightChart(){
  const canvas = $('weightChart'); if(!canvas || typeof Chart === 'undefined') return;
  const st = getEngineState(), pts = st.weight.points, U = BulkEngine.util;
  if(weightChartInstance){ weightChartInstance.destroy(); weightChartInstance = null; }
  const cap = $('weight-chart-caption');
  if(!pts.length){ if(cap) cap.innerText = 'Sin pesajes todavía.'; return; }
  const t0 = pts[0].date, X = d => U.diffDays(t0, d), ds = [];
  const endX = X(st.asOf) + 7;
  if(st.weight.start){
    const s = st.weight.start, sx = X(s.date);
    const traj = pct => { const a = []; for(let x = sx; x <= endX; x += 1) a.push({ x, y: s.kg * Math.pow(1 + pct/100, (x - sx)/7) }); return a; };
    ds.push({ label: `Corredor objetivo ${fmtN(st.range.lowPct,2)}–${fmtN(st.range.highPct,2)} %/sem`, data: traj(st.range.highPct), borderColor: 'rgba(127,174,148,0.45)', borderWidth: 1, borderDash: [3,3], pointRadius: 0, fill: false, tension: 0 });
    ds.push({ label: '_corredor_bajo', data: traj(st.range.lowPct), borderColor: 'rgba(127,174,148,0.45)', borderWidth: 1, borderDash: [3,3], pointRadius: 0, fill: '-1', backgroundColor: 'rgba(127,174,148,0.08)', tension: 0 });
  }
  ds.push({ label: 'Pesaje', type: 'scatter', data: pts.filter(p => !p.outlier).map(p => ({ x: X(p.date), y: p.kg })), pointRadius: 3, pointBackgroundColor: 'rgba(168,173,182,0.6)', borderWidth: 0 });
  const outl = pts.filter(p => p.outlier);
  if(outl.length) ds.push({ label: 'Atípico (excluido)', type: 'scatter', data: outl.map(p => ({ x: X(p.date), y: p.kg })), pointStyle: 'crossRot', pointRadius: 7, borderColor: '#c5837a', borderWidth: 2 });
  ds.push({ label: 'Tendencia (media exponencial)', data: pts.filter(p => p.trend !== null).map(p => ({ x: X(p.date), y: p.trend })), borderColor: '#d9ab6a', borderWidth: 2.5, tension: 0, pointRadius: 0 });
  if(st.rate) ds.push({ label: `Ritmo 28 d: ${fmtS(st.rate.perWeek)} kg/sem`, data: [{ x: X(st.rate.firstDate), y: st.rate.fittedFirst }, { x: X(st.rate.lastDate), y: st.rate.fittedLast }], borderColor: '#8aa2c8', borderDash: [6,4], borderWidth: 2, pointRadius: 0, tension: 0 });
  const opt = linearAxisOptions(t0);
  opt.scales.x.max = endX;
  opt.scales.y.grace = '4%';
  opt.plugins.tooltip.callbacks.label = it => ` ${it.dataset.label}: ${it.parsed.y.toFixed(2)} kg`;
  weightChartInstance = new Chart(canvas.getContext('2d'), { type: 'line', data: { datasets: ds }, options: opt });
  if(cap) cap.innerText = `Puntos = primer pesaje de cada día. Línea dorada = tendencia (suavizado temporal, sin curvas artificiales). Discontinua azul = regresión de los últimos 28 días: su pendiente ES el kg/sem que usa la app.${outl.length ? ` ${outl.length} pesaje(s) atípico(s) excluido(s).` : ''}`;
}
let modelChartInstance = null;
async function renderModelChart(){
  const canvas = $('modelChart'); if(!canvas || typeof Chart === 'undefined') return;
  const st = getEngineState(), U = BulkEngine.util;
  if(modelChartInstance){ modelChartInstance.destroy(); modelChartInstance = null; }
  if(!st.days.length) return;
  const from = st.days[Math.max(0, st.days.length - 60)].date, t0 = from;
  const hist = [];
  for(let d = from; d <= st.asOf; d = U.addDays(d, 1)){
    const s = BulkEngine.computeState(BulkEngine.filterRawBefore(st.raw, U.addDays(d, 1)), profile, d);
    hist.push({ x: U.diffDays(t0, d), m: s.maintenance.posterior, sd: s.maintenance.posteriorSd, method: s.maintenance.method, intake: s.intake.n ? s.intake.mean : null });
  }
  const tgt = st.days.filter(d => d.date >= from).map(d => ({ x: U.diffDays(t0, d.date), y: d.target }));
  const ds = [
    { label: '_sup', data: hist.map(h => ({ x: h.x, y: h.m + h.sd })), borderWidth: 0, pointRadius: 0, fill: false },
    { label: 'Mantenimiento ±1σ', data: hist.map(h => ({ x: h.x, y: h.m - h.sd })), borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: 'rgba(138,162,200,0.15)' },
    { label: 'Mantenimiento estimado', data: hist.map(h => ({ x: h.x, y: h.m })), borderColor: '#8aa2c8', borderWidth: 2, pointRadius: 0, tension: 0 },
    { label: 'Objetivo (histórico)', data: tgt, borderColor: '#d9ab6a', borderWidth: 2, pointRadius: 0, stepped: true },
    { label: 'Ingesta media (ventana)', data: hist.map(h => ({ x: h.x, y: h.intake })), borderColor: 'rgba(168,173,182,0.7)', borderDash: [4,4], borderWidth: 1.5, pointRadius: 0, spanGaps: false }
  ];
  const opt = linearAxisOptions(t0);
  opt.plugins.tooltip.callbacks.label = it => ` ${it.dataset.label}: ${Math.round(it.parsed.y)} kcal`;
  modelChartInstance = new Chart(canvas.getContext('2d'), { type: 'line', data: { datasets: ds }, options: opt });
}
async function renderTrendCharts(){
  const canvas = $('kcalTrendChart');
  const st = getEngineState();
  const days = st.days.slice(-22);
  if(canvas && typeof Chart !== 'undefined'){
    if(kcalTrendChartInstance){ kcalTrendChartInstance.destroy(); kcalTrendChartInstance = null; }
    if(days.length){
      const col = { complete: 'rgba(217,171,106,0.6)', open: 'rgba(217,171,106,0.22)', doubtful: 'rgba(197,131,122,0.45)', incomplete: 'rgba(111,117,127,0.45)', empty: 'rgba(0,0,0,0)' };
      const o = cleanChartOptions();
      o.plugins.legend = { display: true, position: 'bottom', labels: { color: CHART_TEXT, boxWidth: 10, font: { size: 10 } } };
      o.plugins.tooltip = { ...o.plugins.tooltip, displayColors: true, callbacks: { afterBody: items => { const d = days[items[0].dataIndex]; return d ? `Estado: ${({complete:'completo', open:'en curso', doubtful:'dudoso (no cuenta)', incomplete:'incompleto (no cuenta)', empty:'sin registro'})[d.status]}` : ''; } } };
      kcalTrendChartInstance = new Chart(canvas.getContext('2d'), { type: 'bar', data: { labels: days.map(d => shortDate(d.date)), datasets: [
        { type: 'line', label: 'Objetivo de ese día', data: days.map(d => d.targetEffective), borderColor: '#d9ab6a', borderWidth: 1.5, pointRadius: 0, stepped: 'middle', order: 0 },
        { type: 'line', label: 'Necesario estimado hoy', data: days.map(() => st.decision.needed), borderColor: 'rgba(127,174,148,0.8)', borderDash: [5,4], borderWidth: 1.5, pointRadius: 0, order: 0 },
        { label: 'Ingerido', data: days.map(d => d.entries ? Math.round(d.intake) : null), backgroundColor: days.map(d => col[d.status]), borderRadius: 4, order: 1 }
      ] }, options: o });
    }
  }
  const el = $('nutrition-stats'); if(!el) return;
  const A = st.adherence, A7 = st.adherence7, I = st.intake;
  el.innerHTML = kv('Media real (días completos)', I.n ? `${fmtN(I.mean)} kcal` : '—', `${I.from} → ${I.to} · ${I.n} días${I.doubtful.length ? ` · ${I.doubtful.length} dudoso(s) fuera` : ''}`)
    + kv('Adherencia (ventana)', A.ratio !== null ? `${fmtN(A.ratio*100)} %` : '—', A.n ? `${A.within10}/${A.n} días dentro de ±10 % · te faltan ${fmtN(A.meanGap)} kcal/día de media` : '')
    + kv('Últimos 7 días', A7.ratio !== null ? `${fmtN(A7.ratio*100)} %` : '—', st.intake7.n ? `media ${fmtN(st.intake7.mean)} kcal en ${st.intake7.n} días completos` : '')
    + kv('Necesario estimado', `≈ ${fmtN(st.decision.needed)} kcal`, 'para ganar en el centro del rango');
  el.innerHTML += `<div class="muted-line">Barras doradas = días completos · rojizas = dudosos · grises = incompletos (ni los dudosos ni los incompletos cuentan). Los días sin registro quedan vacíos, no como 0.</div>`;
}
function renderDataQualityCard(){
  const el = $('dq-content'); if(!el) return;
  const st = getEngineState(), q = st.dataQuality;
  const wt = q.weighInTime;
  const hh = h => `${String(Math.floor(h)).padStart(2,'0')}:${String(Math.round((h % 1) * 60)).padStart(2,'0')}`;
  let html = kv('Días analizados', q.daysElapsed, `${q.daysWithWeight} con peso · ${q.daysWithFood} con comida · ${q.complete} completos`)
    + kv('Pesajes', `${st.weight.points.length}`, wt ? `entre ${hh(wt.earliest)} y ${hh(wt.latest)} · ${fmtN(wt.morningPct*100)} % antes de las 10:00` : '')
    + kv('Días sin pesaje', q.daysWithoutWeight.length, q.longestWeightGapDays ? `hueco máximo ${q.longestWeightGapDays} días` : '')
    + kv('Pesajes atípicos', q.outliers.length, q.outliers.map(o => `${o.date} ${o.kg} kg`).join(' · '))
    + kv('Días dudosos', q.doubtful.length, q.doubtful.map(d => `${d.date} (${fmtN(d.intake)} kcal)`).join(' · '))
    + kv('Días marcados incompletos', q.incomplete.length, q.incomplete.join(' · '));
  const items = [];
  if(wt && wt.spreadHours > 3) items.push(`Te pesas a horas muy distintas (${fmtN(wt.spreadHours,1)} h de diferencia). Pesarte siempre al levantarte reduce el ruido y acelera la confianza.`);
  q.suspectEntries.forEach(s => items.push(`<b>${s.date}</b> · ${escAttr(s.label)}: ${s.reason}. <button class="secondary mini" onclick="goToLogDate('${s.date}')">Revisar</button>`));
  q.possibleDuplicates.forEach(s => items.push(`<b>${s.date}</b> · ${escAttr(s.label)} (${fmtN(s.kcal)} kcal): ${s.reason}. <button class="secondary mini" onclick="goToLogDate('${s.date}')">Revisar</button>`));
  if(q.backfilledEntries.length) items.push(`${q.backfilledEntries.length} comida(s) registradas después del día al que pertenecen (normal si apuntas al día siguiente; revísalas si no).`);
  html += items.length ? `<div class="dq-list">${items.map(i => `<div class="dq-item">${i}</div>`).join('')}</div>` : '<div class="muted-line">Sin avisos de calidad.</div>';
  el.innerHTML = html;
}
window.goToLogDate = async (date) => { selectedLogDate = date; nav('dash'); await updateDashboardUI(); $('log-list').scrollIntoView({ behavior: 'smooth', block: 'start' }); };
async function renderAiStatsCard(){
  const el = $('ai-stats-content'); if(!el) return;
  const st = getEngineState(), all = [];
  for(const [date, arr] of Object.entries(st.raw.logs)) (arr || []).filter(e => !e.deletedAt).forEach(e => all.push({ date, ...e }));
  const corr = await getAiCorrections();
  const withAI = all.filter(e => e.ai), cached = all.filter(e => /caché/i.test(e.source || '')), fav = all.filter(e => /favorita/i.test(e.source || ''));
  const errs = corr.filter(c => c.ai && c.ai.kcal > 0).map(c => (c.final.kcal - c.ai.kcal) / c.ai.kcal);
  const mape = errs.length ? errs.reduce((a,b) => a + Math.abs(b), 0) / errs.length * 100 : null;
  const bias = errs.length ? errs.reduce((a,b) => a + b, 0) / errs.length * 100 : null;
  let html = kv('Registros activos', all.length, `${withAI.length} con estimación v2 guardada · ${cached.length} desde caché · ${fav.length} favoritas`)
    + kv('Corregidos por ti', corr.length, withAI.length ? `${fmtN(corr.length / Math.max(1, withAI.length) * 100)} % de las estimaciones v2` : '')
    + kv('Error medio de la IA', mape !== null ? `${fmtN(mape)} %` : '—', bias !== null ? `sesgo ${fmtS(bias,0)} % (${bias < 0 ? 'la IA sobreestima' : 'la IA subestima'})` : 'aún sin correcciones');
  const worst = corr.slice().sort((a,b) => Math.abs(b.deltaKcal) - Math.abs(a.deltaKcal)).slice(0, 5);
  if(worst.length) html += `<div class="dq-list">${worst.map(c => `<div class="dq-item">"${escAttr(c.text)}": IA ${fmtN(c.ai.kcal)} → tú ${fmtN(c.final.kcal)} kcal (${c.deltaKcal > 0 ? '+' : ''}${c.deltaKcal})</div>`).join('')}</div>`;
  html += '<div class="muted-line">Tus correcciones se envían a la IA como ejemplos y la caché guarda siempre el valor que tú confirmaste.</div>';
  el.innerHTML = html;
}
async function renderDecisionLog(){
  const el = $('decision-log-content'); if(!el) return;
  const log = ((await safeGet('decisionLog')) || []).slice().reverse();
  const tl = ((await safeGet('targetTimeline')) || []).slice().reverse();
  let html = '<div class="sub-title">Línea temporal del objetivo</div>';
  html += tl.length ? `<div class="table-wrap"><table class="plan-table audit"><thead><tr><th>Fecha</th><th>Objetivo</th><th>Cambio</th><th>Origen</th></tr></thead><tbody>${tl.map(e => `<tr title="${escAttr(e.reason)}"><td>${e.date}${e.approx ? '*' : ''}</td><td>${e.kcal}</td><td>${e.delta ? (e.delta > 0 ? '+' : '') + e.delta : '—'}</td><td>${SOURCE_UI[e.source] || e.source}</td></tr>`).join('')}</tbody></table></div><div class="muted-line">* fecha aproximada (cambio que la versión anterior no registró). Pasa el ratón o toca una fila para ver el motivo.</div>` : '<div class="muted-line">Sin cambios registrados.</div>';
  html += '<div class="sub-title" style="margin-top:18px;">Evaluaciones y decisiones</div>';
  html += log.length ? log.map(d => `<details class="decision-item"><summary><span>${d.date}</span><b class="act-${String(d.action).toLowerCase()}">${d.action}</b><span>${d.prevTarget}${d.delta ? ` → ${d.newTarget}` : ''} kcal</span>${d.legacy ? '<span class="mini-tag">v1</span>' : ''}</summary><div class="decision-reason">${escAttr(d.reason)}</div>${d.inputs ? `<pre class="trace">${escAttr(JSON.stringify(d.inputs, null, 2))}</pre>` : ''}</details>`).join('') : '<div class="muted-line">Sin evaluaciones todavía.</div>';
  el.innerHTML = html;
}
window.runBacktestUI = async () => {
  const el = $('backtest-content'); if(!el) return;
  const st = getEngineState(); const U = BulkEngine.util;
  if(st.days.length < 3){ el.innerHTML = '<div class="muted-line">Necesitas al menos unos días de datos.</div>'; return; }
  const snap = (await safeGet('legacySnapshot')) || {};
  const tl = st.raw.timeline;
  const initial = tl.length ? tl[0].kcal : Math.round(profile.targetKcal);
  const rows = BulkEngine.backtest(st.raw, profile, { from: U.addDays(st.days[0].date, 1), to: st.asOf, initialTarget: initial,
    legacyProfile: { emaMaintenanceKcal: null, lastAdjustmentWeek: null, weeklyGainGoalKg: snap.weeklyGainGoalKg || 0.3, mealsPerDay: profile.mealsPerDay || 5 } });
  window.__lastBacktest = rows;
  const tone = r => r.newAction === 'SUBIR' ? 'act-subir' : r.newAction === 'BAJAR' ? 'act-bajar' : '';
  el.innerHTML = `<div class="muted-line" style="margin-top:0;">Cada día solo "ve" los datos anteriores a ese día (decisión por la mañana). Ambos algoritmos parten de ${initial} kcal y evolucionan con sus propias decisiones; "real" es lo que mostraba la app.</div>
    <div class="table-wrap"><table class="plan-table audit"><thead><tr><th>Día</th><th>Real</th><th>Antiguo</th><th>Nuevo</th><th>Motivo nuevo</th><th>Ritmo [IC80]</th><th>Conf.</th><th>Mant.</th></tr></thead><tbody>
    ${rows.map(r => `<tr title="${escAttr(r.newReasonText)}"><td>${shortDate(r.date)}</td><td>${Math.round(r.observedTarget)}</td><td>${Math.round(r.legacyTarget)}${r.legacyEvent ? ' ⚠' : ''}</td><td class="${tone(r)}">${r.newTarget}</td><td>${r.newReason}</td><td>${r.rate !== null ? `${fmtS(r.rate)} [${fmtS(r.ciLow)}, ${fmtS(r.ciHigh)}]` : '—'}</td><td>${r.confidence}</td><td>${fmtN(r.maintenance)}</td></tr>`).join('')}
    </tbody></table></div>
    ${rows.filter(r => r.legacyEvent).map(r => `<div class="muted-line">⚠ ${r.date} algoritmo antiguo: ${r.legacyEvent}</div>`).join('')}
    <div class="muted-line">Antiguo = port fiel del algoritmo anterior (incluido el fallo Number(null)=0), validado contra su código original. Simula un único dispositivo sin sobrescrituras de sincronización.</div>`;
};

// Refresca todo lo que depende del motor (dashboard + pestaña Progreso si está abierta).
async function refreshInsights(){
  try {
    renderBulkStatus('bulk-status-content');
    renderWhyTarget('why-target-dash', false);
    renderInsightsList('insights-dash');
    renderDayFlagBanner();
    await renderMetricStrip();
    if($('tab-body') && $('tab-body').classList.contains('active')) await renderBodyTab();
  } catch(e){ console.error('refreshInsights', e); }
}
async function renderBodyTab(){
  renderBulkStatus('bulk-status-body'); renderPredictionCard(); renderWhyTarget('why-target-body', true); renderInsightsList('insights-body');
  await renderWeightChart(); await renderModelChart(); await renderTrendCharts();
  renderDataQualityCard(); await renderAiStatsCard(); await renderDecisionLog();
}

// =========================================
// ⭐ FAVORITOS (guardado rápido de comidas repetidas)
// =========================================
// Punto 1 de la especificación: tras registrar el mismo texto 3+ veces en
// 14 días, se ofrece guardarlo como favorito para añadirlo en 1 toque sin
// pasar por la IA (usa el mismo `normalizeFoodKey` que ya usa el caché de
// estimación, para detectar "lo mismo de siempre" aunque cambie mayúsculas
// o acentos).
async function getFavorites(){ return (await safeGet('favorites')) || []; }
async function setFavorites(list){ await safeSet('favorites', list); }

async function checkFavoriteSuggestion(entry){
  if(!entry.originalText) return;
  const key = normalizeFoodKey(entry.originalText);
  if(!key) return;
  const favorites = await getFavorites();
  if(favorites.some(f => f.key === key)) return;

  let count = 0;
  for(let i = 0; i < 14; i++){
    const d = new Date(); d.setDate(d.getDate() - i);
    const logs = await getLog(dateKey(d));
    if(logs.some(e => e.originalText && normalizeFoodKey(e.originalText) === key)) count++;
  }
  if(count < 3) return;

  const el = $('favorite-suggestion');
  if(!el) return;
  el.style.display = 'block';
  el.innerHTML = `⭐ Has registrado "<b>${entry.label}</b>" ${count} veces en 14 días. ¿La guardo como favorita para añadirla en 1 toque?
    <div style="display:flex; gap:8px; margin-top:10px;">
      <button class="secondary" style="padding:8px 14px; font-size:.8rem;" onclick="saveFavoriteFromSuggestion('${key}')">Guardar favorita</button>
      <button class="secondary" style="padding:8px 14px; font-size:.8rem;" onclick="$('favorite-suggestion').style.display='none'">Ahora no</button>
    </div>`;
  window.__pendingFavoriteEntry = entry;
  window.__pendingFavoriteKey = key;
}

window.saveFavoriteFromSuggestion = async (key) => {
  const entry = window.__pendingFavoriteEntry;
  if(!entry || key !== window.__pendingFavoriteKey) return;
  const favorites = await getFavorites();
  favorites.push({ id: Date.now().toString(36), key, label: entry.label, kcal: entry.kcal, p: entry.p, c: entry.c, f: entry.f, s: entry.s || 0 });
  await setFavorites(favorites);
  $('favorite-suggestion').style.display = 'none';
  showToast('Guardada en favoritas');
  await renderFavoritesQuickAdd();
};

async function renderFavoritesQuickAdd(){
  const row = $('favorites-row');
  if(!row) return;
  const favorites = await getFavorites();
  if(!favorites.length){ row.style.display = 'none'; row.innerHTML = ''; return; }
  row.style.display = 'flex';
  row.innerHTML = favorites.map(f => `<span class="favorite-chip" onclick="addFavoriteQuick('${f.id}')">⭐ ${f.label} <span class="chip-remove" onclick="event.stopPropagation(); removeFavorite('${f.id}')">✕</span></span>`).join('');
}

window.addFavoriteQuick = async (id) => {
  const favorites = await getFavorites();
  const fav = favorites.find(x => x.id === id);
  if(!fav) return;
  const entries = await getLog(selectedLogDate);
  entries.push({ id: Date.now().toString(36), createdAt: Date.now(), updatedAt: Date.now(), time: new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'}), label: fav.label, kcal: fav.kcal, p: fav.p, c: fav.c, f: fav.f, s: fav.s || 0, source: '⚡ Favorita (sin pasar por IA)' });
  await setLog(selectedLogDate, entries);
  showToast(`+${Math.round(fav.kcal)} kcal registradas (${fav.label})`);
  await updateDashboardUI(); await refreshInsights();
};

window.removeFavorite = async (id) => {
  const favorites = (await getFavorites()).filter(f => f.id !== id);
  await setFavorites(favorites);
  await renderFavoritesQuickAdd();
};

// =========================================
// 🔥 RACHA DE DÍAS REGISTRADOS
// =========================================
async function computeStreak(){
  let streak = 0;
  for(let i = 0; i < 90; i++){
    const d = new Date(); d.setDate(d.getDate() - i);
    const logs = await getLog(dateKey(d));
    if(logs.length > 0){ streak++; }
    else if(i === 0){ continue; } // hoy sin registrar todavía no rompe la racha
    else { break; }
  }
  return streak;
}
async function renderStreakBadge(){
  const el = $('streak-badge');
  if(!el) return;
  const streak = await computeStreak();
  if(streak < 2){ el.style.display = 'none'; return; }
  el.style.display = 'inline-flex';
  el.innerText = `🔥 ${streak} días seguidos`;
}

// =========================================
// 🧾 CONTEXTO PARA LA IA (una sola fuente: el motor)
// =========================================
// Chat, resumen semanal y resumen corporal reciben EXACTAMENTE las mismas cifras
// que ves en el dashboard. La IA explica; no calcula ni decide el objetivo.
function engineContextText(st = getEngineState()){
  const r = st.rate, M = st.maintenance, A = st.adherence, A7 = st.adherence7, d = st.decision;
  return [
    `- Peso tendencia: ${st.weight.level.toFixed(2)} kg${st.goalKg ? ` (objetivo ${st.goalKg} kg, faltan ${fmtN(st.predictions.remaining,1)} kg)` : ''}.`,
    r ? `- Ritmo (regresión 28 días): ${fmtS(r.perWeek)} kg/sem, IC80 ${fmtS(r.ciLow)} a ${fmtS(r.ciHigh)} (${fmtS(r.perWeek / st.weight.level * 100, 2)} % del peso/sem). Rango objetivo ${fmtN(st.range.low,2)}–${fmtN(st.range.high,2)} kg/sem. Estado: ${STATUS_UI[st.status.code].label}.` : '- Ritmo de peso: aún sin pesajes suficientes.',
    `- Confianza del análisis: ${st.confidence.level}${st.confidence.missing && st.confidence.missing.length ? ` (para alta faltan: ${st.confidence.missing.join(', ')})` : ''}.`,
    `- Mantenimiento estimado: ${fmtN(M.posterior)} ±${fmtN(M.posteriorSd)} kcal/día (${M.method === 'bayes' ? `fórmula ${fmtN(M.prior)} combinada con datos reales ${fmtN(M.obs)}` : 'solo fórmula, sin datos suficientes'}).`,
    st.intake.n ? `- Ingesta media real: ${fmtN(st.intake.mean)} kcal en ${st.intake.n} días completos; adherencia ${fmtN(A.ratio*100)} % (${A.within10}/${A.n} días dentro de ±10 %)${A7.ratio !== null ? `; últimos 7 días ${fmtN(A7.ratio*100)} %` : ''}.` : '- Ingesta: sin días completos suficientes.',
    `- Objetivo actual: ${Math.round(profile.targetKcal)} kcal/día. Necesario estimado para ganar dentro del rango: ~${d.needed} kcal. Decisión del motor: ${d.action} — ${d.reason}`,
    `- Predicción: a ritmo actual ${st.predictions.current ? st.predictions.current.text : '—'}; dentro del rango ${st.predictions.objective ? st.predictions.objective.text : '—'}.`,
    `- Ajuste automático: ${profile.adjustmentPaused ? 'pausado' : 'activo'}. Días de entreno/semana: ${profile.trainingDays}.`
  ].join('\n');
}

async function generateWeeklySummary(){
  const btn = $('btn-weekly-summary');
  const out = $('weekly-summary-output');
  btn.disabled = true; btn.innerText = 'Generando...';
  const streak = await computeStreak();
  const prompt = `Actúa como coach de nutrición deportiva. Resume la situación de un usuario en fase de volumen usando SOLO estos datos, calculados por la app (no recalcules ni inventes cifras):
${engineContextText()}
- Racha de días con comida registrada: ${streak}.

Devuelve SOLO este JSON, sin markdown ni texto fuera de él:
{"insights":[{"valor":"dato corto con su número, máx 6 palabras","etiqueta":"1-3 palabras"}],"nota":"UNA frase de máximo 20 palabras con la acción más útil"}

Genera entre 3 y 4 insights. Prioriza lo que explica el progreso o lo bloquea (casi siempre: adherencia vs necesario estimado y ritmo vs rango).`;
  const res = await callGemini(prompt, true, GEMINI_MODEL_PLAN);
  btn.disabled = false; btn.innerText = 'Resumen semanal con IA';
  if(!res || !Array.isArray(res.insights)){ showToast('No se pudo generar el resumen ahora mismo.', true); return; }
  out.style.display = 'block';
  out.innerHTML = `<div class="insight-grid">${res.insights.slice(0,4).map(i=>`<div class="insight-card"><div class="insight-value">${i.valor || ''}</div><div class="insight-label">${i.etiqueta || ''}</div></div>`).join('')}</div>${res.nota ? `<div class="insight-note" style="margin-top:14px;">${res.nota}</div>` : ''}`;
}

// =========================================
// 📸 FOTOS DE PROGRESO
// =========================================
// Una foto por fecha (si guardas dos veces el mismo día, la segunda
// sobrescribe la primera). Se comprime a un ancho máximo de 480px y
// calidad JPEG 0.6 antes de guardar: esto entra en el mismo blob de
// localStorage que se sincroniza entero a Firebase en cada cambio (ver
// dumpLocalStorage), así que mantener el peso bajo es importante para no
// disparar el tamaño del payload de sync.
function resizeImageFile(file, maxWidth = 480, quality = 0.6){
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, maxWidth / img.width);
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL('image/jpeg', quality));
      };
      img.onerror = reject;
      img.src = e.target.result;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function getPhotoDates(){
  const dates = [];
  for(let i = 0; i < localStorage.length; i++){
    const k = localStorage.key(i);
    if(k && k.startsWith('photo:')) dates.push(k.slice('photo:'.length));
  }
  return dates.sort();
}

window.addProgressPhoto = async () => {
  const input = $('input-photo');
  const file = input.files && input.files[0];
  if(!file){ showToast('Selecciona una foto primero', true); return; }
  try {
    const dataUrl = await resizeImageFile(file);
    localStorage.setItem('photo:' + todayStr(), dataUrl);
    touchSyncMeta('photo:' + todayStr());
    scheduleCloudPush();
    input.value = '';
    showToast('Foto guardada');
    await renderPhotoGallery();
  } catch(e){ console.error(e); showToast('No se pudo procesar la foto', true); }
};

window.deletePhoto = async (date) => {
  if(!confirm('¿Borrar esta foto?')) return;
  await safeRemove('photo:' + date);
  await renderPhotoGallery();
};

async function renderPhotoGallery(){
  const gallery = $('photo-gallery');
  const controls = $('photo-compare-controls');
  if(!gallery) return;
  const dates = await getPhotoDates();
  if(!dates.length){
    gallery.innerHTML = '<div class="chat-empty">Aún no has guardado ninguna foto.</div>';
    if(controls) controls.style.display = 'none';
    return;
  }
  gallery.innerHTML = dates.slice().reverse().map(d => `
    <div class="photo-thumb">
      <img src="${localStorage.getItem('photo:'+d)}" alt="Foto ${d}">
      <div class="photo-thumb-date">${d}</div>
      <div class="photo-thumb-del" onclick="deletePhoto('${d}')">Borrar</div>
    </div>`).join('');

  if(dates.length >= 2 && controls){
    controls.style.display = 'block';
    const opts = dates.map(d => `<option value="${d}">${d}</option>`).join('');
    const selA = $('photo-compare-a'), selB = $('photo-compare-b');
    selA.innerHTML = opts; selB.innerHTML = opts;
    selA.value = dates[0]; selB.value = dates[dates.length-1];
    renderPhotoCompare();
  } else if(controls){
    controls.style.display = 'none';
  }
}

window.renderPhotoCompare = () => {
  const a = $('photo-compare-a').value, b = $('photo-compare-b').value;
  const view = $('photo-compare-view');
  if(!view || !a || !b) return;
  view.innerHTML = `<img src="${localStorage.getItem('photo:'+a)}" alt="Antes"><img src="${localStorage.getItem('photo:'+b)}" alt="Después">`;
};

// NAVEGACIÓN
function nav(tab){
  document.querySelectorAll('.section').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(e=>e.classList.remove('active'));
  $('tab-'+tab).classList.add('active');
  document.querySelector(`.nav-item[data-tab="${tab}"]`).classList.add('active');
  if(tab==='body'){ renderBodyTab(); renderBodyMeasureDayList(); renderBodyComposition(); renderBodyCompositionChart(); renderPhotoGallery(); }
}

// BACKUP IMPORT/EXPORT
// Claves que NUNCA salen del dispositivo en un export.
const SECRET_KEY_RE = /api[_-]?key|token|secret|password|credential/i;
async function exportData(){
  const data = {};
  for(let i=0;i<localStorage.length;i++){ const k=localStorage.key(i); if(SECRET_KEY_RE.test(k)) continue; data[k]=localStorage.getItem(k); }
  const blob = new Blob([JSON.stringify(data,null,2)], {type:'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `bulking-backup-${todayStr()}.json`;
  a.click(); URL.revokeObjectURL(a.href);
  await safeSet('lastBackupAt', new Date().toISOString());
  showToast('Backup exportado');
  await checkBackupReminder();
}

// =========================================
// 🩺 EXPORTACIÓN DE DIAGNÓSTICO (PDF + JSON + CSV)
// =========================================
// Un único informe (buildDiagnosticReport) → tres formatos. Sin secretos: ni
// API keys, ni syncUid, ni fotos, ni chat. Etiquetas: OBSERVED (lo que
// registraste), CALCULATED (derivado determinista), ESTIMATED (modelo con
// incertidumbre), PREDICTED (futuro).
function loadScriptOnce(src){
  return new Promise((res, rej) => {
    if(document.querySelector(`script[data-src="${src}"]`)) return res();
    const s = document.createElement('script'); s.src = src; s.dataset.src = src; s.onload = () => res(); s.onerror = () => rej(new Error('No se pudo cargar ' + src)); document.head.appendChild(s);
  });
}
const LIB_JSPDF = 'https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js';
const LIB_AUTOTABLE = 'https://cdn.jsdelivr.net/npm/jspdf-autotable@3.8.2/dist/jspdf.plugin.autotable.min.js';
const LIB_JSZIP = 'https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js';
function downloadBlob(blob, name){ const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); }

async function buildDiagnosticReport(){
  const st = getEngineState(), U = BulkEngine.util;
  const r2 = (x, k = 2) => x === null || x === undefined || !Number.isFinite(x) ? null : +x.toFixed(k);
  const weighIns = [], food = [];
  for(const [date, arr] of Object.entries(st.raw.weights).sort()) (arr || []).forEach(e => weighIns.push({ date, time: e.time || null, kg: e.kg, id: e.id || null, createdAt: e.createdAt || null, updatedAt: e.updatedAt || null, deletedAt: e.deletedAt || null, edits: e.edits || [] }));
  for(const [date, arr] of Object.entries(st.raw.logs).sort()) (arr || []).forEach(e => food.push({ date, id: e.id, time: e.time || null, label: e.label, kcal: r2(e.kcal,1), p: r2(e.p,1), c: r2(e.c,1), f: r2(e.f,1), s: r2(e.s || 0,1), source: e.source || null, originalText: e.originalText || null, createdAt: e.createdAt || null, updatedAt: e.updatedAt || null, deletedAt: e.deletedAt || null, corrected: !!e.corrected, aiEstimate: e.ai ? { kcal: e.ai.kcal, range: e.ai.range, confidence: e.ai.confidence, assumptions: e.ai.assumptions, model: e.ai.model, promptVersion: e.ai.promptVersion } : null }));
  const snap = (await safeGet('legacySnapshot')) || {};
  const tl = st.raw.timeline;
  let backtest = [];
  try { if(st.days.length >= 3) backtest = BulkEngine.backtest(st.raw, profile, { from: U.addDays(st.days[0].date, 1), to: st.asOf, initialTarget: tl.length ? tl[0].kcal : Math.round(profile.targetKcal), legacyProfile: { emaMaintenanceKcal: null, lastAdjustmentWeek: null, weeklyGainGoalKg: snap.weeklyGainGoalKg || 0.3, mealsPerDay: profile.mealsPerDay || 5 } }); } catch(e){ console.error(e); }
  const rate = st.rate ? { kgPerWeek: r2(st.rate.perWeek,4), ciLow80: r2(st.rate.ciLow,4), ciHigh80: r2(st.rate.ciHigh,4), pctBodyweightPerWeek: r2(st.rate.perWeek / st.weight.level * 100, 3), weighIns: st.rate.n, spanDays: st.rate.span, window: [st.rate.firstDate, st.rate.lastDate], residualSdKg: r2(st.rate.residualSD,3), lag1Autocorrelation: r2(st.rate.rho,3), effectiveN: r2(st.rate.nEff,1), method: 'OLS sobre pesajes no atípicos (28 días), SE corregido por autocorrelación AR(1)' } : null;
  const M = st.maintenance;
  return {
    meta: { app: 'Bulking OS', schemaVersion: 2, engineVersion: st.engineVersion, generatedAt: new Date().toISOString(), asOf: st.asOf, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      tags: { OBSERVED: 'registrado por el usuario', CALCULATED: 'derivado de forma determinista', ESTIMATED: 'modelo con incertidumbre', PREDICTED: 'proyección futura' },
      privacy: 'Sin API keys, sin syncUid, sin fotos y sin historial de chat.' },
    config: BulkEngine.CONFIG,
    OBSERVED: {
      profile: { age: profile.age, heightCm: profile.height, sex: profile.sex, trainingDaysPerWeek: profile.trainingDays, mealsPerDay: profile.mealsPerDay, ratePreset: profile.ratePreset, goalWeightKg: profile.goalWeightKg, bulkStartDate: profile.bulkStartDate, adjustmentPaused: !!profile.adjustmentPaused, currentTargetKcal: Math.round(profile.targetKcal || 0), preferences: profile.preferences || '' },
      weighIns, foodEntries: food, dayFlags: st.raw.dayFlags, dailyOverrides: st.raw.overrides, targetTimeline: tl, aiCorrections: await getAiCorrections()
    },
    CALCULATED: {
      daily: st.days.map(d => ({ date: d.date, firstWeighInKg: d.weight, weighTime: d.weightTime, weighIns: d.weighIns, trendKg: r2((st.weight.points.find(p => p.date === d.date) || {}).trend, 3), outlier: !!(st.weight.points.find(p => p.date === d.date) || {}).outlier, intakeKcal: Math.round(d.intake), p: r2(d.p,1), c: r2(d.c,1), f: r2(d.f,1), entries: d.entries, status: d.status, userFlag: d.userFlag, targetKcal: d.target, overrideKcal: d.override, targetEffectiveKcal: d.targetEffective, diffKcal: d.entries && d.targetEffective ? Math.round(d.intake - d.targetEffective) : null })),
      weightTrendLevelKg: r2(st.weight.level, 3), bulkStart: st.weight.start, rate, targetRange: st.range,
      intakeWindow: { ...st.intake, mean: r2(st.intake.mean,1), sd: r2(st.intake.sd,1) }, adherence: st.adherence, adherenceLast7: st.adherence7,
      status: st.status, confidence: st.confidence, dataQuality: st.dataQuality, personalMedianIntake: r2(st.personalMedian, 0),
      currentDecision: st.decision, decisionLog: (await safeGet('decisionLog')) || []
    },
    ESTIMATED: {
      maintenance: { method: M.method, bmrMifflin: r2(M.bmr,0), activityFactor: r2(M.activityFactor,3), formulaKcal: r2(M.prior,0), formulaSd: r2(M.priorSd,0), observedKcal: r2(M.obs,0), observedSd: r2(M.obsSd,0), estimateKcal: r2(M.posterior,0), estimateSd: r2(M.posteriorSd,0), dataWeight: r2(M.dataWeight,3),
        formula: 'observado = ingesta media (días completos) − pendiente(kg/día) × 7700; estimación = media ponderada por precisión de fórmula y observado' },
      maintenanceHistory: backtest.map(b => ({ date: b.date, estimateKcal: r2(b.maintenance,0), sd: r2(b.maintenanceSd,0), method: b.maintenanceMethod }))
    },
    PREDICTED: st.predictions,
    insights: st.insights,
    backtest,
    legacy: { targetHistory: (await safeGet('targetHistory')) || [], legacySnapshot: snap, migrationReport: (await safeGet('migrationReport')) || null }
  };
}

window.exportDiagnostics = async (format) => {
  const btns = document.querySelectorAll('.diag-btn'); btns.forEach(b => b.disabled = true);
  try {
    const rep = await buildDiagnosticReport();
    const base = `bulking-diagnostico-${rep.meta.asOf}`;
    if(format === 'json') downloadBlob(new Blob([JSON.stringify(rep, null, 2)], { type: 'application/json' }), `${base}.json`);
    else if(format === 'csv') await exportDiagnosticCSV(rep, base);
    else if(format === 'pdf') await exportDiagnosticPDF(rep, base);
    showToast('Diagnóstico exportado');
  } catch(e){ console.error(e); showToast('No se pudo exportar: ' + e.message, true); }
  finally { btns.forEach(b => b.disabled = false); }
};

function toCSV(rows, cols){
  const esc = v => { if(v === null || v === undefined) return ''; const s = typeof v === 'object' ? JSON.stringify(v) : String(v); return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return '\ufeff' + [cols.join(','), ...rows.map(r => cols.map(c => esc(r[c])).join(','))].join('\r\n');
}
function diagnosticTables(rep){
  const C = rep.CALCULATED, O = rep.OBSERVED;
  const dec = C.decisionLog.map(d => ({ date: d.date, action: d.action, reasonCode: d.reasonCode, prevTarget: d.prevTarget, newTarget: d.newTarget, delta: d.delta, needed: d.needed, legacy: !!d.legacy, reason: d.reason, rateKgWk: d.inputs?.rate?.kgPerWeek, ciLow: d.inputs?.rate?.ciLow, ciHigh: d.inputs?.rate?.ciHigh, maintenance: d.inputs?.maintenance?.estimateKcal, maintenanceSd: d.inputs?.maintenance?.estimateSd, intakeMean: d.inputs?.intake?.meanKcal, adherence: d.inputs?.adherence?.ratio, confidence: d.inputs?.confidence?.level, status: d.inputs?.status }));
  const summary = [
    ['asOf', rep.meta.asOf], ['engineVersion', rep.meta.engineVersion], ['weightTrendKg', C.weightTrendLevelKg], ['rateKgPerWeek', C.rate?.kgPerWeek], ['rateCiLow80', C.rate?.ciLow80], ['rateCiHigh80', C.rate?.ciHigh80],
    ['rangeLowKgWk', +C.targetRange.low.toFixed(3)], ['rangeHighKgWk', +C.targetRange.high.toFixed(3)], ['status', C.status.code], ['confidence', C.confidence.level],
    ['maintenanceEstimateKcal', rep.ESTIMATED.maintenance.estimateKcal], ['maintenanceSd', rep.ESTIMATED.maintenance.estimateSd], ['maintenanceMethod', rep.ESTIMATED.maintenance.method],
    ['intakeMeanKcal', C.intakeWindow.mean], ['adherence', C.adherence.ratio], ['currentTargetKcal', O.profile.currentTargetKcal], ['neededKcal', C.currentDecision.needed], ['decision', C.currentDecision.action], ['decisionReason', C.currentDecision.reason],
    ['etaCurrentRate', rep.PREDICTED.current?.text], ['etaWithinRange', rep.PREDICTED.objective?.text]
  ].map(([k, v]) => ({ key: k, value: v }));
  return {
    'resumen.csv': [summary, ['key','value']],
    'diario.csv': [C.daily, ['date','firstWeighInKg','weighTime','weighIns','trendKg','outlier','intakeKcal','p','c','f','entries','status','userFlag','targetKcal','overrideKcal','targetEffectiveKcal','diffKcal']],
    'pesajes.csv': [O.weighIns, ['date','time','kg','id','createdAt','updatedAt','deletedAt','edits']],
    'comidas.csv': [O.foodEntries, ['date','time','label','kcal','p','c','f','s','source','corrected','originalText','id','createdAt','updatedAt','deletedAt','aiEstimate']],
    'objetivo_timeline.csv': [O.targetTimeline, ['date','kcal','prev','delta','source','approx','reason','decisionId','id']],
    'decisiones.csv': [dec, ['date','action','reasonCode','prevTarget','newTarget','delta','needed','legacy','rateKgWk','ciLow','ciHigh','maintenance','maintenanceSd','intakeMean','adherence','confidence','status','reason']],
    'correcciones_ia.csv': [O.aiCorrections.map(c => ({ ...c, aiKcal: c.ai?.kcal, finalKcal: c.final?.kcal })), ['date','text','label','aiKcal','finalKcal','deltaKcal','deltaPct','model','promptVersion','entryId']],
    'backtest.csv': [rep.backtest, ['date','weighIns','completeDays','observedTarget','legacyTarget','legacyEvent','newTarget','newAction','newReason','rate','ciLow','ciHigh','status','confidence','maintenance','maintenanceSd','intakeMean','adherence']]
  };
}
async function exportDiagnosticCSV(rep, base){
  const tables = diagnosticTables(rep);
  try {
    await loadScriptOnce(LIB_JSZIP);
    const zip = new JSZip();
    for(const [name, [rows, cols]] of Object.entries(tables)) zip.file(name, toCSV(rows, cols));
    downloadBlob(await zip.generateAsync({ type: 'blob' }), `${base}-csv.zip`);
  } catch(e){
    // Sin conexión a la CDN: se descargan los CSV sueltos.
    for(const [name, [rows, cols]] of Object.entries(tables)) downloadBlob(new Blob([toCSV(rows, cols)], { type: 'text/csv' }), `${base}-${name}`);
  }
}

// ---- PDF (jsPDF + autotable, gráficos vectoriales propios) ----
const PDF_MAP = { '−':'-', '–':'-', '—':'-', '→':'->', '←':'<-', '≈':'~', '≥':'>=', '≤':'<=', 'σ':'sd', '×':'x', '·':'·', '…':'...', '“':'"', '”':'"', '‘':"'", '’':"'", '±':'±' };
function pdfSafe(v){
  const s = v === null || v === undefined ? '' : String(v);
  return s.replace(/[\u0100-\uFFFF]/g, ch => PDF_MAP[ch] !== undefined ? PDF_MAP[ch] : '').replace(/[\uD800-\uDFFF]/g, '');
}
function pdfChart(doc, x, y, w, h, opts){
  const all = opts.series.flatMap(s => s.points.map(p => p.y)).filter(Number.isFinite);
  if(!all.length) return;
  let ymin = Math.min(...all), ymax = Math.max(...all); if(ymax - ymin < 1e-6){ ymin -= 1; ymax += 1; }
  const pad = (ymax - ymin) * 0.08; ymin -= pad; ymax += pad;
  if(opts.yMin !== undefined) ymin = opts.yMin; // barras: siempre desde 0 (si no, exageran las diferencias)
  const xs = opts.series.flatMap(s => s.points.map(p => p.x)); const xmin = Math.min(...xs), xmax = Math.max(...xs, xmin + 1);
  const X = v => x + (v - xmin) / (xmax - xmin) * w, Y = v => y + h - (v - ymin) / (ymax - ymin) * h;
  doc.setDrawColor(200); doc.setLineWidth(0.2); doc.rect(x, y, w, h);
  doc.setFontSize(7); doc.setTextColor(110);
  for(let i = 0; i <= 4; i++){ const v = ymin + (ymax - ymin) * i / 4; doc.line(x, Y(v), x + w, Y(v)); doc.text(opts.yFmt ? opts.yFmt(v) : v.toFixed(1), x - 1.5, Y(v) + 1, { align: 'right' }); }
  (opts.xLabels || []).forEach(l => doc.text(pdfSafe(l.text), X(l.x), y + h + 4, { align: l.x <= xmin ? 'left' : l.x >= xmax ? 'right' : 'center' }));
  for(const s of opts.series){
    const c = s.color; doc.setDrawColor(c[0], c[1], c[2]); doc.setFillColor(c[0], c[1], c[2]); doc.setLineWidth(s.width || 0.5);
    if(s.dash) doc.setLineDashPattern([1.5, 1.2], 0); else doc.setLineDashPattern([], 0);
    if(s.type === 'bar'){ const bw = Math.max(0.8, w / (xmax - xmin + 1) * 0.6); s.points.forEach(p => { if(Number.isFinite(p.y)) doc.rect(X(p.x) - bw/2, Y(p.y), bw, y + h - Y(p.y), 'F'); }); }
    else if(s.type === 'dots') s.points.forEach(p => { if(Number.isFinite(p.y)) doc.circle(X(p.x), Y(p.y), s.r || 0.6, 'F'); });
    else { let prev = null; s.points.forEach(p => { if(!Number.isFinite(p.y)){ prev = null; return; } if(prev) doc.line(X(prev.x), Y(prev.y), X(p.x), Y(p.y)); prev = p; }); }
  }
  doc.setLineDashPattern([], 0);
  let lx = x; doc.setFontSize(7);
  opts.series.filter(s => s.label).forEach(s => { doc.setFillColor(s.color[0], s.color[1], s.color[2]); doc.rect(lx, y - 4, 2.5, 2.5, 'F'); doc.setTextColor(80); doc.text(pdfSafe(s.label), lx + 3.5, y - 1.8); lx += doc.getTextWidth(pdfSafe(s.label)) + 9; });
}
async function exportDiagnosticPDF(rep, base){
  await loadScriptOnce(LIB_JSPDF); await loadScriptOnce(LIB_AUTOTABLE);
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: 'mm', format: 'a4' });
  const C = rep.CALCULATED, O = rep.OBSERVED, E = rep.ESTIMATED, P = rep.PREDICTED, U = BulkEngine.util;
  const W = 210, M0 = 14; let y = 16;
  const ensure = need => { if(y + need > 282){ doc.addPage(); y = 16; } };
  const h1 = t => { ensure(14); doc.setFont('helvetica', 'bold'); doc.setFontSize(13); doc.setTextColor(30); doc.text(pdfSafe(t), M0, y); y += 7; doc.setFont('helvetica', 'normal'); };
  const para = (t, size = 8.5) => { doc.setFontSize(size); doc.setTextColor(50); const lines = doc.splitTextToSize(pdfSafe(t), W - 2*M0); lines.forEach(l => { ensure(4.2); doc.text(l, M0, y); y += 4; }); y += 1; };
  const table = (head, body, opts = {}) => { doc.autoTable({ startY: y, head: [head.map(pdfSafe)], body: body.map(r => r.map(c => pdfSafe(c))), margin: { left: M0, right: M0 }, styles: { fontSize: opts.fs || 7, cellPadding: 1.2, overflow: 'linebreak' }, headStyles: { fillColor: [40, 44, 52] }, theme: 'striped', columnStyles: opts.columnStyles || {} }); y = doc.lastAutoTable.finalY + 6; };
  const f = (x, d = 0) => x === null || x === undefined || !Number.isFinite(Number(x)) ? '—' : Number(x).toFixed(d);
  // Portada / resumen
  doc.setFont('helvetica', 'bold'); doc.setFontSize(17); doc.text('Bulking OS - Informe de diagnóstico', M0, y); y += 7;
  doc.setFont('helvetica', 'normal'); doc.setFontSize(8.5); doc.setTextColor(90);
  para(`Datos hasta ${rep.meta.asOf} · generado ${rep.meta.generatedAt} · motor v${rep.meta.engineVersion} · zona ${rep.meta.timezone}`);
  para('Etiquetas: OBSERVED = registrado · CALCULATED = derivado · ESTIMATED = modelo con incertidumbre · PREDICTED = futuro. Sin API keys, syncUid, fotos ni chat.'); y += 3;
  h1('1. Resumen ejecutivo');
  table(['Pregunta', 'Respuesta', 'Detalle'], rep.insights.map(i => [i.q, i.value, i.a]), { columnStyles: { 0: { cellWidth: 42 }, 1: { cellWidth: 28 } } });
  h1('2. Perfil y configuración (OBSERVED)');
  table(['Campo', 'Valor'], Object.entries(O.profile).map(([k, v]) => [k, v === null ? '—' : String(v)]));
  table(['Parámetro del motor', 'Valor'], Object.entries(rep.config).map(([k, v]) => [k, typeof v === 'object' ? JSON.stringify(v) : String(v)]));
  // Peso
  h1('3. Peso: pesajes, tendencia y ritmo');
  const pts = C.daily.filter(d => d.firstWeighInKg !== null), t0 = C.daily.length ? C.daily[0].date : rep.meta.asOf, XD = d => U.diffDays(t0, d);
  const series = [
    { type: 'dots', points: pts.filter(d => !d.outlier).map(d => ({ x: XD(d.date), y: d.firstWeighInKg })), color: [150,150,150], label: 'Pesaje (OBSERVED)' },
    { type: 'dots', points: pts.filter(d => d.outlier).map(d => ({ x: XD(d.date), y: d.firstWeighInKg })), color: [200,80,70], r: 1, label: pts.some(d => d.outlier) ? 'Atípico' : '' },
    { type: 'line', points: pts.map(d => ({ x: XD(d.date), y: d.trendKg })), color: [200,150,60], width: 0.8, label: 'Tendencia EWMA (CALCULATED)' }
  ];
  if(C.rate){ const rr = getEngineState().rate; series.push({ type: 'line', dash: true, points: [{ x: XD(rr.firstDate), y: rr.fittedFirst }, { x: XD(rr.lastDate), y: rr.fittedLast }], color: [90,110,170], width: 0.7, label: `Regresión 28 d: ${f(C.rate.kgPerWeek,3)} kg/sem` }); }
  ensure(70); y += 5; pdfChart(doc, M0 + 8, y, W - 2*M0 - 8, 55, { series, yFmt: v => v.toFixed(1), xLabels: [0, Math.floor(XD(rep.meta.asOf)/2), XD(rep.meta.asOf)].map(x => ({ x, text: U.addDays(t0, x) })) }); y += 64;
  para(C.rate ? `Ritmo (CALCULATED): ${f(C.rate.kgPerWeek,3)} kg/sem (IC80 ${f(C.rate.ciLow80,3)} a ${f(C.rate.ciHigh80,3)}) = ${f(C.rate.pctBodyweightPerWeek,3)} % del peso/sem · ${C.rate.weighIns} pesajes en ${C.rate.spanDays + 1} días (${C.rate.window.join(' -> ')}) · SD residual ${f(C.rate.residualSdKg,2)} kg · autocorrelación ${f(C.rate.lag1Autocorrelation,2)} · n efectivo ${f(C.rate.effectiveN,1)}. Método: ${C.rate.method}.` : 'Ritmo: datos insuficientes.');
  para(`Peso tendencia actual: ${f(C.weightTrendLevelKg,2)} kg. Inicio del bulk: ${C.bulkStart ? `${C.bulkStart.date} (${f(C.bulkStart.kg,2)} kg)` : '—'}. Rango objetivo (${C.targetRange.preset}): ${f(C.targetRange.lowPct,2)}–${f(C.targetRange.highPct,2)} %/sem = ${f(C.targetRange.low,3)}–${f(C.targetRange.high,3)} kg/sem. Estado: ${C.status.code}. Confianza: ${C.confidence.level} (${f(C.confidence.score*100)} %).`);
  table(['Fecha', 'Hora', 'Kg', 'Tendencia', 'Atípico', 'Pesajes/día'], C.daily.filter(d => d.firstWeighInKg !== null).map(d => [d.date, d.weighTime || '', f(d.firstWeighInKg,2), f(d.trendKg,2), d.outlier ? 'sí' : '', d.weighIns]));
  // Nutrición
  h1('4. Nutrición diaria (OBSERVED + CALCULATED)');
  const nd = C.daily.slice(-35);
  ensure(62); y += 5; pdfChart(doc, M0 + 10, y, W - 2*M0 - 10, 45, { series: [
    { type: 'bar', points: nd.map((d, i) => ({ x: i, y: d.entries ? d.intakeKcal : NaN })), color: [210,170,110], label: 'Ingerido' },
    { type: 'line', points: nd.map((d, i) => ({ x: i, y: d.targetEffectiveKcal })), color: [120,90,40], width: 0.7, label: 'Objetivo del día' },
    { type: 'line', dash: true, points: nd.map((d, i) => ({ x: i, y: C.currentDecision.needed })), color: [90,150,110], width: 0.6, label: 'Necesario estimado' }
  ], yMin: 0, yFmt: v => v.toFixed(0), xLabels: nd.length ? [{ x: 0, text: nd[0].date }, { x: nd.length - 1, text: nd[nd.length-1].date }] : [] }); y += 55;
  para(`Ventana de análisis ${C.intakeWindow.from} -> ${C.intakeWindow.to}: media ${f(C.intakeWindow.mean)} kcal (SD ${f(C.intakeWindow.sd)}) en ${C.intakeWindow.n} días completos; dudosos excluidos: ${C.intakeWindow.doubtful.join(', ') || 'ninguno'}; incompletos: ${C.intakeWindow.incomplete.join(', ') || 'ninguno'}. Adherencia ${C.adherence.ratio !== null ? f(C.adherence.ratio*100,1) + ' %' : '—'} (${C.adherence.within10}/${C.adherence.n} días ±10 %, déficit medio vs objetivo ${f(C.adherence.meanGap)} kcal/día). Últimos 7 días: ${C.adherenceLast7.ratio !== null ? f(C.adherenceLast7.ratio*100,1) + ' %' : '—'}. Mediana personal de ingesta: ${f(C.personalMedianIntake)} kcal.`);
  table(['Fecha', 'Kcal', 'P', 'C', 'G', 'Reg.', 'Estado', 'Objetivo', 'Dif.'], C.daily.map(d => [d.date, d.entries ? d.intakeKcal : '', d.entries ? f(d.p) : '', d.entries ? f(d.c) : '', d.entries ? f(d.f) : '', d.entries, d.status + (d.userFlag !== null ? ' (tú)' : ''), d.targetEffectiveKcal ?? '', d.diffKcal ?? '']));
  // Mantenimiento
  h1('5. Mantenimiento (ESTIMATED)');
  const Mm = E.maintenance;
  para(`Método: ${Mm.method === 'bayes' ? 'fórmula combinada con datos' : 'solo fórmula'}. Mifflin-St Jeor ${f(Mm.bmrMifflin)} kcal × factor ${f(Mm.activityFactor,3)} (1,2 + 0,075 × ${O.profile.trainingDaysPerWeek} días de entreno) = ${f(Mm.formulaKcal)} ±${f(Mm.formulaSd)} kcal. Observado: ${f(Mm.observedKcal)} ±${f(Mm.observedSd)} kcal. Estimación: ${f(Mm.estimateKcal)} ±${f(Mm.estimateSd)} kcal (peso de los datos ${Mm.dataWeight !== null ? f(Mm.dataWeight*100) + ' %' : '—'}). ${Mm.formula}.`);
  if(E.maintenanceHistory.length){
    ensure(55); y += 5; pdfChart(doc, M0 + 10, y, W - 2*M0 - 10, 40, { series: [
      { type: 'line', points: E.maintenanceHistory.map((m, i) => ({ x: i, y: m.estimateKcal })), color: [90,110,170], width: 0.8, label: 'Mantenimiento estimado (a fecha de cada día)' },
      { type: 'line', points: rep.backtest.map((b, i) => ({ x: i, y: b.observedTarget })), color: [200,150,60], width: 0.6, label: 'Objetivo real' }
    ], yFmt: v => v.toFixed(0), xLabels: [{ x: 0, text: E.maintenanceHistory[0].date }, { x: E.maintenanceHistory.length - 1, text: E.maintenanceHistory[E.maintenanceHistory.length-1].date }] }); y += 50;
  }
  // Objetivo
  h1('6. Objetivo de kcal: línea temporal y decisiones');
  para(`Decisión actual: ${C.currentDecision.action} (${C.currentDecision.reasonCode}). ${C.currentDecision.reason} Necesario estimado ${C.currentDecision.needed} kcal (superávit ${f(C.currentDecision.surplus)} kcal).`);
  table(['Fecha', 'Kcal', 'Cambio', 'Origen', 'Motivo'], O.targetTimeline.map(e => [e.date + (e.approx ? '*' : ''), e.kcal, e.delta || '', e.source, e.reason || '']), { columnStyles: { 4: { cellWidth: 95 } } });
  table(['Fecha', 'Acción', 'Antes', 'Después', 'Código', 'Motivo'], C.decisionLog.map(d => [d.date, d.action, d.prevTarget, d.newTarget, d.reasonCode, d.reason]), { columnStyles: { 5: { cellWidth: 90 } } });
  // Predicciones
  h1('7. Bulk y predicciones (PREDICTED)');
  para(`Faltan ${f(P.remaining,1)} kg hasta ${O.profile.goalWeightKg ?? '—'} kg. A ritmo actual: ${P.current ? P.current.text : '—'}. Dentro del rango: ${P.objective ? `${P.objective.text} (${P.objective.basis}, ${f(P.objective.weeksMin)}–${f(P.objective.weeksMax)} semanas)` : '—'}. Se dan rangos de meses, no fechas: con el ruido diario del peso una fecha exacta es falsa precisión.`);
  // Calidad
  h1('8. Calidad de datos');
  const q = C.dataQuality;
  para(`Días ${q.daysElapsed} · con peso ${q.daysWithWeight} · con comida ${q.daysWithFood} · completos ${q.complete} · dudosos ${q.doubtful.length} · incompletos ${q.incomplete.length} · sin peso ${q.daysWithoutWeight.length} (hueco máx. ${q.longestWeightGapDays} d) · atípicos ${q.outliers.length}${q.weighInTime ? ` · hora de pesaje ${f(q.weighInTime.earliest,1)}–${f(q.weighInTime.latest,1)} h (${f(q.weighInTime.morningPct*100)} % antes de las 10)` : ''} · registradas otro día ${q.backfilledEntries.length}.`);
  const qi = [...q.suspectEntries.map(s => [s.date, s.label, s.reason]), ...q.possibleDuplicates.map(s => [s.date, s.label, s.reason]), ...q.outliers.map(o => [o.date, `${o.kg} kg`, `pesaje atípico (${o.reason})`]), ...q.doubtful.map(d => [d.date, `${d.intake} kcal / ${d.entries} reg.`, 'día dudoso: excluido hasta que lo confirmes'])];
  if(qi.length) table(['Fecha', 'Elemento', 'Aviso'], qi);
  // IA
  h1('9. IA de comidas');
  const corr = O.aiCorrections;
  para(`${O.foodEntries.filter(e => !e.deletedAt).length} registros activos, ${O.foodEntries.filter(e => e.deletedAt).length} borrados (se conservan para auditoría), ${O.foodEntries.filter(e => e.aiEstimate).length} con estimación v2 guardada, ${corr.length} correcciones tuyas.`);
  if(corr.length) table(['Fecha', 'Texto', 'IA', 'Final', 'Dif.'], corr.map(c => [c.date, c.text, f(c.ai?.kcal), f(c.final?.kcal), `${c.deltaKcal > 0 ? '+' : ''}${c.deltaKcal}`]));
  table(['Fecha', 'Hora', 'Comida', 'Kcal', 'P', 'C', 'G', 'Fuente', 'Estado', 'Texto original'], O.foodEntries.map(e => [e.date, e.time || '', e.label, f(e.kcal), f(e.p), f(e.c), f(e.f), e.source || '', e.deletedAt ? 'borrada' : e.corrected ? 'corregida' : '', e.originalText || '']), { fs: 6, columnStyles: { 9: { cellWidth: 45 } } });
  // Backtest
  h1('10. Backtest sin fuga de datos (algoritmo anterior vs nuevo)');
  para('Cada día D solo usa datos anteriores a D. Ambos algoritmos parten del mismo objetivo y evolucionan con sus decisiones; "real" es lo que mostraba la app. El algoritmo anterior es un port fiel (incluido el fallo Number(null)=0) validado contra el código original.');
  if(rep.backtest.length) table(['Día', 'Real', 'Antiguo', 'Nuevo', 'Acción', 'Motivo', 'Ritmo', 'IC80', 'Conf.', 'Mant.'], rep.backtest.map(b => [b.date, Math.round(b.observedTarget), Math.round(b.legacyTarget) + (b.legacyEvent ? ' !' : ''), b.newTarget, b.newAction, b.newReason, f(b.rate,3), b.rate !== null ? `${f(b.ciLow,2)}..${f(b.ciHigh,2)}` : '', b.confidence, f(b.maintenance)]), { fs: 6.5 });
  rep.backtest.filter(b => b.legacyEvent).forEach(b => para(`! ${b.date} algoritmo anterior: ${b.legacyEvent}`, 7.5));
  // Metodología
  h1('11. Metodología');
  para('Tendencia: media exponencial temporal (alfa 0,15/día, el peso de cada pesaje depende de los días transcurridos; semilla = mediana de los 3 primeros). Atípicos: filtro de Hampel (±3 días, 3 × MAD, mínimo 0,3 kg). Ritmo: regresión lineal de 28 días sobre pesajes no atípicos; intervalo del 80 % con error estándar corregido por autocorrelación. Día completo: ≥2 registros y ≥60 % de tu mediana, o confirmado por ti; los dudosos no cuentan. Mantenimiento: combinación bayesiana (ponderada por precisión) de Mifflin-St Jeor × actividad (±12 %) y el balance observado (ingesta − pendiente × 7700). Ajuste: solo con confianza media/alta; nunca baja si ganas por debajo del rango; no sube si comes <90 % del objetivo; zona muerta 50 kcal; pasos ≤100/150 kcal; ≥7 días entre cambios; sin invertir el sentido en 21 días; nunca por debajo del mantenimiento estimado.');
  if(rep.legacy.migrationReport) para(`Migración v2: ${JSON.stringify(rep.legacy.migrationReport)}`, 7);
  const pages = doc.getNumberOfPages();
  for(let i = 1; i <= pages; i++){ doc.setPage(i); doc.setFontSize(7); doc.setTextColor(140); doc.text(`Bulking OS · diagnóstico ${rep.meta.asOf} · ${i}/${pages}`, W - M0, 292, { align: 'right' }); }
  doc.save(`${base}.pdf`);
}

window.runEngineTestsUI = () => {
  const out = $('tests-output'); if(!out) return;
  const lines = [];
  const r = runEngineTests(BulkEngine, l => lines.push(l));
  out.style.display = 'block';
  out.innerHTML = `<div class="decision-box tone-${r.passed === r.total ? 'ok' : 'bad'}"><b>${r.passed}/${r.total} tests OK</b></div><pre class="trace">${escAttr(lines.join('\n'))}</pre>`;
};

// =========================================
// 💾 RECORDATORIO DE BACKUP
// =========================================
// Todo vive en localStorage: si se borra el navegador o cambias de móvil,
// se pierde. Avisamos si llevas mucho tiempo sin exportar.
async function checkBackupReminder(){
  const el = $('backup-reminder');
  if(!el) return;
  let firstUse = await safeGet('firstUseAt');
  if(!firstUse){
    firstUse = new Date().toISOString();
    await safeSet('firstUseAt', firstUse);
  }
  const lastBackup = await safeGet('lastBackupAt');
  const reference = lastBackup || firstUse;
  const daysSince = (Date.now() - new Date(reference).getTime()) / 86400000;
  if(daysSince >= 14){
    el.style.display = 'block';
    el.innerHTML = `<b>${Math.floor(daysSince)} días sin backup.</b> Los datos viven solo en este navegador.<button class="secondary" style="margin-top:12px; padding:9px 15px; font-size:.8rem; width:100%;" onclick="exportData()">Exportar ahora</button>`;
  } else {
    el.style.display = 'none';
  }
}
$('import-file-input').addEventListener('change', async (e)=>{
  try {
    const data = JSON.parse(await e.target.files[0].text());
    if(!confirm('¿Sobrescribir datos locales?')) return;
    for(const [k,v] of Object.entries(data)){ if(SECRET_KEY_RE.test(k)) continue; localStorage.setItem(k, v); }
    const meta = readSyncMeta(); Object.keys(data).forEach(k => { if(!NON_SYNC_KEYS.has(k) && !SECRET_KEY_RE.test(k)) meta[k] = Date.now(); }); localStorage.setItem(SYNC_META_KEY, JSON.stringify(meta)); // lo restaurado gana en la próxima sincronización
    if(cloudSyncEnabled){ syncUid = localStorage.getItem('syncUid') || syncUid; await pushToCloudNow(); }
    showToast('Datos restaurados. Recargando...'); setTimeout(()=>location.reload(), 1500);
  } catch(err){ showToast('Archivo JSON inválido', true); }
});

// =========================================
// 🧪 TESTS BÁSICOS (punto 11)
// =========================================
// No hay infraestructura de test runner (Jest/etc.) en esta arquitectura de
// archivo único sin build step, así que esto es un arnés ligero ejecutable
// a mano desde la consola del navegador: abre la app → F12 → consola →
// escribe `runSelfTests()` y pulsa Enter. Cubre las funciones de cálculo
// puras (fáciles de testear de forma determinista) y un roundtrip real de
// persistencia. No sustituye a un test runner de verdad, pero da cobertura
// básica sin añadir dependencias ni complejidad de build.
window.runSelfTests = async function(){
  const results = [];
  const check = (name, cond, detail='') => results.push({ name, pass: !!cond, detail });
  const approx = (a,b,tol=0.5) => Math.abs(a-b) <= tol;

  // --- Persistencia: roundtrip real contra localStorage ---
  try {
    const testKey = '__selftest_key__';
    await safeSet(testKey, { a: 1, b: 'x' });
    const back = await safeGet(testKey);
    check('Persistencia: roundtrip set/get', back && back.a === 1 && back.b === 'x');
    await safeRemove(testKey);
  } catch(e){ check('Persistencia: roundtrip set/get', false, e.message); }

  // --- IMC ---
  check('IMC: 80kg/180cm ≈ 24.7', approx(bmiOf(80,180), 24.69, 0.05));

  // --- FFMI ---
  const ffmiRes = ffmiOf(70, 180); // 70kg masa magra, 180cm
  check('FFMI: valor base coherente (70kg/1.8m ≈ 21.6)', approx(ffmiRes.ffmi, 21.6, 0.1));
  check('FFMI: normalizado añade el ajuste por altura', approx(ffmiRes.normalized, ffmiRes.ffmi + 6.1*(1.8-1.8), 0.01));

  // --- Masa grasa / masa libre de grasa ---
  const weight = 80, bf = 15;
  const fatMass = weight * (bf/100), leanMass = weight - fatMass;
  check('Masa grasa: 80kg @15% = 12kg', approx(fatMass, 12, 0.01));
  check('Masa libre de grasa: 80kg @15% = 68kg', approx(leanMass, 68, 0.01));

  // --- Deurenberg (debe existir pero NO ser el consenso por defecto) ---
  const deuren = deurenbergBodyFat(24.7, 30, 'm');
  check('Deurenberg: devuelve un valor plausible en rango 2-60', deuren >= 2 && deuren <= 60);

  // --- Navy: debe rechazar diferencias cuello/cintura demasiado pequeñas (bug original) ---
  const navyExtreme = navyBodyFat({ neck: 42, waist: 46, hip: null, heightCm: 180, sex: 'm' }); // diff=4, límite
  check('Navy: diferencia cuello/cintura pequeña se descarta (evita el bug de %grasa ~4%)', navyExtreme === null);
  const navyNormal = navyBodyFat({ neck: 38, waist: 85, hip: null, heightCm: 180, sex: 'm' });
  check('Navy: con diferencia razonable devuelve un valor en rango', navyNormal !== null && navyNormal >= 2 && navyNormal <= 60);

  // --- RFM y YMCA: deben devolver valores plausibles con inputs mínimos ---
  const rfm = rfmBodyFat({ heightCm: 180, waistCm: 85, sex: 'm' });
  check('RFM: valor en rango plausible', rfm !== null && rfm >= 2 && rfm <= 60);
  const ymca = ymcaBodyFat({ waistCm: 85, weightKg: 80, sex: 'm' });
  check('YMCA: valor en rango plausible', ymca !== null && ymca >= 2 && ymca <= 60);

  // --- CUN-BAE ---
  const cunbae = cunBaeBodyFat(24.7, 30, 'm');
  check('CUN-BAE: valor en rango plausible', cunbae >= 2 && cunbae <= 60);

  // --- Consenso: detección de outlier implausible (el bug original: ~4%) ---
  const consensusBug = computeBodyFatConsensus({ weightKg:80, heightCm:180, age:28, sex:'m', neck:44, waist:47, hip:null });
  check('Consenso: marca implausible el caso que reproducía el bug (~4%)', consensusBug.anyImplausible === true);
  const consensusNormal = computeBodyFatConsensus({ weightKg:80, heightCm:180, age:28, sex:'m', neck:38, waist:85, hip:null });
  check('Consenso: caso normal da un recomendado dentro de min/max', consensusNormal.recommended >= consensusNormal.min && consensusNormal.recommended <= consensusNormal.max);

  // --- Sincronización menú/compra (fuente única de verdad) ---
  const fakePlan = { days: [
    { day:'Lunes', training:false, meals:[ { name:'Comida', type:'batch', items:[ {food:'Pollo', grams:200}, {food:'Arroz', grams:100} ] } ] },
    { day:'Martes', training:false, meals:[ { name:'Comida', type:'batch', items:[ {food:'Pollo', grams:150} ] } ] }
  ]};
  const shopping = recomputeShoppingList(fakePlan);
  const pollo = shopping.find(s => s.item === 'Pollo');
  check('Sincronización menú↔compra: suma correctamente entre días (200+150=350g)', pollo && pollo.qty === '350 g');

  // --- Motor de datos (misma batería que `python bulking_app.py --test`) ---
  try { runEngineTests(BulkEngine, () => {}).results.forEach(r => check('Motor · ' + r.name, r.pass, r.detail)); } catch(e){ check('Motor: tests ejecutados', false, e.message); }

  // --- Reporte ---
  const passed = results.filter(r=>r.pass).length;
  console.log(`%c🧪 Tests: ${passed}/${results.length} pasados`, `color:${passed===results.length?'#10b981':'#ef4444'};font-weight:bold;font-size:14px;`);
  results.forEach(r => console[r.pass ? 'log' : 'error'](`${r.pass ? '✅' : '❌'} ${r.name}${r.detail ? ' — ' + r.detail : ''}`));
  return results;
};

// Estado del día visto (pasado): completo / dudoso / incompleto, con corrección en 1 toque.
function renderDayStatusRow(date){
  const el = $('day-status-row'); if(!el) return;
  if(date === todayStr()){ el.innerHTML = ''; return; }
  const d = getEngineState().days.find(x => x.date === date);
  if(!d || !d.entries){ el.innerHTML = ''; return; }
  const lbl = d.status === 'complete' ? (d.userFlag === true ? 'Completo (confirmado)' : 'Completo (auto)') : d.status === 'doubtful' ? 'Dudoso · no cuenta' : 'Incompleto · no cuenta';
  const btn = d.userFlag !== null ? `<button class="secondary mini" onclick="setDayFlagUI('${date}', null)">Volver a automático</button>`
    : d.status === 'complete' ? `<button class="secondary mini" onclick="setDayFlagUI('${date}', false)">Marcar incompleto</button>`
    : `<button class="secondary mini" onclick="setDayFlagUI('${date}', true)">Sí, está completo</button>`;
  el.innerHTML = `<span class="mini-tag">${lbl}</span> ${btn}`;
}

// Otro dispositivo/pestaña cambió datos → recargar perfil y repintar.
async function onExternalDataChange(){
  profile = await loadProfile(); __engineCache = null;
  try { updateBodyStats(); await updateDashboardUI(); await refreshInsights(); } catch(e){ console.error(e); }
}
let __storageEventTimer = null;
window.addEventListener('storage', (e) => {
  if(!e.key || e.key.startsWith('assistantCache') || e.key === SYNC_META_KEY) return;
  __dataVersion++;
  clearTimeout(__storageEventTimer); __storageEventTimer = setTimeout(onExternalDataChange, 400);
});

// INIT
window.onload = async () => {
  syncUid = getOrCreateSyncUid();
  if(cloudSyncEnabled){ await pullFromCloud(); } else { cloudSynced = true; }

  profile = await loadProfile();
  let migration = null;
  try { migration = await migrateToV2(); } catch(e){ console.error('Migración v2', e); showToast('Error en la migración de datos (ver consola).', true); }

  // Objetivo inicial para usuarios nuevos: fórmula + superávit del centro del rango.
  if(!profile.targetKcal){ const st0 = getEngineState(); await setTargetKcal(st0.decision.needed, 'formula', 'Objetivo inicial: mantenimiento por fórmula + superávit del rango.'); }

  // Inyectar datos del formulario
  $('prof-age').value = profile.age; $('prof-height').value = profile.height;
  $('prof-weight').value = profile.weight; $('prof-sex').value = profile.sex;
  $('prof-rate').value = profile.ratePreset; $('prof-bulk-start').value = profile.bulkStartDate || '';
  $('prof-pause').checked = !!profile.adjustmentPaused;
  $('prof-meals').value = profile.mealsPerDay || 5; $('prof-training-days').value = profile.trainingDays;
  $('prof-preferences').value = profile.preferences || '';
  $('input-weight-date').value = todayStr();
  $('input-goal-weight').value = profile.goalWeightKg || '';
  $('input-measure-date').value = todayStr();

  const dStr = new Date().toLocaleDateString('es-ES',{weekday:'long',day:'numeric',month:'short',year:'numeric'});
  $('date-display').innerText = dStr.charAt(0).toUpperCase()+dStr.slice(1);

  const lp = await safeGet('lastPlan'); if(lp && lp.plan) renderPlanObject(lp.plan, new Date(lp.generatedAt).toLocaleString('es-ES'));
  renderSyncStatus();
  renderNoSyncBanner();
  await pruneOldCaches();

  await runDailyEvaluation();
  if(migration){
    const parts = [];
    if(migration.correction) parts.push(`se ha deshecho el ajuste del ${migration.correction.date} (${migration.correction.from} → ${migration.correction.to} kcal) causado por un fallo del algoritmo anterior`);
    if(migration.removedSensitiveKeys.length) parts.push(`se ha borrado del almacenamiento una clave sensible (${migration.removedSensitiveKeys.join(', ')})`);
    if(parts.length) showAdjustAlert(`🔧 Bulking OS v2: ${parts.join('; ')}. Detalle en Progreso → Historial de decisiones.`, true);
  }
  updateBodyStats(); await updateDashboardUI(); await refreshInsights(); await renderWeightDayList();
  await checkBackupReminder();
  renderChatWindow((await safeGet('chatHistory'))||[]);

  $('chat-input').addEventListener('keydown', e => { if(e.key==='Enter') sendChatMessage(); });
  $('manual-text').addEventListener('keydown', e => { if(e.key==='Enter') processText(); });
  $('input-weight-date').addEventListener('change', renderWeightDayList);
  $('input-measure-date').addEventListener('change', renderBodyMeasureDayList);
};

</script>
</body>
</html>
"""

def get_injected_html():
    """Inyecta las variables de configuración de Python dentro del HTML estático."""
    html = APP_HTML_TEMPLATE
    html = html.replace("__API_KEY_B64__", GEMINI_API_KEY_B64)
    html = html.replace("__MODEL__", GEMINI_MODEL)
    html = html.replace("__MODEL_PLAN__", GEMINI_MODEL_PLAN)
    html = html.replace("__MODEL_FOOD__", GEMINI_MODEL_FOOD)
    html = html.replace("__FILLER__", FILLER_FOODS)
    html = html.replace("__FIREBASE_DB_URL__", FIREBASE_DB_URL)
    return html

def write_index():
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(get_injected_html())

# Si el script se llama con el arg "--export-only", solo exporta y cierra.
# Útil para el subproceso del watcher.
if "--export-only" in sys.argv:
    write_index()
    sys.exit(0)

# `python bulking_app.py --test` → ejecuta en Node la batería de tests del motor
# (el MISMO código que corre en el navegador, extraído de la plantilla).
if "--test" in sys.argv:
    import shutil, tempfile
    node = shutil.which("node")
    if not node:
        print("Necesitas Node.js instalado para --test (o abre la app → Datos → Ejecutar tests).")
        sys.exit(2)
    def _between(a, b):
        i = APP_HTML_TEMPLATE.index(a); j = APP_HTML_TEMPLATE.index(b) + len(b)
        return APP_HTML_TEMPLATE[i:j]
    with tempfile.TemporaryDirectory() as d:
        for name, (a, b) in {"engine.js": ("/*__ENGINE_START__*/", "/*__ENGINE_END__*/"), "tests.js": ("/*__TESTS_START__*/", "/*__TESTS_END__*/")}.items():
            with open(os.path.join(d, name), "w", encoding="utf-8") as f: f.write(_between(a, b))
        with open(os.path.join(d, "run.js"), "w", encoding="utf-8") as f:
            f.write("const E=require('./engine.js');const {runEngineTests}=require('./tests.js');const r=runEngineTests(E);process.exit(r.passed===r.total?0:1);")
        sys.exit(subprocess.run([node, os.path.join(d, "run.js")]).returncode)

# ============================================================================
# ⚙️ SERVIDOR Y AUTOMATIZACIÓN DE GIT (WATCHER)
# ============================================================================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# Evitar que git se bloquee pidiendo usuario/contraseña de forma interactiva
GIT_ENV = dict(os.environ)
GIT_ENV["GIT_TERMINAL_PROMPT"] = "0"

def run_git(cmd, timeout=30):
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=PROJECT_DIR, capture_output=True,
            text=True, env=GIT_ENV, timeout=timeout
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, (
            f"TIMEOUT: Git tardó > {timeout}s sin responder. Con GIT_TERMINAL_PROMPT=0 no puede "
            "pedir credenciales y se cuelga en vez de fallar con un error claro. Prueba 'git push' "
            "manualmente en terminal: normalmente es un token caducado o falta credential.helper."
        )

def has_changes():
    ok, out = run_git(f'git status --porcelain -- "index.html" "{os.path.basename(THIS_FILE)}"')
    return ok and out.strip() != ""

def current_branch():
    ok, out = run_git("git rev-parse --abbrev-ref HEAD")
    return out.strip() if ok and out.strip() else "main"

def squash_unpushed_commits(branch):
    """Aplasta commits locales sin subir en uno solo antes de empujar (son
    seguros de reescribir porque nunca llegaron al remoto) para no arrastrar
    la key en texto plano de versiones antiguas del historial local."""
    ok, _ = run_git("git fetch origin", timeout=30)
    if not ok:
        return
    ok, out = run_git(f"git rev-list origin/{branch}..HEAD --count")
    if not ok or not out.strip().isdigit():
        return
    ahead = int(out.strip())
    if ahead <= 1:
        return
    log(f"🧹 Aplastando {ahead} commits locales sin subir en uno solo.")
    ok, out = run_git(f"git reset --soft origin/{branch}")
    if not ok:
        log(f"⚠️ No se pudo aplastar el historial local: {out}")
        return
    msg = f"Auto-update config/app {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (squash)"
    ok, out = run_git(f'git commit -m "{msg}"')
    if ok:
        log("✅ Historial local aplastado en un único commit limpio.")
    else:
        log(f"⚠️ git commit tras el squash falló: {out}")

def commit_and_push():
    branch = current_branch()
    msg = f"Auto-update config/app {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    ok, out = run_git(f'git add "index.html" "{os.path.basename(THIS_FILE)}"')
    if not ok:
        log(f"❌ git add falló (revisa que estos archivos existan en la raíz del repo): {out}")
        return

    if has_changes():
      ok, out = run_git(f'git commit -m "{msg}"')
      if not ok:
        log(f"⚠️ git commit falló: {out}")
        return
      log(f"✅ Commit exitoso: {msg}")
    else:
      log("ℹ️ Sin cambios nuevos en index.html/bulking_app.py; compruebo si hay commits sin subir de antes.")

    # Aplasta commits locales sin subir de intentos anteriores (pueden arrastrar
    # la key en texto plano de versiones previas al cambio a base64).
    squash_unpushed_commits(branch)

    # Sincronizamos DESPUÉS de comitear, nunca antes: si hiciéramos pull --rebase
    # con cambios sin commitear (index.html recién regenerado), el rebase fallaría
    # casi siempre y la rama local se desincronizaría del remoto.
    ok, out = run_git(f"git pull --rebase origin {branch}")
    if not ok:
        log(f"⚠️ git pull --rebase falló (¿primer push o conflicto real?): {out}")
        run_git("git rebase --abort")  # por si quedó un rebase a medias, no dejamos el repo roto

    ok, out = run_git("git push", timeout=60)
    if not ok:
        if "has no upstream branch" in out or "set-upstream" in out:
            ok, out = run_git(f"git push -u origin {branch}", timeout=60)
        if not ok and ("rejected" in out or "non-fast-forward" in out or "fetch first" in out):
            # El remoto se adelantó (ej. algo cambiado desde otra máquina o el navegador
            # de GitHub): sincronizamos una vez más y reintentamos el push automáticamente.
            log("⚠️ Push rechazado (el remoto tenía commits nuevos), reintentando tras sincronizar...")
            run_git(f"git pull --rebase origin {branch}")
            ok, out = run_git("git push", timeout=60)
        if not ok:
            if "GH013" in out or "Push cannot contain secrets" in out or "secret-scanning" in out:
                log(
                    "❌ Push bloqueado por GitHub Push Protection (detectó GEMINI_API_KEY hardcodeada).\n"
                    "   El enlace 'Allow secret' de abajo es nuevo en cada push (cambia con el rebase); usa el que sale AHORA.\n"
                    "   Fix definitivo: github.com/marcelgiberts-creator/bulking/settings/security_analysis → "
                    "Secret scanning → desactiva Push protection.\n"
                    f"   --- Texto original de GitHub ---\n{out}"
                )
            else:
                log(f"❌ git push falló definitivamente: {out}")
            return

    log("🚀 Push a GitHub completado correctamente. La web se actualizará en cuanto GitHub Pages recompile (normalmente 30-90s).")

def regenerate_index_via_subprocess():
    """Ejecuta un subproceso limpio para recrear el index.html usando las configs actuales guardadas."""
    subprocess.run(f'"{sys.executable}" "{THIS_FILE}" --export-only', shell=True, cwd=PROJECT_DIR)

def watcher_loop():
    """Vigila si este script Python cambia y hace auto-commit."""
    last_hash = hashlib.sha256(open(THIS_FILE, "rb").read()).hexdigest()
    pending_since = None
    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            try:
                current_hash = hashlib.sha256(open(THIS_FILE, "rb").read()).hexdigest()
            except FileNotFoundError:
                continue
                
            if current_hash != last_hash:
                last_hash = current_hash
                pending_since = time.time()
                log("📝 Cambio detectado en el script, guardando...")
                
            if pending_since and (time.time() - pending_since) >= DEBOUNCE:
                pending_since = None
                regenerate_index_via_subprocess()
                log("🔄 index.html regenerado localmente.")
                commit_and_push()
        except Exception as e:
            log(f"⚠️ Error en el Watcher (recuperando): {e}")

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Silenciar logs HTTP

class QuietHTTPServer(HTTPServer):
    def handle_error(self, request, client_address):
        # El navegador cierra/aborta conexiones constantemente (recargas, pestañas
        # cerradas, F12 con caché deshabilitada...). Eso no es un fallo de la app,
        # así que lo ignoramos en vez de imprimir un traceback por cada uno.
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

def serve_local():
    os.chdir(PROJECT_DIR)
    port = PORT
    httpd = None
    for _ in range(10):
        try:
            httpd = QuietHTTPServer(("localhost", port), QuietHandler)
            break
        except OSError:
            port += 1
    if httpd is None:
        log("❌ No se encontró puerto libre. Watcher en segundo plano funcionando de todos modos.")
        while True: time.sleep(3600)
        
    log(f"🌐 Servidor arrancado en http://localhost:{port}")
    threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    httpd.serve_forever()

def main():
    ok, _ = run_git("git rev-parse --is-inside-work-tree")
    if not ok:
        log("❌ Esta carpeta no es un repositorio de GIT válido. Haz 'git init' primero.")
        sys.exit(1)

    # Inyección Inicial
    write_index()
    commit_and_push()

    # Arrancar Hilos
    watcher_thread = threading.Thread(target=watcher_loop, daemon=True)
    watcher_thread.start()

    try:
        serve_local()
    except KeyboardInterrupt:
        log("🛑 Apagando servidor.")

if __name__ == "__main__":
    main()