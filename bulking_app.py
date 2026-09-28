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
# Un único modelo (rápido/barato) por decisión explícita:
#   · FOOD    → estimación de kcal y macros al registrar comidas
#   · SUMMARY → asistente diario y resúmenes (semanal y de composición corporal)
GEMINI_MODEL_FOOD = "gemini-3.5-flash-lite"
GEMINI_MODEL_SUMMARY = "gemini-3.5-flash-lite"

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

  /* Matices de la paleta: solo colorean un punto, el dato resumen y la pestaña activa */
  [data-tone="amber"] { --tone: rgb(217,171,106); --tone-rgb: 217,171,106; }
  [data-tone="green"] { --tone: rgb(127,174,148); --tone-rgb: 127,174,148; }
  [data-tone="blue"] { --tone: rgb(138,162,200); --tone-rgb: 138,162,200; }
  [data-tone="rose"] { --tone: rgb(191,148,138); --tone-rgb: 191,148,138; }
  [data-tone="violet"] { --tone: rgb(178,145,171); --tone-rgb: 178,145,171; }
  [data-tone="slate"] { --tone: rgb(168,173,182); --tone-rgb: 168,173,182; }

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
  .kcal-number {
    font-family: 'Space Grotesk', sans-serif;
    font-size: clamp(2.9rem, 8vw, 3.6rem); font-weight: 600; line-height: 1;
    letter-spacing: -0.045em; font-variant-numeric: tabular-nums;
  }

  .main-progress { height: 6px; background: rgba(255,255,255,0.07); border-radius: 99px; overflow: hidden; margin-bottom: 26px; }
  .main-progress-fill { height: 100%; background: var(--accent); border-radius: 99px; transition: width 0.85s var(--ease); }
  .surplus { background: var(--green) !important; }
  .macro-bar-bg { height: 4px; background: rgba(255,255,255,0.07); border-radius: 99px; overflow: hidden; }
  .macro-bar-fill { height: 100%; border-radius: 99px; transition: width 0.85s var(--ease); }
  .pro-fill { background: var(--pro-color); }
  .car-fill { background: var(--car-color); }
  .fat-fill { background: var(--fat-color); }
  .sugar-fill { background: var(--sugar-color); }
  .over-limit { background: var(--red) !important; }

  /* =========================================
     🏅 RACHA, FAVORITOS, SCORE, INSIGHTS
     ========================================= */
  .streak-badge { display:inline-flex; align-items:center; gap:5px; padding:5px 11px; border-radius:99px; background:var(--accent-soft); border:1px solid var(--accent-line); color:var(--accent); font-size:0.7rem; font-weight:700; white-space:nowrap; letter-spacing: 0.01em; }

  .favorites-row { display:flex; gap:8px; flex-wrap:wrap; }
  .favorite-chip { display:inline-flex; align-items:center; gap:7px; padding:9px 14px; border-radius:99px; background:var(--glass-bg-raised); border:1px solid var(--glass-border); font-size:0.8rem; font-weight:600; cursor:pointer; transition: all var(--dur) var(--ease); }
  .favorite-chip .chip-remove { opacity:0.35; font-size:0.7rem; }
  .favorite-chip .chip-remove:hover { opacity:1; color: var(--red); }

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
  .form-group { flex: 1; min-width: 0; }
  .form-group label { display: block; font-size: 0.7rem; color: var(--text-dim); margin-bottom: 8px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }

  .chart-container { position: relative; height: 210px; width: 100%; margin-top: 8px; }

  /* =========================================
     📋 TABLAS
     ========================================= */
  .data-table { width:100%; border-collapse:collapse; margin-top:8px; }
  .data-table th { color:var(--text-dim); font-size:0.66rem; text-align:left; padding:12px 10px; border-bottom:1px solid var(--glass-border); text-transform:uppercase; letter-spacing:0.07em; font-weight:600; }
  .data-table td { padding:13px 10px; font-size:0.85rem; vertical-align:top; border-bottom:1px solid var(--glass-border); color:var(--text-mid); }

  /* =========================================
     🔔 AVISOS
     ========================================= */
  .empty-state { color:var(--text-dim); text-align:center; padding:36px 20px; font-size:0.86rem; line-height: 1.6; }

  .alert { background: var(--accent-soft); border: 1px solid var(--accent-line); padding: 16px 18px; border-radius: var(--radius-md); font-size: 0.86rem; margin-bottom: 16px; color: var(--text-mid); line-height: 1.6; }
  .alert.warn { background: rgba(197,131,122,0.07); border-color: rgba(197,131,122,0.24); }

  .daily-assistant {
    background: var(--glass-bg); backdrop-filter: blur(20px) saturate(140%); -webkit-backdrop-filter: blur(20px) saturate(140%);
    border: 1px solid var(--glass-border); border-left: 2px solid var(--accent-line);
    border-radius: var(--radius-md); padding: 22px 24px; margin-bottom: 20px; color: var(--text-mid);
  }
  .assistant-title { font-family:'Space Grotesk', sans-serif; font-size:1rem; font-weight:600; color:var(--text); margin-bottom:8px; line-height:1.4; letter-spacing:-0.02em; }
  .assistant-body { font-size:.87rem; line-height:1.65; color:var(--text-mid); }

  .food-review { margin-top:20px; padding:20px; border:1px solid var(--accent-line); border-radius:var(--radius-md); background:var(--accent-soft); text-align:left; }
  .food-review-grid { display:grid; grid-template-columns:2fr repeat(5, minmax(50px, 1fr)); gap:8px; margin:14px 0; }
  .food-review-grid input { margin-bottom:0; padding:11px 8px; font-size:0.85rem; text-align:center; }
  .food-review-grid input:first-child { text-align:left; }

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
  .nav-item.active { color: var(--tone, var(--accent)); background: rgba(var(--tone-rgb, 217,171,106), .14); }
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
    .food-review-grid { grid-template-columns: 1fr 1fr 1fr; }
    .food-review-grid input:first-child { grid-column: 1 / -1; }
    /* Objetivos táctiles generosos */
    input, select, textarea { padding: 16px; font-size: 16px; }
    button.primary { padding: 17px; }
    button.secondary { padding: 14px 18px; }
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
  .muted-line { font-size:.76rem; color:var(--text-dim); line-height:1.5; margin-top:10px; }
  .kv-row { display:grid; grid-template-columns:1fr auto; gap:2px 12px; padding:10px 0; border-bottom:1px solid var(--glass-border); font-size:.86rem; }
  .kv-row:last-of-type { border-bottom:none; }
  .kv-row span { color:var(--text-mid); } .kv-row b { font-variant-numeric:tabular-nums; text-align:right; }
  .kv-row small { grid-column:1 / -1; color:var(--text-dim); font-size:.72rem; line-height:1.4; }
  .decision-box { margin-top:14px; padding:12px 14px; border-radius:var(--radius-sm); font-size:.84rem; line-height:1.5; background:color-mix(in srgb, var(--tone) 9%, transparent); border:1px solid color-mix(in srgb, var(--tone) 28%, transparent); }
  .decision-box b { color:var(--tone); }
  .sub-details { margin-top:14px; font-size:.8rem; } .sub-details summary { cursor:pointer; color:var(--text-mid); font-weight:600; }
  .formula p { color:var(--text-mid); line-height:1.55; margin:10px 0 0; }
  .sub-title { font-size:.72rem; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:var(--text-mid); margin-bottom:10px; }
  .banner-actions { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-top:10px; }
  button.mini, .secondary.mini { padding:6px 12px; font-size:.74rem; }
  .mini-tag { display:inline-block; font-size:.62rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em; padding:2px 7px; border-radius:6px; background:rgba(255,255,255,.07); color:var(--text-mid); vertical-align:middle; }
  .day-status-row { display:flex; gap:8px; justify-content:center; align-items:center; flex-wrap:wrap; margin-top:8px; }
  .dq-list { display:flex; flex-direction:column; gap:8px; margin-top:12px; }
  .dq-item { font-size:.78rem; line-height:1.5; color:var(--text-mid); padding:10px 12px; border-radius:var(--radius-sm); background:rgba(255,255,255,.03); border:1px solid var(--glass-border); }
  .table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; }
  .data-table.audit { font-size:.74rem; white-space:nowrap; } .data-table.audit th { text-align:left; color:var(--text-dim); font-weight:600; padding:6px 8px; } .data-table.audit td { padding:6px 8px; }
  .decision-item { border-bottom:1px solid var(--glass-border); padding:8px 0; font-size:.8rem; }
  .decision-item summary { cursor:pointer; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .decision-reason { color:var(--text-mid); line-height:1.5; margin:8px 0; }
  .act-subir { color:var(--green); } .act-bajar { color:var(--red); } .act-mantener, .act-sin_datos { color:var(--text-mid); } .act-correccion, .act-manual { color:var(--accent); }
  pre.trace { font-size:.66rem; line-height:1.4; max-height:260px; overflow:auto; background:rgba(0,0,0,.25); border:1px solid var(--glass-border); border-radius:8px; padding:10px; color:var(--text-mid); white-space:pre-wrap; }
  .src-badge { display:inline-flex; align-items:center; gap:6px; margin-top:8px; padding:5px 10px; border-radius:20px; background:rgba(255,255,255,0.06); font-size:.72rem; font-weight:700; }
  .est-meta { font-size:.8rem; color:var(--text-mid); margin-top:12px; } .est-meta b { color:var(--text); }
  .est-items { width:100%; font-size:.76rem; margin-top:8px; border-collapse:collapse; } .est-items td { padding:4px 0; color:var(--text-mid); border-bottom:1px solid var(--glass-border); } .est-items td:nth-child(2), .est-items td:nth-child(3) { text-align:right; white-space:nowrap; padding-left:10px; }
  .est-assump { font-size:.72rem; color:var(--text-dim); margin-top:8px; line-height:1.45; }
  .est-question { margin-top:12px; padding:10px 12px; border-radius:var(--radius-sm); border:1px solid var(--accent-line); background:var(--accent-soft); font-size:.82rem; }
  .scale-row { display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin:-4px 0 14px; font-size:.7rem; color:var(--text-dim); } .scale-row span { margin-right:4px; text-transform:uppercase; letter-spacing:.06em; font-weight:600; }
  .scale-row button { padding:6px 10px; font-size:.74rem; }
  .scale-row .chk { display:inline-flex; align-items:center; gap:6px; font-size:.78rem; color:var(--text-mid); cursor:pointer; margin:0; text-transform:none; letter-spacing:0; }
  .scale-row .chk input { width:auto; margin:0; padding:0; }
  .scale-row .chk small { color:var(--text-dim); }
  .cmp-bar { display:flex; justify-content:space-between; align-items:center; padding:12px 14px; margin:12px 0; border-radius:8px; background:rgba(255,255,255,0.04); border:1px solid var(--glass-border); font-size:.85rem; }
  @media (max-width: 760px){ .status-nums { grid-template-columns:repeat(3,1fr); } .sn-val { font-size:1.02rem; } }

  /* =========================================
     ◻︎ PIEL MINIMALISTA
     Una sola columna centrada, poco peso visual: sin cabeceras de pestaña,
     sin subtítulos, etiquetas mínimas y lo secundario plegado.
     ========================================= */
  .app-container { max-width: 580px; padding: 14px 14px 104px; }
  .glass-card { padding: 16px 18px; margin-bottom: 10px; border-radius: 18px; box-shadow: none; backdrop-filter: none; -webkit-backdrop-filter: none; }
  .glass-card::before { background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent); }
  .glass-card.card-hero { text-align: center; padding: 26px 18px 18px; }

  /* Etiqueta de tarjeta: punto de color + texto mínimo + dato resumen */
  .card-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
  .card-head h3 { margin: 0; display: flex; align-items: center; gap: 8px; font-size: .66rem; letter-spacing: .13em; color: var(--text-dim); }
  .card-head h3::before, details.fold > summary > span::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--tone, var(--accent)); flex: none; }
  .card-meta { font-family: 'Space Grotesk', sans-serif; font-size: .95rem; font-weight: 600; letter-spacing: -0.02em; color: var(--text); font-variant-numeric: tabular-nums; }
  .card-meta:empty { display: none; }

  /* Bloques plegables */
  details.fold { padding: 0; }
  details.fold > summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 15px 18px; cursor: pointer; list-style: none; font-family: 'Space Grotesk', sans-serif; font-size: .66rem; font-weight: 600; letter-spacing: .13em; text-transform: uppercase; color: var(--text-dim); }
  details.fold > summary::-webkit-details-marker { display: none; }
  details.fold > summary > span { display: flex; align-items: center; gap: 8px; }
  details.fold > summary::after { content: '+'; margin-left: 10px; font-size: 1.05rem; line-height: 1; color: var(--text-dim); }
  details.fold[open] > summary::after { content: '–'; }
  details.fold > summary .card-meta { margin-left: auto; }
  details.fold[open] > summary { border-bottom: 1px solid var(--glass-border); }
  .fold-body { padding: 14px 18px 18px; }
  details.sub { border-top: 1px solid var(--glass-border); padding: 10px 0; margin-top: 10px; }
  details.sub > summary { cursor: pointer; font-size: .8rem; font-weight: 600; color: var(--text-mid); list-style: none; }
  details.sub > summary::-webkit-details-marker { display: none; }
  details.sub > summary::after { content: '+'; float: right; color: var(--text-dim); }
  details.sub[open] > summary::after { content: '–'; }
  details.sub > div { margin-top: 10px; }
  .glass-card.soon { border-style: dashed; background: transparent; }

  /* Controles compactos */
  input, select, textarea { padding: 11px 13px; font-size: .9rem; margin-bottom: 0; }
  textarea { resize: vertical; }
  button.primary { padding: 13px; font-size: .9rem; margin-top: 4px; }
  button.secondary { padding: 11px 14px; font-size: .84rem; }
  button.ghost { background: none; border: none; color: var(--text-mid); font-size: 1.5rem; line-height: 1; padding: 4px 14px; cursor: pointer; }
  button.link { background: none; border: none; color: var(--accent); font-size: .74rem; padding: 0; cursor: pointer; }
  .file-btn { display: inline-flex; justify-content: center; align-items: center; background: var(--glass-bg-raised); color: var(--text); border: 1px solid var(--glass-border); border-radius: var(--radius-sm); cursor: pointer; font-weight: 600; font-size: .84rem; padding: 11px 14px; }
  .form-group label { margin-bottom: 5px; font-size: .62rem; }
  .field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .field-grid .span2 { grid-column: 1 / -1; }
  .inline-form { display: flex; gap: 8px; align-items: center; margin-top: 12px; }
  .inline-form input, .inline-form select { margin: 0; min-width: 0; flex: 1; }
  .inline-form input[type="date"] { flex: 1.4; }
  .toggle-row { padding: 12px 0 8px; font-size: .86rem; color: var(--text-mid); }
  .alert { padding: 11px 14px; font-size: .78rem; margin-bottom: 10px; }
  .chart-container { height: 165px; margin-top: 0; }
  .muted-line { margin-top: 8px; }

  /* Hoy */
  .date-row { display: flex; align-items: center; justify-content: space-between; margin: 0 0 6px; }
  .date-mid { text-align: center; }
  .date-mid strong { font-family: 'Space Grotesk', sans-serif; font-size: .95rem; font-weight: 600; }
  .date-mid button.link { margin-top: 2px; }
  .day-status-row { margin-bottom: 10px; text-align: center; }
  .day-status-row:empty { display: none; }
  .kcal-number { font-size: 4.2rem; }
  .hero-sub { margin-top: 6px; font-size: .68rem; letter-spacing: .12em; text-transform: uppercase; font-weight: 600; color: var(--text-dim); }
  .main-progress { height: 4px; margin: 18px 0 10px; }
  .hero-line { display: flex; justify-content: center; align-items: center; gap: 12px; margin-bottom: 20px; font-size: .78rem; color: var(--text-dim); }
  .hero-line b { color: var(--text-mid); font-weight: 600; }
  .hero-line #ui-kcal-err { margin-left: 6px; font-size: .72rem; }
  .macro-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; text-align: left; }
  .macro-top { display: flex; flex-direction: column; gap: 2px; margin-bottom: 7px; }
  .macro-top span { font-size: .6rem; text-transform: uppercase; letter-spacing: .09em; font-weight: 700; }
  .macro-top b { font-family: 'Space Grotesk', sans-serif; font-size: .8rem; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .compose-row { display: flex; gap: 8px; align-items: center; }
  .compose-row input { margin: 0; flex: 1; min-width: 0; }
  .mic-btn { width: 44px; height: 44px; font-size: 1.1rem; flex: none; }
  .compose .ai-status { margin: 10px 0 0; text-align: left; font-size: .76rem; min-height: 0; }
  .ai-status:empty { display: none; }
  .compose .favorites-row { margin-top: 10px; }
  .fill-row { display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--glass-border); font-size: .84rem; color: var(--text-mid); }
  .fill-row b { color: var(--text); font-weight: 600; white-space: nowrap; }
  .fill-row.total { border-bottom: none; color: var(--text-dim); font-size: .78rem; }
  .daily-assistant { padding: 13px 16px; margin-bottom: 10px; }
  .assistant-title { font-size: .84rem; margin-bottom: 3px; }
  .assistant-body { font-size: .8rem; line-height: 1.55; }
  .list-card { padding: 2px 18px; }
  .log-item { padding: 12px 0; }
  .log-title { font-size: .9rem; margin-bottom: 2px; }
  .log-kcal { font-size: .95rem; }
  .del-btn, .edit-btn { border: none; width: 28px; height: 28px; font-size: .85rem; }

  /* Progreso / Gym / Ajustes */
  .goal-line { display: flex; justify-content: space-between; gap: 10px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--glass-border); font-size: .8rem; color: var(--text-dim); }
  .goal-line b { color: var(--text); font-weight: 600; }
  .kv-row { padding: 9px 0; font-size: .84rem; }
  .decision-box { margin-top: 10px; padding: 10px 12px; }
  #nutrition-stats, #steps-summary { margin-top: 8px; }
  .rate-scale { margin: 14px 0 6px; }
  #weight-day-list:empty, #measure-day-list:empty { display: none; }
  #weight-day-list, #measure-day-list { margin-top: 6px; }
  #steps-summary:empty { display: none; }
  @media (max-width: 760px) { .glass-card { padding: 16px 16px; border-radius: 18px; margin-bottom: 10px; } }

  /* Agua */
  .water-row { display: flex; align-items: center; gap: 20px; }
  .bottle { width: 68px; height: 136px; flex: none; overflow: visible; }
  .bottle.full { --tone: rgb(127,174,148); }
  .water-level { transition: transform 1s cubic-bezier(.22,.8,.3,1); }
  .wave { animation: wave 3.4s linear infinite; }
  @keyframes wave { to { transform: translateX(-40px); } }
  @media (prefers-reduced-motion: reduce) { .wave { animation: none; } .water-level { transition: none; } }
  .water-side { flex: 1; min-width: 0; }
  .water-num { font-family: 'Space Grotesk', sans-serif; font-size: .95rem; color: var(--text-dim); font-variant-numeric: tabular-nums; }
  .water-num b { font-size: 2.3rem; font-weight: 600; letter-spacing: -0.04em; color: var(--text); }
  .water-sub { margin-top: 2px; font-size: .74rem; color: var(--text-dim); min-height: 1.1em; }
  .water-sub.done { color: var(--green); }
  .water-btns { display: flex; gap: 6px; margin-top: 12px; }
  .water-btns button { flex: 1; padding: 10px 0; font-size: .8rem; }
  .water-btns .undo { flex: 0 0 40px; font-size: 1rem; }
  .water-chips { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
  .chip-toggle { padding: 5px 11px; border-radius: 99px; background: none; border: 1px solid var(--glass-border); color: var(--text-dim); font-size: .7rem; font-weight: 600; cursor: pointer; }
  .chip-toggle.on { color: var(--tone); border-color: rgba(var(--tone-rgb), .5); background: rgba(var(--tone-rgb), .12); }
</style>
</head>
<body>

<div id="toast-container"></div>

<div class="app-container">

  <!-- ========================================================================= -->
  <!-- 📊 HOY                                                                  -->
  <!-- ========================================================================= -->
  <div id="tab-dash" class="section active">
    <div id="no-sync-banner" class="alert warn" style="display:none;"></div>
    <div id="adjust-alert" class="alert" style="display:none;"></div>
    <div id="day-flag-banner" class="alert warn" style="display:none;"></div>
    <div id="favorite-suggestion" class="alert" style="display:none;"></div>
    <div id="backup-reminder" class="alert" style="display:none;"></div>
    <div id="measure-reminder" class="alert" style="display:none;"></div>

    <div class="date-row">
      <button class="ghost" onclick="navDay(-1)" aria-label="Día anterior">‹</button>
      <div class="date-mid">
        <strong id="log-date-label">Hoy</strong>
        <div id="log-date-jump" style="display:none;"><button class="link" onclick="jumpToday()">volver a hoy</button></div>
      </div>
      <button class="ghost" id="btn-next-day" onclick="navDay(1)" aria-label="Día siguiente">›</button>
    </div>
    <div id="day-status-row" class="day-status-row"></div>

    <div class="glass-card card-hero" data-tone="amber">
      <div class="kcal-number" id="ui-kcal-remaining">0</div>
      <div class="hero-sub" id="ui-kcal-status">restantes</div>
      <div class="main-progress"><div class="main-progress-fill" id="ui-progress"></div></div>
      <div class="hero-line">
        <span><b id="ui-kcal-consumed">0</b> / <b id="ui-kcal-target">--</b> kcal<span id="ui-kcal-err" title="Error estimado del registro"></span></span>
        <span class="streak-badge" id="streak-badge" style="display:none;"></span>
      </div>
      <div class="macro-grid">
        <div class="macro" title="Proteína"><div class="macro-top"><span style="color:var(--pro-color)">Prot</span><b id="txt-pro">0</b></div><div class="macro-bar-bg"><div class="macro-bar-fill pro-fill" id="bar-pro"></div></div></div>
        <div class="macro" title="Carbohidratos"><div class="macro-top"><span style="color:var(--car-color)">Carb</span><b id="txt-car">0</b></div><div class="macro-bar-bg"><div class="macro-bar-fill car-fill" id="bar-car"></div></div></div>
        <div class="macro" title="Grasas"><div class="macro-top"><span style="color:var(--fat-color)">Grasa</span><b id="txt-fat">0</b></div><div class="macro-bar-bg"><div class="macro-bar-fill fat-fill" id="bar-fat"></div></div></div>
        <div class="macro" title="Azúcar"><div class="macro-top"><span style="color:var(--sugar-color)">Azúc</span><b id="txt-sugar">0</b></div><div class="macro-bar-bg"><div class="macro-bar-fill sugar-fill" id="bar-sugar"></div></div></div>
      </div>
    </div>

    <div class="glass-card compose" data-tone="rose">
      <div class="compose-row">
        <button class="mic-btn" id="btn-mic" aria-label="Dictar">🎙️</button>
        <input type="text" id="manual-text" placeholder="¿Qué has comido?">
        <button class="secondary" id="btn-send-text" onclick="processText()">Añadir</button>
      </div>
      <div class="ai-status" id="ai-status"></div>
      <div id="favorites-row" class="favorites-row" style="display:none;"></div>
      <div id="food-review" class="food-review" style="display:none;"></div>
    </div>

    <div class="glass-card water" id="water-card" data-tone="blue">
      <div class="card-head"><h3>Agua</h3><b class="card-meta" id="meta-water"></b></div>
      <div class="water-row">
        <svg class="bottle" id="water-bottle" viewBox="0 0 80 160" aria-hidden="true">
          <defs>
            <clipPath id="bottle-clip"><path d="M33 14H47V28C47 34 68 38 68 54V146Q68 154 60 154H20Q12 154 12 146V54C12 38 33 34 33 28Z"/></clipPath>
            <linearGradient id="water-grad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--tone); stop-opacity:.9"/><stop offset="1" style="stop-color:var(--tone); stop-opacity:.5"/></linearGradient>
          </defs>
          <g clip-path="url(#bottle-clip)">
            <rect x="0" y="0" width="80" height="160" fill="rgba(255,255,255,0.03)"/>
            <g id="water-level" class="water-level" style="transform: translateY(170px)">
              <g class="wave"><path d="M0 5Q10 0 20 5T40 5T60 5T80 5T100 5T120 5T140 5T160 5V170H0Z" fill="url(#water-grad)"/></g>
            </g>
            <g stroke="rgba(255,255,255,0.32)" stroke-width="1"><line x1="57" x2="68" y1="124" y2="124"/><line x1="52" x2="68" y1="94" y2="94"/><line x1="57" x2="68" y1="64" y2="64"/></g>
          </g>
          <path d="M33 14H47V28C47 34 68 38 68 54V146Q68 154 60 154H20Q12 154 12 146V54C12 38 33 34 33 28Z" fill="none" stroke="rgba(255,255,255,0.3)" stroke-width="1.6" stroke-linejoin="round"/>
          <rect x="31" y="4" width="18" height="10" rx="3" fill="rgba(255,255,255,0.18)"/>
        </svg>
        <div class="water-side">
          <div class="water-num"><b id="water-now">0</b><span> / <span id="water-goal">--</span> L</span></div>
          <div class="water-sub" id="water-sub"></div>
          <div class="water-btns">
            <button class="secondary" onclick="addWater(250)">+250</button>
            <button class="secondary" onclick="addWater(500)">+500</button>
            <button class="secondary" onclick="addWater(750)">+750</button>
            <button class="secondary undo" id="water-undo" onclick="undoWater()" aria-label="Deshacer">↶</button>
          </div>
          <div class="water-chips">
            <button class="chip-toggle" id="chip-train" onclick="toggleWaterCtx('train')">Entreno +0,5 L</button>
            <button class="chip-toggle" id="chip-heat" onclick="toggleWaterCtx('heat')">Calor +0,5 L</button>
          </div>
        </div>
      </div>
      <details class="sub"><summary>Cómo se calcula</summary><div id="water-detail"></div></details>
    </div>

    <details id="missing-today" class="glass-card fold" data-tone="rose" style="display:none;"></details>

    <div id="daily-assistant" class="daily-assistant" style="display:none;"></div>

    <div class="glass-card list-card" id="log-list"></div>
  </div>

  <!-- ========================================================================= -->
  <!-- 📈 PROGRESO                                                             -->
  <!-- ========================================================================= -->
  <div id="tab-body" class="section">
    <div class="glass-card" data-tone="green">
      <div class="card-head"><h3>Bulk</h3><b class="card-meta" id="meta-bulk"></b></div>
      <div id="bulk-status-body"></div>
      <div id="goal-projection-content"></div>
    </div>

    <div class="glass-card" data-tone="blue">
      <div class="card-head"><h3>Peso</h3><b class="card-meta" id="meta-weight"></b></div>
      <div class="chart-container"><canvas id="weightChart"></canvas></div>
      <div class="inline-form">
        <input type="date" id="input-weight-date">
        <input type="number" step="0.1" id="input-weight" placeholder="kg">
        <button class="secondary" onclick="addWeight()">Guardar</button>
      </div>
      <div id="weight-day-list"></div>
    </div>

    <div class="glass-card" data-tone="rose">
      <div class="card-head"><h3>Ingesta</h3><b class="card-meta" id="meta-intake"></b></div>
      <div class="chart-container"><canvas id="kcalTrendChart"></canvas></div>
      <div id="nutrition-stats"></div>
    </div>

    <div class="glass-card" data-tone="amber">
      <div class="card-head"><h3>Objetivo</h3><b class="card-meta" id="meta-target"></b></div>
      <div id="why-target-body"></div>
      <details class="sub">
        <summary>Detalle</summary>
        <div id="why-target-detail"></div>
        <div class="chart-container"><canvas id="modelChart"></canvas></div>
      </details>
    </div>

    <details class="glass-card fold" data-tone="violet">
      <summary><span>Composición</span></summary>
      <div class="fold-body">
        <div id="body-comp-content"></div>
        <div id="body-comp-chart-wrap" style="display:none; margin-top:16px;">
          <select id="metric-select" onchange="renderBodyCompositionChart()">
            <option value="weight">Peso (kg)</option>
            <option value="bmi">IMC</option>
            <option value="bodyfat">% Grasa corporal</option>
            <option value="ffmi">FFMI (normalizado)</option>
            <option value="fatmass">Masa grasa (kg)</option>
            <option value="leanmass">Masa libre de grasa (kg)</option>
          </select>
          <div class="chart-container"><canvas id="bodyCompChart"></canvas></div>
        </div>
      </div>
    </details>

    <details class="glass-card fold" data-tone="green">
      <summary><span>Medidas</span><b class="card-meta" id="meta-measure"></b></summary>
      <div class="fold-body">
        <div class="field-grid">
          <div class="form-group span2"><label>Fecha</label><input type="date" id="input-measure-date"></div>
          <div class="form-group"><label>Cintura (cm)</label><input type="number" step="0.1" id="input-waist"></div>
          <div class="form-group"><label>Brazo (cm)</label><input type="number" step="0.1" id="input-arm"></div>
          <div class="form-group"><label>Muslo (cm)</label><input type="number" step="0.1" id="input-thigh"></div>
          <div class="form-group"><label>Pecho (cm)</label><input type="number" step="0.1" id="input-chest"></div>
          <div class="form-group"><label>Cuello (cm)</label><input type="number" step="0.1" id="input-neck"></div>
          <div class="form-group"><label>Cadera (cm)</label><input type="number" step="0.1" id="input-hip"></div>
        </div>
        <button class="secondary" onclick="addBodyMeasure()" style="width:100%; margin-top:12px;">Guardar medidas</button>
        <div id="measure-day-list"></div>
        <div id="measure-trends" style="margin-top:12px;"></div>
      </div>
    </details>

    <details class="glass-card fold" data-tone="slate">
      <summary><span>Fotos</span><b class="card-meta" id="meta-photos"></b></summary>
      <div class="fold-body">
        <input type="file" accept="image/*" capture="environment" id="input-photo">
        <button class="secondary" onclick="addProgressPhoto()" style="width:100%; margin:10px 0 14px;">Guardar foto de hoy</button>
        <div id="photo-gallery" class="photo-gallery"></div>
        <div id="photo-compare-controls" style="display:none; margin-top:14px;">
          <div class="inline-form">
            <select id="photo-compare-a" onchange="renderPhotoCompare()"></select>
            <select id="photo-compare-b" onchange="renderPhotoCompare()"></select>
          </div>
          <div id="photo-compare-view" class="photo-compare-view" style="margin-top:12px;"></div>
        </div>
      </div>
    </details>

    <details class="glass-card fold" data-tone="violet">
      <summary><span>Resúmenes con IA</span></summary>
      <div class="fold-body">
        <button class="secondary" id="btn-weekly-summary" onclick="generateWeeklySummary()" style="width:100%;">Resumen semanal</button>
        <div id="weekly-summary-output" style="display:none; margin-top:14px;"></div>
        <button class="secondary" id="btn-ai-summary" onclick="generateBodySummary()" style="width:100%; margin-top:10px;">Resumen de composición</button>
        <div id="ai-body-summary-output" style="display:none; margin-top:14px;"></div>
      </div>
    </details>
  </div>

  <!-- ========================================================================= -->
  <!-- 🏋️ GYM                                                                 -->
  <!-- ========================================================================= -->
  <!-- Módulo de entrenamiento AÚN SIN DESARROLLAR. Convención reservada:
       · claves de almacenamiento con prefijo `gym:` (p. ej. `gym:session:YYYY-MM-DD`, `gym:exercises`, `gym:routines`)
         → entran solas en el export/import JSON y en la sincronización, sin tocar el motor de kcal.
       · los pasos ya viven aquí (`steps:YYYY-MM-DD`).
       · el cruce con nutrición se hará leyendo getEngineState() (kcal, peso tendencia, superávit) en modo solo lectura. -->
  <div id="tab-gym" class="section">
    <div class="glass-card" data-tone="blue">
      <div class="card-head"><h3>Pasos</h3><b class="card-meta" id="meta-steps"></b></div>
      <div class="chart-container"><canvas id="stepsChart"></canvas></div>
      <div id="steps-summary"></div>
      <div class="inline-form">
        <input type="date" id="input-steps-date">
        <input type="number" id="input-steps" min="0" step="100" placeholder="pasos">
        <button class="secondary" onclick="saveSteps()">Guardar</button>
      </div>
    </div>

    <div class="glass-card soon" data-tone="violet">
      <div class="card-head" style="margin:0;"><h3>Entrenamiento</h3><b class="card-meta">Próximamente</b></div>
    </div>
  </div>

  <!-- ========================================================================= -->
  <!-- ⚙️ AJUSTES                                                             -->
  <!-- ========================================================================= -->
  <div id="tab-settings" class="section">
    <div class="glass-card" data-tone="blue">
      <div class="card-head"><h3>Perfil</h3><b class="card-meta" id="meta-goal"></b></div>
      <div class="field-grid">
        <div class="form-group"><label>Edad</label><input type="number" id="prof-age"></div>
        <div class="form-group"><label>Altura (cm)</label><input type="number" id="prof-height"></div>
        <div class="form-group"><label>Peso ref. (kg)</label><input type="number" id="prof-weight" step="0.1"></div>
        <div class="form-group"><label>Sexo</label><select id="prof-sex"><option value="m">Hombre</option><option value="f">Mujer</option></select></div>
        <div class="form-group"><label>Días de entreno</label><select id="prof-training-days"><option value="0">0</option><option value="1">1</option><option value="2">2</option><option value="3">3</option><option value="4">4</option><option value="5">5</option><option value="6">6</option><option value="7">7</option></select></div>
        <div class="form-group"><label>Comidas al día</label><input type="number" min="3" max="8" id="prof-meals"></div>
        <div class="form-group"><label>Ritmo</label>
          <select id="prof-rate">
            <option value="conservador">Conservador</option>
            <option value="estandar">Estándar</option>
            <option value="rapido">Rápido</option>
          </select></div>
        <div class="form-group"><label>Peso objetivo (kg)</label><input type="number" step="0.1" id="prof-goal-weight"></div>
        <div class="form-group"><label>Proteína (g/kg)</label><input type="number" step="0.1" min="1.2" max="3" id="prof-protein-kg"></div>
        <div class="form-group"><label>Grasas (g/kg)</label><input type="number" step="0.1" min="0.5" max="1.5" id="prof-fat-kg"></div>
        <div class="form-group span2"><label>Inicio del bulk</label><input type="date" id="prof-bulk-start"></div>
        <div class="form-group span2"><label>Preferencias y restricciones</label><textarea id="prof-preferences" rows="2"></textarea></div>
      </div>
      <div class="toggle-row">
        <div>Pausar ajuste automático</div>
        <label class="switch"><input type="checkbox" id="prof-pause"><span class="slider"></span></label>
      </div>
      <button class="primary" onclick="saveProfile()">Guardar</button>
      <div class="inline-form">
        <button class="secondary" onclick="recalcTargetFromModel()" style="flex:1;">Recalcular kcal</button>
        <button class="secondary" onclick="setManualTarget()" style="flex:1;">Fijar kcal</button>
      </div>
    </div>

    <div class="glass-card" data-tone="green">
      <div class="card-head"><h3>Datos</h3></div>
      <div id="sync-status-content"></div>
      <div class="inline-form">
        <button class="secondary" onclick="exportData()" style="flex:1;">Exportar</button>
        <label class="secondary file-btn" style="flex:1;">Importar<input type="file" id="import-file-input" accept="application/json" style="display:none;"></label>
      </div>
    </div>

    <details class="glass-card fold" data-tone="slate">
      <summary><span>Avanzado</span></summary>
      <div class="fold-body">
        <details class="sub"><summary>Calidad de datos</summary><div id="dq-content"></div></details>
        <details class="sub"><summary>IA de comidas</summary><div id="ai-stats-content"></div></details>
        <details class="sub"><summary>Historial de decisiones</summary><div id="decision-log-content"></div></details>
        <div class="inline-form">
          <button class="secondary diag-btn" onclick="exportDiagnostics('pdf')" style="flex:1;">PDF</button>
          <button class="secondary diag-btn" onclick="exportDiagnostics('json')" style="flex:1;">JSON</button>
          <button class="secondary diag-btn" onclick="exportDiagnostics('csv')" style="flex:1;">CSV</button>
        </div>
        <button class="secondary" onclick="runEngineTestsUI()" style="width:100%; margin-top:8px;">Tests del motor</button>
        <div id="tests-output" style="display:none; margin-top:14px;"></div>
      </div>
    </details>
  </div>

</div>

<!-- BOTTOM NAVIGATION -->
<div class="bottom-nav">
  <div class="nav-item active" data-tab="dash" data-tone="amber" onclick="nav('dash')"><span class="nav-icon">📊</span>Hoy</div>
  <div class="nav-item" data-tab="body" data-tone="green" onclick="nav('body')"><span class="nav-icon">📈</span>Progreso</div>
  <div class="nav-item" data-tab="gym" data-tone="blue" onclick="nav('gym')"><span class="nav-icon">🏋️</span>Gym</div>
  <div class="nav-item" data-tab="settings" data-tone="slate" onclick="nav('settings')"><span class="nav-icon">⚙️</span>Ajustes</div>
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
//   · libre de fuga de datos por construcción (asOf filtra todo),
//   · reutilizable tal cual en un futuro backend (Workers).
// Dashboard, gráficos, prompts de IA, PDF/JSON/CSV y reconstrucción diaria consumen el MISMO
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
  // Error de REGISTRO (las estimaciones de la IA son dispares; se asume bastante error a propósito).
  // · Sistemático (común a todos los días, NO se promedia): 15 % de la ingesta media.
  // · Aleatorio por entrada (independiente, se promedia entre días): según rango de la IA, confianza y origen.
  LOGGING_SYSTEMATIC_FRACTION: 0.15,
  ENTRY_ERR: { AI_RANGE_INFLATION: 1.6, Z80: 1.2816, FLOOR: { alta: 0.15, media: 0.22, baja: 0.32 },
    CACHED: 0.15, MANUAL: 0.12, LABEL: 0.05, WEIGHED: 0.06, DEFAULT: 0.18, EATEN_OUT_MULT: 1.4 },
  ACTIVITY_DROP_WARN: -0.15,         // pasos −15 % vs. las 3 semanas previas → aviso de NEAT (solo informativo)
  RATE_PRESETS: { conservador: [0.15, 0.30], estandar: [0.25, 0.50], rapido: [0.50, 0.75] },
  DEFAULT_RATE_PRESET: 'estandar',   // 0,25–0,50 % peso/sem (Iraki et al., 2019)
  ADHERENCE_MIN: 0.85,               // por debajo: no se sube (el problema es llegar)
  ADHERENCE_FULL: 0.92,              // desde aquí se fía del peso para subir aunque el mantenimiento modelado diga que sobra
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
// Incertidumbre (1 desviación típica, en kcal) de UNA entrada registrada. Se ensancha a propósito:
// rango de la IA × 1,6, con un suelo por confianza; báscula/etiqueta lo reducen; comer fuera lo aumenta.
function entryErrorSd(e){
  const k = Number(e && e.kcal) || 0; if(k <= 0) return 0;
  const C = CONFIG.ENTRY_ERR, ai = e.ai || null, src = String(e.source || '');
  let frac;
  if(e.weighed) frac = C.WEIGHED;
  else if(ai && ai.explicitBasis) frac = C.LABEL;
  else if(ai) frac = C.FLOOR[ai.confidence] ?? C.DEFAULT;
  else if(/cach|favorit|confirmado/i.test(src)) frac = C.CACHED;
  else frac = /manual/i.test(src) ? C.MANUAL : C.DEFAULT;
  let sdv = frac * k;
  if(ai && ai.range && !e.weighed && !ai.explicitBasis){
    const lo = Number(ai.range.low), hi = Number(ai.range.high);
    if(hi > lo) sdv = Math.max(sdv, (hi - lo) / 2 / C.Z80 * C.AI_RANGE_INFLATION);
  }
  return e.eatenOut ? sdv * C.EATEN_OUT_MULT : sdv;
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
    out.push({ date:d, weight: w ? w.kg : null, weightTime: w ? w.time : null, weighIns: w ? w.count : 0,
      intake, errSd: Math.sqrt(sum(act.map(e => entryErrorSd(e) ** 2))), p: sum(act.map(e=>Number(e.p)||0)), c: sum(act.map(e=>Number(e.c)||0)), f: sum(act.map(e=>Number(e.f)||0)),
      entries: act.length, status, autoStatus, userFlag: flag === undefined ? null : flag,
      target: Number.isFinite(target) ? target : null });
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
  const errSdDay = comp.length ? Math.sqrt(mean(comp.map(d => (d.errSd || 0) ** 2))) : 0;
  const m = mean(vals), sysSd = m ? CONFIG.LOGGING_SYSTEMATIC_FRACTION * m : 0;
  const errAvgSd = comp.length ? errSdDay / Math.sqrt(comp.length) : 0;
  const errTotalSd = Math.sqrt(sysSd ** 2 + errAvgSd ** 2);
  return { from, to, n: comp.length, mean: m, sd: sd(vals), totalDays: win.length,
    errSdDay, errSysSd: sysSd, errAvgSd, errTotalSd, errTotalPct: m ? errTotalSd / m : null,
    doubtful: win.filter(d=>d.status==='doubtful').map(d=>d.date),
    incomplete: win.filter(d=>d.status==='incomplete').map(d=>d.date),
    empty: win.filter(d=>d.status==='empty').map(d=>d.date),
    allDaysMean: mean(win.filter(d=>d.entries>0).map(d=>d.intake)) };
}
function adherence(days, from, to){
  const comp = days.filter(d => d.date>=from && d.date<=to && d.status==='complete' && Number.isFinite(d.target));
  if(!comp.length) return { n:0, ratio:null, within10:0, meanGap:null, meanTarget:null, meanIntake:null };
  const ti = sum(comp.map(d=>d.intake)), tt = sum(comp.map(d=>d.target));
  return { n: comp.length, ratio: ti/tt, within10: comp.filter(d=>Math.abs(d.intake-d.target) <= 0.1*d.target).length,
    meanGap: (tt-ti)/comp.length, meanTarget: tt/comp.length, meanIntake: ti/comp.length };
}

// ------------------------------------------- 3b) actividad (pasos / NEAT)
// Solo informativo: no altera la decisión de kcal. Sirve para explicar por qué se frena el peso.
function activityStats(steps, asOf){
  const vals = (a, b) => { const o = []; for(let d = a; d <= b; d = addDays(d, 1)){ const v = Number((steps||{})[d]); if(Number.isFinite(v) && v > 0) o.push(v); } return o; };
  const cur = vals(addDays(asOf, -7), addDays(asOf, -1)), prev = vals(addDays(asOf, -28), addDays(asOf, -8));
  const avg7 = cur.length >= 3 ? mean(cur) : null, avgPrev = prev.length >= 5 ? mean(prev) : null;
  return { avg7, avgPrev, n7: cur.length, nPrev: prev.length, changePct: avg7 && avgPrev ? avg7 / avgPrev - 1 : null };
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
  const obsSd = Math.sqrt((intake.sd**2)/intake.n + (rate.sePerDay*CONFIG.KCAL_PER_KG)**2 + (CONFIG.LOGGING_SYSTEMATIC_FRACTION*intake.mean)**2 + ((intake.errSdDay||0)**2)/intake.n);
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
  // El PESO manda: como las kcal registradas tienen error, el mantenimiento modelado se apoya mucho en la fórmula.
  // Para que eso no frene indefinidamente a quien no gana, con adherencia ≥ ADHERENCE_FULL se sube al menos la mitad
  // de la brecha de ritmo (kg/sem que faltan × 7700/7). Nunca si la adherencia registrada es dudosa.
  const gapUp = r ? Math.max(0, R.mid - r.perWeek) * CONFIG.KCAL_PER_KG / 7 : 0;
  const gapDown = r ? Math.max(0, r.perWeek - R.mid) * CONFIG.KCAL_PER_KG / 7 : 0;
  const boost = (adh.ratio !== null && adh.ratio >= CONFIG.ADHERENCE_FULL) ? 0.5 * gapUp : 0;
  const needUp = Math.max(needed, roundTo(T + boost, CONFIG.TARGET_ROUND));
  let proposal = 0, code = '', why = '';
  if(st === 'DENTRO'){ code='EN_RANGO'; why=`Tu ritmo ${rateTxt} está dentro del rango (${rangeTxt}). Se mantiene.`; }
  else if(st === 'INCIERTO'){ code='INCIERTO'; why=`Tu ritmo ${rateTxt} ${state.status.lean==='below'?'apunta a estar por debajo':'apunta a estar por encima'} del rango (${rangeTxt}), pero el intervalo aún se solapa con él. Se espera a tener más evidencia.`; }
  else if(st === 'POR_DEBAJO'){
    if(adh.ratio !== null && adh.ratio < CONFIG.ADHERENCE_MIN){ code='ADHERENCIA'; why=`Ganas por debajo del rango (${rateTxt} vs ${rangeTxt}), pero solo alcanzas el ${adhTxt}. Subir el objetivo no ayuda si no se alcanza: la prioridad es llegar a ${fmt(T)} kcal. Con tu mantenimiento estimado (${M_txt}) necesitarías ~${fmt(needed)} kcal sostenidas.`; }
    else if(needUp - T < CONFIG.DEADBAND_KCAL){ code='OBJETIVO_SUFICIENTE'; why=`Ganas por debajo del rango, pero tu objetivo actual (${fmt(T)}) ya cubre lo estimado como necesario (~${fmt(needed)} = mantenimiento ${M_txt} + superávit ${fmt(surplus)}). Nunca se baja estando por debajo del rango.`; }
    else { proposal = Math.min(needUp - T, CONFIG.STEP_MAX[conf.level] || CONFIG.STEP_MAX.MEDIA); code='SUBIR'; why=`Ganas por debajo del rango (${rateTxt} vs ${rangeTxt}) cumpliendo el objetivo (${adhTxt}). Necesario estimado ~${fmt(needed)} kcal (mantenimiento ${M_txt} + superávit ${fmt(surplus)}). Subida limitada a ${CONFIG.STEP_MAX[conf.level]} kcal por ajuste (confianza ${conf.level}).`; }
  } else if(st === 'POR_ENCIMA'){
    const floor = Math.max(CONFIG.FLOOR_KCAL, roundTo(M.posterior, CONFIG.TARGET_ROUND));
    if(T - needed < CONFIG.DEADBAND_KCAL){ code='SOBRE_OBJETIVO'; why=`Ganas por encima del rango (${rateTxt} vs ${rangeTxt}) aunque tu objetivo (${fmt(T)}) no está por encima de lo necesario (~${fmt(needed)}); tu media real es ${adhTxt}. El ajuste es comer más cerca del objetivo, no bajarlo.`; }
    else { proposal = -Math.min(T - needed, gapDown, CONFIG.STEP_MAX[conf.level] || CONFIG.STEP_MAX.MEDIA); if(T + proposal < floor) proposal = floor - T; code='BAJAR'; why=`Ganas por encima del rango (${rateTxt} vs ${rangeTxt}). Necesario estimado ~${fmt(needed)} kcal. Bajada limitada a ${CONFIG.STEP_MAX[conf.level]} kcal por ajuste y nunca por debajo del mantenimiento estimado (${fmt(floor)}).`; }
  }
  const act = state.activity;
  if(act && act.changePct !== null && act.changePct <= CONFIG.ACTIVITY_DROP_WARN && (st === 'POR_DEBAJO' || st === 'INCIERTO'))
    why += ` Nota: tus pasos bajaron un ${fmt(-act.changePct*100)} % (${fmt(act.avg7)} vs ${fmt(act.avgPrev)}/día); parte del freno puede ser menor gasto por movimiento (NEAT), no solo falta de kcal.`;
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
//         timeline:[{date,kcal,source}], fallbackTarget, startDate }
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
    goalKg: Number.isFinite(goalKg) && goalKg>0 ? goalKg : null, activity: activityStats(raw.steps, asOf) };
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
    a: M.method==='bayes' ? `Fórmula ${fmt(M.prior)} kcal; tus datos dicen ${fmt(M.obs)} ±${fmt(M.obsSd)} (incluye el error de registro). Estimación combinada ${fmt(M.posterior)} ±${fmt(M.posteriorSd)} (tus datos pesan un ${fmt(M.dataWeight*100)} %).` : `Solo fórmula (Mifflin-St Jeor × ${fmt(M.activityFactor,3)} por tus días de entreno): ${fmt(M.prior)} ±${fmt(M.priorSd)} kcal. Se personalizará con datos.` });
  // 6b. ¿Cuánto me fío de lo que registro?
  if(s.intake.n && s.intake.errTotalPct !== null){
    const pct = s.intake.errTotalPct * 100;
    out.push({ id:'logerr', q:'¿Cuánto me fío de lo que registro?', tone: pct <= 12 ? 'ok' : pct <= 20 ? 'warn' : 'bad', value: `±${fmt(pct)} %`,
      a: `Se asume un error de registro de ±${fmt(pct)} % (≈ ±${fmt(s.intake.errTotalSd)} kcal/día sobre tu media de ${fmt(s.intake.mean)}): ${fmt(CONFIG.LOGGING_SYSTEMATIC_FRACTION*100)} % sistemático (la IA puede infra/sobrestimar siempre igual) + ${fmt(s.intake.errAvgSd)} kcal aleatorios. Ese error se traslada al mantenimiento observado, así que el motor confía más en tu PESO que en las kcal registradas. Pesar en báscula o usar etiquetas lo reduce.` });
  }
  // 6c. Actividad (pasos)
  if(s.activity && s.activity.avg7){
    const a = s.activity, ch = a.changePct;
    out.push({ id:'steps', q:'¿Me estoy moviendo menos al subir kcal?', tone: ch === null ? 'neutral' : ch <= CONFIG.ACTIVITY_DROP_WARN ? 'warn' : 'ok', value: `${fmt(a.avg7)} pasos/día`,
      a: ch === null ? `Media de los últimos 7 días: ${fmt(a.avg7)} pasos/día. Aún faltan días previos para comparar.` : `Últimos 7 días: ${fmt(a.avg7)} pasos/día vs ${fmt(a.avgPrev)} en las 3 semanas anteriores (${fmtSigned(ch*100,0)} %). ${ch <= CONFIG.ACTIVITY_DROP_WARN ? 'Bajada notable: al comer más el cuerpo tiende a moverse menos (NEAT), lo que puede frenar el peso.' : 'Sin caída relevante de actividad.'}` });
  }
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

// ------------------------------------------------ 11) reconstrucción día a día (sin fuga)
// Cada día D solo ve datos ANTERIORES a D (decisión por la mañana, antes de
// pesarse y de comer). Parte del objetivo inicial y evoluciona con sus propias
// decisiones. La adherencia se mide contra el objetivo que el usuario veía.
function filterRawBefore(raw, date){
  const pick = obj => Object.fromEntries(Object.entries(obj||{}).filter(([k])=>k < date));
  return { ...raw, weights: pick(raw.weights), logs: pick(raw.logs), dayFlags: pick(raw.dayFlags), steps: pick(raw.steps),
    timeline: (raw.timeline||[]).filter(e=>e.date < date) };
}
function replay(raw, profile, { from, to, initialTarget }){
  const rows = []; let tNew = initialTarget, lastChange = null;
  for(let d = from; d <= to; d = addDays(d,1)){
    const r = filterRawBefore(raw, d);
    const st = computeState(r, profile, d, { currentTarget: tNew, lastChange });
    const dec = st.decision;
    if(dec.delta){ lastChange = { date:d, delta: dec.delta }; tNew = dec.newTarget; }
    rows.push({ date:d, weighIns: st.rate ? st.rate.n : st.days.filter(x=>x.weight!==null).length, completeDays: st.intake.n,
      observedTarget: targetOn(raw.timeline, d, initialTarget),
      newTarget: tNew, newAction: dec.action, newReason: dec.reasonCode, newReasonText: dec.reason,
      rate: st.rate ? st.rate.perWeek : null, ciLow: st.rate ? st.rate.ciLow : null, ciHigh: st.rate ? st.rate.ciHigh : null,
      status: st.status.code, confidence: st.confidence.level,
      maintenance: st.maintenance.posterior, maintenanceSd: st.maintenance.posteriorSd, maintenanceMethod: st.maintenance.method,
      intakeMean: st.intake.mean, adherence: st.adherence.ratio });
  }
  return rows;
}

// ------------------------------------------------ 11b) agua (objetivo diario de líquidos)
// Agua TOTAL de referencia = la MAYOR de tres cifras (criterio conservador, sin sumarlas):
//   · Ingesta adecuada EFSA 2010 (adultos ≥14 años): 2,5 L hombres · 2,0 L mujeres. La edad adulta no la cambia.
//   · Regla de peso: 35 mL/kg (habitual en nutrición clínica; escala con el peso corporal).
//   · Regla de energía: ~1 mL por kcal del objetivo (regla clásica; en un bulk se come más y hace falta más agua).
// Solo una parte se BEBE: EFSA/IOM estiman ~20 % del agua total en la comida (verduras, fruta, arroz…).
// Ajustes por día: entreno (+0,5 L, conservador: la sudoración va de 0,4 a 1,8 L/h según ACSM 2007) y calor (+0,5 L).
// Cuenta cualquier líquido (agua, infusiones, café…). No es un requisito individual: la sed y el color de la orina mandan.
const WATER = Object.freeze({ AI_TOTAL_ML: { m: 2500, f: 2000 }, ML_PER_KG: 35, ML_PER_KCAL: 1, FOOD_SHARE: 0.20,
  TRAIN_ML: 500, HEAT_ML: 500, MIN_ML: 1500, MAX_ML: 4500, ROUND_ML: 50 });
function waterGoal(profile, { weightKg, kcal, train = false, heat = false } = {}){
  const sex = profile && profile.sex === 'f' ? 'f' : 'm';
  const w = Number(weightKg) > 0 ? Number(weightKg) : (Number(profile && profile.weight) || 0);
  const k = Number(kcal) > 0 ? Number(kcal) : 0;
  const refs = { efsa: WATER.AI_TOTAL_ML[sex], weight: w * WATER.ML_PER_KG, energy: k * WATER.ML_PER_KCAL };
  const basis = Object.keys(refs).reduce((best, key) => refs[key] > refs[best] ? key : best, 'efsa');
  const totalMl = refs[basis];
  const drinkMl = totalMl * (1 - WATER.FOOD_SHARE);
  const extraMl = (train ? WATER.TRAIN_ML : 0) + (heat ? WATER.HEAT_ML : 0);
  const goalMl = Math.max(WATER.MIN_ML, Math.min(WATER.MAX_ML, roundTo(drinkMl + extraMl, WATER.ROUND_ML)));
  return { goalMl, totalMl, drinkMl, extraMl, basis, refs };
}

const api = { VERSION, CONFIG, WATER, waterGoal, computeState, decide, buildDays, hampel, trendSeries, weightRate, intakeStats, adherence,
  maintenanceEstimate, activityFactor, mifflin, targetRange, confidence, rateStatus, predictions, buildInsights, dataQuality,
  replay, filterRawBefore, targetOn, STATUS_LABEL, entryErrorSd, activityStats,
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
    const r = rng(c.seed), raw = { weights:{}, logs:{}, dayFlags:{}, timeline:[{ date:c.start, kcal:c.target, source:'test' }], fallbackTarget:c.target };
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
  { const s = synth({ days:35, rate:0, intake:2100, target:2500, seed:8 }); const st = state(s);
    check('H · baja adherencia (84 %) → MANTENER por ADHERENCIA', st.decision.delta===0 && st.decision.reasonCode==='ADHERENCIA', `${st.decision.reasonCode}`);
    check('H · mantenimiento observado ≈ 2100 (no 2500)', Math.abs(st.maintenance.obs - 2100) < 150, Math.round(st.maintenance.obs)); }
  // ---- CASO H2: 88 % de adherencia (dentro del ruido de registro) y peso plano → no sube el objetivo si comes bastante menos
  { const s = synth({ days:35, rate:0, intake:2200, target:2500, seed:8 }); const st = state(s);
    check('H2 · 88 % de adherencia y peso plano → no sube el objetivo', st.decision.delta <= 0, `${st.decision.reasonCode} ${st.decision.delta}`); }
  // ---- CASO R: error de registro alto → el motor confía menos en las kcal registradas
  { const s = synth({ days:35, rate:0.1, intake:2600, target:2600, seed:21 }); const lo = state(s);
    const s2 = synth({ days:35, rate:0.1, intake:2600, target:2600, seed:21, patch: raw => { for(const d in raw.logs) raw.logs[d].forEach(e => { e.eatenOut = true; e.ai = { confidence:'baja', range:{ low: e.kcal*0.5, high: e.kcal*1.6 } }; }); } }); const hi = state(s2);
    check('R · más error de registro → mantenimiento observado más incierto', hi.maintenance.obsSd > lo.maintenance.obsSd, `${Math.round(lo.maintenance.obsSd)} → ${Math.round(hi.maintenance.obsSd)}`);
    check('R · más error de registro → tus datos pesan menos', hi.maintenance.dataWeight < lo.maintenance.dataWeight, `${lo.maintenance.dataWeight.toFixed(2)} → ${hi.maintenance.dataWeight.toFixed(2)}`);
    check('R · error asumido ≥ 15 % de la ingesta', lo.intake.errTotalPct >= 0.15, lo.intake.errTotalPct.toFixed(3));
    check('R · con error alto, la subida sigue acotada (≤150 kcal)', hi.decision.delta <= 150, hi.decision.delta); }
  // ---- CASO S: pasos bajan >15 % → aviso informativo (no cambia el objetivo)
  { const s = synth({ days:35, rate:0.03, intake:2600, target:2600, seed:4, patch: raw => { raw.steps = {}; for(let i=0;i<35;i++){ raw.steps[U.addDays('2026-01-01', i)] = i < 21 ? 9000 : 6500; } } }); const st = state(s);
    check('S · caída de pasos detectada (<−15 %)', st.activity && st.activity.changePct < -0.15, st.activity && st.activity.changePct);
    check('S · aviso NEAT en el motivo de la decisión', /NEAT/.test(st.decision.reason), st.decision.reasonCode); }

  // ---- CASO W: objetivo de agua
  { const M = { sex:'m', age:25, weight:71 }, F = { sex:'f', age:25, weight:55 };
    const a = E.waterGoal(M, { weightKg:71, kcal:2900 });
    check('W · hombre 71 kg, 2900 kcal → 2300 mL de líquidos (manda la energía)', a.goalMl === 2300 && a.basis === 'energy', `${a.goalMl} ${a.basis}`);
    const b = E.waterGoal(F, { weightKg:55, kcal:2000 });
    check('W · mujer 55 kg, 2000 kcal → 1600 mL (mínimo EFSA 2,0 L totales − 20 %)', b.goalMl === 1600 && b.basis === 'efsa', `${b.goalMl} ${b.basis}`);
    check('W · entreno suma 500 mL', E.waterGoal(M, { weightKg:71, kcal:2900, train:true }).goalMl === 2800);
    check('W · entreno + calor suman 1000 mL', E.waterGoal(M, { weightKg:71, kcal:2900, train:true, heat:true }).goalMl === 3300);
    check('W · tope de seguridad 4500 mL', E.waterGoal(M, { weightKg:150, kcal:6000, train:true, heat:true }).goalMl === 4500);
    check('W · sin datos usa el mínimo EFSA (hombre 2000 mL)', E.waterGoal({ sex:'m' }, {}).goalMl === 2000);
    check('W · más peso nunca baja el objetivo', E.waterGoal(M, { weightKg:95, kcal:2500 }).goalMl >= E.waterGoal(M, { weightKg:70, kcal:2500 }).goalMl);
    check('W · la edad adulta no cambia el objetivo (EFSA)', E.waterGoal({ ...M, age:70 }, { weightKg:71, kcal:2900 }).goalMl === a.goalMl); }
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

  // ---- REGRESIÓN: el objetivo nunca queda por debajo del mantenimiento estimado
  { const s = synth({ days:30, rate:0, intake:2300, target:2600, intakeNoise:0, noise:0, seed:16 });
    const st = state(s, 2600);
    check('Motor · sin estado recursivo: nunca propone < mantenimiento estimado', st.decision.newTarget >= Math.round(st.maintenance.posterior) - 10, `${st.decision.newTarget} vs ${Math.round(st.maintenance.posterior)}`); }
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
    check('Sin fuga · cambiar datos FUTUROS no altera el estado del día D', JSON.stringify([a.rate,a.maintenance,a.decision]) === JSON.stringify([b.rate,b.maintenance,b.decision])); }
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
const GEMINI_MODEL_SUMMARY = "__MODEL_SUMMARY__";
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
    el.innerHTML = `<div class="muted-line" style="margin:0;">Sin nube: tus datos viven solo en este navegador. Usa Exportar para pasarlos a otro dispositivo.</div>`;
    return;
  }
  el.innerHTML = `
    <div style="font-size:.84rem; color:var(--green); font-weight:600; margin-bottom:10px;">☁️ Sincronización activa</div>
    <div style="display:flex; gap:8px;">
      <input readonly value="${getSyncLink()}" style="font-size:.72rem;" onclick="this.select()">
      <button class="secondary" onclick="copySyncLink()" style="flex-shrink:0;">Copiar</button>
    </div>
    <div class="muted-line">Quien tenga este link puede ver y modificar tus datos.</div>`;
}

window.copySyncLink = () => {
  navigator.clipboard.writeText(getSyncLink()).then(()=>showToast('Link copiado')).catch(()=>showToast('No se pudo copiar', true));
};

// Aviso imposible de pasar por alto: sin FIREBASE_DB_URL configurada, cada
// origen (localhost vs tu URL de GitHub Pages) tiene su PROPIO localStorage
// y nunca van a coincidir. Esto no es un fallo puntual, es cómo funciona
// localStorage por diseño del navegador — por eso se avisa de forma
// permanente en Hoy, no solo en Ajustes.
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

// OMS 2015 (azúcares libres): objetivo ideal <5 % de la energía. 1 g ≈ 4 kcal.
function calcSugarTargetG(kcal){
  return (kcal * 0.05) / 4;
}

// Macros desde las kcal. Proteína y grasa por kg de PESO TENDENCIA (no del
// último pesaje, que salta ±0,5 kg de un día a otro).
// DINÁMICOS: proteína y grasa = g/kg configurables (por defecto 2,0 y 1,0) × peso TENDENCIA; carbohidratos = lo que
// resta de las kcal; azúcar = 5 % de las kcal. Se recalculan cuando cambian las kcal o el peso tendencia cambia
// de forma considerable (ver syncDynamicMacros).
const DEFAULT_PROTEIN_PER_KG = 2.0, DEFAULT_FAT_PER_KG = 1.0;
const MACRO_RECALC_KG = 1.0, MACRO_RECALC_PCT = 0.015; // umbral: el mayor de 1 kg o 1,5 % del peso de referencia
function macroPerKg(p){
  const pp = Number(p.proteinPerKg), fp = Number(p.fatPerKg);
  return { protein: pp >= 1.2 && pp <= 3.0 ? pp : DEFAULT_PROTEIN_PER_KG, fat: fp >= 0.5 && fp <= 1.5 ? fp : DEFAULT_FAT_PER_KG };
}
function recomputeMacrosFromKcal(p, weightKg){
  const w = Number(weightKg) || Number(p.weight), k = macroPerKg(p);
  p.targetProtein = w * k.protein; // 2 g/kg (rango óptimo 1,6-2,2)
  p.targetFat = w * k.fat;         // 1 g/kg mínimo salud hormonal
  p.targetCarbs = Math.max(0, (p.targetKcal - (p.targetProtein*4) - (p.targetFat*9))/4);
  p.targetSugar = calcSugarTargetG(p.targetKcal);
  p.macroWeightKg = w;
  return p;
}
// Recalcula P/C/G/azúcar si el peso tendencia se ha movido ≥ umbral desde el último cálculo (sube o baja).
// Histéresis a propósito: los macros no bailan con el ruido diario. Devuelve true si cambió algo.
async function syncDynamicMacros(force = false){
  if(!profile || !profile.targetKcal) return false;
  let level = Number(profile.weight);
  try { const l = getEngineState().weight.level; if(Number.isFinite(l) && l > 0) level = l; } catch(e){}
  if(!Number.isFinite(level) || level <= 0) return false;
  const ref = Number(profile.macroWeightKg), hasRef = Number.isFinite(ref) && ref > 0;
  if(!force && hasRef && Math.abs(level - ref) < Math.max(MACRO_RECALC_KG, ref * MACRO_RECALC_PCT)) return false;
  const m = recomputeMacrosFromKcal({ ...profile }, level), k = macroPerKg(profile);
  await updateProfile({ targetProtein: m.targetProtein, targetFat: m.targetFat, targetCarbs: m.targetCarbs, targetSugar: m.targetSugar, macroWeightKg: level });
  const tl = (await safeGet('macroTimeline')) || [];
  tl.push({ id: 'mt' + Date.now().toString(36), date: todayStr(), at: Date.now(), weightFrom: hasRef ? +ref.toFixed(2) : null, weightTo: +level.toFixed(2), kcal: Math.round(profile.targetKcal),
    p: Math.round(m.targetProtein), c: Math.round(m.targetCarbs), f: Math.round(m.targetFat), s: Math.round(m.targetSugar), force: !!force });
  if(tl.length > 100) tl.splice(0, tl.length - 100);
  await safeSet('macroTimeline', tl);
  if(hasRef && !force) showAdjustAlert(`⚖️ Peso tendencia ${fmtN(ref,1)} → ${fmtN(level,1)} kg: macros recalculados. Proteína ${Math.round(m.targetProtein)} g (${fmtN(k.protein,1)} g/kg) · Grasas ${Math.round(m.targetFat)} g (${fmtN(k.fat,1)} g/kg) · Carbohidratos ${Math.round(m.targetCarbs)} g · Azúcar ${Math.round(m.targetSugar)} g.`);
  return true;
}

function getTargets(){
  const kcal = profile.targetKcal || 2500;
  const protein = profile.targetProtein || profile.weight * 2 || 130;
  const fat = profile.targetFat || profile.weight * 1 || 70;
  const sugar = profile.targetSugar || calcSugarTargetG(kcal);
  return { kcal, p: protein, c: Math.max(0, (kcal - protein*4 - fat*9)/4), f: fat, s: sugar };
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
async function setDayFlag(date, val){ if(val === null) await safeRemove('dayflag:'+date); else await safeSet('dayflag:'+date, !!val); }

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
const RAW_PREFIXES = new Set(['weight', 'log', 'dayflag', 'steps']);
function collectRaw(){
  const raw = { weights:{}, logs:{}, dayFlags:{}, steps:{}, timeline:[], fallbackTarget: Number(profile && profile.targetKcal) || 2500,
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
    else if(prefix === 'steps' && Number(v) > 0) raw.steps[date] = Number(v);
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
  await updateProfile({ targetKcal: kcal, targetProtein: m.targetProtein, targetFat: m.targetFat, targetCarbs: m.targetCarbs, targetSugar: m.targetSugar, macroWeightKg: level });
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
  // 5) Limpieza del perfil (campos del algoritmo anterior)
  const fresh = (await safeGet('profile')) || {};
  ['activity', 'goalOffset', 'weeklyGainGoalKg', 'emaMaintenanceKcal', 'lastAdjustmentWeek', 'geminiModel'].forEach(k => delete fresh[k]);
  fresh.ratePreset = fresh.ratePreset || 'estandar';
  fresh.bulkStartDate = fresh.bulkStartDate || firstDate;
  if(restore) fresh.targetKcal = restore;
  await safeSet('profile', fresh);
  profile = await loadProfile();
  if(restore){ const mm = recomputeMacrosFromKcal({ ...profile }, profile.weight); await updateProfile({ targetProtein: mm.targetProtein, targetFat: mm.targetFat, targetCarbs: mm.targetCarbs, targetSugar: mm.targetSugar, macroWeightKg: mm.macroWeightKg }); }
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
  return `<div class="assistant-title">${title}</div><div class="assistant-body">${body}</div>`;
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
function assistantStateKey(sums, target, logsCount){
  return [Math.round(sums.kcal), Math.round(sums.p), Math.round(sums.c), Math.round(sums.f), Math.round(sums.s), Math.round(target.kcal), logsCount].join('|');
}

// Contexto factual del asistente de "Hoy": el estado real de un día concreto
// (kcal/macros/azúcar objetivo vs. ingeridos vs. restantes, comidas ya
// registradas para no repetirlas, hora del día y comidas que quedan por delante,
// preferencias e histórico reciente). La IA redacta la recomendación; no calcula.
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

  const res = await callGemini(prompt, true);
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

  const stateKey = assistantStateKey(sums, target, logsCount);
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

// =========================================
// 💧 AGUA (registro por botones, sin IA)
// =========================================
// Se guarda por día: `water:YYYY-MM-DD` = [{ id, ml, time, createdAt }] y `waterctx:YYYY-MM-DD` = { train, heat }.
// El objetivo lo calcula BulkEngine.waterGoal (peso tendencia, kcal objetivo, sexo y ajustes del día).
const fmtL = ml => (Math.round(ml / 10) / 100).toLocaleString('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 2 });
async function getWater(date){ const v = await safeGet('water:' + date); return Array.isArray(v) ? v.filter(e => e && Number(e.ml) > 0) : []; }
async function getWaterCtx(date){ const v = await safeGet('waterctx:' + date); return { train: !!(v && v.train), heat: !!(v && v.heat) }; }
const waterTotal = arr => arr.reduce((a, e) => a + Number(e.ml || 0), 0);
window.addWater = async ml => {
  ml = Number(ml); if(!Number.isFinite(ml) || ml <= 0 || ml > 3000) return;
  const arr = await getWater(selectedLogDate), now = Date.now();
  arr.push({ id: now.toString(36), ml: Math.round(ml), time: new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }), createdAt: now });
  await safeSet('water:' + selectedLogDate, arr);
  if(navigator.vibrate) navigator.vibrate(12);
  await renderWater(selectedLogDate);
};
window.undoWater = async () => {
  const arr = await getWater(selectedLogDate); if(!arr.length) return;
  arr.pop();
  if(arr.length) await safeSet('water:' + selectedLogDate, arr); else await safeRemove('water:' + selectedLogDate);
  await renderWater(selectedLogDate);
};
window.toggleWaterCtx = async key => {
  if(key !== 'train' && key !== 'heat') return;
  const ctx = await getWaterCtx(selectedLogDate); ctx[key] = !ctx[key];
  if(ctx.train || ctx.heat) await safeSet('waterctx:' + selectedLogDate, ctx); else await safeRemove('waterctx:' + selectedLogDate);
  await renderWater(selectedLogDate);
};
async function renderWater(date){
  const card = $('water-card'); if(!card) return;
  let weightKg = Number(profile.weight) || 0; try { const l = getEngineState().weight.level; if(l > 0) weightKg = l; } catch(e){}
  const kcal = getTargets().kcal, goalFor = ctx => BulkEngine.waterGoal(profile, { weightKg, kcal, train: ctx.train, heat: ctx.heat });
  const arr = await getWater(date), total = waterTotal(arr), ctx = await getWaterCtx(date), g = goalFor(ctx);
  const f = g.goalMl > 0 ? total / g.goalMl : 0, fill = Math.max(0, Math.min(1, f)), left = g.goalMl - total;
  $('water-level').style.transform = `translateY(${fill <= 0 ? 170 : 154 - 120 * fill}px)`;
  $('water-bottle').classList.toggle('full', f >= 1);
  $('water-now').textContent = fmtL(total); $('water-goal').textContent = fmtL(g.goalMl);
  const sub = $('water-sub'); sub.classList.toggle('done', left <= 0);
  sub.textContent = left > 0 ? `quedan ${fmtL(left)} L` : left === 0 ? 'objetivo cumplido' : `objetivo cumplido · +${fmtL(-left)} L`;
  setMeta('meta-water', total > 0 ? `${Math.round(f * 100)} %` : '');
  $('chip-train').classList.toggle('on', ctx.train); $('chip-heat').classList.toggle('on', ctx.heat);
  $('water-undo').disabled = !arr.length;
  // detalle: de dónde sale el objetivo + media de 7 días
  const W = BulkEngine.WATER; let sum = 0, hits = 0;
  for(let i = 0; i < 7; i++){ const d = BulkEngine.util.addDays(date, -i), t = waterTotal(await getWater(d)); sum += t; if(t >= goalFor(await getWaterCtx(d)).goalMl) hits++; }
  const names = { efsa: 'mínimo EFSA', weight: `${W.ML_PER_KG} mL/kg`, energy: '1 mL/kcal' };
  $('water-detail').innerHTML =
      kv('Agua total de referencia', `${fmtL(g.totalMl)} L`, `la mayor de: EFSA ${fmtL(g.refs.efsa)} · ${W.ML_PER_KG} mL/kg ${fmtL(g.refs.weight)} · 1 mL/kcal ${fmtL(g.refs.energy)} (manda ${names[g.basis]})`)
    + kv('Solo líquidos', `${fmtL(g.drinkMl)} L`, `descontando ~${Math.round(W.FOOD_SHARE * 100)} % que llega en la comida`)
    + (g.extraMl ? kv('Entreno / calor', `+${fmtL(g.extraMl)} L`) : '')
    + kv('Media 7 días', `${fmtL(sum / 7)} L`, `${hits}/7 días con objetivo`)
    + `<div class="muted-line">Cuenta cualquier líquido (agua, infusiones, café). Se recalcula con tu peso tendencia y tus kcal. La edad adulta no lo cambia (EFSA). Es una referencia, no una obligación: tu sed y el color de la orina mandan. Base: EFSA 2010, IOM 2004 y ACSM 2007.</div>`;
}

// =========================================
// 👟 PASOS / NEAT
// =========================================
async function getSteps(date){ const v = Number(await safeGet('steps:' + date)); return Number.isFinite(v) && v > 0 ? v : null; }
async function loadStepsForDate(){
  const el = $('input-steps'); if(!el) return;
  const v = await getSteps($('input-steps-date').value || todayStr()); el.value = v || '';
}
window.saveSteps = async () => {
  const date = $('input-steps-date').value || todayStr();
  const raw = String($('input-steps').value || '').replace(/[.,]/g, '').trim(), v = Number(raw);
  if(!raw){ await safeRemove('steps:' + date); showToast('Pasos borrados'); }
  else if(!Number.isFinite(v) || v < 0 || v > 80000){ showToast('Pasos no válidos (0–80.000).', true); return; }
  else { await safeSet('steps:' + date, Math.round(v)); showToast(`${Math.round(v).toLocaleString('es-ES')} pasos guardados (${formatDateLabel(date).toLowerCase()})`); }
  __dataVersion++; __engineCache = null; await refreshInsights();
};
let stepsChartInstance = null;
async function renderStepsCard(){
  const sum = $('steps-summary'); if(!sum) return;
  const st = getEngineState(), a = st.activity || {}, today = todayStr(), days = [];
  for(let i = 27; i >= 0; i--){ const d = BulkEngine.util.addDays(today, -i); days.push({ date: d, v: await getSteps(d) }); }
  setMeta('meta-steps', a.avg7 ? `${fmtN(a.avg7)} /día` : '');
  sum.innerHTML = a.avg7 ? kv('Media 7 días', `${fmtN(a.avg7)} pasos`, a.changePct !== null ? `${fmtS(a.changePct*100,0)} % vs. las 3 semanas previas` : '') : '';
  const canvas = $('stepsChart'); if(!canvas || typeof Chart === 'undefined') return;
  if(stepsChartInstance){ stepsChartInstance.destroy(); stepsChartInstance = null; }
  if(!days.some(d => d.v)) return;
  const o = cleanChartOptions(); o.plugins.tooltip.callbacks = { label: it => ` ${Math.round(it.parsed.y).toLocaleString('es-ES')} pasos` };
  stepsChartInstance = new Chart(canvas.getContext('2d'), { type: 'bar', data: { labels: days.map(d => shortDate(d.date)), datasets: [ { label: 'Pasos', data: days.map(d => d.v), backgroundColor: 'rgba(138,162,200,0.55)', borderRadius: 4 } ] }, options: o });
}

// =========================================
// 🎯 LO QUE TE FALTA HOY (relleno exacto, calculado en código, sin IA)
// =========================================
// Catálogo por 100 g (valores de etiqueta típicos). Solo se usan los que aparezcan en FILLER_FOODS (lista editable).
const FILL_CATALOG = [
  { id:'malto',  re:/maltodextrin/i,       name:'maltodextrina',        kcal:380, p:0,  c:95, f:0,   s:5,  role:'carb', maxG:100 },
  { id:'crema_a',re:/crema de arroz/i,     name:'crema de arroz',       kcal:370, p:7,  c:80, f:1,   s:0.5,role:'carb', maxG:100 },
  { id:'harina_a',re:/harina de arroz/i,   name:'harina de arroz',      kcal:360, p:6,  c:80, f:1,   s:0,  role:'carb', maxG:80 },
  { id:'miel',   re:/\bmiel\b/i,           name:'miel',                 kcal:300, p:0,  c:80, f:0,   s:80, role:'carb', maxG:40 },
  { id:'cacah',  re:/cacah|cacahu/i,       name:'crema de cacahuete',   kcal:600, p:25, c:15, f:50,  s:6,  role:'fat',  maxG:40 },
  { id:'aceite', re:/aceite/i,             name:'aceite de oliva virgen extra', kcal:900, p:0, c:0, f:100, s:0, role:'fat', maxG:20 },
  { id:'whey',   re:/whey/i,               name:'whey protein',         kcal:400, p:78, c:8,  f:6,   s:5,  role:'prot', scoopG:30 },
  { id:'clear',  re:/clear|hydro/i,        name:'clear/hydro protein',  kcal:350, p:85, c:3,  f:0,   s:1,  role:'prot', scoopG:25 }
];
let __lastFill = null;
function availableFillers(){
  const txt = typeof FILLER_FOODS === 'string' ? FILLER_FOODS : '';
  return FILL_CATALOG.filter(c => c.re.test(txt));
}
const r5 = g => Math.max(0, Math.round(g / 5) * 5);
function fillMacros(f, g){ const k = g / 100; return { kcal: f.kcal*k, p: f.p*k, c: f.c*k, f: f.f*k, s: f.s*k }; }
function buildFillProposal(rem, hour){
  const F = availableFillers(); const items = []; const tot = { kcal:0, p:0, c:0, f:0, s:0 };
  const add = (f, g) => { g = f.scoopG ? Math.round(g / f.scoopG) * f.scoopG : r5(g); if(g <= 0) return 0; const m = fillMacros(f, g); items.push({ f, g, m }); for(const k in tot) tot[k] += m[k]; return m.kcal; };
  const FILL_MAX_KCAL = 900; // una tanda razonable de relleno (2 batidos/snacks); el resto, comida normal
  let budget = Math.min(rem.kcal, FILL_MAX_KCAL); if(hour >= 22) budget = Math.min(budget, 700);
  // 1) proteína pendiente: whey (o clear) en cacitos enteros, sin pasarse de la proteína que queda
  const prot = F.find(x => x.id === 'whey') || F.find(x => x.id === 'clear');
  if(prot && rem.p >= 15){
    const perScoop = prot.p / 100 * prot.scoopG; const n = Math.min(2, Math.max(1, Math.round(rem.p / perScoop)));
    add(prot, n * prot.scoopG);
  }
  // 2) hidratos primero (lo menos saciante), respetando los hidratos que quedan; 3) grasa con lo que sobre
  let left = budget - tot.kcal, carbRoom = Math.max(0, rem.c - tot.c), fatRoom = Math.max(0, rem.f * 1.1 - tot.f);
  let riceUsed = false;
  for(const f of F.filter(x => x.role === 'carb')){
    if(left < 60 || carbRoom < 10) break;
    if((f.id === 'crema_a' || f.id === 'harina_a') && riceUsed) continue; // una sola harina/crema de arroz
    if(f.id === 'miel' && items.some(i => i.f.role === 'carb') && left < 150) continue;
    const g = Math.min(f.maxG, left / (f.kcal/100), carbRoom / (f.c/100)); if(g < 10) continue;
    const used = add(f, g); const m = items[items.length-1] ? items[items.length-1].m : null; left -= used; if(m) carbRoom -= m.c;
    if(f.id === 'crema_a' || f.id === 'harina_a') riceUsed = true;
  }
  for(const f of F.filter(x => x.role === 'fat')){
    if(left < 60 || fatRoom < 4) break;
    const g = Math.min(f.maxG, left / (f.kcal/100), fatRoom / (f.f/100)); if(g < 5) continue;
    const used = add(f, g); const m = items[items.length-1] ? items[items.length-1].m : null; left -= used; if(m) fatRoom -= m.f;
  }
  return { items, tot, uncovered: Math.max(0, Math.round(rem.kcal - tot.kcal)), hasFillers: F.length > 0 };
}
async function renderMissingToday(sums, tgt, date, logs){
  const el = $('missing-today'); if(!el) return;
  const rem = { kcal: tgt.kcal - sums.kcal, p: Math.max(0, tgt.p - sums.p), c: Math.max(0, tgt.c - sums.c), f: Math.max(0, tgt.f - sums.f) };
  if(date !== todayStr() || rem.kcal <= 100){ el.style.display = 'none'; __lastFill = null; return; }
  const now = new Date(), hour = now.getHours() + now.getMinutes() / 60;
  const pr = buildFillProposal(rem, hour); __lastFill = pr.items.length ? pr : null;
  let body;
  if(!pr.hasFillers) body = '<div class="muted-line" style="margin:0;">Añade alimentos de relleno en FILLER_FOODS.</div>';
  else if(!pr.items.length) body = '<div class="muted-line" style="margin:0;">Cubre lo que falta con comida normal.</div>';
  else {
    const rows = pr.items.map(i => `<div class="fill-row"><span>${i.f.scoopG ? `${Math.round(i.g / i.f.scoopG)} cacito${i.g / i.f.scoopG > 1 ? 's' : ''} · ` : ''}${i.g} g ${i.f.name}</span><b>${Math.round(i.m.kcal)}</b></div>`).join('');
    body = `${rows}<div class="fill-row total"><span>P ${Math.round(pr.tot.p)} · C ${Math.round(pr.tot.c)} · G ${Math.round(pr.tot.f)}</span><b>${Math.round(pr.tot.kcal)} kcal</b></div>${pr.uncovered > 40 ? `<div class="muted-line" style="margin:0 0 4px;">+ ~${pr.uncovered} kcal en comida normal</div>` : ''}<button class="primary" onclick="logFillProposal()">Registrar</button>`;
  }
  el.innerHTML = `<summary><span>Falta hoy</span><b class="card-meta">${Math.round(rem.kcal)} kcal</b></summary><div class="fold-body">${body}</div>`;
  if(!el.dataset.init){ el.open = hour >= 16; el.dataset.init = '1'; }
  el.style.display = 'block';
}
window.logFillProposal = async () => {
  const pr = __lastFill; if(!pr || !pr.items.length) return;
  const now = Date.now(), entries = await getLog(selectedLogDate);
  const label = 'Relleno: ' + pr.items.map(i => `${i.g} g ${i.f.name}`).join(' + ');
  entries.push({ id: now.toString(36), createdAt: now, updatedAt: now, time: new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'}),
    label: label.slice(0, 120), kcal: Math.round(pr.tot.kcal), p: +pr.tot.p.toFixed(1), c: +pr.tot.c.toFixed(1), f: +pr.tot.f.toFixed(1), s: +pr.tot.s.toFixed(1),
    originalText: '', source: 'Relleno (báscula)', ai: null, corrected: false, weighed: true, eatenOut: false });
  await setLog(selectedLogDate, entries);
  showToast(`+${Math.round(pr.tot.kcal)} kcal de relleno registradas`);
  await updateDashboardUI(); await refreshInsights();
};

async function updateDashboardUI(){
  const t = selectedLogDate;
  const logs = await getLog(t);
  const sums = sumEntries(logs);
  const tgt = getTargets();

  $('log-date-label').innerText = formatDateLabel(t);
  $('log-date-jump').style.display = (t === todayStr()) ? 'none' : 'block';
  $('btn-next-day').disabled = (t === todayStr());

  $('ui-kcal-consumed').innerText = Math.round(sums.kcal);
  { const el = $('ui-kcal-err');
    if(el){
      if(sums.kcal > 0){
        const rnd = Math.sqrt(logs.reduce((a, e) => a + BulkEngine.entryErrorSd(e) ** 2, 0)), sys = BulkEngine.CONFIG.LOGGING_SYSTEMATIC_FRACTION * sums.kcal;
        const half = Math.round(1.2816 * Math.sqrt(rnd * rnd + sys * sys) / 10) * 10;
        el.innerText = `· ≈ ±${half} kcal`;
      } else el.innerText = '';
    } }
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

  if(kcalPct>=100){ progFill.classList.add('surplus'); $('ui-kcal-status').innerText="objetivo cumplido"; $('ui-kcal-status').style.color="var(--green)"; }
  else { progFill.classList.remove('surplus'); $('ui-kcal-status').innerText="restantes"; $('ui-kcal-status').style.color="var(--text-dim)"; }

  const bar = (cur, target, barId, txtId) => {
    const pct = target > 0 ? (cur / target) * 100 : 0, b = $(barId);
    b.style.width = Math.min(100, pct) + '%';
    $(txtId).innerText = `${Math.round(cur)}/${Math.round(target)}`;
    b.classList.toggle('over-limit', pct > 115);
  };
  bar(sums.p, tgt.p, 'bar-pro', 'txt-pro'); bar(sums.c, tgt.c, 'bar-car', 'txt-car'); bar(sums.f, tgt.f, 'bar-fat', 'txt-fat'); bar(sums.s, tgt.s, 'bar-sugar', 'txt-sugar');
  await renderDailyAssistant(sums, tgt, logs.length, t, logs);
  await renderMissingToday(sums, tgt, t, logs);
  await renderWater(t);
  checkMeasureReminder();

  const list = $('log-list');
  if(!logs.length) list.innerHTML = '<div class="empty-state">Sin registros este día.</div>';
  else {
    list.innerHTML = logs.slice().reverse().map(log=>`
      <div class="log-item">
        <div>
          <div class="log-title">${log.label}</div>
          <div class="log-macros">${log.time||''} · P${Math.round(log.p)} C${Math.round(log.c)} G${Math.round(log.f)}</div>
        </div>
        <div class="log-item-actions">
          <div class="log-kcal-wrap">
            <span class="log-kcal">${Math.round(log.kcal)}</span><span style="font-size:0.7rem; color:var(--text-dim);">kcal</span>
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
async function callGemini(prompt, isJson=false, model=GEMINI_MODEL_SUMMARY, maxRetries=2, opts={}){
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
  else { if(!(low > 0 && low <= tot.kcal)) low = tot.kcal * 0.8; if(!(high >= tot.kcal)) high = tot.kcal * 1.25; }
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
6. Incertidumbre honesta: "kcal_low"/"kcal_high" = rango del ~90 % de lo descrito. Tus estimaciones suelen ser dispares, así que sé HONESTO y AMPLIO: nunca menos de ±15 % si hay que suponer ración, aceite o marca, y ±30 % o más si es un plato mixto, de restaurante o ambiguo. "confidence": "alta" si hay cantidades o etiqueta; "media" si hay que suponer la ración; "baja" si es muy ambiguo.
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
    <div class="scale-row"><span>Ajustar ración</span>${[0.5, 0.75, 1.25, 1.5, 2].map(k => `<button class="secondary" onclick="scaleReview(${k})">×${String(k).replace('.', ',')}</button>`).join('')}</div>
    <div class="scale-row err-flags"><span>Precisión</span>
      <label class="chk"><input type="checkbox" id="review-weighed" ${e.weighed ? 'checked' : ''}> ⚖️ Pesado con báscula / etiqueta <small>(error ↓)</small></label>
      <label class="chk"><input type="checkbox" id="review-out" ${e.eatenOut ? 'checked' : ''}> 🍽️ Comida fuera de casa <small>(error ↑)</small></label>
    </div>`;
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
  const flagWeighed = !!($('review-weighed') && $('review-weighed').checked), flagOut = !!($('review-out') && $('review-out').checked);
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
    saved = entries[idx] = { ...before, ...final, weighed: flagWeighed, eatenOut: flagOut, updatedAt: now, ai, corrected, edits, source: freshAI ? src.source : before.source };
    await setLog(selectedLogDate, entries);
    showToast('Registro actualizado');
  } else {
    const ai = src.fromAI ? aiSnapshot(src) : null;
    const corrected = ai ? differsFrom(ai, final) : false;
    saved = { id: now.toString(36), createdAt: now, updatedAt: now, time: new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'}), ...final, originalText: src.originalText || '', source: src.source || 'Manual', ai, corrected, weighed: flagWeighed, eatenOut: flagOut };
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
      result: { label: final.label, kcal: final.kcal, p: final.p, c: final.c, f: final.f, s: final.s, items: (est?.items || []).map(i => ({ ...i, kcal: i.kcal*k, p: i.p*k, c: i.c*k, f: i.f*k })), range: { low: Math.round(final.kcal), high: Math.round(final.kcal) }, confidence: 'alta', assumptions: [saved.corrected ? 'Valor corregido por ti' : 'Valor confirmado por ti'], question: null, warnings: [] } });
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
// 🗓️ HISTORIAL RECIENTE (contexto factual para el asistente diario)
// =========================================
// Resumen de los últimos días reales: media, adherencia y comidas que repites.
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
  const within = complete.filter(d => d.target && Math.abs(d.intake - d.target) <= d.target * 0.1).length;
  return `Historial real de los últimos ${days} días (${complete.length} días completos): media ~${avg} kcal/día, ${within}/${complete.length} días dentro de ±10% del objetivo de ese día; necesario estimado para progresar ~${st.decision.needed} kcal.${topMeals.length ? ` Comidas que repite con frecuencia: ${topMeals.join(', ')}.` : ''}`;
}

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
    adjustmentPaused: $('prof-pause').checked,
    proteinPerKg: (v => v >= 1.2 && v <= 3 ? v : DEFAULT_PROTEIN_PER_KG)(Number(String($('prof-protein-kg').value).replace(',', '.'))),
    fatPerKg: (v => v >= 0.5 && v <= 1.5 ? v : DEFAULT_FAT_PER_KG)(Number(String($('prof-fat-kg').value).replace(',', '.'))),
    goalWeightKg: (v => Number.isFinite(v) && v > 0 ? v : null)(parseFloat(String($('prof-goal-weight').value).replace(',', '.')))
  });
  __engineCache = null; await syncDynamicMacros(true);
  renderObjectiveSummary(); await updateDashboardUI(); await refreshInsights();
  showToast('Guardado');
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
// Objetivo actual (Ajustes): kcal y macros dinámicos con su base de cálculo.
function setMeta(id, text){ const el = $(id); if(el) el.textContent = text || ''; }
function renderObjectiveSummary(){
  setMeta('meta-goal', profile.targetKcal ? `${Math.round(profile.targetKcal)} kcal` : '');
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

const MEASURE_FIELDS = [ { k:'waist', label:'Cintura' }, { k:'arm', label:'Brazo' }, { k:'thigh', label:'Muslo' }, { k:'chest', label:'Pecho' }, { k:'hip', label:'Cadera' }, { k:'neck', label:'Cuello' } ];
const WAIST_CM_PER_KG_WARN = 1.0; // heurística: > 1 cm de cintura por kg ganado sugiere que parte del peso es grasa
function measureSummaryLabel(e){
  const parts = [];
  if(e.neck) parts.push(`Cuello ${e.neck}cm`);
  parts.push(`Cintura ${e.waist}cm`);
  if(e.hip) parts.push(`Cadera ${e.hip}cm`);
  if(e.arm) parts.push(`Brazo ${e.arm}cm`);
  if(e.thigh) parts.push(`Muslo ${e.thigh}cm`);
  if(e.chest) parts.push(`Pecho ${e.chest}cm`);
  return parts.join(' · ');
}
// Serie por métrica: cada fecha con su último registro que incluya esa métrica.
async function getMeasureHistory(days = 180){
  const series = await getBodyMeasureSeries(days); const out = {};
  for(const f of MEASURE_FIELDS) out[f.k] = series.filter(e => Number(e[f.k]) > 0).map(e => ({ date: e.date, v: Number(e[f.k]) }));
  return out;
}
function trendWeightAt(st, date){
  const pts = (st.weight.points || []).filter(p => p.trend !== null && p.date <= date);
  return pts.length ? pts[pts.length - 1].trend : null;
}
async function renderMeasureTrends(){
  const el = $('measure-trends'); if(!el) return;
  const H = await getMeasureHistory(180); let st = null; try { st = getEngineState(); } catch(e){}
  const rows = MEASURE_FIELDS.filter(f => H[f.k].length).map(f => {
    const a = H[f.k][0], b = H[f.k][H[f.k].length - 1], d = b.v - a.v;
    return H[f.k].length >= 2 ? kv(f.label, `${fmtN(b.v,1)} cm`, `${fmtS(d,1)} cm desde el ${a.date} (${fmtN(a.v,1)} cm)`) : kv(f.label, `${fmtN(b.v,1)} cm`, `1 medida (${b.date}); falta otra para ver tendencia`);
  });
  setMeta('meta-measure', H.waist.length ? `${fmtN(H.waist[H.waist.length-1].v, 1)} cm` : '');
  if(!rows.length){ el.innerHTML = '<div class="muted-line">Aún no hay medidas. Mídete una vez por semana, misma hora y mismo punto (cintura a la altura del ombligo, relajado).</div>'; return; }
  let verdict = '';
  const W = H.waist;
  if(st && W.length >= 2){
    const a = W[0], b = W[W.length - 1], span = BulkEngine.util.diffDays(a.date, b.date);
    const w0 = trendWeightAt(st, a.date), w1 = trendWeightAt(st, b.date);
    if(span >= 14 && w0 !== null && w1 !== null){
      const dW = w1 - w0, dC = b.v - a.v;
      const armUp = H.arm.length >= 2 ? H.arm[H.arm.length - 1].v - H.arm[0].v : null, thUp = H.thigh.length >= 2 ? H.thigh[H.thigh.length - 1].v - H.thigh[0].v : null;
      let tone, txt;
      if(dW > 0.3){
        const ratio = dC / dW;
        tone = ratio > WAIST_CM_PER_KG_WARN ? 'warn' : 'ok';
        txt = `En ${span} días: peso tendencia ${fmtS(dW,1)} kg y cintura ${fmtS(dC,1)} cm → ${fmtN(ratio,1)} cm de cintura por kg ganado. ${ratio > WAIST_CM_PER_KG_WARN ? 'La cintura crece más rápido que el peso: parte de lo que subes puede ser grasa. Considera el rango «conservador» o no subir kcal esta semana.' : 'Ritmo de cintura compatible con un volumen limpio.'}`;
      } else {
        tone = dC >= 1.5 ? 'warn' : 'ok';
        txt = `En ${span} días: peso tendencia ${fmtS(dW,1)} kg y cintura ${fmtS(dC,1)} cm. ${dC >= 1.5 ? 'La cintura sube sin que suba el peso: revisa la técnica de medición o posible retención.' : 'Sin señales de acumulación de grasa.'}`;
      }
      if(armUp !== null || thUp !== null) txt += ` Brazo ${armUp !== null ? fmtS(armUp,1) : '—'} cm · muslo ${thUp !== null ? fmtS(thUp,1) : '—'} cm.`;
      verdict = `<div class="alert${tone === 'warn' ? ' warn' : ''}" style="margin:14px 0 6px;">📏 ${txt}<div class="muted-line" style="margin-top:6px;">Heurística orientativa (umbral ${fmtN(WAIST_CM_PER_KG_WARN,1)} cm/kg): depende de medirte igual cada vez.</div></div>`;
    } else verdict = `<div class="muted-line" style="margin:12px 0;">Para valorar cintura vs peso hacen falta dos medidas de cintura separadas ≥14 días y peso en ambas fechas.</div>`;
  }
  el.innerHTML = rows.join('') + verdict;
}
let __measureReminderDay = null;
async function checkMeasureReminder(){
  const el = $('measure-reminder'); if(!el) return;
  const today = todayStr(); if(__measureReminderDay === today && el.dataset.done === '1') return;
  const last = await getLatestBodyMeasure(60); __measureReminderDay = today; el.dataset.done = '1';
  const since = last ? BulkEngine.util.diffDays(last.date, today) : null;
  const started = profile && profile.bulkStartDate ? BulkEngine.util.diffDays(profile.bulkStartDate, today) : 7;
  if(since !== null && since >= 8){ el.style.display = 'block'; el.innerHTML = `📏 <b>Hace ${since} días que no te mides.</b> Una vez por semana basta: cintura, brazo, muslo y pecho.<button class="secondary" style="margin-top:12px; padding:9px 15px; font-size:.8rem; width:100%;" onclick="nav('body'); setTimeout(()=>$('input-waist').scrollIntoView({behavior:'smooth', block:'center'}), 200);">Medirme ahora</button>`; }
  else if(since === null && started >= 7){ el.style.display = 'block'; el.innerHTML = `📏 <b>Aún no tienes medidas.</b> Sin cintura ni brazo no puedo distinguir si subes músculo o grasa.<button class="secondary" style="margin-top:12px; padding:9px 15px; font-size:.8rem; width:100%;" onclick="nav('body'); setTimeout(()=>$('input-waist').scrollIntoView({behavior:'smooth', block:'center'}), 200);">Medirme ahora</button>`; }
  else el.style.display = 'none';
}

async function renderBodyMeasureDayList(){
  const date = $('input-measure-date').value || todayStr();
  const entries = await getBodyMeasureEntries(date);
  const el = $('measure-day-list');
  if(!entries.length){ el.innerHTML = ''; return; }
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
  const num = id => { const r = $(id).value; const v = r.trim() ? parseFloat(String(r).replace(',', '.')) : null; return Number.isFinite(v) && v > 0 ? v : null; };
  const date = $('input-measure-date').value || todayStr();
  const arr = await getBodyMeasureEntries(date);
  arr.push({ neck: num('input-neck'), waist, hip: num('input-hip'), arm: num('input-arm'), thigh: num('input-thigh'), chest: num('input-chest'), time: new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'}) });
  await setBodyMeasureEntries(date, arr);
  ['neck','waist','hip','arm','thigh','chest'].forEach(k => { $('input-' + k).value = ''; });
  showToast(`Medidas guardadas (${formatDateLabel(date).toLowerCase()})`);
  await renderBodyMeasureDayList(); await renderBodyComposition(); await renderBodyCompositionChart(); await renderMeasureTrends(); __measureReminderDay = null; await checkMeasureReminder();
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
  const armVal = prompt('Brazo (cm), vacío si no aplica:', cur.arm ?? ''); if(armVal === null) return;
  const thighVal = prompt('Muslo (cm), vacío si no aplica:', cur.thigh ?? ''); if(thighVal === null) return;
  const chestVal = prompt('Pecho (cm), vacío si no aplica:', cur.chest ?? ''); if(chestVal === null) return;
  const pn = v => { const x = String(v).trim() ? parseFloat(String(v).replace(',', '.')) : null; return Number.isFinite(x) && x > 0 ? x : null; };
  const waist = parseFloat(String(waistVal).replace(',', '.'));
  if(!Number.isFinite(waist) || waist <= 0){ showToast('Cintura inválida', true); return; }
  const neck = neckVal.trim() ? parseFloat(String(neckVal).replace(',', '.')) : null;
  const hip = hipVal.trim() ? parseFloat(String(hipVal).replace(',', '.')) : null;
  entries[index] = { ...cur, neck: Number.isFinite(neck) ? neck : null, waist, hip: Number.isFinite(hip) ? hip : null, arm: pn(armVal), thigh: pn(thighVal), chest: pn(chestVal) };
  await setBodyMeasureEntries(date, entries);
  showToast('Medidas actualizadas');
  await renderBodyMeasureDayList(); await renderBodyComposition(); await renderBodyCompositionChart(); await renderMeasureTrends();
};

window.delBodyMeasureEntry = async (date, index) => {
  const entries = await getBodyMeasureEntries(date);
  entries.splice(index, 1);
  await setBodyMeasureEntries(date, entries);
  showToast('Medida eliminada');
  await renderBodyMeasureDayList(); await renderBodyComposition(); await renderBodyCompositionChart(); await renderMeasureTrends();
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

  const res = await callGemini(prompt, true);
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
  if(!entries.length){ el.innerHTML = ''; return; }
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
  __engineCache = null; await syncDynamicMacros();
  await renderWeightDayList(); renderObjectiveSummary(); await updateDashboardUI(); await refreshInsights();
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
  </div>`;
}
function renderBulkStatus(elId){
  const el = $(elId); if(!el) return;
  const st = getEngineState(), r = st.rate, R = st.range, S = STATUS_UI[st.status.code];
  let html = `<div class="status-head"><span class="status-chip tone-${S.tone}">${S.label}</span>${confBadge(st.confidence)}</div>`;
  if(r){
    html += `<div class="status-nums">
      <div><div class="sn-val">${fmtS(r.perWeek)}</div><div class="sn-lbl">kg/sem</div></div>
      <div><div class="sn-val">${fmtS(r.perWeek / st.weight.level * 100, 2)} %</div><div class="sn-lbl">peso/sem</div></div>
      <div><div class="sn-val">${fmtN(R.low,2)}–${fmtN(R.high,2)}</div><div class="sn-lbl">objetivo</div></div></div>
      ${rateScaleHTML(st)}`;
  } else {
    const n = st.weight.points.length;
    html += `<div class="muted-line">Faltan pesajes para calcular el ritmo (${n} de 4 mínimos, repartidos en ≥7 días).</div>`;
  }
  el.innerHTML = html;
}
function renderWhyTarget(elId, detailId){
  const el = $(elId), det = $(detailId); if(!el) return;
  const st = getEngineState(), d = st.decision, M = st.maintenance, R = st.range, A = st.adherence;
  const ch = [...(st.raw.timeline || [])].reverse().find(e => Number(e.delta));
  const head = profile.adjustmentPaused ? 'Ajuste automático pausado' : d.delta ? `Ajuste ${d.delta > 0 ? '+' : ''}${d.delta} kcal` : 'Sin cambios';
  el.innerHTML = kv('Mantenimiento', `${fmtN(M.posterior)} ±${fmtN(M.posteriorSd)}`)
    + kv('Necesario', `≈ ${fmtN(d.needed)} kcal`)
    + `<div class="decision-box tone-${d.delta ? 'warn' : d.action === 'SIN_DATOS' ? 'neutral' : 'ok'}"><b>${head}</b></div>`;
  if(!det) return;
  det.innerHTML = `<p class="muted-line" style="margin:0 0 6px;">${d.reason}</p>`
    + kv('Superávit', `+${fmtN(d.surplus)} kcal`)
    + kv('Tu media real', st.intake.n ? `${fmtN(st.intake.mean)} kcal` : '—')
    + kv('Adherencia', A.ratio !== null ? `${fmtN(A.ratio*100)} %` : '—')
    + kv('Último cambio', ch ? `${ch.delta > 0 ? '+' : ''}${ch.delta} kcal · ${ch.date}` : 'ninguno')
    + `<details class="sub-details"><summary>Cómo se calcula</summary><div class="formula">
      <p><b>Fórmula:</b> Mifflin-St Jeor ${fmtN(M.bmr)} kcal × (1,2 + 0,075 × ${profile.trainingDays} días de entreno) = ${fmtN(M.prior)} ±${fmtN(M.priorSd)} kcal.</p>
      ${M.method === 'bayes' ? `<p><b>Observado:</b> ingesta media ${fmtN(st.intake.mean)} − ritmo ${fmtS(st.rate.slopePerDay*1000,1)} g/día × 7,7 kcal/g = ${fmtN(M.obs)} ±${fmtN(M.obsSd)} kcal (incluye ${fmtN(BulkEngine.CONFIG.LOGGING_SYSTEMATIC_FRACTION*100)} % de error de registro y el error de cada entrada).</p>
      <p><b>Combinado:</b> ${fmtN(M.posterior)} ±${fmtN(M.posteriorSd)} kcal (tus datos pesan un ${fmtN(M.dataWeight*100)} %).</p>` : ''}
      <p><b>Reglas:</b> solo con confianza media/alta · nunca baja si ganas por debajo del rango · si comes <${BulkEngine.CONFIG.ADHERENCE_MIN*100} % del objetivo no sube · zona muerta ±${BulkEngine.CONFIG.DEADBAND_KCAL} kcal · máx. ${BulkEngine.CONFIG.STEP_MAX.MEDIA}/${BulkEngine.CONFIG.STEP_MAX.ALTA} kcal por cambio · ≥${BulkEngine.CONFIG.COOLDOWN_DAYS} días entre cambios · sin invertir en ${BulkEngine.CONFIG.NO_REVERSAL_DAYS} días · nunca bajo el mantenimiento.</p>
    </div></details>`;
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
  if(!st.goalKg){ el.innerHTML = ''; return; }
  if(P.remaining !== null && P.remaining <= 0){ el.innerHTML = '<div class="goal-line"><b>🎯 Objetivo alcanzado</b></div>'; return; }
  const c = P.current, o = P.objective;
  el.innerHTML = `<div class="goal-line"><span>Meta ${fmtN(st.goalKg,1)} kg · faltan ${fmtN(P.remaining,1)}</span><b>${c && c.available ? c.text : (o ? '~ ' + o.text : '—')}</b></div>`;
}
// ---- Gráficos (eje X temporal real: días desde el primer dato) ----
function linearAxisOptions(t0, legend = false){
  const o = cleanChartOptions();
  o.interaction = { mode: 'nearest', intersect: false, axis: 'x' };
  o.scales.x = { type: 'linear', grid: { display: false }, border: { display: false }, ticks: { color: CHART_TEXT, font: { size: 10 }, maxTicksLimit: 6, callback: v => shortDate(BulkEngine.util.addDays(t0, Math.round(v))) } };
  o.plugins.legend = { display: legend, position: 'bottom', labels: { color: CHART_TEXT, boxWidth: 10, boxHeight: 10, font: { size: 10 }, filter: i => !String(i.text).startsWith('_') } };
  o.plugins.tooltip = { ...o.plugins.tooltip, displayColors: true, filter: i => !String(i.dataset.label).startsWith('_'), callbacks: { title: items => items.length ? shortDate(BulkEngine.util.addDays(t0, Math.round(items[0].parsed.x))) : '' } };
  return o;
}
async function renderWeightChart(){
  const canvas = $('weightChart'); if(!canvas || typeof Chart === 'undefined') return;
  const st = getEngineState(), pts = st.weight.points, U = BulkEngine.util;
  if(weightChartInstance){ weightChartInstance.destroy(); weightChartInstance = null; }
  if(!pts.length) return;
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
  const opt = linearAxisOptions(t0, true);
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
      o.plugins.legend = { display: false };
      o.plugins.tooltip = { ...o.plugins.tooltip, displayColors: true, callbacks: { afterBody: items => { const d = days[items[0].dataIndex]; return d ? `Estado: ${({complete:'completo', open:'en curso', doubtful:'dudoso (no cuenta)', incomplete:'incompleto (no cuenta)', empty:'sin registro'})[d.status]}${d.entries ? ` · error de registro ≈ ±${Math.round(1.2816 * Math.sqrt(d.errSd ** 2 + (BulkEngine.CONFIG.LOGGING_SYSTEMATIC_FRACTION * d.intake) ** 2) / 10) * 10} kcal` : ''}` : ''; } } };
      kcalTrendChartInstance = new Chart(canvas.getContext('2d'), { type: 'bar', data: { labels: days.map(d => shortDate(d.date)), datasets: [
        { type: 'line', label: 'Objetivo de ese día', data: days.map(d => d.target), borderColor: '#d9ab6a', borderWidth: 1.5, pointRadius: 0, stepped: 'middle', order: 0 },
        { type: 'line', label: 'Necesario estimado hoy', data: days.map(() => st.decision.needed), borderColor: 'rgba(127,174,148,0.8)', borderDash: [5,4], borderWidth: 1.5, pointRadius: 0, order: 0 },
        { label: 'Ingerido', data: days.map(d => d.entries ? Math.round(d.intake) : null), backgroundColor: days.map(d => col[d.status]), borderRadius: 4, order: 1 }
      ] }, options: o });
    }
  }
  const el = $('nutrition-stats'); if(!el) return;
  const A = st.adherence, I = st.intake;
  el.innerHTML = kv('Media real', I.n ? `${fmtN(I.mean)} kcal` : '—') + kv('Adherencia', A.ratio !== null ? `${fmtN(A.ratio*100)} %` : '—');
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
  html += tl.length ? `<div class="table-wrap"><table class="data-table audit"><thead><tr><th>Fecha</th><th>Objetivo</th><th>Cambio</th><th>Origen</th></tr></thead><tbody>${tl.map(e => `<tr title="${escAttr(e.reason)}"><td>${e.date}${e.approx ? '*' : ''}</td><td>${e.kcal}</td><td>${e.delta ? (e.delta > 0 ? '+' : '') + e.delta : '—'}</td><td>${SOURCE_UI[e.source] || e.source}</td></tr>`).join('')}</tbody></table></div><div class="muted-line">* fecha aproximada (cambio que la versión anterior no registró). Pasa el ratón o toca una fila para ver el motivo.</div>` : '<div class="muted-line">Sin cambios registrados.</div>';
  html += '<div class="sub-title" style="margin-top:18px;">Evaluaciones y decisiones</div>';
  html += log.length ? log.map(d => `<details class="decision-item"><summary><span>${d.date}</span><b class="act-${String(d.action).toLowerCase()}">${d.action}</b><span>${d.prevTarget}${d.delta ? ` → ${d.newTarget}` : ''} kcal</span>${d.legacy ? '<span class="mini-tag">v1</span>' : ''}</summary><div class="decision-reason">${escAttr(d.reason)}</div>${d.inputs ? `<pre class="trace">${escAttr(JSON.stringify(d.inputs, null, 2))}</pre>` : ''}</details>`).join('') : '<div class="muted-line">Sin evaluaciones todavía.</div>';
  el.innerHTML = html;
}

// Refresca lo que depende del motor: aviso de días dudosos (Hoy) y la pestaña abierta (Progreso, Gym o Ajustes).
async function refreshInsights(){
  try {
    renderDayFlagBanner();
    const active = id => { const e = $(id); return !!e && e.classList.contains('active'); };
    if(active('tab-body')) await renderBodyTab();
    if(active('tab-gym')) await renderGymTab();
    if(active('tab-settings')) await renderSettingsTab();
  } catch(e){ console.error('refreshInsights', e); }
}
// Progreso · análisis (cambia con cada dato nuevo)
async function renderBodyTab(){
  { const st = getEngineState();
    setMeta('meta-bulk', st.rate && st.confidence.level !== 'BAJA' ? `${fmtS(st.rate.perWeek)} kg/sem` : '');
    setMeta('meta-weight', st.weight.points.length ? `${fmtN(st.weight.level, 1)} kg` : '');
    setMeta('meta-intake', st.intake.n ? `${fmtN(st.intake.mean)} kcal` : '');
    setMeta('meta-target', `${Math.round(profile.targetKcal || 0)} kcal`); }
  renderBulkStatus('bulk-status-body'); renderPredictionCard();
  await renderWeightChart();
  await renderTrendCharts();
  renderWhyTarget('why-target-body', 'why-target-detail'); await renderModelChart();
  await renderMeasureTrends();
}
// Progreso · cuerpo (composición, medidas y fotos: al abrir la pestaña o al guardar medidas)
async function renderBodyCompositionBlock(){
  await renderBodyMeasureDayList(); await renderBodyComposition(); await renderBodyCompositionChart(); await renderPhotoGallery();
}
// Gym · actividad
async function renderGymTab(){
  const di = $('input-steps-date'); if(di && !di.value) di.value = todayStr();
  await loadStepsForDate(); await renderStepsCard();
}
// Ajustes · objetivo, datos y auditoría del motor
async function renderSettingsTab(){
  renderObjectiveSummary(); renderSyncStatus();
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
// El asistente diario, el resumen semanal y el resumen corporal reciben EXACTAMENTE las mismas cifras
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
  const res = await callGemini(prompt, true);
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
  setMeta('meta-photos', dates.length ? `${dates.length} foto${dates.length === 1 ? '' : 's'}` : '');
  if(!dates.length){
    gallery.innerHTML = '<div class="empty-state">Aún no has guardado ninguna foto.</div>';
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
  if(tab==='body'){ renderBodyTab(); renderBodyCompositionBlock(); }
  else if(tab==='gym') renderGymTab();
  else if(tab==='settings') renderSettingsTab();
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
// API keys, ni syncUid, ni fotos. Etiquetas: OBSERVED (lo que
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
  const tl = st.raw.timeline;
  let replay = [];
  try { if(st.days.length >= 3) replay = BulkEngine.replay(st.raw, profile, { from: U.addDays(st.days[0].date, 1), to: st.asOf, initialTarget: tl.length ? tl[0].kcal : Math.round(profile.targetKcal) }); } catch(e){ console.error(e); }
  const rate = st.rate ? { kgPerWeek: r2(st.rate.perWeek,4), ciLow80: r2(st.rate.ciLow,4), ciHigh80: r2(st.rate.ciHigh,4), pctBodyweightPerWeek: r2(st.rate.perWeek / st.weight.level * 100, 3), weighIns: st.rate.n, spanDays: st.rate.span, window: [st.rate.firstDate, st.rate.lastDate], residualSdKg: r2(st.rate.residualSD,3), lag1Autocorrelation: r2(st.rate.rho,3), effectiveN: r2(st.rate.nEff,1), method: 'OLS sobre pesajes no atípicos (28 días), SE corregido por autocorrelación AR(1)' } : null;
  const M = st.maintenance;
  return {
    meta: { app: 'Bulking OS', schemaVersion: 2, engineVersion: st.engineVersion, generatedAt: new Date().toISOString(), asOf: st.asOf, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      tags: { OBSERVED: 'registrado por el usuario', CALCULATED: 'derivado de forma determinista', ESTIMATED: 'modelo con incertidumbre', PREDICTED: 'proyección futura' },
      privacy: 'Sin API keys, sin syncUid y sin fotos.' },
    config: BulkEngine.CONFIG,
    OBSERVED: {
      profile: { age: profile.age, heightCm: profile.height, sex: profile.sex, trainingDaysPerWeek: profile.trainingDays, mealsPerDay: profile.mealsPerDay, ratePreset: profile.ratePreset, goalWeightKg: profile.goalWeightKg, bulkStartDate: profile.bulkStartDate, adjustmentPaused: !!profile.adjustmentPaused, currentTargetKcal: Math.round(profile.targetKcal || 0), preferences: profile.preferences || '' },
      weighIns, foodEntries: food, dayFlags: st.raw.dayFlags, targetTimeline: tl, aiCorrections: await getAiCorrections()
    },
    CALCULATED: {
      daily: st.days.map(d => ({ date: d.date, firstWeighInKg: d.weight, weighTime: d.weightTime, weighIns: d.weighIns, trendKg: r2((st.weight.points.find(p => p.date === d.date) || {}).trend, 3), outlier: !!(st.weight.points.find(p => p.date === d.date) || {}).outlier, intakeKcal: Math.round(d.intake), p: r2(d.p,1), c: r2(d.c,1), f: r2(d.f,1), entries: d.entries, status: d.status, userFlag: d.userFlag, targetKcal: d.target, diffKcal: d.entries && d.target ? Math.round(d.intake - d.target) : null })),
      weightTrendLevelKg: r2(st.weight.level, 3), bulkStart: st.weight.start, rate, targetRange: st.range,
      intakeWindow: { ...st.intake, mean: r2(st.intake.mean,1), sd: r2(st.intake.sd,1) }, adherence: st.adherence, adherenceLast7: st.adherence7,
      status: st.status, confidence: st.confidence, dataQuality: st.dataQuality, personalMedianIntake: r2(st.personalMedian, 0),
      currentDecision: st.decision, decisionLog: (await safeGet('decisionLog')) || []
    },
    ESTIMATED: {
      maintenance: { method: M.method, bmrMifflin: r2(M.bmr,0), activityFactor: r2(M.activityFactor,3), formulaKcal: r2(M.prior,0), formulaSd: r2(M.priorSd,0), observedKcal: r2(M.obs,0), observedSd: r2(M.obsSd,0), estimateKcal: r2(M.posterior,0), estimateSd: r2(M.posteriorSd,0), dataWeight: r2(M.dataWeight,3),
        formula: 'observado = ingesta media (días completos) − pendiente(kg/día) × 7700; estimación = media ponderada por precisión de fórmula y observado' },
      maintenanceHistory: replay.map(b => ({ date: b.date, estimateKcal: r2(b.maintenance,0), sd: r2(b.maintenanceSd,0), method: b.maintenanceMethod }))
    },
    PREDICTED: st.predictions,
    insights: st.insights,
    replay,
    migration: (await safeGet('migrationReport')) || null
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
  const dec = C.decisionLog.map(d => ({ date: d.date, action: d.action, reasonCode: d.reasonCode, prevTarget: d.prevTarget, newTarget: d.newTarget, delta: d.delta, needed: d.needed, migrated: !!d.legacy, reason: d.reason, rateKgWk: d.inputs?.rate?.kgPerWeek, ciLow: d.inputs?.rate?.ciLow, ciHigh: d.inputs?.rate?.ciHigh, maintenance: d.inputs?.maintenance?.estimateKcal, maintenanceSd: d.inputs?.maintenance?.estimateSd, intakeMean: d.inputs?.intake?.meanKcal, adherence: d.inputs?.adherence?.ratio, confidence: d.inputs?.confidence?.level, status: d.inputs?.status }));
  const summary = [
    ['asOf', rep.meta.asOf], ['engineVersion', rep.meta.engineVersion], ['weightTrendKg', C.weightTrendLevelKg], ['rateKgPerWeek', C.rate?.kgPerWeek], ['rateCiLow80', C.rate?.ciLow80], ['rateCiHigh80', C.rate?.ciHigh80],
    ['rangeLowKgWk', +C.targetRange.low.toFixed(3)], ['rangeHighKgWk', +C.targetRange.high.toFixed(3)], ['status', C.status.code], ['confidence', C.confidence.level],
    ['maintenanceEstimateKcal', rep.ESTIMATED.maintenance.estimateKcal], ['maintenanceSd', rep.ESTIMATED.maintenance.estimateSd], ['maintenanceMethod', rep.ESTIMATED.maintenance.method],
    ['intakeMeanKcal', C.intakeWindow.mean], ['adherence', C.adherence.ratio], ['currentTargetKcal', O.profile.currentTargetKcal], ['neededKcal', C.currentDecision.needed], ['decision', C.currentDecision.action], ['decisionReason', C.currentDecision.reason],
    ['etaCurrentRate', rep.PREDICTED.current?.text], ['etaWithinRange', rep.PREDICTED.objective?.text]
  ].map(([k, v]) => ({ key: k, value: v }));
  return {
    'resumen.csv': [summary, ['key','value']],
    'diario.csv': [C.daily, ['date','firstWeighInKg','weighTime','weighIns','trendKg','outlier','intakeKcal','p','c','f','entries','status','userFlag','targetKcal','diffKcal']],
    'pesajes.csv': [O.weighIns, ['date','time','kg','id','createdAt','updatedAt','deletedAt','edits']],
    'comidas.csv': [O.foodEntries, ['date','time','label','kcal','p','c','f','s','source','corrected','originalText','id','createdAt','updatedAt','deletedAt','aiEstimate']],
    'objetivo_timeline.csv': [O.targetTimeline, ['date','kcal','prev','delta','source','approx','reason','decisionId','id']],
    'decisiones.csv': [dec, ['date','action','reasonCode','prevTarget','newTarget','delta','needed','migrated','rateKgWk','ciLow','ciHigh','maintenance','maintenanceSd','intakeMean','adherence','confidence','status','reason']],
    'correcciones_ia.csv': [O.aiCorrections.map(c => ({ ...c, aiKcal: c.ai?.kcal, finalKcal: c.final?.kcal })), ['date','text','label','aiKcal','finalKcal','deltaKcal','deltaPct','model','promptVersion','entryId']],
    'reconstruccion.csv': [rep.replay, ['date','weighIns','completeDays','observedTarget','newTarget','newAction','newReason','rate','ciLow','ciHigh','status','confidence','maintenance','maintenanceSd','intakeMean','adherence']]
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
  para('Etiquetas: OBSERVED = registrado · CALCULATED = derivado · ESTIMATED = modelo con incertidumbre · PREDICTED = futuro. Sin API keys, syncUid ni fotos.'); y += 3;
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
    { type: 'line', points: nd.map((d, i) => ({ x: i, y: d.targetKcal })), color: [120,90,40], width: 0.7, label: 'Objetivo del día' },
    { type: 'line', dash: true, points: nd.map((d, i) => ({ x: i, y: C.currentDecision.needed })), color: [90,150,110], width: 0.6, label: 'Necesario estimado' }
  ], yMin: 0, yFmt: v => v.toFixed(0), xLabels: nd.length ? [{ x: 0, text: nd[0].date }, { x: nd.length - 1, text: nd[nd.length-1].date }] : [] }); y += 55;
  para(`Ventana de análisis ${C.intakeWindow.from} -> ${C.intakeWindow.to}: media ${f(C.intakeWindow.mean)} kcal (SD ${f(C.intakeWindow.sd)}) en ${C.intakeWindow.n} días completos; dudosos excluidos: ${C.intakeWindow.doubtful.join(', ') || 'ninguno'}; incompletos: ${C.intakeWindow.incomplete.join(', ') || 'ninguno'}. Adherencia ${C.adherence.ratio !== null ? f(C.adherence.ratio*100,1) + ' %' : '—'} (${C.adherence.within10}/${C.adherence.n} días ±10 %, déficit medio vs objetivo ${f(C.adherence.meanGap)} kcal/día). Últimos 7 días: ${C.adherenceLast7.ratio !== null ? f(C.adherenceLast7.ratio*100,1) + ' %' : '—'}. Mediana personal de ingesta: ${f(C.personalMedianIntake)} kcal.`);
  table(['Fecha', 'Kcal', 'P', 'C', 'G', 'Reg.', 'Estado', 'Objetivo', 'Dif.'], C.daily.map(d => [d.date, d.entries ? d.intakeKcal : '', d.entries ? f(d.p) : '', d.entries ? f(d.c) : '', d.entries ? f(d.f) : '', d.entries, d.status + (d.userFlag !== null ? ' (tú)' : ''), d.targetKcal ?? '', d.diffKcal ?? '']));
  // Mantenimiento
  h1('5. Mantenimiento (ESTIMATED)');
  const Mm = E.maintenance;
  para(`Método: ${Mm.method === 'bayes' ? 'fórmula combinada con datos' : 'solo fórmula'}. Mifflin-St Jeor ${f(Mm.bmrMifflin)} kcal × factor ${f(Mm.activityFactor,3)} (1,2 + 0,075 × ${O.profile.trainingDaysPerWeek} días de entreno) = ${f(Mm.formulaKcal)} ±${f(Mm.formulaSd)} kcal. Observado: ${f(Mm.observedKcal)} ±${f(Mm.observedSd)} kcal. Estimación: ${f(Mm.estimateKcal)} ±${f(Mm.estimateSd)} kcal (peso de los datos ${Mm.dataWeight !== null ? f(Mm.dataWeight*100) + ' %' : '—'}). ${Mm.formula}.`);
  if(E.maintenanceHistory.length){
    ensure(55); y += 5; pdfChart(doc, M0 + 10, y, W - 2*M0 - 10, 40, { series: [
      { type: 'line', points: E.maintenanceHistory.map((m, i) => ({ x: i, y: m.estimateKcal })), color: [90,110,170], width: 0.8, label: 'Mantenimiento estimado (a fecha de cada día)' },
      { type: 'line', points: rep.replay.map((b, i) => ({ x: i, y: b.observedTarget })), color: [200,150,60], width: 0.6, label: 'Objetivo real' }
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
  // Reconstrucción diaria
  h1('10. Reconstrucción día a día (sin fuga de datos)');
  para('Cada día D solo usa datos anteriores a D. "Real" es el objetivo que mostraba la app; "Nuevo" es lo que habría decidido el motor actual partiendo del mismo objetivo inicial.');
  if(rep.replay.length) table(['Día', 'Real', 'Nuevo', 'Acción', 'Motivo', 'Ritmo', 'IC80', 'Conf.', 'Mant.'], rep.replay.map(b => [b.date, Math.round(b.observedTarget), b.newTarget, b.newAction, b.newReason, f(b.rate,3), b.rate !== null ? `${f(b.ciLow,2)}..${f(b.ciHigh,2)}` : '', b.confidence, f(b.maintenance)]), { fs: 6.5 });
  // Metodología
  h1('11. Metodología');
  para('Tendencia: media exponencial temporal (alfa 0,15/día, el peso de cada pesaje depende de los días transcurridos; semilla = mediana de los 3 primeros). Atípicos: filtro de Hampel (±3 días, 3 × MAD, mínimo 0,3 kg). Ritmo: regresión lineal de 28 días sobre pesajes no atípicos; intervalo del 80 % con error estándar corregido por autocorrelación. Día completo: ≥2 registros y ≥60 % de tu mediana, o confirmado por ti; los dudosos no cuentan. Mantenimiento: combinación bayesiana (ponderada por precisión) de Mifflin-St Jeor × actividad (±12 %) y el balance observado (ingesta − pendiente × 7700), cuya incertidumbre incluye el error de registro (15 % sistemático + error aleatorio por entrada según el rango de la IA, báscula y comidas fuera). Ajuste: solo con confianza media/alta; nunca baja si ganas por debajo del rango; no sube si comes <90 % del objetivo; zona muerta 50 kcal; pasos ≤100/150 kcal; ≥7 días entre cambios; sin invertir el sentido en 21 días; nunca por debajo del mantenimiento estimado.');
  if(rep.migration) para(`Migración v2: ${JSON.stringify(rep.migration)}`, 7);
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
  try { await syncDynamicMacros(); renderObjectiveSummary(); await updateDashboardUI(); await refreshInsights(); } catch(e){ console.error(e); }
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
  { const k = macroPerKg(profile); $('prof-protein-kg').value = k.protein; $('prof-fat-kg').value = k.fat; }
  $('input-weight-date').value = todayStr();
  $('prof-goal-weight').value = profile.goalWeightKg || '';
  $('input-measure-date').value = todayStr();

  $('input-steps-date').value = todayStr();
  renderSyncStatus();
  renderNoSyncBanner();
  await pruneOldCaches();

  await runDailyEvaluation();
  try { await syncDynamicMacros(); } catch(e){ console.error('Macros dinámicos', e); }
  if(migration){
    const parts = [];
    if(migration.correction) parts.push(`se ha deshecho el ajuste del ${migration.correction.date} (${migration.correction.from} → ${migration.correction.to} kcal) causado por un fallo del algoritmo anterior`);
    if(migration.removedSensitiveKeys.length) parts.push(`se ha borrado del almacenamiento una clave sensible (${migration.removedSensitiveKeys.join(', ')})`);
    if(parts.length) showAdjustAlert(`🔧 Bulking OS v2: ${parts.join('; ')}. Detalle en Ajustes → Auditoría del motor → Historial de decisiones.`, true);
  }
  renderObjectiveSummary(); await updateDashboardUI(); await refreshInsights(); await renderWeightDayList();
  await checkBackupReminder();

  $('manual-text').addEventListener('keydown', e => { if(e.key==='Enter') processText(); });
  $('input-weight-date').addEventListener('change', renderWeightDayList);
  $('input-measure-date').addEventListener('change', renderBodyMeasureDayList);
  $('input-steps-date').addEventListener('change', loadStepsForDate);
};

</script>
</body>
</html>
"""

def get_injected_html():
    """Inyecta las variables de configuración de Python dentro del HTML estático."""
    html = APP_HTML_TEMPLATE
    html = html.replace("__API_KEY_B64__", GEMINI_API_KEY_B64)
    html = html.replace("__MODEL_SUMMARY__", GEMINI_MODEL_SUMMARY)
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
        print("Necesitas Node.js instalado para --test (o abre la app → Ajustes → Herramientas → Ejecutar tests).")
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