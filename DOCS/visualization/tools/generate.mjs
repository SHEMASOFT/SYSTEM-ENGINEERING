#!/usr/bin/env node
/**
 * generate.mjs — Generador determinista de artefactos estáticos de SYSTEM-ENGINEERING.
 *
 * Entrada  : index.html (fuente única: el objeto SE_MODEL dentro de <script>)
 * Salidas  : diagram.svg  (diagrama estático de la vista 1 "Vista general")
 *            diagram.mmd  (Mermaid flowchart TD de la misma vista)
 *
 * Uso: node tools\generate.mjs
 * Sin dependencias, sin red, sin instalaciones. Salida byte-idéntica en cada corrida.
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const INDEX = path.join(ROOT, 'index.html');
const SVG_OUT = path.join(ROOT, 'diagram.svg');
const MMD_OUT = path.join(ROOT, 'diagram.mmd');

/* ------------------------------------------------------------------ paleta */
const PAL = {
  bg: '#F6F8FA',
  card: '#FFFFFF',
  ink: '#1B3A5C',
  muted: '#64748B',
  teal: '#14B8A6',
  green: '#15803D',
  blue: '#1B3A5C',
  amber: '#B45309',
  gray: '#64748B',
  line: '#D8DEE6',
  lineSoft: '#E7ECF1',
  greenBg: '#EAF6EE',
  blueBg: '#EAF0F6',
  amberBg: '#FBF1E3',
  grayBg: '#EEF1F4'
};

const STATE_ORDER = ['green', 'blue', 'amber', 'gray'];
const STATE = {
  green: { label: 'Implementada y probada', fg: PAL.green, bg: PAL.greenBg, border: '#9CCDAF' },
  blue: { label: 'Implementada; depende de ruta/configuración', fg: PAL.blue, bg: PAL.blueBg, border: '#B9CDE2' },
  amber: { label: 'En desarrollo / pendiente de validar', fg: PAL.amber, bg: PAL.amberBg, border: '#E6CBA6' },
  gray: { label: 'Planificada / no implementada', fg: PAL.gray, bg: PAL.grayBg, border: '#CBD4DE' }
};

/* ------------------------------------------------------------- extracción */
function extractModel(html) {
  const re = /<script\b[^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  let code = null;
  while ((m = re.exec(html)) !== null) {
    if (m[1].indexOf('const SE_MODEL') !== -1) { code = m[1]; break; }
  }
  if (!code) throw new Error('No se encontro "const SE_MODEL" en index.html');
  const ctx = { console };
  vm.createContext(ctx);
  vm.runInContext(code + '\n;globalThis.__SE_MODEL__ = SE_MODEL;', ctx, { timeout: 5000 });
  if (!ctx.__SE_MODEL__) throw new Error('SE_MODEL no pudo evaluarse');
  return ctx.__SE_MODEL__;
}

/* ------------------------------------------------------------- utilidades */
function wrap(text, max) {
  const words = String(text == null ? '' : text).split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = '';
  for (const w of words) {
    if (!cur.length) { cur = w; continue; }
    if ((cur + ' ' + w).length <= max) { cur += ' ' + w; continue; }
    lines.push(cur);
    cur = w;
  }
  if (cur.length) lines.push(cur);
  return lines.length ? lines : [''];
}

function xml(s) {
  const AMP = String.fromCharCode(38);
  const map = {
    '&': AMP + 'amp;',
    '<': AMP + 'lt;',
    '>': AMP + 'gt;',
    '"': AMP + 'quot;',
    "'": AMP + 'apos;'
  };
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return map[c]; });
}

function n(v) { return Number(v).toFixed(1); }

/* ------------------------------------------------- layout específico v1 */
/* Dos bandas: banda A = flujo principal; banda B = anotaciones laterales. */
const V1_LAYOUT = {
  bandA: [
    { x: 40, ids: ['n1', 'n2', 'n3'] },
    { x: 300, ids: ['n5', 'n6'] },
    { x: 560, ids: ['n7', 'n8'] },
    { x: 820, ids: ['n10', 'n11'] },
    { x: 1080, ids: ['n12'] }
  ],
  bandB: [
    { x: 40, ids: ['n13', 'd2'] },
    { x: 300, ids: ['n4', 'd3'] },
    { x: 560, ids: ['n9', 'd1'] },
    { x: 820, ids: ['g3'] },
    { x: 1080, ids: ['g1', 'g2'] }
  ]
};

const NODE_W = 224;
const PAD = 12;
const ROLE_H = 12;
const TITLE_LH = 14;
const STATUS_LH = 11;
const GAP_TITLE_STATUS = 8;
const V_GAP = 26;
const TITLE_CHARS = 28;
const STATUS_CHARS = 38;

function buildGeometry(nodes) {
  const geo = {};
  const bands = {};
  const startA = 132;
  const startB = null; // se calcula después de la banda A

  function layoutBand(specs, yStart) {
    let bottom = yStart;
    for (const col of specs) {
      let y = yStart;
      for (const id of col.ids) {
        const node = nodes[id];
        if (!node) continue;
        const tLines = wrap(node.title, TITLE_CHARS);
        const sLines = wrap(node.statusLabel, STATUS_CHARS);
        const h = PAD + ROLE_H + 6 + tLines.length * TITLE_LH + GAP_TITLE_STATUS + sLines.length * STATUS_LH + PAD;
        geo[id] = { x: col.x, y, w: NODE_W, h, tLines, sLines, node };
        y += h + V_GAP;
      }
      bottom = Math.max(bottom, y - V_GAP);
    }
    return bottom;
  }

  bands.A = layoutBand(V1_LAYOUT.bandA, startA);
  bands.B = layoutBand(V1_LAYOUT.bandB, bands.A + 96);
  return { geo, bands };
}

/* ---------------------------------------------------------- rutas de arista */
function arrowPath(kind, geo, from, to) {
  const a = geo[from], b = geo[to];
  if (!a || !b) return null;
  const ax = a.x + a.w / 2, ay = a.y + a.h;
  const bx = b.x + b.w / 2, by = b.y;

  if (kind === 'left-lane') {
    const lane = a.x - 26;
    return 'M' + n(a.x) + ' ' + n(a.y + a.h / 2) + ' L' + n(lane) + ' ' + n(a.y + a.h / 2) +
      ' L' + n(lane) + ' ' + n(b.y + b.h / 2) + ' L' + n(b.x) + ' ' + n(b.y + b.h / 2);
  }
  if (kind === 'right-lane') {
    const lane = a.x + a.w + 26;
    return 'M' + n(a.x + a.w) + ' ' + n(a.y + a.h / 2) + ' L' + n(lane) + ' ' + n(a.y + a.h / 2) +
      ' L' + n(lane) + ' ' + n(b.y + b.h / 2) + ' L' + n(b.x + b.w) + ' ' + n(b.y + b.h / 2);
  }
  if (kind === 'down') {
    // de banda A a banda B: baja desde el centro inferior hasta el centro superior
    const dy = Math.max(24, (by - ay) / 2);
    return 'M' + n(ax) + ' ' + n(ay) + ' C' + n(ax) + ' ' + n(ay + dy) + ' ' + n(bx) + ' ' + n(by - dy) + ' ' + n(bx) + ' ' + n(by);
  }
  if (kind === 'right') {
    const sx = a.x + a.w, sy = a.y + a.h / 2;
    const tx = b.x, ty = b.y + b.h / 2;
    const mx = (sx + tx) / 2;
    return 'M' + n(sx) + ' ' + n(sy) + ' C' + n(mx) + ' ' + n(sy) + ' ' + n(mx) + ' ' + n(ty) + ' ' + n(tx) + ' ' + n(ty);
  }
  // mismo eje vertical: una debajo de la otra
  const dy = Math.max(16, (by - ay) / 2);
  return 'M' + n(ax) + ' ' + n(ay) + ' C' + n(ax) + ' ' + n(ay + dy) + ' ' + n(bx) + ' ' + n(by - dy) + ' ' + n(bx) + ' ' + n(by);
}

const EDGE_ROUTES = {
  'n2>n13': 'left-lane',
  'n12>g2': 'right-lane'
};

function classifyEdge(kind, geo, from, to) {
  if (EDGE_ROUTES[from + '>' + to]) return EDGE_ROUTES[from + '>' + to];
  const a = geo[from], b = geo[to];
  if (!a || !b) return 'right';
  const bandOf = (g) => (g.y < geo.__splitY ? 'A' : 'B');
  if (bandOf(a) === 'A' && bandOf(b) === 'B') return 'down';
  if (a.x === b.x) return 'stack';
  if (b.x > a.x) return 'right';
  return 'down';
}

/* ------------------------------------------------------------------ SVG */
function buildSvg(model) {
  const view = model.views.find(v => v.id === 'v1');
  if (!view) throw new Error('La vista v1 no existe en SE_MODEL');
  const nodes = view.nodes;
  const { geo, bands } = buildGeometry(nodes);
  geo.__splitY = bands.A + 48;

  const mainEdges = (view.edges || []).map(e => [e[0], e[1]]);
  const extraEdges = (view.extraEdges || []).map(e => [e[0], e[1]]);

  const width = 1400;
  const legendTop = bands.B + 44;

  /* --- leyenda: 4 estados + etiquetas textuales reales --- */
  const labelsByState = {};
  for (const s of STATE_ORDER) labelsByState[s] = [];
  for (const v of model.views) {
    for (const id of Object.keys(v.nodes)) {
      const node = v.nodes[id];
      if (!labelsByState[node.status]) continue;
      if (labelsByState[node.status].indexOf(node.statusLabel) === -1) labelsByState[node.status].push(node.statusLabel);
    }
  }

  const legendLines = [];
  let legendH = 46;
  for (const s of STATE_ORDER) {
    const all = labelsByState[s];
    const primary = STATE[s].label;
    const others = all.filter(l => l !== primary);
    legendLines.push({ state: s, primary, others });
    legendH += 16;
    if (others.length) {
      const wrapped = wrap('Otras etiquetas de este estado: ' + others.join('  ·  '), 150);
      legendH += wrapped.length * 12 + 4;
    } else {
      legendH += 4;
    }
  }
  legendH += 14;
  const legendBottom = legendTop + legendH;

  const footerLines = [
    'Contexto del snapshot: repositorio principal SYSTEM-ENGINEERING · rama ' + model.meta.branch + ' · HEAD ' + model.meta.head + ' · fecha ' + model.meta.date + (model.meta.mainHead ? ' · main ' + model.meta.mainHead + ' (ancestro de HEAD)' : '') + '.',
    'El trabajo P3-A / P3-B.1 / P3-C ya está commiteado en main (' + model.meta.mainHead + ') y en ' + model.meta.branch + ' (' + model.meta.head + '); este prototipo solo lee el árbol, nunca lo modifica.',
    'Prototipo independiente, fuera de cualquier repositorio Git, no publicado; autorizado sólo para inspección humana. Exportación estática: la animación del prototipo interactivo es explicativa y no simula una ejecución real.'
  ];

  const height = legendBottom + 26 + footerLines.length * 15 + 24;

  const out = [];
  out.push('<?xml version="1.0" encoding="UTF-8"?>');
  out.push('<svg xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' + Math.round(height) +
    '" viewBox="0 0 ' + width + ' ' + Math.round(height) + '" font-family="system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif" role="img" aria-labelledby="svgTitle svgDesc">');
  out.push('  <title id="svgTitle">' + xml(view.title) + '</title>');
  out.push('  <desc id="svgDesc">' + xml(view.desc + ' Exportación estática de la vista 1 del prototipo interactivo; el color no es la única señal porque cada nodo incluye su etiqueta de estado.') + '</desc>');
  out.push('  <defs>');
  out.push('    <marker id="arrowTeal" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">');
  out.push('      <path d="M0,0 L10,5 L0,10 z" fill="' + PAL.teal + '"/>');
  out.push('    </marker>');
  out.push('    <marker id="arrowGray" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">');
  out.push('      <path d="M0,0 L10,5 L0,10 z" fill="' + PAL.muted + '"/>');
  out.push('    </marker>');
  out.push('  </defs>');

  out.push('  <rect x="0" y="0" width="' + width + '" height="' + Math.round(height) + '" fill="' + PAL.bg + '"/>');

  /* --- encabezado --- */
  out.push('  <text x="40" y="54" font-size="23" font-weight="700" fill="' + PAL.ink + '">' + xml('SYSTEM-ENGINEERING — ' + view.title) + '</text>');
  out.push('  <text x="40" y="78" font-size="12.5" fill="' + PAL.muted + '">' + xml(view.desc) + '</text>');
  out.push('  <text x="40" y="97" font-size="11" fill="' + PAL.muted + '">' + xml('Exportación estática de la vista 1 del prototipo index.html · el color no es la única señal: cada nodo incluye etiqueta de estado.') + '</text>');
  out.push('  <line x1="40" y1="110" x2="' + (width - 40) + '" y2="110" stroke="' + PAL.line + '" stroke-width="1"/>');

  /* --- aristas (debajo de los nodos) --- */
  out.push('  <g class="edges" fill="none">');
  for (const e of mainEdges) {
    const d = arrowPath(classifyEdge('main', geo, e[0], e[1]), geo, e[0], e[1]);
    if (!d) continue;
    out.push('    <path class="edge" d="' + d + '" stroke="' + PAL.teal + '" stroke-width="2" marker-end="url(#arrowTeal)"/>');
  }
  for (const e of extraEdges) {
    const d = arrowPath(classifyEdge('extra', geo, e[0], e[1]), geo, e[0], e[1]);
    if (!d) continue;
    out.push('    <path class="edge-extra" d="' + d + '" stroke="' + PAL.muted + '" stroke-width="1.5" stroke-dasharray="5 4" marker-end="url(#arrowGray)"/>');
  }
  out.push('  </g>');

  /* --- nodos --- */
  out.push('  <g class="nodes">');
  const ordered = [];
  for (const band of ['bandA', 'bandB']) {
    for (const col of V1_LAYOUT[band]) for (const id of col.ids) if (nodes[id]) ordered.push(id);
  }
  for (const id of ordered) {
    const node = nodes[id];
    const g = geo[id];
    const st = STATE[node.status] || STATE.gray;
    out.push('    <g class="node ' + node.status + '" data-node-id="' + xml(node.id) + '" data-state="' + xml(node.status) + '">');
    out.push('      <title>' + xml(node.title + ' — ' + node.statusLabel) + '</title>');
    out.push('      <rect x="' + n(g.x) + '" y="' + n(g.y) + '" width="' + n(g.w) + '" height="' + n(g.h) + '" rx="10" fill="' + st.bg + '" stroke="' + st.border + '" stroke-width="1.4"/>');
    out.push('      <rect x="' + n(g.x) + '" y="' + n(g.y) + '" width="5" height="' + n(g.h) + '" rx="2.5" fill="' + st.fg + '"/>');
    out.push('      <text x="' + n(g.x + 16) + '" y="' + n(g.y + PAD + 8) + '" font-size="9" font-weight="700" letter-spacing="0.6" fill="' + PAL.muted + '">' + xml(String(node.role).toUpperCase()) + '</text>');
    let ty = g.y + PAD + ROLE_H + 6;
    g.tLines.forEach((line, i) => {
      out.push('      <text x="' + n(g.x + 16) + '" y="' + n(ty + 10 + i * TITLE_LH) + '" font-size="12.5" font-weight="700" fill="' + PAL.ink + '">' + xml(line) + '</text>');
    });
    const statusTop = ty + g.tLines.length * TITLE_LH + GAP_TITLE_STATUS;
    g.sLines.forEach((line, i) => {
      out.push('      <text class="status-label" x="' + n(g.x + 16) + '" y="' + n(statusTop + 9 + i * STATUS_LH) + '" font-size="9.5" font-weight="700" fill="' + st.fg + '">' + xml(line) + '</text>');
    });
    out.push('    </g>');
  }
  out.push('  </g>');

  /* --- leyenda --- */
  out.push('  <g class="legend">');
  out.push('    <rect x="40" y="' + n(legendTop) + '" width="' + (width - 80) + '" height="' + n(legendH) + '" rx="10" fill="' + PAL.card + '" stroke="' + PAL.line + '" stroke-width="1"/>');
  out.push('    <text x="60" y="' + n(legendTop + 24) + '" font-size="12" font-weight="700" fill="' + PAL.ink + '">Leyenda de estados — el color no es la única señal: cada nodo incluye etiqueta de estado</text>');
  let ly = legendTop + 44;
  for (const item of legendLines) {
    const st = STATE[item.state];
    out.push('    <rect x="60" y="' + n(ly - 9) + '" width="14" height="14" rx="3" fill="' + st.bg + '" stroke="' + st.fg + '" stroke-width="1.6"/>');
    out.push('    <text x="84" y="' + n(ly + 2) + '" font-size="11.5" font-weight="700" fill="' + PAL.ink + '">' + xml(st.fg + ' · ' + item.primary) + '</text>');
    ly += 16;
    if (item.others.length) {
      const wrapped = wrap('Otras etiquetas de este estado: ' + item.others.join('  ·  '), 150);
      wrapped.forEach((line, i) => {
        out.push('    <text x="84" y="' + n(ly + 2 + i * 12) + '" font-size="10" fill="' + PAL.muted + '">' + xml(line) + '</text>');
      });
      ly += wrapped.length * 12 + 4;
    } else {
      ly += 4;
    }
  }
  out.push('  </g>');

  /* --- pie --- */
  let fy = legendBottom + 26;
  for (const line of footerLines) {
    out.push('  <text x="40" y="' + n(fy) + '" font-size="10.5" fill="' + PAL.muted + '">' + xml(line) + '</text>');
    fy += 15;
  }

  out.push('</svg>');
  return out.join('\n') + '\n';
}

/* ------------------------------------------------------------------ MMD */
function mmdLabel(text) {
  return String(text == null ? '' : text)
    .replace(/`/g, '')
    .replace(/"/g, '\'')
    .replace(/\s+/g, ' ')
    .trim();
}

function buildMmd(model) {
  const view = model.views.find(v => v.id === 'v1');
  const nodes = view.nodes;
  const out = [];
  out.push('%% SYSTEM-ENGINEERING — Vista general (flujo principal del workflow)');
  out.push('%% Generado por tools/generate.mjs desde SE_MODEL en index.html. No editar a mano.');
  out.push('%% Contexto del snapshot: repositorio principal SYSTEM-ENGINEERING · rama ' + model.meta.branch + ' · HEAD ' + model.meta.head + ' · fecha ' + model.meta.date + (model.meta.mainHead ? ' · main ' + model.meta.mainHead : '') + '.');
  out.push('%% El trabajo P3-A / P3-B.1 / P3-C ya está commiteado en main y en ' + model.meta.branch + '; este prototipo solo lee el árbol, nunca lo modifica.');
  out.push('%% El color no es la única señal: cada nodo incluye etiqueta de estado textual.');
  out.push('flowchart TD');

  const ids = [];
  for (const band of ['bandA', 'bandB']) {
    for (const col of V1_LAYOUT[band]) for (const id of col.ids) if (nodes[id]) ids.push(id);
  }
  for (const id of ids) {
    const node = nodes[id];
    out.push('  ' + node.id + '["' + mmdLabel(node.title) + ' — ' + mmdLabel(node.statusLabel) + '"]');
  }
  for (const e of (view.edges || [])) {
    out.push('  ' + e[0] + ' --> ' + e[1]);
  }
  for (const e of (view.extraEdges || [])) {
    out.push('  ' + e[0] + ' -.-> ' + e[1]);
  }
  out.push('  classDef green fill:' + PAL.greenBg + ',stroke:' + PAL.green + ',stroke-width:2px,color:' + PAL.ink);
  out.push('  classDef blue fill:' + PAL.blueBg + ',stroke:' + PAL.blue + ',stroke-width:2px,color:' + PAL.ink);
  out.push('  classDef amber fill:' + PAL.amberBg + ',stroke:' + PAL.amber + ',stroke-width:2px,color:' + PAL.ink);
  out.push('  classDef gray fill:' + PAL.grayBg + ',stroke:' + PAL.gray + ',stroke-width:2px,color:' + PAL.ink);
  for (const s of STATE_ORDER) {
    const group = ids.filter(id => nodes[id].status === s);
    if (!group.length) continue;
    out.push('  class ' + group.join(',') + ' ' + s);
  }
  return out.join('\n') + '\n';
}

/* ------------------------------------------- tabla de capacidades (README) */
function mdEscape(s) {
  return String(s == null ? '' : s).replace(/\|/g, '\\|').replace(/\r?\n/g, ' ');
}

function buildCapabilityTable(model) {
  const rows = [];
  rows.push('| Vista | Nodo | Estado | Etiqueta de estado | Evidencia (`archivo:línea`) |');
  rows.push('| --- | --- | --- | --- | --- |');
  for (const view of model.views) {
    const seen = [];
    for (const col of (view.columns || [])) {
      for (const id of col.ids) if (view.nodes[id] && seen.indexOf(id) === -1) seen.push(id);
    }
    for (const id of Object.keys(view.nodes)) if (seen.indexOf(id) === -1) seen.push(id);
    for (const id of seen) {
        const node = view.nodes[id];
        const st = STATE[node.status] || STATE.gray;
        const ev = (node.evidence || []).length
          ? node.evidence.map(mdEscape).join('<br>')
          : '— (nodo ilustrativo, sin evidencia de código)';
        rows.push('| ' + mdEscape(view.tab) + ' | `' + node.id + '` — ' + mdEscape(node.title) +
          ' | ' + st.fg + ' (' + node.status + ') | ' + mdEscape(node.statusLabel) + ' | ' + ev + ' |');
      }
  }
  return rows.join('\n');
}

/* ------------------------------------------------------------------ main */
function main() {
  const args = process.argv.slice(2);
  const html = fs.readFileSync(INDEX, 'utf8');
  const model = extractModel(html);

  if (args.indexOf('--print-capability-table') !== -1) {
    process.stdout.write(buildCapabilityTable(model) + '\n');
    return;
  }

  const svg = buildSvg(model);
  const mmd = buildMmd(model);

  fs.writeFileSync(SVG_OUT, svg, 'utf8');
  fs.writeFileSync(MMD_OUT, mmd, 'utf8');

  const view = model.views.find(v => v.id === 'v1');
  const ids = Object.keys(view.nodes);
  console.log('OK  diagram.svg  ' + SVG_OUT + '  (' + Buffer.byteLength(svg, 'utf8') + ' bytes)');
  console.log('OK  diagram.mmd  ' + MMD_OUT + '  (' + Buffer.byteLength(mmd, 'utf8') + ' bytes)');
  console.log('OK  vista v1 "' + view.tab + '": ' + ids.length + ' nodos, ' +
    (view.edges || []).length + ' aristas edges, ' + (view.extraEdges || []).length + ' aristas extraEdges');
}

main();
