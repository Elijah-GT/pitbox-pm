// Tree rendering.
//
// Rendering is a full redraw of the visible rows on every change. That sounds
// wasteful, but a Baja BOM is a few thousand nodes and only the expanded ones are
// ever in the DOM -- it stays well under a frame, and it removes every class of
// "the UI and the data disagree" bug. If a team ever grows a tree big enough to
// stutter here, the fix is windowing this one function, not restructuring the app.

import { state, childrenOf, roots, tagsOf } from './state.js';
import { computeVisibility, expandToMatches } from './filter.js';

export const STATUS_COLORS = {
  concept: '#767d8c',
  design: '#3b82f6',
  in_review: '#8b5cf6',
  ordered: '#14b8a6',
  in_fabrication: '#f59e0b',
  assembled: '#84cc16',
  // Rose rather than another yellow: at 8px the amber of In Fabrication is
  // indistinguishable from one. Keep in step with frontend/src/lib/format.ts.
  not_installed: '#fb7185',
  installed: '#22c55e',
};

// Declaration order is the order of the status dropdown (main.js builds it from
// Object.entries), so this reads as the life of a part.
export const STATUS_LABELS = {
  concept: 'Concept',
  design: 'Design',
  in_review: 'In Review',
  ordered: 'Ordered',
  in_fabrication: 'In Fabrication',
  assembled: 'Assembled',
  not_installed: 'Not Installed',
  installed: 'Installed',
};

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;   // textContent, never innerHTML:
  return node;                                  // part names are user input.
};

let handlers = {};

export function initTree(callbacks) {
  handlers = callbacks;
}

export function renderTree() {
  const container = document.getElementById('treeRoot');
  const { matched, context, visible, active } = computeVisibility();

  if (active) expandToMatches(matched);

  const isolate = state.filter.mode === 'isolate';
  const frag = document.createDocumentFragment();

  const walk = (nodes) => {
    for (const node of nodes) {
      // Isolate prunes; highlight keeps everything and dims the misses.
      if (active && isolate && !visible.has(node.id)) continue;

      frag.appendChild(buildRow(node, { matched, context, active, isolate }));

      const kids = childrenOf(node.id);
      if (kids.length && state.expanded.has(node.id)) walk(kids);
    }
  };
  walk(roots());

  container.replaceChildren(frag);
  updateFilterCount(matched, active);
}

function updateFilterCount(matched, active) {
  const label = document.getElementById('filterCount');
  label.textContent = active
    ? `${matched.size} of ${state.nodes.length} nodes match`
    : `${state.nodes.length} nodes`;
}

function buildRow(node, ctx) {
  const row = el('div', 'row');
  row.dataset.id = node.id;
  row.setAttribute('role', 'treeitem');
  row.style.paddingLeft = `${8 + node.depth * 16}px`;

  if (node.id === state.selectedId) row.classList.add('selected');
  if (ctx.active) {
    if (ctx.matched.has(node.id)) row.classList.add('is-match');
    else if (ctx.isolate) row.classList.add('is-context');
    else row.classList.add('dimmed');
  }

  // --- twisty
  const kids = childrenOf(node.id);
  const twisty = el('span', 'twisty', kids.length ? '▶' : '');
  if (!kids.length) twisty.classList.add('leaf');
  if (state.expanded.has(node.id)) twisty.classList.add('open');
  twisty.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!kids.length) return;
    state.expanded.has(node.id)
      ? state.expanded.delete(node.id)
      : state.expanded.add(node.id);
    renderTree();
  });
  row.appendChild(twisty);

  // --- status pip
  const pip = el('span', 'status-pip');
  pip.style.background = STATUS_COLORS[node.status] || '#767d8c';
  pip.title = STATUS_LABELS[node.status] || node.status;
  row.appendChild(pip);

  // --- type badge
  if (node.node_type !== 'part') {
    const badge = el('span', 'node-type-badge', node.node_type.slice(0, 4));
    badge.dataset.type = node.node_type;
    badge.title = node.node_type;
    row.appendChild(badge);
  }

  // --- name / part number / qty
  row.appendChild(el('span', 'node-name', node.name));
  if (node.part_number) row.appendChild(el('span', 'node-pn', node.part_number));
  if (node.quantity > 1) row.appendChild(el('span', 'node-qty', `x${node.quantity}`));

  // --- add-child button
  const add = el('button', 'row-add', '+');
  add.title = 'Add a child node';
  add.setAttribute('aria-label', `Add a child under ${node.name}`);
  add.addEventListener('click', (e) => {
    e.stopPropagation();
    handlers.onAddChild?.(node);
  });
  row.appendChild(add);

  // --- tag dots + file count, right aligned
  const meta = el('span', 'row-tags');
  const fileCount = state.attachmentCounts.get(node.id);
  if (fileCount) {
    meta.appendChild(el('span', 'file-pip', `\u{1F4CE}${fileCount}`));
  }
  for (const tag of tagsOf(node.id).slice(0, 6)) {
    const dot = el('span', `tag-dot${tag.inherited ? ' inherited' : ''}`);
    dot.style.background = tag.color;
    // Square dots mean "inherited from a branch tag", round means "set here".
    dot.title = tag.inherited ? `${tag.name} (inherited)` : tag.name;
    meta.appendChild(dot);
  }
  row.appendChild(meta);

  // --- interaction
  row.addEventListener('click', () => handlers.onSelect?.(node));
  row.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    handlers.onContextMenu?.(node, e);
  });

  attachDragAndDrop(row, node);
  return row;
}

function attachDragAndDrop(row, node) {
  row.draggable = true;

  row.addEventListener('dragstart', (e) => {
    e.dataTransfer.setData('text/plain', String(node.id));
    e.dataTransfer.effectAllowed = 'move';
    row.classList.add('dragging');
  });
  row.addEventListener('dragend', () => row.classList.remove('dragging'));

  row.addEventListener('dragover', (e) => {
    const draggedId = Number(e.dataTransfer.getData('text/plain'));
    // getData is often blocked during dragover for security; fall back to a
    // permissive highlight and let the server reject an illegal move.
    if (draggedId === node.id) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    row.classList.add('drop-target');
  });
  row.addEventListener('dragleave', () => row.classList.remove('drop-target'));

  row.addEventListener('drop', (e) => {
    e.preventDefault();
    row.classList.remove('drop-target');
    const draggedId = Number(e.dataTransfer.getData('text/plain'));
    if (!draggedId || draggedId === node.id) return;
    handlers.onMove?.(draggedId, node.id);
  });
}
