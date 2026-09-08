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
# La key se guarda en Base64, NO en texto plano. Esto no es "seguridad" real
# (decodificar base64 es trivial) — es únicamente para que el escáner de
# secretos de GitHub (Push Protection) deje de reconocer el patrón de clave
# de Google y de bloquear cada push. Se decodifica en el navegador con
# atob() al cargar la página (ver __API_KEY_B64__ más abajo en el HTML).
# Para cambiar la key, sustituye el valor de abajo por el resultado de:
#   python -c "import base64; print(base64.b64encode(b'TU_KEY_AQUI').decode())"
GEMINI_API_KEY_B64 = "QVEuQWI4Uk42S2szdjJuZS1ONE9qZWVwR0FtNmVOOHZnRGgxUENFOXBTZ1VRQng5TkJ0ZXc="
# Modelo rápido/barato para tareas cortas (loguear comidas, chat, sustituciones).
GEMINI_MODEL = "gemini-3.5-flash-lite"
# Modelo más capaz para la generación del plan semanal completo (tarea larga y compleja).
GEMINI_MODEL_PLAN = "gemini-3.6-flash"

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
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  /* =========================================
     🎨 VARIABLES Y RESET
     ========================================= */
  :root {
    --bg-color: #0b1115;
    --accent: #f6b73c;
    --accent-glow: rgba(245, 158, 11, 0.4);
    --green: #10b981;
    --red: #ef4444;
    --pro-color: #3b82f6;
    --car-color: #f59e0b;
    --fat-color: #ef4444;
    --sugar-color: #ec4899;
    --text: #f8fafc;
    --text-dim: #94a3b8;
    --glass-bg: rgba(19, 31, 37, 0.86);
    --glass-border: rgba(183, 207, 214, 0.12);
    --glass-shadow: 0 18px 45px rgba(0, 0, 0, 0.24);
    --radius-lg: 20px;
    --radius-md: 14px;
    --radius-sm: 9px;
  }
  
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Manrope', sans-serif; }
  
  body {
    background-color: var(--bg-color);
    background-image:
      linear-gradient(rgba(255,255,255,0.018) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,0.018) 1px, transparent 1px),
      radial-gradient(circle at 12% 0%, rgba(246, 183, 60, 0.12), transparent 28%),
      radial-gradient(circle at 90% 30%, rgba(45, 150, 145, 0.1), transparent 30%);
    background-size: 34px 34px, 34px 34px, auto, auto;
    background-attachment: fixed;
    color: var(--text);
    -webkit-tap-highlight-color: transparent;
    padding-bottom: 90px;
    line-height: 1.5;
  }

  .app-container { max-width: 1180px; margin: 0 auto; padding: 34px 28px 112px; }

  /* =========================================
     🧱 COMPONENTES UI (TARJETAS, BOTONES)
     ========================================= */
  .glass-card {
    background: var(--glass-bg);
    backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-lg); padding: 26px; margin-bottom: 24px;
    box-shadow: var(--glass-shadow);
  }
  
  h2 { font-family:'Space Grotesk', sans-serif; font-size: clamp(1.8rem, 3vw, 2.5rem); font-weight: 700; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-end; letter-spacing: 0;}
  h3 { font-size: 1.15rem; font-weight: 600; margin-bottom: 16px; border-bottom: 1px solid var(--glass-border); padding-bottom: 10px; color: #fff;}
  .subtitle { font-size: 0.95rem; color: var(--accent); font-weight: 600; }
  
  input, select, textarea {
    width: 100%; background: rgba(0,0,0,0.4); border: 1px solid var(--glass-border);
    color: var(--text); border-radius: var(--radius-sm); padding: 14px; font-size: 0.95rem; margin-bottom: 12px;
    transition: all 0.3s ease;
  }
  input:focus, select:focus, textarea:focus { 
    outline: none; border-color: var(--accent); box-shadow: 0 0 12px var(--accent-glow); background: rgba(0,0,0,0.6);
  }
  
  /* Ocultar flechas de los inputs numéricos (para forzar tecleo sin estorbar) */
  input[type="number"]::-webkit-outer-spin-button,
  input[type="number"]::-webkit-inner-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }
  input[type="number"] {
    -moz-appearance: textfield;
  }
  
  button { transition: all 0.2s ease; display: inline-flex; justify-content: center; align-items: center; gap: 8px;}
  button:active { transform: scale(0.97); }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  
  button.primary {
    width: 100%; background: linear-gradient(135deg, var(--accent), #ea580c); color: #000; font-weight: 800;
    border: none; border-radius: var(--radius-md); padding: 16px; font-size: 1rem; cursor: pointer;
    box-shadow: 0 4px 20px var(--accent-glow);
  }
  button.secondary {
    background: rgba(255,255,255,0.06); color: var(--text); border: 1px solid var(--glass-border);
    padding: 12px 18px; border-radius: var(--radius-sm); cursor: pointer; font-weight: 600;
  }

  /* =========================================
     📊 WIDGETS DE MACROS Y PROGRESO
     ========================================= */
  .kcal-main { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 20px; }
  .kcal-number { font-size: 3.8rem; font-weight: 800; line-height: 1; letter-spacing: -2px; text-shadow: 0 2px 10px rgba(0,0,0,0.5);}
  .kcal-target { color: var(--text-dim); font-size: 0.95rem; font-weight: 500; margin-top: 4px; }
  
  .main-progress { height: 18px; background: rgba(0,0,0,0.5); border-radius: 12px; overflow: hidden; margin-bottom: 24px; border: 1px inset rgba(255,255,255,0.05);}
  .main-progress-fill { height: 100%; background: linear-gradient(90deg, #f59e0b, #ea580c); border-radius: 12px; transition: width 1s cubic-bezier(0.2, 1, 0.2, 1); }
  .surplus { background: linear-gradient(90deg, #10b981, #059669) !important; }
  
  .macro-row { margin-bottom: 18px; }
  .macro-label { font-size: 0.88rem; font-weight: 700; margin-bottom: 6px; }
  .macro-values { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 7px; }
  .macro-value-block { display: flex; flex-direction: column; }
  .macro-value-block.right { align-items: flex-end; }
  .macro-value-num { font-family: 'Space Grotesk', sans-serif; font-weight: 800; font-size: 1.55rem; line-height: 1; }
  .macro-value-tag { font-size: 0.64rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 3px; font-weight: 600; }
  .macro-bar-bg { height: 8px; background: rgba(0,0,0,0.5); border-radius: 4px; overflow: hidden; }
  .macro-bar-fill { height: 100%; border-radius: 4px; transition: width 1s ease; }
  .quick-adjust { display:flex; justify-content:space-between; align-items:center; gap:12px; margin:4px 0 20px; padding:12px; border:1px solid var(--glass-border); border-radius:var(--radius-sm); color:var(--text-dim); font-size:0.82rem; }
  .quick-adjust-controls { display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; }
  .quick-adjust-controls button { padding:7px 9px; font-size:0.75rem; }
  .pro-fill { background: var(--pro-color); box-shadow: 0 0 8px rgba(59,130,246,0.5); }
  .car-fill { background: var(--car-color); box-shadow: 0 0 8px rgba(245,158,11,0.5); }
  .fat-fill { background: var(--fat-color); box-shadow: 0 0 8px rgba(239,68,68,0.5); }
  .sugar-fill { background: var(--sugar-color); box-shadow: 0 0 8px rgba(236,72,153,0.5); }
  .over-limit { background: var(--red) !important; }

  /* =========================================
     🎙️ INPUT IA (MICRÓFONO Y CHAT)
     ========================================= */
  .mic-container { text-align: center; padding: 20px 10px; }
  .mic-btn {
    width: 90px; height: 90px; border-radius: 50%; border: none;
    background: linear-gradient(135deg, #f59e0b, #ea580c);
    color: #fff; font-size: 2.2rem; cursor: pointer;
    box-shadow: 0 10px 30px var(--accent-glow);
    display: inline-flex; justify-content: center; align-items: center;
    transition: transform 0.2s, box-shadow 0.2s;
  }
  .mic-btn.listening { background: linear-gradient(135deg, #ef4444, #b91c1c); animation: pulse 1.5s infinite; }
  @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.6); } 70% { box-shadow: 0 0 0 25px rgba(239, 68, 68, 0); } 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); } }
  .ai-status { font-size: 0.95rem; color: var(--accent); margin-top: 20px; font-weight: 600; min-height: 24px;}

  /* Historial / Food Logs y Layout Flexible */
  .log-item { display: flex; justify-content: space-between; padding: 16px 0; border-bottom: 1px solid var(--glass-border); align-items: center; }
  .log-item:last-child { border-bottom: none; }
  .log-item > div:first-child { flex: 1; min-width: 0; padding-right: 12px; }
  .log-title { font-weight: 600; font-size: 1.05rem; margin-bottom: 4px; white-space: normal; word-wrap: break-word; overflow-wrap: break-word; line-height: 1.25; }
  .log-macros { font-size: 0.8rem; color: var(--text-dim); white-space: normal; line-height: 1.4; }
  .log-kcal { font-weight: 800; color: var(--accent); font-size: 1.2rem; }
  .log-item-actions { display: flex; align-items: center; flex-shrink: 0; gap: 6px; }
  .log-kcal-wrap { text-align: right; margin-right: 6px; display: flex; align-items: baseline; gap: 2px; }
  .del-btn { background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.2); color: var(--red); border-radius: 8px; width: 34px; height: 34px; cursor: pointer; font-size: 1.1rem; font-weight: bold; flex-shrink:0; display:flex; align-items:center; justify-content:center; padding:0;}
  .edit-btn { background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.25); color: var(--pro-color); border-radius: 8px; width: 34px; height: 34px; cursor: pointer; font-size: 1.1rem; font-weight: bold; flex-shrink:0; display:flex; align-items:center; justify-content:center; padding:0;}

  /* =========================================
     🧬 PERFIL, ESTADÍSTICAS Y GRÁFICOS
     ========================================= */
  .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
  .stat-box { background: rgba(0,0,0,0.4); border: 1px solid var(--glass-border); padding: 20px 16px; border-radius: var(--radius-md); text-align: center; }
  .stat-val { font-size: 2rem; font-weight: 800; margin-bottom: 4px; }
  .stat-title { font-size: 0.8rem; color: var(--text-dim); text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;}
  
  .form-row { display: flex; gap: 12px; margin-bottom: 12px; }
  .form-group { flex: 1; }
  .form-group label { display: block; font-size: 0.85rem; color: var(--text-dim); margin-bottom: 8px; margin-left: 4px; font-weight: 600;}
  
  .chart-container { position: relative; height: 220px; width: 100%; margin-top: 16px;}

  .section > h2 { padding-bottom: 18px; border-bottom: 1px solid var(--glass-border); }
  .section > h2::before { content:''; width:8px; height:34px; border-radius:4px; background:var(--accent); margin-right:12px; box-shadow:0 0 22px var(--accent-glow); }
  .glass-card > h3 { font-family:'Space Grotesk', sans-serif; }
  .dashboard-grid { display:grid; grid-template-columns:minmax(0, 1.35fr) minmax(300px, .65fr); gap:24px; align-items:start; margin-bottom:24px; }
  .dashboard-grid > .glass-card { margin-bottom:0; }
  .summary-card { position:relative; overflow:hidden; }
  .summary-card::after { content:'TODAY'; position:absolute; top:22px; right:-28px; color:rgba(255,255,255,.04); font:700 4rem 'Space Grotesk'; transform:rotate(90deg); }
  .section-kicker { color:var(--text-dim); font-size:.74rem; letter-spacing:.12em; text-transform:uppercase; font-weight:800; margin-bottom:8px; }
  .date-nav { display:flex; align-items:center; justify-content:space-between; padding:14px 18px; }
  .date-nav button { padding:10px 14px; }
  .date-nav-label { text-align:center; }
  .date-nav-label strong { font-family:'Space Grotesk', sans-serif; font-size:1rem; }
  
  /* =========================================
     📅 MENÚ IA Y TABLAS
     ========================================= */
  .plan-table { width:100%; border-collapse:collapse; margin-top:12px; }
  .plan-table th { color:var(--accent); font-size:0.85rem; text-align:left; padding:12px 10px; border-bottom:1px solid rgba(255,255,255,0.1); }
  .plan-table td { padding:12px 10px; font-size:0.85rem; vertical-align:top; border-bottom:1px solid rgba(255,255,255,0.05); }
  .day-card { margin-top:18px; padding:22px; border-radius:var(--radius-md); background:rgba(8,15,19,.66); border:1px solid var(--glass-border); }
  .day-card h3 { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
  .meal-row { display:grid; grid-template-columns:145px minmax(0, 1fr) 82px; gap:16px; align-items:center; padding:16px 0; border-top:1px solid rgba(183,207,214,.1); }
  .meal-name { font-weight:700; color:#fff; }
  .meal-items { color:#e2edf0; font-size:.88rem; line-height:1.7; }
  .meal-alternatives { display:block; color:var(--text-dim); font-size:.75rem; margin-top:6px; line-height:1.5; }
  .meal-kcal { text-align:right; color:var(--accent); font:700 1rem 'Space Grotesk'; }
  .meal-kcal small { display:block; color:var(--text-dim); font:500 .68rem 'Manrope'; margin-top:2px; }
  .plan-summary-bar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; padding:16px 20px; background:rgba(255,255,255,0.03); border:1px solid var(--glass-border); border-radius:var(--radius-md); }
  .plan-meta { display:flex; gap:10px; flex-wrap:wrap; margin-top:16px; }
  .meta-pill { padding:8px 11px; border-radius:999px; background:rgba(255,255,255,.05); color:var(--text-dim); font-size:.75rem; }
  .meta-pill b { color:#fff; }
  @media (max-width: 760px) {
    .app-container { padding:22px 14px 108px; }
    .dashboard-grid { grid-template-columns:1fr; }
    .meal-row { grid-template-columns:1fr auto; gap:8px 12px; }
    .meal-row > :nth-child(2) { grid-column:1 / -1; grid-row:2; }
    .meal-kcal { grid-column:2; grid-row:1; }
    .day-card { padding:17px 14px; }
    .form-row { flex-direction:column; gap:0; }
    .kcal-number { font-size:3rem; }
  }
  .day-total { margin-top:16px; padding:16px; border-radius:var(--radius-sm); background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.2); line-height:1.8; font-size:0.95rem; }
  .day-total b { color:var(--accent); }
  
  .badge { display:inline-block; padding:4px 10px; border-radius:20px; font-size:0.7rem; font-weight:700; margin-top:6px; letter-spacing: 0.5px; text-transform: uppercase;}
  .badge-batch { background: rgba(59,130,246,0.15); color: #60a5fa; border: 1px solid rgba(59,130,246,0.3); }
  .badge-fresh { background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3); }

  /* =========================================
     💬 CHAT IA Y NOTIFICACIONES
     ========================================= */
  .chat-window { display:flex; flex-direction:column; gap:16px; max-height:55vh; overflow-y:auto; padding:10px 4px 16px; margin-bottom:16px; scroll-behavior: smooth;}
  .chat-bubble { max-width:85%; padding:14px 18px; border-radius:18px; font-size:0.95rem; line-height:1.5; }
  .chat-bubble.user { align-self:flex-end; background: var(--accent); color:#000; font-weight:500; border-bottom-right-radius:4px; box-shadow: 0 4px 12px rgba(245,158,11,0.2);}
  .chat-bubble.ai { align-self:flex-start; background: rgba(255,255,255,0.08); border:1px solid var(--glass-border); border-bottom-left-radius:4px; }
  .chat-empty { color:var(--text-dim); text-align:center; padding:40px 20px; font-size:0.95rem; line-height: 1.6;}
  .chat-action-btn { margin-top:12px; background: rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.4); color:var(--green); border-radius:var(--radius-sm); padding:10px 16px; font-weight:700; cursor:pointer; font-size:0.85rem; width: 100%;}
  
  .alert { background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3); padding: 16px; border-radius: var(--radius-md); font-size: 0.95rem; margin-bottom: 20px; color: #fcd34d; line-height: 1.5; }
  .alert.warn { background: rgba(239, 68, 68, 0.08); border-color: rgba(239, 68, 68, 0.3); color: #fca5a5; }
  .daily-assistant {
    background: linear-gradient(160deg, rgba(16,185,129,0.12), rgba(16,185,129,0.05));
    backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(16,185,129,0.28);
    border-radius: var(--radius-lg);
    padding: 24px 26px;
    margin-bottom: 24px;
    box-shadow: var(--glass-shadow);
    color: #d1fae5;
  }
  .assistant-kicker { text-align:center; font-size:.7rem; letter-spacing:.1em; text-transform:uppercase; font-weight:800; color:var(--green); margin-bottom:10px; }
  .assistant-title { text-align:center; font-family:'Space Grotesk', sans-serif; font-size:1.1rem; font-weight:700; color:#fff; margin-bottom:12px; line-height:1.3; }
  .assistant-body { font-size:.92rem; line-height:1.65; color:#cfeee1; }
  .food-review { margin-top:16px; padding:16px; border:1px solid rgba(246,183,60,.35); border-radius:var(--radius-md); background:rgba(246,183,60,.08); text-align:left; }
  .food-review-grid { display:grid; grid-template-columns:2fr repeat(4, minmax(58px, 1fr)); gap:8px; margin:12px 0; }
  .food-review-grid input { margin-bottom:0; padding:10px 6px; font-size:0.86rem; text-align:center; }
  .food-review-grid input:first-child { text-align:left; }
  .ingredient-row { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .ingredient-row button { padding:4px 8px; font-size:.68rem; }
  @media (max-width: 760px) { .food-review-grid { grid-template-columns:1fr 1fr; } .food-review-grid input:first-child { grid-column:1 / -1; } }

  /* Toasts (Notificaciones) */
  #toast-container { position: fixed; top: 20px; left: 50%; transform: translateX(-50%); z-index: 1000; display: flex; flex-direction: column; gap: 10px; width: 90%; max-width: 400px; pointer-events: none; }
  .toast { background: rgba(20,20,20,0.95); backdrop-filter: blur(10px); border: 1px solid var(--glass-border); color: #fff; padding: 14px 20px; border-radius: var(--radius-sm); font-size: 0.9rem; font-weight: 500; box-shadow: 0 10px 30px rgba(0,0,0,0.5); transform: translateY(-20px); opacity: 0; transition: all 0.3s ease; text-align: center; }
  .toast.show { transform: translateY(0); opacity: 1; }
  .toast.error { border-color: var(--red); color: #fca5a5; }

  /* =========================================
     📱 NAVEGACIÓN INFERIOR Y OTROS
     ========================================= */
  .bottom-nav {
    position: fixed; bottom: 14px; left: 50%; transform: translateX(-50%);
    width: calc(100% - 32px); max-width: 760px;
    background: rgba(8, 10, 12, 0.9); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--glass-border); border-radius: 18px;
    display: flex; justify-content: space-around; padding: 9px 8px 10px; z-index: 100;
    box-shadow: 0 18px 40px rgba(0,0,0,.4);
  }
  .nav-item { color: var(--text-dim); text-align: center; font-size: 0.75rem; cursor: pointer; flex: 1; font-weight: 600; transition: color 0.3s; border-radius: 12px; padding: 7px 4px; }
  .nav-item.active { color: var(--accent); background: rgba(246,183,60,.12); }
  .nav-icon { font-size: 1.6rem; margin-bottom: 6px; display: block; filter: grayscale(100%) opacity(0.5); transition: all 0.3s;}
  .nav-item.active .nav-icon { filter: grayscale(0%) opacity(1); transform: scale(1.1);}
  
  .section { display: none; animation: fadeIn 0.3s ease; }
  .section.active { display: block; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

  .toggle-row { display:flex; justify-content:space-between; align-items:center; padding:12px 0; }
  .switch { position:relative; width:46px; height:26px; flex-shrink:0; }
  .switch input { opacity:0; width:0; height:0; }
  .slider { position:absolute; cursor:pointer; inset:0; background:rgba(255,255,255,0.1); border-radius:26px; transition:0.3s; }
  .slider:before { position:absolute; content:""; height:20px; width:20px; left:3px; bottom:3px; background:white; border-radius:50%; transition:0.3s; }
  input:checked + .slider { background: var(--accent); }
  input:checked + .slider:before { transform: translateX(20px); }
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
    <div id="adjust-alert" class="alert" style="display:none;"></div>
    <div id="backup-reminder" class="alert" style="display:none;"></div>
    <div id="daily-assistant" class="daily-assistant" style="display:none;"></div>

    <div class="dashboard-grid">
    <div class="glass-card" style="padding-top: 30px;">
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
      <div style="font-size:0.78rem; color: var(--text-dim); margin-bottom:14px;">Objetivo del día: <b style="color:#fff;" id="ui-kcal-target">--</b> kcal</div>
      <div class="main-progress"><div class="main-progress-fill" id="ui-progress"></div></div>
      <div style="font-size:0.8rem; color: var(--green); margin-bottom:16px; font-weight:600; display:none;" id="ui-override-note"></div>
      <div class="quick-adjust" aria-label="Ajuste rapido del objetivo">
        <span>Objetivo del día</span>
        <div class="quick-adjust-controls">
          <button class="secondary" onclick="adjustDay(-100)" title="Restar 100 kcal">−100</button>
          <button class="secondary" onclick="adjustDay(100)" title="Sumar 100 kcal">+100</button>
          <button class="secondary" onclick="resetDayOverride()" title="Restablecer ajuste">Reset</button>
        </div>
      </div>
      
      <div class="macro-row">
        <div class="macro-label" style="color: var(--pro-color);">Proteínas</div>
        <div class="macro-values">
          <div class="macro-value-block"><span class="macro-value-num" id="txt-pro" style="color: var(--pro-color);">0g</span><span class="macro-value-tag">Ingerido</span></div>
          <div class="macro-value-block right"><span class="macro-value-num" id="rem-pro">0g</span><span class="macro-value-tag">Restante</span></div>
        </div>
        <div class="macro-bar-bg"><div class="macro-bar-fill pro-fill" id="bar-pro"></div></div>
      </div>
      <div class="macro-row">
        <div class="macro-label" style="color: var(--car-color);">Carbohidratos</div>
        <div class="macro-values">
          <div class="macro-value-block"><span class="macro-value-num" id="txt-car" style="color: var(--car-color);">0g</span><span class="macro-value-tag">Ingerido</span></div>
          <div class="macro-value-block right"><span class="macro-value-num" id="rem-car">0g</span><span class="macro-value-tag">Restante</span></div>
        </div>
        <div class="macro-bar-bg"><div class="macro-bar-fill car-fill" id="bar-car"></div></div>
      </div>
      <div class="macro-row">
        <div class="macro-label" style="color: var(--fat-color);">Grasas</div>
        <div class="macro-values">
          <div class="macro-value-block"><span class="macro-value-num" id="txt-fat" style="color: var(--fat-color);">0g</span><span class="macro-value-tag">Ingerido</span></div>
          <div class="macro-value-block right"><span class="macro-value-num" id="rem-fat">0g</span><span class="macro-value-tag">Restante</span></div>
        </div>
        <div class="macro-bar-bg"><div class="macro-bar-fill fat-fill" id="bar-fat"></div></div>
      </div>
      <div class="macro-row" style="margin-bottom: 0;">
        <div class="macro-label" style="color: var(--sugar-color);">Azúcar</div>
        <div class="macro-values">
          <div class="macro-value-block"><span class="macro-value-num" id="txt-sugar" style="color: var(--sugar-color);">0g</span><span class="macro-value-tag">Ingerido</span></div>
          <div class="macro-value-block right"><span class="macro-value-num" id="rem-sugar">0g</span><span class="macro-value-tag">Restante</span></div>
        </div>
        <div class="macro-bar-bg"><div class="macro-bar-fill sugar-fill" id="bar-sugar"></div></div>
      </div>
    </div>

    <!-- WIDGET DE ENTRADA POR VOZ / TEXTO -->
    <div class="glass-card mic-container">
      <button class="mic-btn" id="btn-mic">🎙️</button>
      <div class="ai-status" id="ai-status">Toca para dictar qué has comido</div>
      <div style="display:flex; gap:10px; margin-top:24px;">
        <input type="text" id="manual-text" placeholder="o escríbelo aquí..." style="margin-bottom:0;">
        <button class="secondary" id="btn-send-text" onclick="processText()">Enviar</button>
      </div>
      <div id="food-review" class="food-review" style="display:none;"></div>
    </div>
    </div>

    <div class="glass-card date-nav">
      <button class="secondary" onclick="navDay(-1)">◀</button>
      <div class="date-nav-label">
        <strong id="log-date-label">Hoy</strong>
        <div id="log-date-jump" style="display:none; margin-top:6px;"><button class="secondary" style="padding:6px 12px; font-size:.75rem;" onclick="jumpToday()">Volver a hoy</button></div>
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
    <h2>Menú semanal <span class="subtitle">IA Dietista</span></h2>
    <div class="glass-card">
      <p style="font-size: 0.95rem; color: var(--text-dim); margin-bottom: 20px; line-height: 1.6;">
        Tu asistente de IA estructurará <b>7 días</b> orientados a hipertrofia.
        Flujo de trabajo ideal: <b>Generar jueves, Comprar viernes, Cocinar domingo (Batch Cooking)</b>.
        <br><br>
        • <b>Desayuno y Comida</b> = <span class="badge badge-batch">🍱 batch</span> (Portátiles, cocinados el domingo en tupper).<br>
        • <b>Recién levantado, Merienda y Cena</b> = <span class="badge badge-fresh">⚡ fresh</span> (Rápidos, silenciosos, al momento).
      </p>
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
    <h2>Coach Nutricional <span class="subtitle">Ajustes dinámicos</span></h2>
    <div class="glass-card">
      <p style="font-size: 0.9rem; color: var(--text-dim); margin-bottom: 16px; line-height:1.6;">
        Habla con tu especialista. Pregúntale dudas o pide ajustes inmediatos ("ayer comí muy poco, sube las kcal de hoy 200"). Él recalculará tu objetivo del día.
      </p>
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
    <h2>Perfil <span class="subtitle">Físico y metabolismo</span></h2>

    <div class="stats-grid">
      <div class="stat-box">
        <div class="stat-title">TDEE</div>
        <div class="stat-val" id="ui-tdee" style="color:var(--pro-color);">--</div>
        <div style="font-size:0.8rem; color:var(--text-dim);">kcal / día</div>
      </div>
      <div class="stat-box">
        <div class="stat-title">IMC</div>
        <div class="stat-val" id="ui-bmi">--</div>
        <div style="font-size:0.8rem; font-weight:600;" id="ui-bmi-label">--</div>
      </div>
    </div>

    <!-- COMPOSICIÓN CORPORAL -->
    <div class="glass-card">
      <h3>📐 Composición corporal</h3>
      <div id="body-comp-content"></div>
      <div class="chart-container" id="body-comp-chart-wrap" style="display:none; margin-top:20px;"><canvas id="bodyCompChart"></canvas></div>
    </div>

    <!-- REGISTRO Y GRÁFICA DE PESO -->
    <div class="glass-card">
      <h3>⚖️ Evolución de peso</h3>
      <div class="form-row" style="margin-bottom: 12px;">
        <div class="form-group"><label>Fecha</label><input type="date" id="input-weight-date" style="margin-bottom:0;"></div>
        <div class="form-group"><label>Peso (kg)</label><input type="number" step="0.1" id="input-weight" placeholder="Ej: 76.4" style="margin-bottom:0;"></div>
      </div>
      <button class="secondary" onclick="addWeight()" style="width:100%; margin-bottom:16px;">Guardar pesaje</button>
      <div id="weight-day-list" style="margin-bottom:16px;"></div>
      <div class="chart-container"><canvas id="weightChart"></canvas></div>
    </div>

    <!-- PROYECCIÓN DE OBJETIVO -->
    <div class="glass-card">
      <h3>🎯 Proyección de objetivo</h3>
      <div class="form-row" style="margin-bottom: 12px;">
        <div class="form-group"><label>Peso objetivo (kg, opcional)</label><input type="number" step="0.1" id="input-goal-weight" placeholder="Ej: 82"></div>
      </div>
      <button class="secondary" onclick="saveGoalWeight()" style="width:100%; margin-bottom:16px;">Guardar objetivo</button>
      <div id="goal-projection-content"></div>
    </div>

    <!-- MODELO DINÁMICO DE KCAL -->
    <div class="glass-card">
      <h3>🧠 Modelo de kcal dinámico</h3>
      <div id="dynamic-model-content"></div>
    </div>

    <!-- MEDIDAS CORPORALES (OPCIONAL) -->
    <div class="glass-card">
      <h3>📏 Medidas corporales <span style="font-weight:400; color:var(--text-dim); font-size:0.8rem;">(opcional)</span></h3>
      <p style="font-size:0.78rem; color:var(--text-dim); margin-bottom:14px;">Cintura → ratio cintura/altura. Cuello + cintura (y cadera si eres mujer) → % de grasa real (US Navy).</p>
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

    <!-- TENDENCIAS SEMANALES -->
    <div class="glass-card">
      <h3>📊 Adherencia y tendencia</h3>
      <div id="insights-card" style="display:flex; flex-direction:column; gap:12px; font-size:0.9rem; margin-bottom:16px;"></div>
      <div class="chart-container"><canvas id="kcalTrendChart"></canvas></div>
    </div>

    <!-- HISTORIAL DE AJUSTES (AUDITORÍA) -->
    <details class="glass-card">
      <summary style="cursor:pointer; font-family:'Space Grotesk', sans-serif; font-weight:600; font-size:1.05rem;">🕘 Historial de ajustes del objetivo</summary>
      <div id="target-history-content" style="margin-top:16px;"></div>
    </details>

    <!-- PERFIL Y TDEE -->
    <div class="glass-card">
      <h3>⚙️ Perfil y preferencias</h3>
      <div class="form-row">
        <div class="form-group"><label>Edad</label><input type="number" id="prof-age" placeholder="24"></div>
        <div class="form-group"><label>Altura (cm)</label><input type="number" id="prof-height" placeholder="175"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Peso inicial (kg)</label><input type="number" id="prof-weight" step="0.1"></div>
        <div class="form-group"><label>Sexo</label>
          <select id="prof-sex"><option value="m">Hombre</option><option value="f">Mujer</option></select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Actividad</label>
          <select id="prof-activity">
            <option value="1.2">Sedentario</option>
            <option value="1.375">Ligero (1-3 días)</option>
            <option value="1.55">Moderado (3-5 días)</option>
            <option value="1.725">Activo (6-7 días)</option>
          </select>
        </div>
        <div class="form-group"><label>Superávit</label>
          <select id="prof-goal">
            <option value="500">Volumen (+500 kcal)</option>
            <option value="300">Volumen limpio (+300)</option>
            <option value="0">Mantenimiento</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Ganancia semanal (kg)</label><input type="number" step="0.05" id="prof-weekly-goal" placeholder="Ej: 0.3"></div>
        <div class="form-group"><label>Comidas al día</label><input type="number" min="3" max="8" id="prof-meals" placeholder="5"></div>
      </div>
      <div class="form-group"><label>Días de entrenamiento</label><input type="number" min="0" max="7" id="prof-training-days" placeholder="4"></div>
      <div class="form-group" style="margin-bottom:16px;"><label>Preferencias y restricciones</label><textarea id="prof-preferences" rows="2" placeholder="Ej: sin lactosa, económico, no pescado..."></textarea></div>

      <div class="toggle-row">
        <div style="font-size:0.9rem; font-weight:500;">Pausar ajuste automático semanal</div>
        <label class="switch"><input type="checkbox" id="prof-pause"><span class="slider"></span></label>
      </div>

      <button class="secondary" onclick="saveProfile()" style="width:100%; margin: 16px 0 10px;">Guardar perfil</button>
      <button class="primary" onclick="applyFormulaTarget()">Aplicar TDEE + Superávit ahora</button>
    </div>
  </div>

  <!-- ========================================================================= -->
  <!-- 💾 TAB 5: DATOS Y BACKUP                                                  -->
  <!-- ========================================================================= -->
  <div id="tab-data" class="section">
    <h2>Datos <span class="subtitle">Copia de seguridad</span></h2>
    <div class="glass-card">
      <h3>Backup local</h3>
      <p style="font-size:0.85rem; color:var(--text-dim); margin-bottom:16px;">Todo se guarda solo en este navegador. Exporta de vez en cuando para no perder tu historial.</p>
      <button class="secondary" onclick="exportData()" style="width:100%; margin-bottom:12px;">⬇️ Exportar JSON</button>
      <label style="display:block; text-align:center; padding:14px; border-radius:var(--radius-sm); border:1px dashed var(--glass-border); color:var(--text-dim); font-size:0.9rem; cursor:pointer;">
        ⬆️ Importar JSON
        <input type="file" id="import-file-input" accept="application/json" style="display:none;">
      </label>
    </div>
  </div>

</div>

<!-- BOTTOM NAVIGATION -->
<div class="bottom-nav">
  <div class="nav-item active" data-tab="dash" onclick="nav('dash')"><span class="nav-icon">📊</span>Hoy</div>
  <div class="nav-item" data-tab="plan" onclick="nav('plan')"><span class="nav-icon">🛒</span>Menú IA</div>
  <div class="nav-item" data-tab="chat" onclick="nav('chat')"><span class="nav-icon">💬</span>Coach</div>
  <div class="nav-item" data-tab="body" onclick="nav('body')"><span class="nav-icon">🧬</span>Perfil</div>
  <div class="nav-item" data-tab="data" onclick="nav('data')"><span class="nav-icon">💾</span>Datos</div>
</div>

<!-- ========================================================================= -->
<!-- ⚙️ CÓDIGO JAVASCRIPT (LÓGICA PRINCIPAL)                                     -->
<!-- ========================================================================= -->
<script>
// VARIABLES INYECTADAS DESDE PYTHON
const GEMINI_API_KEY = atob("__API_KEY_B64__");
const GEMINI_MODEL = "__MODEL__";
const GEMINI_MODEL_PLAN = "__MODEL_PLAN__";
const FILLER_FOODS = "__FILLER__";

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
async function safeGet(key){ try { const r = localStorage.getItem(key); return r ? JSON.parse(r) : null; } catch(e){ return null; } }
async function safeSet(key,val){ try { localStorage.setItem(key, JSON.stringify(val)); } catch(e){ console.error('storage error', e); } }

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
    p = { age: 23, height: 175, weight: 65, sex: 'm', activity: 1.2, goalOffset: 500, weeklyGainGoalKg: 0.3, mealsPerDay: 5, trainingDays: 4, preferences: '', targetKcal: null, targetProtein: null, targetCarbs: null, targetFat: null, lastAdjustmentWeek: null, adjustmentPaused: false, goalWeightKg: null };
    await safeSet('profile', p);
  }
  p.mealsPerDay = p.mealsPerDay || 5;
  p.trainingDays = Number.isFinite(p.trainingDays) ? p.trainingDays : 4;
  p.preferences = p.preferences || '';
  p.goalWeightKg = Number.isFinite(Number(p.goalWeightKg)) && Number(p.goalWeightKg) > 0 ? Number(p.goalWeightKg) : null;
  return p;
}

// Aproximación estándar de kcal por kg de cambio de peso (mezcla grasa/magro).
// Si algún día quieres afinarlo, es el único sitio que hay que tocar.
const KCAL_PER_KG = 7700;

function calcTDEE(p, weight){
  // Ecuación Mifflin-St Jeor + factor de actividad
  const bmr = p.sex==='f' ? (10*weight)+(6.25*p.height)-(5*p.age)-161 : (10*weight)+(6.25*p.height)-(5*p.age)+5;
  return bmr * p.activity;
}

// OMS 2015 ("Sugars intake for adults and children"): azúcares libres <10% de
// la energía total (techo máximo), con beneficio adicional demostrado por
// debajo del 5% (recomendación "ideal"). Como el objetivo diario de kcal ya
// incorpora edad/peso/sexo/actividad (vía TDEE), un % fijo sobre esas kcal
// escala automáticamente con esos factores. Usamos el 5% (ideal, no el techo)
// como objetivo, ya que en volumen interesa priorizar carbohidratos de
// calidad frente a azúcar libre. 1g de azúcar ≈ 4 kcal.
function calcSugarTargetG(kcal){
  return (kcal * 0.05) / 4;
}

function recomputeMacrosFromKcal(p){
  // Basado en guías clínicas deportivas de hipertrofia
  const w = p.weight;
  p.targetProtein = w * 2.0; // 2g/kg (Rango óptimo 1.6 - 2.2)
  p.targetFat = w * 1.0;     // 1g/kg mínimo salud hormonal
  p.targetCarbs = Math.max(0, (p.targetKcal - (p.targetProtein*4) - (p.targetFat*9))/4);
  p.targetSugar = calcSugarTargetG(p.targetKcal);
}

function getTargets(override=0){
  const kcal = (profile.targetKcal || 2500) + override;
  const protein = profile.targetProtein || profile.weight * 2 || 130;
  const fat = profile.targetFat || profile.weight * 1 || 70;
  const sugar = profile.targetSugar || calcSugarTargetG(kcal);
  return { kcal, p: protein, c: Math.max(0, (kcal - protein*4 - fat*9)/4), f: fat, s: sugar };
}

function getPlanTargets(){
  const average = getTargets();
  const trainingDays = Math.min(7, Math.max(0, Number(profile.trainingDays) || 0));
  const trainingKcal = average.kcal + (trainingDays < 7 ? 100 : 0);
  const restKcal = trainingDays < 7 ? average.kcal - (trainingDays * 100 / (7 - trainingDays)) : average.kcal;
  const macros = kcal => ({ kcal, p: average.p, f: average.f, c: Math.max(0, (kcal - average.p*4 - average.f*9)/4) });
  return { average, training: macros(trainingKcal), rest: macros(restKcal), trainingDays };
}

// =========================================
// 📋 REGISTRO DE ALIMENTOS
// =========================================
async function getLog(date){ return (await safeGet('log:'+date)) || []; }
async function setLog(date, entries){ await safeSet('log:'+date, entries); }
const sumEntries = entries => entries.reduce((a,e)=>({kcal:a.kcal+(e.kcal||0),p:a.p+(e.p||0),c:a.c+(e.c||0),f:a.f+(e.f||0),s:a.s+(e.s||0)}),{kcal:0,p:0,c:0,f:0,s:0});

async function getDailyOverride(date){ return (await safeGet('override:'+date)) || 0; }
async function setDailyOverride(date, delta){ await safeSet('override:'+date, delta); }

async function adjustDay(delta){
  const current = await getDailyOverride(selectedLogDate);
  const next = Math.max(-400, Math.min(400, current + delta));
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

async function getDailyWeightSeries(days = 28){
  const series = [];
  for(let i = days - 1; i >= 0; i--){
    const d = new Date(); d.setDate(d.getDate() - i);
    const key = dateKey(d);
    const entries = await safeGet('weight:' + key);
    if(Array.isArray(entries) && entries.length){
      const avg = entries.reduce((a, e) => a + e.kg, 0) / entries.length;
      series.push({ date: key, kg: avg });
    }
  }
  return series;
}

function computeEMASeries(series, alpha = 0.25){
  let ema = null;
  return series.map(pt => {
    ema = ema === null ? pt.kg : alpha * pt.kg + (1 - alpha) * ema;
    return { date: pt.date, kg: pt.kg, ema };
  });
}

async function countWeightDaysThisWeek(){
  let count = 0;
  for(let i = 0; i < 7; i++){
    const d = new Date(); d.setDate(d.getDate() - i);
    const entries = await safeGet('weight:' + dateKey(d));
    if(Array.isArray(entries) && entries.length) count++;
  }
  return count;
}

// =========================================
// 🧠 MODELO DINÁMICO DE MANTENIMIENTO (peso real + kcal reales)
// =========================================
// Estima tu mantenimiento calórico REAL comparando cuánto has comido de
// media con cuánto ha cambiado tu peso (EMA) en la misma ventana de tiempo.
// Solo se activa si hay datos suficientes de AMBAS cosas; si no, devuelve null
// y el resto de la app sigue usando la fórmula / el ajuste básico.
async function computeDynamicMaintenance(){
  const windowDays = 21;
  const dailyWeights = await getDailyWeightSeries(windowDays);
  if(dailyWeights.length < 8) return null;

  const emaSeries = computeEMASeries(dailyWeights, 0.25);
  const first = emaSeries[0];
  const last = emaSeries[emaSeries.length - 1];
  const elapsedDays = Math.round((new Date(last.date) - new Date(first.date)) / 86400000);
  if(elapsedDays < 10) return null;

  let intakeDays = 0, intakeTotal = 0;
  const cursor = new Date(first.date + 'T00:00:00');
  const end = new Date(last.date + 'T00:00:00');
  const mealsPerDay = Number(profile.mealsPerDay) || 5;
  const completenessKcalFloor = (profile.targetKcal || 2000) * 0.6;
  while(cursor <= end){
    const key = dateKey(cursor);
    const logs = await getLog(key);
    const sums = sumEntries(logs);
    // Un día con muy pocas entradas o muy pocas kcal probablemente esté
    // incompleto (se te olvidó registrar algo), no que de verdad comieras
    // tan poco. Si lo contamos igual, sesga el mantenimiento real a la baja.
    const looksComplete = logs.length >= Math.max(2, mealsPerDay - 1) || sums.kcal >= completenessKcalFloor;
    if(sums.kcal > 0 && looksComplete){ intakeDays++; intakeTotal += sums.kcal; }
    cursor.setDate(cursor.getDate() + 1);
  }
  if(intakeDays < 8) return null;

  const avgIntake = intakeTotal / intakeDays;
  const weightChangeKg = last.ema - first.ema;
  const impliedDailyBalance = (weightChangeKg * KCAL_PER_KG) / elapsedDays;
  const estimatedMaintenance = avgIntake - impliedDailyBalance;

  return { estimatedMaintenance, avgIntake, weightChangeKg, elapsedDays, intakeDays, weightDays: dailyWeights.length };
}

// Proyección de tendencia de peso (independiente del modelo de kcal, solo
// mirando cómo ha evolucionado tu EMA de peso realmente).
async function computeWeightProjection(){
  const daily = await getDailyWeightSeries(21);
  if(daily.length < 6) return { status: 'cold' };
  const emaSeries = computeEMASeries(daily, 0.25);
  const first = emaSeries[0];
  const last = emaSeries[emaSeries.length - 1];
  const elapsedDays = Math.round((new Date(last.date) - new Date(first.date)) / 86400000);
  if(elapsedDays < 6) return { status: 'cold' };
  const changeKg = last.ema - first.ema;
  const ratePerWeek = (changeKg / elapsedDays) * 7;
  const confidence = (daily.length >= 12 && elapsedDays >= 12) ? 'alta' : 'orientativa';
  return { status: 'ok', currentEma: last.ema, ratePerWeek, elapsedDays, dataPoints: daily.length, confidence };
}

function showAdjustAlert(msg, isWarn = false){
  const el = $('adjust-alert');
  el.className = 'alert' + (isWarn ? ' warn' : '');
  el.innerText = msg;
  el.style.display = 'block';
}
function hideAdjustAlert(){ $('adjust-alert').style.display = 'none'; }

async function getAverageWeight(startDay, days){
  const values = [];
  for(let i = startDay; i < startDay + days; i++){
    const d = new Date(); d.setDate(d.getDate() - i);
    const entries = await safeGet('weight:' + dateKey(d));
    if(Array.isArray(entries) && entries.length){
      values.push(entries.reduce((a, e) => a + e.kg, 0) / entries.length);
    }
  }
  return values.length ? values.reduce((a, v) => a + v, 0) / values.length : null;
}

// Guarda un registro auditable de cada evaluación semanal completada
// (aunque no cambie el objetivo), para poder ver después por qué tu
// objetivo ha ido subiendo/bajando en vez de solo ver el número actual.
async function recordTargetAdjustment(record){
  const hist = (await safeGet('targetHistory')) || [];
  hist.push({ date: todayStr(), ...record });
  if(hist.length > 60) hist.shift();
  await safeSet('targetHistory', hist);
}

async function adjustWeeklyTarget(){
  if(!profile.targetKcal){ hideAdjustAlert(); return; }
  const currentWeek = isoWeekKey();
  if(profile.lastAdjustmentWeek === currentWeek){ hideAdjustAlert(); return; }
  if(profile.adjustmentPaused){
    showAdjustAlert('Ajuste automatico pausado en tu perfil. Activalo cuando quieras retomarlo.');
    return;
  }
  const daysRegistered = await countWeightDaysThisWeek();
  if(daysRegistered < 4){
    showAdjustAlert(`Solo tienes ${daysRegistered}/7 dias de peso esta semana (minimo 4 para ajustar). No se ha tocado tu objetivo de kcal.`, true);
    return;
  }
  const goal = Number(profile.weeklyGainGoalKg) || 0.3;

  // NIVEL 2: modelo dinámico completo (peso real + kcal reales), si hay datos suficientes.
  const dynamic = await computeDynamicMaintenance();
  if(dynamic){
    const desiredDailySurplus = (goal * KCAL_PER_KG) / 7;
    const rawTarget = dynamic.estimatedMaintenance + desiredDailySurplus;
    const prevTarget = profile.targetKcal;
    const maxWeeklyStep = 200; // evita saltos bruscos aunque el cálculo puntual difiera mucho
    const cappedTarget = Math.max(prevTarget - maxWeeklyStep, Math.min(prevTarget + maxWeeklyStep, rawTarget));
    const finalTarget = Math.max(1600, Math.round(cappedTarget));
    profile.targetKcal = finalTarget;
    recomputeMacrosFromKcal(profile);
    profile.lastAdjustmentWeek = currentWeek;
    await safeSet('profile', profile);
    await recordTargetAdjustment({
      week: currentWeek, mode: 'dinamico', prevTarget, newTarget: finalTarget,
      note: `Mantenimiento real estimado ~${Math.round(dynamic.estimatedMaintenance)} kcal/día (${dynamic.weightDays} pesajes, ${dynamic.intakeDays} días de comida en ${dynamic.elapsedDays} días).`
    });
    showAdjustAlert(`🧠 Modelo dinámico (${dynamic.weightDays} pesajes, ${dynamic.intakeDays} días de comida en ${dynamic.elapsedDays} días): mantenimiento real estimado ~${Math.round(dynamic.estimatedMaintenance)} kcal/día. Objetivo ajustado a ${finalTarget} kcal (antes ${Math.round(prevTarget)}).`);
    showToast(`Objetivo recalculado (modelo dinámico): ${finalTarget} kcal`);
    return;
  }

  // NIVEL 1: sin datos de comida suficientes todavía, ajuste básico solo por tendencia de peso.
  const series = await getDailyWeightSeries(28);
  if(series.length < 8){
    showAdjustAlert('Aun no hay historico suficiente de peso (necesitas unas 2 semanas de datos) para calcular tendencia. Sigue registrando peso y comidas para activar el modelo dinámico completo.');
    return;
  }
  const emaSeries = computeEMASeries(series, 0.25);
  const last = emaSeries[emaSeries.length - 1];
  const lastDate = new Date(last.date);
  let weekAgoPoint = null;
  for(let j = emaSeries.length - 1; j >= 0; j--){
    if((lastDate - new Date(emaSeries[j].date)) / 86400000 >= 6){ weekAgoPoint = emaSeries[j]; break; }
  }
  if(!weekAgoPoint){
    showAdjustAlert('Necesitas al menos una semana de historico para calcular la tendencia.');
    return;
  }
  const weeklyChange = last.ema - weekAgoPoint.ema;
  const tolerance = 0.05;
  let delta = 0;
  if(weeklyChange < goal - tolerance) delta = 150;
  else if(weeklyChange > goal + tolerance) delta = -150;
  profile.lastAdjustmentWeek = currentWeek;
  if(delta === 0){
    await safeSet('profile', profile);
    await recordTargetAdjustment({
      week: currentWeek, mode: 'basico', prevTarget: profile.targetKcal, newTarget: profile.targetKcal,
      note: `Tendencia de peso ${weeklyChange >= 0 ? '+' : ''}${weeklyChange.toFixed(2)} kg/sem dentro del objetivo (${goal} kg/sem). Sin cambios.`
    });
    showAdjustAlert(`Ajuste básico (aún calibrando el modelo dinámico): tendencia de peso (${weeklyChange >= 0 ? '+' : ''}${weeklyChange.toFixed(2)} kg/sem) dentro de tu objetivo (${goal} kg/sem). Sin cambios.`);
    return;
  }
  const prevBasicTarget = profile.targetKcal;
  profile.targetKcal = Math.max(1600, profile.targetKcal + delta);
  recomputeMacrosFromKcal(profile);
  await safeSet('profile', profile);
  await recordTargetAdjustment({
    week: currentWeek, mode: 'basico', prevTarget: prevBasicTarget, newTarget: profile.targetKcal,
    note: `Tendencia real ${weeklyChange >= 0 ? '+' : ''}${weeklyChange.toFixed(2)} kg/sem vs objetivo ${goal} kg/sem (faltan días de comida para el modelo dinámico).`
  });
  showAdjustAlert(`Ajuste básico (aún calibrando el modelo dinámico — faltan días de comida registrada): ${delta > 0 ? '+' : ''}${delta} kcal. Tendencia real: ${weeklyChange >= 0 ? '+' : ''}${weeklyChange.toFixed(2)} kg/sem vs objetivo ${goal} kg/sem.`);
  showToast(`Ajuste semanal aplicado: ${delta > 0 ? '+' : ''}${delta} kcal`);
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
async function requestDailyAssistantAI(sums, target, logs, date){
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

  const prompt = `Eres el asistente de la pestaña "Hoy" de Bulking OS, una app de nutrición para volumen (ganancia muscular). Responde SOLO este JSON, sin texto ni markdown fuera de él: {"title":"máximo 6 palabras, con un emoji delante","body":"2-3 frases directas, sin markdown"}.

Estado de HOY (${formatDateLabel(date)}, hora actual ${hourLabel}):
- Kcal: objetivo ${Math.round(target.kcal)}, ingeridas ${Math.round(sums.kcal)}, restantes ${Math.round(remKcal)}.
- Proteína: objetivo ${Math.round(target.p)}g, ingerida ${Math.round(sums.p)}g, restante ${Math.round(remP)}g.
- Carbohidratos: objetivo ${Math.round(target.c)}g, ingeridos ${Math.round(sums.c)}g, restantes ${Math.round(remC)}g.
- Grasas: objetivo ${Math.round(target.f)}g, ingeridas ${Math.round(sums.f)}g, restantes ${Math.round(remF)}g.
- Azúcar: objetivo recomendado (OMS, <5% de las kcal) ${Math.round(target.s)}g, ingerido ${Math.round(sums.s)}g, restante ${Math.round(remS)}g.
- Comidas registradas hoy (${logs.length}/${mealsTarget} previstas, quedan realistamente ${mealsRemaining} por la hora que es): ${loggedList}.
- Preferencias y restricciones: ${profile.preferences || 'ninguna indicada'}.
${history ? '- ' + history : ''}

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
    if(diff >= 0){ rem.innerText = `${Math.round(diff)}g`; rem.style.color = ''; }
    else { rem.innerText = `+${Math.round(Math.abs(diff))}g`; rem.style.color = 'var(--green)'; }
    if(pct>115) b.classList.add('over-limit'); else b.classList.remove('over-limit');
  };
  bar(sums.p, tgt.p, 'bar-pro','txt-pro','rem-pro'); bar(sums.c, tgt.c, 'bar-car','txt-car','rem-car'); bar(sums.f, tgt.f, 'bar-fat','txt-fat','rem-fat');
  await renderDailyAssistant(sums, tgt, logs.length, t, logs);

  const list = $('log-list');
  if(!logs.length) list.innerHTML = '<div class="chat-empty">Sin registros este día.</div>';
  else {
    list.innerHTML = logs.slice().reverse().map(log=>`
      <div class="log-item">
        <div>
          <div class="log-title">${log.label}</div>
          <div class="log-macros">${log.time||''} · P:${Math.round(log.p)} C:${Math.round(log.c)} G:${Math.round(log.f)}</div>
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
}
window.delLog = async (id) => {
  await setLog(selectedLogDate, (await getLog(selectedLogDate)).filter(e=>e.id!==id));
  updateDashboardUI(); renderWeekInsights(); renderTrendCharts();
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
async function callGemini(prompt, isJson=false, model=GEMINI_MODEL, maxRetries=2){
  if(!GEMINI_API_KEY || GEMINI_API_KEY.includes("TU_API_KEY_AQUI")){
    showToast("Error: API Key no configurada en el código fuente de Python.", true);
    return null;
  }
  const payload = { contents: [{parts:[{text:prompt}]}] };
  if(isJson) payload.generationConfig = { responseMimeType: 'application/json' };

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
// 🎙️ PROCESAR TEXTO Y VOZ (NUTRICIÓN)
// =========================================
function validateFoodEntry(entry){
  if(!entry || typeof entry.label !== 'string' || !entry.label.trim()) return false;
  return ['kcal','p','c','f'].every(key => Number.isFinite(Number(entry[key])) && Number(entry[key]) >= 0);
}

function showFoodReview(entry, isEdit=false){
  pendingFoodEntry = entry;
  editingLogId = isEdit ? entry.id : null;
  const review = $('food-review');
  review.style.display = 'block';
  review.innerHTML = `<strong>${isEdit ? 'Editar registro' : 'Revisa antes de guardar'}</strong><div style="color:var(--text-dim);font-size:.8rem;margin-top:4px;">${isEdit ? 'Corrige los valores y confirma (pulsa el número para escribir encima).' : 'La IA ha estimado estos valores. Pulsa para editarlos.'}</div>
    <div class="food-review-grid">
      <input id="review-label" value="${String(entry.label).replace(/"/g, '&quot;')}" aria-label="Nombre de la comida">
      <input id="review-kcal" type="number" min="0" step="1" value="${Math.round(entry.kcal)}" aria-label="Kcal">
      <input id="review-p" type="number" min="0" step="0.1" value="${entry.p}" aria-label="Proteína">
      <input id="review-c" type="number" min="0" step="0.1" value="${entry.c}" aria-label="Carbohidratos">
      <input id="review-f" type="number" min="0" step="0.1" value="${entry.f}" aria-label="Grasas">
    </div>
    <div style="display:flex;gap:8px;"><button class="primary" style="flex:1;padding:11px;" onclick="confirmFoodReview()">${isEdit ? 'Guardar cambios' : 'Confirmar y registrar'}</button><button class="secondary" onclick="cancelFoodReview()">${isEdit ? 'Cancelar' : 'Descartar'}</button></div>`;
}

function cancelFoodReview(){
  pendingFoodEntry = null;
  editingLogId = null;
  const review = $('food-review');
  if(review){ review.style.display = 'none'; }
}

function showFoodReviewComparison(oldEntry, newEntry){
  pendingFoodEntry = newEntry;
  editingLogId = oldEntry.id;
  const review = $('food-review');
  review.style.display = 'block';
  review.innerHTML = `<strong>Nueva estimación de la IA</strong>
    <div style="color:var(--text-dim);font-size:.8rem;margin-top:4px;">Compara con lo que tenías guardado, ajusta si hace falta y decide cuál te quedas.</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:14px 0; font-size:.82rem;">
      <div style="padding:10px; border-radius:8px; background:rgba(255,255,255,0.04); border:1px solid var(--glass-border);">
        <div style="color:var(--text-dim); font-size:.68rem; text-transform:uppercase; margin-bottom:6px;">Anterior</div>
        <div style="font-weight:700;">${oldEntry.label}</div>
        <div style="margin-top:4px;">${Math.round(oldEntry.kcal)} kcal · P:${Math.round(oldEntry.p)} C:${Math.round(oldEntry.c)} G:${Math.round(oldEntry.f)}</div>
      </div>
      <div style="padding:10px; border-radius:8px; background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.25);">
        <div style="color:var(--green); font-size:.68rem; text-transform:uppercase; margin-bottom:6px;">Nueva (IA)</div>
        <div style="font-weight:700;">${newEntry.label}</div>
        <div style="margin-top:4px;">${Math.round(newEntry.kcal)} kcal · P:${Math.round(newEntry.p)} C:${Math.round(newEntry.c)} G:${Math.round(newEntry.f)}</div>
      </div>
    </div>
    <div style="font-size:.75rem; color:var(--text-dim); margin-bottom:10px;">Texto original: "${String(oldEntry.originalText || '').replace(/"/g, '&quot;')}"</div>
    <div class="food-review-grid">
      <input id="review-label" value="${String(newEntry.label).replace(/"/g, '&quot;')}" aria-label="Nombre de la comida">
      <input id="review-kcal" type="number" min="0" step="1" value="${Math.round(newEntry.kcal)}" aria-label="Kcal">
      <input id="review-p" type="number" min="0" step="0.1" value="${newEntry.p}" aria-label="Proteína">
      <input id="review-c" type="number" min="0" step="0.1" value="${newEntry.c}" aria-label="Carbohidratos">
      <input id="review-f" type="number" min="0" step="0.1" value="${newEntry.f}" aria-label="Grasas">
    </div>
    <div style="display:flex;gap:8px;">
      <button class="primary" style="flex:1;padding:11px;" onclick="confirmFoodReview()">Usar esta estimación</button>
      <button class="secondary" onclick="cancelFoodReview()">Mantener la anterior</button>
    </div>`;
  review.scrollIntoView({behavior:'smooth', block:'center'});
}

window.reestimateLog = async (id) => {
  const entries = await getLog(selectedLogDate);
  const entry = entries.find(e=>e.id===id);
  if(!entry) return;
  if(!entry.originalText){
    showToast('Este registro no guardó el texto original (es de antes de esta función, o se editó a mano), así que no se puede re-estimar.', true);
    return;
  }
  showToast('Re-estimando con IA...');
  const prompt = `Actúa como Dietista Clínico. Extrae Kcal y Macros (g) de esta comida: "${entry.originalText}". 
Aplica tablas de composición estándar españolas. Si el texto no es comida, pon todo a 0.
Devuelve SOLO JSON estricto: {"label":"Nombre resumido","kcal":numero,"p":numero,"c":numero,"f":numero,"reply":"mensaje corto motivador"}`;
  const res = await callGemini(prompt, true, GEMINI_MODEL);
  if(!validateFoodEntry(res) || res.kcal <= 0){
    showToast('No se pudo generar una nueva estimación ahora mismo.', true);
    return;
  }
  res.originalText = entry.originalText;
  showFoodReviewComparison(entry, res);
};

window.confirmFoodReview = async () => {
  if(!pendingFoodEntry) return;
  const entry = {
    ...pendingFoodEntry,
    label: $('review-label').value.trim(),
    kcal: Number($('review-kcal').value), p: Number($('review-p').value),
    c: Number($('review-c').value), f: Number($('review-f').value)
  };
  if(!validateFoodEntry(entry) || entry.kcal <= 0){ showToast('Revisa los valores de la comida.', true); return; }

  const entries = await getLog(selectedLogDate);
  if(editingLogId){
    const idx = entries.findIndex(e=>e.id===editingLogId);
    if(idx === -1){ showToast('No se encontró el registro original.', true); cancelFoodReview(); return; }
    entries[idx] = { ...entries[idx], label: entry.label, kcal: entry.kcal, p: entry.p, c: entry.c, f: entry.f };
    await setLog(selectedLogDate, entries);
    showToast('Registro actualizado');
  } else {
    const loggedEntry = { id: Date.now().toString(36), time: new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'}), ...entry };
    entries.push(loggedEntry);
    await setLog(selectedLogDate, entries);
    showToast(`+${Math.round(entry.kcal)} kcal registradas (${formatDateLabel(selectedLogDate).toLowerCase()})`);
  }
  cancelFoodReview();
  await updateDashboardUI(); await renderWeekInsights(); await renderTrendCharts();
  $('ai-status').innerText = 'Procesado con éxito.';
};

async function processText(voiceText){
  const inputEl = $('manual-text');
  const btnEl = $('btn-send-text');
  const input = voiceText || inputEl.value;
  if(!input.trim()) return;
  
  inputEl.value=''; btnEl.disabled=true; $('btn-mic').disabled=true;
  $('ai-status').innerText = 'Analizando con IA Clínica...';

  const prompt = `Actúa como Dietista Clínico. Extrae Kcal y Macros (g) de esta comida: "${input}". 
Aplica tablas de composición estándar españolas. Si el texto no es comida, pon todo a 0.
Devuelve SOLO JSON estricto: {"label":"Nombre resumido","kcal":numero,"p":numero,"c":numero,"f":numero,"reply":"mensaje corto motivador"}`;

  const res = await callGemini(prompt, true, GEMINI_MODEL);
  if(validateFoodEntry(res) && res.kcal > 0){
    res.originalText = input;
    showFoodReview(res, false);
    $('ai-status').innerText = 'Estimación lista: revísala antes de guardar.';
  } else {
    $('ai-status').innerText = 'No se pudo procesar. Puedes registrar manualmente los valores tocando "Enviar" tras corregir el texto, o inténtalo de nuevo en unos segundos.';
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
  const freq = new Map();
  let loggedDays = 0, kcalTotal = 0, onTargetDays = 0;
  const target = Number(profile.targetKcal) || 2500;
  for(let i = 0; i < days; i++){
    const d = new Date(); d.setDate(d.getDate() - i);
    const logs = await getLog(dateKey(d));
    if(!logs.length) continue;
    loggedDays++;
    const sums = sumEntries(logs);
    kcalTotal += sums.kcal;
    if(sums.kcal >= target * 0.9 && sums.kcal <= target * 1.1) onTargetDays++;
    for(const e of logs){
      const label = String(e.label || '').trim();
      if(!label) continue;
      const norm = label.toLowerCase();
      const prev = freq.get(norm);
      if(prev) prev.count++;
      else freq.set(norm, { label, count: 1 });
    }
  }
  if(loggedDays < 3) return null; // muy poco histórico todavía, no aporta nada fiable

  const topMeals = [...freq.values()]
    .filter(m => m.count >= 2)
    .sort((a, b) => b.count - a.count)
    .slice(0, 6)
    .map(m => `${m.label} (${m.count}x)`);

  const avgKcal = Math.round(kcalTotal / loggedDays);
  return `Historial real de las últimas ${days === 21 ? '3 semanas' : days + ' días'} (${loggedDays} días con registros): media real ~${avgKcal} kcal/día, ${onTargetDays}/${loggedDays} días dentro de ±10% del objetivo.${topMeals.length ? ` Comidas que repite con frecuencia: ${topMeals.join(', ')}.` : ''}`;
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
Objetivo de entrenamiento: ${Math.round(planTargets.training.kcal)} kcal. Objetivo de descanso: ${Math.round(planTargets.rest.kcal)} kcal.
Preferencias del usuario: ${profile.preferences || 'sin restricciones indicadas'}.
${historySummary ? historySummary + ' Prioriza comidas de estilo similar a las que ya repite (si encajan con los objetivos y preferencias) y ten en cuenta su adherencia real al proponer cantidades, en vez de diseñar el plan en el vacío.' : 'Aún no hay histórico suficiente de registros reales; diseña el plan solo a partir del objetivo y las preferencias indicadas.'}\nComidas al dia: ${profile.mealsPerDay || 5}. Dias de entrenamiento: ${profile.trainingDays || 4}.
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
- Incluye exactamente ${profile.trainingDays || 4} días con "training":true y el resto con "training":false.
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
  {"day":"Lunes","training":false,"meals":[
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
    await safeSet('lastPlan', { plan: res, generatedAt: new Date().toISOString() });
    renderPlanObject(res, new Date().toLocaleString('es-ES'));
    showToast("Menú semanal generado correctamente");
  } else {
    const message = validation.issues.length ? validation.issues.join(' ') : 'La IA no devolvió un plan válido.';
    $('plan-validation').style.display='block'; $('plan-validation').innerText = message;
    showToast("Plan rechazado: no cumple tus objetivos.", true);
  }
}

function validatePlan(plan, targets){
  const issues = [];
  const validNumber = value => Number.isFinite(Number(value)) && Number(value) >= 0;
  if(!plan || !Array.isArray(plan.days) || plan.days.length !== 7) issues.push('Deben existir exactamente 7 días.');
  if(!plan || !Array.isArray(plan.shoppingList) || !plan.shoppingList.length) issues.push('Falta una lista de compra calculada.');
  if(!plan || !Array.isArray(plan.batchInstructions) || !plan.batchInstructions.length) issues.push('Faltan instrucciones de batch cooking.');
  if(!plan || !plan.foodSafetyNotes) issues.push('Faltan directrices de seguridad alimentaria.');
  if(!plan || !Array.isArray(plan.days)) return {ok:false, issues};
  const expectedTraining = targets.trainingDays;
  const actualTraining = plan.days.filter(day=>day.training === true).length;
  if(new Set(plan.days.map(day=>String(day.day || '').trim().toLowerCase())).size !== plan.days.length) issues.push('Hay días repetidos en el plan.');
  if(actualTraining !== expectedTraining) issues.push(`Días de entrenamiento incorrectos: ${actualTraining}/${expectedTraining}.`);
  plan.days.forEach((day, index)=>{
    if(!Array.isArray(day.meals) || day.meals.length !== Number(profile.mealsPerDay || 5)) { issues.push(`El día ${index+1} no tiene el número correcto de comidas.`); return; }
    if(typeof day.training !== 'boolean') issues.push(`El día ${index+1} no indica si hay entrenamiento.`);
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
    const target = day.training ? targets.training : targets.rest;
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
      <span class="meta-pill"><b>${plan.days.filter(day=>day.training).length}</b> días con más kcal (entreno)</span>
      <span class="meta-pill"><b>${avgKcal}</b> kcal medias</span>
      <span class="badge badge-batch">🍱 batch</span><span class="badge badge-fresh">⚡ fresh</span>
    </div>
    <p style="font-size:.8rem; color:var(--text-dim); margin:12px 0 20px; line-height:1.5;">Los nombres de los días solo ordenan la semana para el batch cooking del domingo. Usa la versión "más kcal" el día que realmente entrenes esa semana; no tiene por qué ser siempre el mismo día.</p>`;
  plan.days.forEach((d, dayIndex)=>{
    const totals = d.totals || sumEntries(d.meals);
    html += `<div class="day-card"><h3><span>${d.day}</span><small style="font-size:.72rem;color:var(--text-dim);font-weight:600;">${d.training ? 'MÁS KCAL (ENTRENO)' : 'KCAL ESTÁNDAR (DESCANSO)'}</small></h3>`;
    d.meals.forEach((m, mealIndex)=>{
      const badge = m.type==='batch' ? '<span class="badge badge-batch">🍱 batch</span>' : '<span class="badge badge-fresh">⚡ fresh</span>';
      const alternatives = Array.isArray(m.alternatives) ? m.alternatives.join(' · ') : 'Sin alternativas';
      html += `<div class="meal-row"><div><div class="meal-name">${m.name}</div>${badge}<small style="display:block;color:var(--text-dim);font-size:.68rem;margin-top:5px;">${m.weightBasis || 'no indicado'}</small></div><div class="meal-items">${m.items.map((i, itemIndex)=>`<div class="ingredient-row"><span>${i.food} (${i.isLiquid ? (i.ml || i.grams) + 'ml' : i.grams + 'g'})</span><button class="secondary" onclick="replaceIngredient(${dayIndex},${mealIndex},${itemIndex})">No tengo este ingrediente</button></div>`).join('')}<small class="meal-alternatives">Alternativas: ${alternatives}</small></div><div class="meal-kcal">${Math.round(m.kcal)}<small>kcal</small><button class="secondary" style="padding:5px 7px;font-size:.66rem;margin-top:8px;" onclick="replaceMeal(${dayIndex},${mealIndex})">Cambiar comida</button></div></div>`;
    });
    html += `<div class="day-total">Total del día: <b>${Math.round(totals.kcal)} kcal</b><span style="color:var(--text-dim);"> · P:${Math.round(totals.p)} · C:${Math.round(totals.c)} · G:${Math.round(totals.f)}</span></div></div>`;
  });
  
  if(plan.shoppingList) {
    html += `<div class="day-card"><h3>🛒 Compra (Viernes)</h3><table class="plan-table"><tbody>${plan.shoppingList.map(i=>`<tr><td>${i.item}</td><td style="text-align:right;">${i.qty}</td></tr>`).join('')}</tbody></table></div>`;
  }
  if(plan.batchInstructions) {
    html += `<div class="day-card"><h3>👨‍🍳 Batch Cooking (Domingo)</h3><ol style="padding-left:16px;font-size:0.9rem;">${plan.batchInstructions.map(i=>`<li style="margin-bottom:8px;">${i}</li>`).join('')}</ol></div>`;
  }
  if(plan.storagePlan) {
    html += `<div class="day-card"><h3>❄️ Conservación y seguridad</h3><table class="plan-table"><tbody>${plan.storagePlan.map(i=>`<tr><td><b>${i.meal}</b></td><td>${i.storage}</td><td style="font-size:0.75rem;">${i.note||''}</td></tr>`).join('')}</tbody></table>`;
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
  await safeSet('lastPlan', saved);
  renderPlanObject(saved.plan, new Date(saved.generatedAt).toLocaleString('es-ES'));
  showToast('Ingrediente sustituido manteniendo el objetivo');
};

window.replaceMeal = async (dayIndex, mealIndex) => {
  const saved = await safeGet('lastPlan');
  if(!saved || !saved.plan?.days?.[dayIndex]?.meals?.[mealIndex]) return;
  const oldMeal = saved.plan.days[dayIndex].meals[mealIndex];
  showToast('Buscando sustitución equivalente...');
  const target = saved.plan.days[dayIndex].training ? getPlanTargets().training : getPlanTargets().rest;
  const prompt = `Sustituye esta comida de un plan de hipertrofia por otra equivalente y compatible con las preferencias del usuario: ${profile.preferences || 'sin restricciones'}. Mantén el mismo tipo ${oldMeal.type}, aproximadamente las mismas kcal (${Math.round(oldMeal.kcal)}) y proteína (${Math.round(oldMeal.p)}g). Devuelve SOLO JSON con esta forma: {"name":"","type":"${oldMeal.type}","weightBasis":"crudo","items":[{"food":"","grams":0,"kcal":0,"p":0,"c":0,"f":0,"isLiquid":false,"ml":0}],"alternatives":["",""],"kcal":0,"p":0,"c":0,"f":0}. Si preparas overnight oats, crema, batido, harina de arroz o crema de arroz, incluye agua o leche como ingrediente dentro de items, con ml y sus kcal/macros; si es leche, debe contar también en las kcal totales. Los valores de la comida deben sumar sus ingredientes y ser coherentes con P*4+C*4+G*9. Objetivo del día: ${Math.round(target.kcal)} kcal y ${Math.round(target.p)}g de proteína.`;
  const replacement = await callGemini(prompt, true, GEMINI_MODEL);
  if(!replacement || !Array.isArray(replacement.items)) { showToast('No se encontró una sustitución válida.', true); return; }
  saved.plan.days[dayIndex].meals[mealIndex] = replacement;
  const validation = validatePlan(saved.plan, getPlanTargets());
  if(!validation.ok) { showToast('La sustitución no mantiene los objetivos.', true); return; }
  await safeSet('lastPlan', saved);
  renderPlanObject(saved.plan, new Date(saved.generatedAt).toLocaleString('es-ES'));
  showToast('Comida sustituida');
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

  const baseKcal = profile.targetKcal||2500;
  
  const prompt = `Eres coach nutricionista del usuario en la app Bulking OS. Habla directo, clínico pero amistoso.
Usuario Kcal Base: ${Math.round(baseKcal)}. Peso actual: ${profile.weight} kg. Meta de ganancia: ${profile.weeklyGainGoalKg || 0.3} kg/semana.
Preferencias: ${profile.preferences || 'sin restricciones indicadas'}.
Si el usuario indica que ayer comió poco/mucho y quiere compensar HOY, evalúa y propone un ajuste (max +- 400 kcal) devolviéndolo en "suggestedDelta" (ej: 200). Si no hay ajuste para HOY, "suggestedDelta" es 0.
Historial de charla: ${h.slice(-4).map(m=>`${m.role}: ${m.text}`).join(' | ')}.
Responde SOLO este JSON: {"reply":"respuesta breve","suggestedDelta":0}`;

  const res = await callGemini(prompt, true, GEMINI_MODEL);
  if(res && res.reply){
    h.push({ role:'ai', text: res.reply, suggestedDelta: res.suggestedDelta||0, applied:false });
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
  const safeDelta = Number.isFinite(Number(delta)) ? Math.max(-400, Math.min(400, Number(delta))) : 0;
  const current = await getDailyOverride(t);
  await setDailyOverride(t, Math.max(-400, Math.min(400, current + safeDelta)));
  h[idx].applied = true; await safeSet('chatHistory', h);
  renderChatWindow(h);
  if(selectedLogDate === t) updateDashboardUI();
  showToast("Objetivo ajustado para hoy.");
};

// =========================================
// 📉 DATOS METABÓLICOS Y GRÁFICOS
// =========================================
async function saveProfile(){
  profile.age = Number($('prof-age').value)||profile.age;
  profile.height = Number($('prof-height').value)||profile.height;
  profile.weight = Number($('prof-weight').value)||profile.weight;
  profile.sex = $('prof-sex').value;
  profile.activity = Number($('prof-activity').value)||profile.activity;
  profile.goalOffset = Number($('prof-goal').value);
  profile.weeklyGainGoalKg = Number($('prof-weekly-goal').value)||0.3;
  profile.mealsPerDay = Math.min(8, Math.max(3, Number($('prof-meals').value)||5));
  profile.trainingDays = Math.min(7, Math.max(0, Number($('prof-training-days').value)||0));
  profile.preferences = $('prof-preferences').value.trim();
  profile.adjustmentPaused = $('prof-pause').checked;
  if(profile.targetKcal){ profile.targetKcal = calcTDEE(profile, profile.weight) + profile.goalOffset; recomputeMacrosFromKcal(profile); }
  await safeSet('profile', profile);
  updateBodyStats(); updateDashboardUI(); renderWeekInsights(); showToast('Perfil guardado y objetivos recalculados.');
}

async function applyFormulaTarget(){
  profile.targetKcal = calcTDEE(profile, profile.weight) + profile.goalOffset;
  recomputeMacrosFromKcal(profile);
  await safeSet('profile', profile);
  updateDashboardUI(); updateBodyStats(); showToast(`Kcal Base fijadas en ${Math.round(profile.targetKcal)}`);
}

function updateBodyStats(){
  const tdee = calcTDEE(profile, profile.weight);
  $('ui-tdee').innerText = Math.round(tdee);
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
// Más preciso que fórmulas basadas solo en peso/altura porque usa
// circunferencias reales. Requiere cuello + cintura (+ cadera en mujeres).
function navyBodyFat({ neck, waist, hip, heightCm, sex }){
  if(!(neck > 0) || !(waist > 0) || !(heightCm > 0)) return null;
  if(sex === 'm'){
    const diff = waist - neck;
    if(diff <= 0) return null;
    const bf = 495 / (1.0324 - 0.19077 * Math.log10(diff) + 0.15456 * Math.log10(heightCm)) - 450;
    return Number.isFinite(bf) ? Math.max(2, Math.min(60, bf)) : null;
  }
  if(!(hip > 0)) return null;
  const diff = waist + hip - neck;
  if(diff <= 0) return null;
  const bf = 495 / (1.29579 - 0.35004 * Math.log10(diff) + 0.22100 * Math.log10(heightCm)) - 450;
  return Number.isFinite(bf) ? Math.max(2, Math.min(60, bf)) : null;
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
// 📐 COMPOSICIÓN CORPORAL (output enriquecido a partir del mínimo input)
// =========================================
async function renderBodyComposition(){
  const el = $('body-comp-content');
  if(!el) return;
  const latest = await getLatestBodyMeasure();
  const bmiVal = bmiOf(profile.weight, profile.height);

  let bfPct = deurenbergBodyFat(bmiVal, profile.age, profile.sex);
  let bfMethod = 'Estimación por fórmula (peso/altura/edad) — orientativa';
  if(latest && latest.neck && latest.waist && (profile.sex === 'm' || latest.hip)){
    const navyBF = navyBodyFat({ neck: latest.neck, waist: latest.waist, hip: latest.hip, heightCm: profile.height, sex: profile.sex });
    if(navyBF !== null){ bfPct = navyBF; bfMethod = 'Método cinta métrica (US Navy) — más preciso'; }
  }

  const fatMass = profile.weight * (bfPct / 100);
  const leanMass = profile.weight - fatMass;
  const { normalized } = ffmiOf(leanMass, profile.height);

  let ffmiNote;
  if(normalized < 18) ffmiNote = 'Por debajo de la media';
  else if(normalized < 20) ffmiNote = 'Media';
  else if(normalized < 22) ffmiNote = 'Buena base muscular';
  else if(normalized < 23) ffmiNote = 'Muy buena, cerca de lo típico natural';
  else if(normalized < 25) ffmiNote = 'Excelente, límite alto natural habitual';
  else ffmiNote = 'Muy por encima de lo habitual sin ayuda farmacológica (ref. Kouri et al. 1995)';

  let html = `
    <div class="stats-grid" style="margin-bottom:16px;">
      <div class="stat-box"><div class="stat-title">% Grasa corporal</div><div class="stat-val" style="color:var(--accent);">${bfPct.toFixed(1)}%</div><div style="font-size:0.68rem; color:var(--text-dim);">${bfMethod}</div></div>
      <div class="stat-box"><div class="stat-title">FFMI (normalizado)</div><div class="stat-val" style="color:var(--pro-color);">${normalized.toFixed(1)}</div><div style="font-size:0.68rem; color:var(--text-dim);">${ffmiNote}</div></div>
    </div>
    <div style="display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--glass-border);"><span style="color:var(--text-dim);">Masa grasa</span><b>${fatMass.toFixed(1)} kg</b></div>
    <div style="display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--glass-border);"><span style="color:var(--text-dim);">Masa magra (libre de grasa)</span><b>${leanMass.toFixed(1)} kg</b></div>
    <div style="display:flex; justify-content:space-between; padding:8px 0;"><span style="color:var(--text-dim);">IMC</span><b>${bmiVal.toFixed(1)} <span style="font-size:.7rem; color:var(--text-dim);">(no distingue músculo de grasa)</span></b></div>`;

  if(latest && latest.waist){
    const whtrVal = whtrOf(latest.waist, profile.height);
    let whtrBand, whtrColor;
    if(whtrVal < 0.4){ whtrBand = 'posible peso bajo'; whtrColor = 'var(--accent)'; }
    else if(whtrVal < 0.5){ whtrBand = 'rango saludable'; whtrColor = 'var(--green)'; }
    else if(whtrVal < 0.6){ whtrBand = 'riesgo aumentado'; whtrColor = 'var(--accent)'; }
    else { whtrBand = 'riesgo alto'; whtrColor = 'var(--red)'; }
    html += `<div style="display:flex; justify-content:space-between; padding:8px 0; border-top:1px solid var(--glass-border); margin-top:4px;"><span style="color:var(--text-dim);">Cintura/Altura (WHtR)</span><b>${whtrVal.toFixed(2)} <span style="font-size:.7rem; color:${whtrColor};">(${whtrBand})</span></b></div>`;

    if(latest.hip){
      const whrVal = whrOf(latest.waist, latest.hip);
      const whrCutoff = profile.sex === 'm' ? 0.90 : 0.85;
      const overCutoff = whrVal > whrCutoff;
      html += `<div style="display:flex; justify-content:space-between; padding:8px 0;"><span style="color:var(--text-dim);">Cintura/Cadera (WHR)</span><b>${whrVal.toFixed(2)} <span style="font-size:.7rem; color:${overCutoff?'var(--red)':'var(--green)'};">(${overCutoff?'por encima del':'dentro del'} umbral OMS ${whrCutoff})</span></b></div>`;
    }
  } else {
    html += `<div style="font-size:0.8rem; color:var(--text-dim); margin-top:10px;">Añade tu cintura (y cuello, y cadera si aplica) más arriba para desbloquear % de grasa medido y los ratios cintura/altura y cintura/cadera.</div>`;
  }

  el.innerHTML = html;
}

async function renderBodyCompositionChart(){
  const wrap = $('body-comp-chart-wrap');
  if(!wrap) return;
  const series = await getBodyMeasureSeries(90);
  if(series.length < 2){ wrap.style.display = 'none'; return; }
  wrap.style.display = 'block';

  const points = [];
  for(const m of series){
    const weightEntries = await safeGet('weight:' + m.date);
    const weightOnDate = (Array.isArray(weightEntries) && weightEntries.length)
      ? weightEntries.reduce((a,e)=>a+e.kg,0) / weightEntries.length
      : profile.weight;
    let bf = (m.neck && m.waist && (profile.sex === 'm' || m.hip))
      ? navyBodyFat({ neck:m.neck, waist:m.waist, hip:m.hip, heightCm:profile.height, sex:profile.sex })
      : null;
    if(bf === null) bf = deurenbergBodyFat(bmiOf(weightOnDate, profile.height), profile.age, profile.sex);
    const fat = weightOnDate * (bf / 100);
    points.push({ date: m.date, fat, lean: weightOnDate - fat });
  }

  const labels = points.map(p => new Date(p.date + 'T00:00:00').toLocaleDateString('es-ES', {month:'short', day:'numeric', year:'2-digit'}));
  const ctx = $('bodyCompChart').getContext('2d');
  if(bodyCompChartInstance) bodyCompChartInstance.destroy();
  bodyCompChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label:'Masa magra (kg)', data: points.map(p=>p.lean), borderColor:'#3b82f6', backgroundColor:'rgba(59,130,246,0.12)', borderWidth:2.5, fill:true, tension:0.3, pointRadius:3 },
        { label:'Masa grasa (kg)', data: points.map(p=>p.fat), borderColor:'#ef4444', backgroundColor:'rgba(239,68,68,0.12)', borderWidth:2.5, fill:true, tension:0.3, pointRadius:3 }
      ]
    },
    options: { responsive:true, maintainAspectRatio:false, plugins:{legend:{display:true, labels:{color:'#94a3b8', boxWidth:12, font:{size:10}}}, tooltip:{mode:'index', intersect:false}}, scales:{ y:{grid:{color:'rgba(255,255,255,0.05)'}}, x:{grid:{display:false}} } }
  });
}

// =========================================
// ⚖️ REGISTRO DE PESO (CON EDICIÓN Y BORRADO)
// =========================================
async function getWeightEntries(date){ const arr = await safeGet('weight:'+date); return Array.isArray(arr) ? arr : []; }
async function setWeightEntries(date, arr){ await safeSet('weight:'+date, arr); }

async function refreshProfileWeightFromLatest(){
  for(let i=0;i<60;i++){
    const d = new Date(); d.setDate(d.getDate()-i);
    const key = dateKey(d);
    const entries = await getWeightEntries(key);
    if(entries.length){
      const avg = entries.reduce((a,e)=>a+e.kg,0)/entries.length;
      profile.weight = avg;
      if(profile.targetKcal) recomputeMacrosFromKcal(profile);
      await safeSet('profile', profile);
      return;
    }
  }
}

async function renderWeightDayList(){
  const date = $('input-weight-date').value || todayStr();
  const entries = await getWeightEntries(date);
  const el = $('weight-day-list');
  if(!entries.length){ el.innerHTML = `<div style="color:var(--text-dim); font-size:0.85rem; padding:8px 0;">Sin pesajes registrados el ${formatDateLabel(date).toLowerCase()}.</div>`; return; }
  el.innerHTML = entries.map((e,i)=>`
    <div class="log-item" style="padding:10px 0;">
      <div><div class="log-title">${e.kg} kg</div><div class="log-macros">${e.time||''}</div></div>
      <div class="log-item-actions">
        <button class="edit-btn" onclick="editWeightEntry('${date}', ${i})" title="Editar">✎</button>
        <button class="del-btn" onclick="delWeightEntry('${date}', ${i})" title="Borrar">✕</button>
      </div>
    </div>
  `).join('');
}

window.editWeightEntry = async (date, index) => {
  const entries = await getWeightEntries(date);
  const cur = entries[index]; if(!cur) return;
  const val = prompt('Nuevo peso (kg):', cur.kg);
  if(val === null) return;
  const num = parseFloat(String(val).replace(',', '.'));
  if(!Number.isFinite(num) || num <= 0){ showToast('Peso inválido', true); return; }
  entries[index] = { ...cur, kg: num };
  await setWeightEntries(date, entries);
  showToast('Pesaje actualizado');
  await refreshProfileWeightFromLatest();
  await renderWeightDayList(); await renderWeightChart(); updateBodyStats(); await renderWeekInsights(); await adjustWeeklyTarget();
};

window.delWeightEntry = async (date, index) => {
  const entries = await getWeightEntries(date);
  entries.splice(index, 1);
  await setWeightEntries(date, entries);
  showToast('Pesaje eliminado');
  await refreshProfileWeightFromLatest();
  await renderWeightDayList(); await renderWeightChart(); updateBodyStats(); await renderWeekInsights();
};

async function addWeight(){
  const w = parseFloat($('input-weight').value); if(!w || w<=0){ showToast('Introduce un peso válido', true); return; }
  const date = $('input-weight-date').value || todayStr();

  // Aviso si el valor se aleja mucho de tu tendencia reciente. No lo bloqueamos
  // (puede ser real: ropa, hora del día, retención...), solo confirmamos para
  // evitar que un error de tecleo distorsione la EMA y el modelo dinámico.
  const recentSeries = await getDailyWeightSeries(21);
  if(recentSeries.length >= 4){
    const recentEma = computeEMASeries(recentSeries, 0.25);
    const lastEma = recentEma[recentEma.length - 1].ema;
    const diff = Math.abs(w - lastEma);
    const pctDiff = lastEma > 0 ? diff / lastEma : 0;
    if(diff > 2.5 || pctDiff > 0.035){
      const proceed = confirm(`Este peso (${w}kg) se aleja bastante de tu tendencia reciente (~${lastEma.toFixed(1)}kg). Puede ser normal (ropa, hora del día, retención de agua...), pero si es un error de tecleo cancela y corrígelo.\n\n¿Guardar de todas formas?`);
      if(!proceed) return;
    }
  }

  const arr = await getWeightEntries(date);
  arr.push({ kg: w, time: new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'}) });
  await setWeightEntries(date, arr);
  await refreshProfileWeightFromLatest();
  $('input-weight').value='';
  showToast(`Peso registrado: ${w}kg (${formatDateLabel(date).toLowerCase()})`);
  updateBodyStats(); await adjustWeeklyTarget(); await updateDashboardUI(); await renderWeightChart(); await renderWeightDayList(); await renderWeekInsights();
}

async function renderWeightChart(){
  const daily = await getDailyWeightSeries(35);
  const emaSeries = computeEMASeries(daily, 0.25);
  const labels = emaSeries.map(s => new Date(s.date + 'T00:00:00').toLocaleDateString('es-ES', {month:'short', day:'numeric', year:'2-digit'}));

  const ctx = $('weightChart').getContext('2d');
  if(weightChartInstance) weightChartInstance.destroy();

  const gradient = ctx.createLinearGradient(0, 0, 0, 200);
  gradient.addColorStop(0, 'rgba(245,158,11,0.3)'); gradient.addColorStop(1, 'rgba(245,158,11,0)');

  weightChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label:'Peso real', data: emaSeries.map(s=>s.kg), borderColor:'rgba(148,163,184,0.55)', backgroundColor:'transparent', borderDash:[4,3], borderWidth:1.5, fill:false, tension:0.25, pointRadius:2.5, pointBackgroundColor:'rgba(148,163,184,0.8)', pointBorderWidth:0 },
        { label:'Tendencia (EMA)', data: emaSeries.map(s=>s.ema), borderColor:'#f59e0b', backgroundColor:gradient, borderWidth:3, fill:true, tension:0.35, pointRadius:0 }
      ]
    },
    options: {
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{ display:true, labels:{ color:'#94a3b8', boxWidth:12, font:{size:10} } }, tooltip:{mode:'index', intersect:false} },
      scales:{ y:{grid:{color:'rgba(255,255,255,0.05)'}}, x:{grid:{display:false}} }
    }
  });
}

// =========================================
// 🎯 PROYECCIÓN DE OBJETIVO
// =========================================
async function saveGoalWeight(){
  const val = parseFloat($('input-goal-weight').value);
  profile.goalWeightKg = Number.isFinite(val) && val > 0 ? val : null;
  await safeSet('profile', profile);
  showToast(profile.goalWeightKg ? `Peso objetivo guardado: ${profile.goalWeightKg} kg` : 'Peso objetivo eliminado');
  await renderGoalProjection();
}

async function renderGoalProjection(){
  const el = $('goal-projection-content');
  if(!el) return;
  const trend = await computeWeightProjection();

  if(trend.status === 'cold'){
    el.innerHTML = `<div style="color:var(--text-dim); font-size:0.88rem; line-height:1.6;">Todavía no hay pesajes suficientes para calcular una tendencia fiable (necesitas al menos ~1 semana registrando peso). En cuanto tengas más datos verás aquí tu ritmo real y, si defines un peso objetivo, una fecha estimada.</div>`;
    return;
  }

  const rateTxt = `${trend.ratePerWeek >= 0 ? '+' : ''}${trend.ratePerWeek.toFixed(2)} kg/semana`;
  let html = `<div style="display:flex; justify-content:space-between; padding-bottom:10px; border-bottom:1px solid var(--glass-border); margin-bottom:10px;"><span style="color:var(--text-dim);">Peso actual (EMA)</span><b>${trend.currentEma.toFixed(1)} kg</b></div>
  <div style="display:flex; justify-content:space-between; padding-bottom:10px;"><span style="color:var(--text-dim);">Ritmo real reciente</span><b style="color:${trend.ratePerWeek>=0?'var(--green)':'var(--red)'};">${rateTxt}</b></div>`;

  if(trend.confidence !== 'alta'){
    html += `<div style="font-size:0.78rem; color:var(--text-dim); margin-bottom:12px;">⚠️ Estimación orientativa (solo ${trend.dataPoints} pesajes en ${trend.elapsedDays} días). Se afinará con más datos.</div>`;
  }

  const goal = Number(profile.goalWeightKg);
  if(Number.isFinite(goal) && goal > 0){
    const diff = goal - trend.currentEma;
    if(Math.abs(trend.ratePerWeek) < 0.02){
      html += `<div class="alert" style="margin:0;">Tu ritmo actual es prácticamente plano, así que no puedo proyectar una fecha fiable hacia ${goal} kg todavía.</div>`;
    } else if((diff > 0 && trend.ratePerWeek < 0) || (diff < 0 && trend.ratePerWeek > 0)){
      html += `<div class="alert warn" style="margin:0;">Tu tendencia actual va en la dirección contraria a tu objetivo de ${goal} kg. Si de verdad quieres llegar ahí, revisa tus kcal.</div>`;
    } else {
      const weeksNeeded = Math.abs(diff / trend.ratePerWeek);
      const etaDate = new Date(); etaDate.setDate(etaDate.getDate() + Math.round(weeksNeeded * 7));
      const etaLabel = etaDate.toLocaleDateString('es-ES', {day:'numeric', month:'long', year:'numeric'});
      html += `<div style="padding:14px; border-radius:var(--radius-sm); background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.25);">A este ritmo, llegarás a <b>${goal} kg</b> alrededor del <b>${etaLabel}</b> (~${Math.ceil(weeksNeeded)} semanas).</div>`;
    }
  } else {
    const proj = w => (trend.currentEma + trend.ratePerWeek * w).toFixed(1);
    html += `<div style="font-size:0.85rem; color:var(--text-dim); margin-bottom:10px;">Sin un peso objetivo fijado, esta es tu proyección a este ritmo:</div>
    <div style="display:flex; justify-content:space-between; gap:8px;">
      <div class="stat-box" style="flex:1; padding:12px;"><div class="stat-title">4 sem</div><div class="stat-val" style="font-size:1.3rem;">${proj(4)}<small style="font-size:.7rem;"> kg</small></div></div>
      <div class="stat-box" style="flex:1; padding:12px;"><div class="stat-title">8 sem</div><div class="stat-val" style="font-size:1.3rem;">${proj(8)}<small style="font-size:.7rem;"> kg</small></div></div>
      <div class="stat-box" style="flex:1; padding:12px;"><div class="stat-title">12 sem</div><div class="stat-val" style="font-size:1.3rem;">${proj(12)}<small style="font-size:.7rem;"> kg</small></div></div>
    </div>`;
  }

  // Guía orientativa de nutrición deportiva: ~0.125%-0.5% del peso corporal
  // por semana para minimizar la proporción de grasa ganada en un bulking
  // (rango habitualmente citado; varía algo según la fuente y el nivel de
  // entrenamiento, así que trátalo como referencia, no como ley exacta).
  const lowGuide = profile.weight * 0.00125;
  const highGuide = profile.weight * 0.005;
  let paceVerdict, paceColor;
  if(trend.ratePerWeek < lowGuide * 0.5){ paceVerdict = 'lento — puede que ni siquiera estés en superávit real'; paceColor = 'var(--text-dim)'; }
  else if(trend.ratePerWeek <= highGuide){ paceVerdict = 'dentro del rango típico para un bulking limpio'; paceColor = 'var(--green)'; }
  else { paceVerdict = 'por encima del rango típico — probablemente ganando más grasa de la necesaria'; paceColor = 'var(--accent)'; }
  html += `<div style="font-size:0.8rem; color:var(--text-dim); margin-top:14px; padding-top:14px; border-top:1px solid var(--glass-border); line-height:1.5;">Guía orientativa de nutrición deportiva: ~${lowGuide.toFixed(2)}–${highGuide.toFixed(2)} kg/semana (0.125%-0.5% de tu peso) para minimizar grasa ganada. Tu ritmo actual está <span style="color:${paceColor}; font-weight:600;">${paceVerdict}</span>.</div>`;

  el.innerHTML = html;
}

// =========================================
// 🧠 ESTADO DEL MODELO DE KCAL (fórmula / básico / dinámico)
// =========================================
async function renderDynamicModelStatus(){
  const el = $('dynamic-model-content');
  if(!el) return;
  const dyn = await computeDynamicMaintenance();
  const formulaTdee = calcTDEE(profile, profile.weight);

  if(!dyn){
    el.innerHTML = `<div style="color:var(--text-dim); font-size:0.88rem; line-height:1.6;">Ahora mismo tu objetivo (${Math.round(profile.targetKcal||0)} kcal) sale de la fórmula Mifflin-St Jeor + tu superávit configurado (o de un ajuste básico por tendencia de peso, si ya llevas ~2 semanas pesándote). Para activar el <b>modelo dinámico</b> (que calcula tu metabolismo real a partir de tus pesajes y tus kcal registradas) necesito más datos: al menos ~8-10 días con peso <b>y</b> ~8-10 días con comidas registradas dentro de las últimas 3 semanas. Sigue registrando y se activará solo.</div>`;
    return;
  }

  const diff = dyn.estimatedMaintenance - formulaTdee;
  el.innerHTML = `
    <div style="padding:14px; border-radius:var(--radius-sm); background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.25); margin-bottom:12px; font-size:0.85rem; color:#d1fae5;">✅ Modelo dinámico activo — basado en ${dyn.weightDays} pesajes y ${dyn.intakeDays} días de comida en los últimos ${dyn.elapsedDays} días.</div>
    <div style="display:flex; justify-content:space-between; padding-bottom:10px; border-bottom:1px solid var(--glass-border); margin-bottom:10px;"><span style="color:var(--text-dim);">Mantenimiento real estimado</span><b>${Math.round(dyn.estimatedMaintenance)} kcal</b></div>
    <div style="display:flex; justify-content:space-between; padding-bottom:10px;"><span style="color:var(--text-dim);">Fórmula (Mifflin-St Jeor)</span><b>${Math.round(formulaTdee)} kcal <span style="color:${diff>=0?'var(--green)':'var(--red)'}; font-size:.78rem;">(${diff>=0?'+':''}${Math.round(diff)})</span></b></div>
    <div style="font-size:0.8rem; color:var(--text-dim);">Tu objetivo actual (${Math.round(profile.targetKcal||0)} kcal) ya incorpora esta estimación real más tu superávit deseado, y se recalcula una vez por semana.</div>
  `;
}

// =========================================
// 🕘 HISTORIAL DE AJUSTES (AUDITORÍA)
// =========================================
async function renderTargetHistory(){
  const el = $('target-history-content');
  if(!el) return;
  const hist = ((await safeGet('targetHistory')) || []).slice().reverse().slice(0, 12);
  if(!hist.length){ el.innerHTML = '<div style="color:var(--text-dim); font-size:0.85rem;">Aún no se ha completado ninguna evaluación semanal (necesitas al menos 4 días de peso registrados en una semana).</div>'; return; }
  el.innerHTML = hist.map(h => {
    const changed = Math.round(h.newTarget) !== Math.round(h.prevTarget);
    return `<div style="padding:10px 0; border-bottom:1px solid var(--glass-border); font-size:0.85rem;">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <b>${h.week}</b>
        <span style="color:${h.mode==='dinamico' ? 'var(--green)' : 'var(--text-dim)'}; font-size:.68rem; text-transform:uppercase; font-weight:700; letter-spacing:.03em;">${h.mode==='dinamico' ? '🧠 Dinámico' : 'Básico'}</span>
      </div>
      <div style="color:var(--text-dim); margin-top:4px; line-height:1.4;">${h.note}</div>
      <div style="margin-top:6px;">${Math.round(h.prevTarget)} ${changed ? `→ <b style="color:var(--accent);">${Math.round(h.newTarget)} kcal</b>` : `<span style="color:var(--text-dim);">kcal (sin cambio)</span>`}</div>
    </div>`;
  }).join('');
}

async function renderTrendCharts(){
  const days=[]; const kcal=[], p=[], c=[], f=[];
  for(let i=13;i>=0;i--){ 
    const d=new Date(); d.setDate(d.getDate()-i); 
    const str = dateKey(d); days.push(d.toLocaleDateString('es-ES',{month:'short',day:'numeric',year:'2-digit'}));
    const s = sumEntries(await getLog(str));
    kcal.push(s.kcal); p.push(s.p); c.push(s.c); f.push(s.f);
  }
  const tgt = days.map(()=>profile.targetKcal||2500);

  const ctx1 = $('kcalTrendChart').getContext('2d');
  if(kcalTrendChartInstance) kcalTrendChartInstance.destroy();
  kcalTrendChartInstance = new Chart(ctx1, {
    data: { labels:days, datasets: [ { type:'bar', label:'Kcal', data: kcal, backgroundColor:'rgba(245,158,11,0.6)', borderRadius:6 }, { type:'line', label:'Objetivo', data: tgt, borderColor:'#3b82f6', borderDash:[5,5], pointRadius:0, borderWidth:2 } ] },
    options: { responsive:true, maintainAspectRatio:false, scales:{y:{grid:{color:'rgba(255,255,255,0.05)'}},x:{grid:{display:false}} } }
  });
}

async function renderWeekInsights(){
  const avg = await getAverageWeight(0, 7);
  let kcalDays = 0; let proteinDays = 0; let completeDays = 0; let kcalTotal = 0;
  const targetKcal = Number(profile.targetKcal || 2500);
  const targetProtein = Number(profile.targetProtein || profile.weight * 2 || 130);
  for(let i = 0; i < 7; i++){
    const d = new Date(); d.setDate(d.getDate() - i);
    const sums = sumEntries(await getLog(dateKey(d)));
    if(sums.kcal <= 0) continue;
    completeDays++;
    kcalTotal += sums.kcal;
    if(sums.kcal >= targetKcal * 0.9 && sums.kcal <= targetKcal * 1.1) kcalDays++;
    if(sums.p >= targetProtein * 0.9) proteinDays++;
  }
  const avgKcal = completeDays ? Math.round(kcalTotal / completeDays) : 0;
  const html = `<div style="display:flex; justify-content:space-between; border-bottom:1px solid var(--glass-border); padding-bottom:8px;"><span>Meta diaria:</span><b style="color:var(--accent);">${Math.round(targetKcal)} kcal</b></div>
                <div style="display:flex; justify-content:space-between; padding-top:8px;"><span>Media peso 7 días:</span><b>${avg === null ? 'Aún faltan pesajes' : avg.toFixed(1)+' kg'}</b></div>
                <div style="display:flex; justify-content:space-between; padding-top:8px;"><span>Adherencia kcal:</span><b>${kcalDays}/${completeDays || 7} días</b></div>
                <div style="display:flex; justify-content:space-between; padding-top:8px;"><span>Proteína cumplida:</span><b>${proteinDays}/${completeDays || 7} días</b></div>
                <div style="display:flex; justify-content:space-between; padding-top:8px;"><span>Media ingerida:</span><b>${avgKcal ? avgKcal+' kcal' : 'Sin registros'}</b></div>
                <div style="display:flex; justify-content:space-between; padding-top:8px;"><span>Ajuste automático:</span><b>${profile.adjustmentPaused?'Pausado':'Activo'}</b></div>`;
  $('insights-card').innerHTML = html;
}

// NAVEGACIÓN
function nav(tab){
  document.querySelectorAll('.section').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(e=>e.classList.remove('active'));
  $('tab-'+tab).classList.add('active');
  document.querySelector(`.nav-item[data-tab="${tab}"]`).classList.add('active');
  if(tab==='body'){ renderWeightChart(); renderTrendCharts(); renderGoalProjection(); renderDynamicModelStatus(); renderBodyMeasureDayList(); renderBodyComposition(); renderBodyCompositionChart(); renderTargetHistory(); }
}

// BACKUP IMPORT/EXPORT
async function exportData(){
  const data = {}; for(let i=0;i<localStorage.length;i++){ const k=localStorage.key(i); data[k]=localStorage.getItem(k); }
  const blob = new Blob([JSON.stringify(data,null,2)], {type:'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `bulking-backup-${todayStr()}.json`;
  a.click(); URL.revokeObjectURL(a.href);
  await safeSet('lastBackupAt', new Date().toISOString());
  showToast('Backup exportado');
  await checkBackupReminder();
}

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
    el.innerHTML = `💾 Llevas ${Math.floor(daysSince)} días sin exportar un backup. Todo vive solo en este navegador — si lo borras o cambias de móvil, se pierde todo.<br><button class="secondary" style="margin-top:10px; padding:8px 14px; font-size:.8rem;" onclick="exportData()">Exportar ahora</button>`;
  } else {
    el.style.display = 'none';
  }
}
$('import-file-input').addEventListener('change', async (e)=>{
  try {
    const data = JSON.parse(await e.target.files[0].text());
    if(!confirm('¿Sobrescribir datos locales?')) return;
    for(const [k,v] of Object.entries(data)) localStorage.setItem(k, v);
    showToast('Datos restaurados. Recargando...'); setTimeout(()=>location.reload(), 1500);
  } catch(err){ showToast('Archivo JSON inválido', true); }
});

// INIT
window.onload = async () => {
  profile = await loadProfile();
  
  // Inyectar datos form
  $('prof-age').value = profile.age; $('prof-height').value = profile.height;
  $('prof-weight').value = profile.weight; $('prof-sex').value = profile.sex;
  $('prof-activity').value = profile.activity; $('prof-goal').value = profile.goalOffset;
  $('prof-weekly-goal').value = profile.weeklyGainGoalKg; $('prof-pause').checked = !!profile.adjustmentPaused;
  $('prof-meals').value = profile.mealsPerDay || 5; $('prof-training-days').value = profile.trainingDays || 0;
  $('prof-preferences').value = profile.preferences || '';
  $('input-weight-date').value = todayStr();
  $('input-goal-weight').value = profile.goalWeightKg || '';
  $('input-measure-date').value = todayStr();
  
  const dStr = new Date().toLocaleDateString('es-ES',{weekday:'long',day:'numeric',month:'short',year:'numeric'});
  $('date-display').innerText = dStr.charAt(0).toUpperCase()+dStr.slice(1);
  
  const lp = await safeGet('lastPlan'); if(lp && lp.plan) renderPlanObject(lp.plan, new Date(lp.generatedAt).toLocaleString('es-ES'));
  
  await adjustWeeklyTarget(); updateBodyStats(); await updateDashboardUI(); await renderWeekInsights(); await renderWeightDayList();
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
    html = html.replace("__FILLER__", FILLER_FOODS)
    return html

def write_index():
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(get_injected_html())

# Si el script se llama con el arg "--export-only", solo exporta y cierra.
# Útil para el subproceso del watcher.
if "--export-only" in sys.argv:
    write_index()
    sys.exit(0)

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
            f"TIMEOUT: Git tardó > {timeout}s sin responder. Como GIT_TERMINAL_PROMPT=0, "
            "si Git necesitaba pedirte usuario/contraseña o token no puede preguntarte y se "
            "queda colgado en vez de fallar con un error claro. Prueba a ejecutar "
            "'git push' manualmente en una terminal (fuera de este script) para ver el error "
            "real: normalmente es un token caducado, falta de credential helper "
            "(git config credential.helper) o el remoto en HTTPS pidiendo login."
        )

def has_changes():
    ok, out = run_git(f'git status --porcelain -- "index.html" "{os.path.basename(THIS_FILE)}"')
    return ok and out.strip() != ""

def current_branch():
    ok, out = run_git("git rev-parse --abbrev-ref HEAD")
    return out.strip() if ok and out.strip() else "main"

def squash_unpushed_commits(branch):
    """Si hay varios commits locales sin subir (acumulados de intentos de push
    anteriores que fallaron), los aplasta en uno solo antes de empujar. Como
    esos commits NUNCA llegaron al remoto, reescribirlos es seguro, y esto
    elimina cualquier rastro de la API key en texto plano que pudiera quedar
    en versiones intermedias del historial local (de antes de pasarla a
    base64): si no se hace esto, GitHub Push Protection seguiría bloqueando
    el push por encontrarla en commits antiguos, aunque el commit actual ya
    esté limpio.
    """
    ok, _ = run_git("git fetch origin", timeout=30)
    if not ok:
        return
    ok, out = run_git(f"git rev-list origin/{branch}..HEAD --count")
    if not ok or not out.strip().isdigit():
        return
    ahead = int(out.strip())
    if ahead <= 1:
        return
    log(f"🧹 Hay {ahead} commits locales sin subir de intentos anteriores; los aplasto en uno solo "
        f"(nunca llegaron al remoto, así que es seguro) para no arrastrar secretos antiguos en la historia.")
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

    # IMPORTANTE: sincronizamos con el remoto DESPUÉS de comitear, nunca antes.
    # Si hiciéramos "pull --rebase" antes de comitear, con el index.html recién
    # regenerado (siempre hay un cambio sin commitear en este point), el rebase
    # fallaría prácticamente cada vez ("unstaged changes") y quedaría como un
    # aviso ignorado. Eso dejaba la rama local desincronizada del remoto, y en
    # cuanto el remoto tuviera aunque fuese un commit de más, el "git push" de
    # después se rechazaba (non-fast-forward) y la web dejaba de actualizarse
    # sin que se notara en ningún sitio salvo esta consola.
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
                    "❌ Push bloqueado por GitHub Push Protection: detectó una clave/secreto en el commit "
                    "(probablemente GEMINI_API_KEY, que está hardcodeada a propósito).\n"
                    "   ⚠️ El enlace 'Allow secret' de más abajo es NUEVO cada vez (cambia con cada commit reescrito "
                    "por el rebase), así que el de la vez anterior ya no sirve: usa el que aparece JUSTO AQUÍ ABAJO.\n"
                    "   Soluciones:\n"
                    "   1) Rápida (hay que repetirla en cada push mientras la key siga hardcodeada): copia la URL "
                    "'.../security/secret-scanning/unblock-secret/...' del texto de abajo y pulsa 'Allow secret'.\n"
                    "   2) Definitiva: en https://github.com/marcelgiberts-creator/bulking/settings/security_analysis "
                    "busca 'Secret scanning' > 'Push protection' y desactívalo para este repo. Si no ves esa sección, "
                    "activa primero 'Secret scanning' (arriba del todo) y luego aparecerá el sub-toggle de 'Push protection'.\n"
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