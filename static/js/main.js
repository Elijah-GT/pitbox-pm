// Bootstrap and event wiring.

import { api } from './api.js';
import { state, loadTree } from './state.js';
import { renderTree, initTree, STATUS_LABELS } from './treeview.js';
import { renderDetail, clearDetail, initDetail } from './detail.js';

// --- toast -------------------------------------------------------------------

let toastTimer = null;
function toast(message, isError = false) {
  const box = document.getElementById('toast');
  box.textContent = message;
  box.className = `toast${isError ? ' error' : ''}`;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, isError ? 6000 : 2600);
}
const showError = (err) => toast(err.message || String(err), true);

// --- data --------------------------------------------------------------------

async function refreshTree({ keepSelection = true } = {}) {
  const payload = await api.getTree(state.projectId);
  loadTree(payload);
  renderTagChips();
  renderTree();
  if (keepSelection && state.selectedId && state.byId.has(state.selectedId)) {
    await selectNode(state.selectedId);
  } else {
    state.selectedId = null;
    clearDetail();
  }
}

async function selectNode(id) {
  state.selectedId = id;
  renderTree();
  try {
    renderDetail(await api.getNode(id));
  } catch (err) {
    showError(err);
  }
}

async function switchProject(projectId) {
  state.projectId = Number(projectId);
  state.expanded = new Set();
  state.selectedId = null;
  document.getElementById('exportBtn').href = `/api/projects/${state.projectId}/export.csv`;
  await refreshTree({ keepSelection: false });
}

// --- filter bar --------------------------------------------------------------

function renderTagChips() {
  const container = document.getElementById('tagFilters');
  const frag = document.createDocumentFragment();

  for (const tag of state.tags) {
    const chip = document.createElement('button');
    chip.className = 'chip';
    chip.type = 'button';
    const active = state.filter.tags.has(tag.slug);
    chip.setAttribute('aria-pressed', String(active));
    if (active) chip.style.background = tag.color;
    if (tag.category) chip.title = tag.category;

    const dot = document.createElement('span');
    dot.className = 'dot';
    dot.style.background = active ? 'rgba(0,0,0,.45)' : tag.color;
    chip.appendChild(dot);
    chip.appendChild(document.createTextNode(tag.name));

    if (tag.node_count) {
      const count = document.createElement('span');
      count.className = 'count';
      count.textContent = tag.node_count;
      chip.appendChild(count);
    }

    chip.addEventListener('click', () => {
      state.filter.tags.has(tag.slug)
        ? state.filter.tags.delete(tag.slug)
        : state.filter.tags.add(tag.slug);
      renderTagChips();
      renderTree();
    });
    frag.appendChild(chip);
  }
  container.replaceChildren(frag);
}

function populateFilterSelects() {
  const status = document.getElementById('statusFilter');
  status.replaceChildren();
  const anyStatus = new Option('Any status', '');
  status.appendChild(anyStatus);
  for (const [value, label] of Object.entries(STATUS_LABELS)) {
    status.appendChild(new Option(label, value));
  }
  status.value = state.filter.status;

  const assignee = document.getElementById('assigneeFilter');
  assignee.replaceChildren();
  assignee.appendChild(new Option('Anyone', ''));
  for (const m of state.members) assignee.appendChild(new Option(m.name, m.id));
  assignee.value = state.filter.assigneeId;
}

function wireFilterBar() {
  let debounce = null;
  document.getElementById('searchInput').addEventListener('input', (e) => {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      state.filter.query = e.target.value.trim().toLowerCase();
      renderTree();
    }, 120);
  });

  document.getElementById('statusFilter').addEventListener('change', (e) => {
    state.filter.status = e.target.value;
    renderTree();
  });
  document.getElementById('assigneeFilter').addEventListener('change', (e) => {
    state.filter.assigneeId = e.target.value;
    renderTree();
  });
  document.getElementById('includeDescendants').addEventListener('change', (e) => {
    state.filter.includeDescendants = e.target.checked;
    renderTree();
  });

  const wireSegmented = (attr, key) => {
    document.querySelectorAll(`[data-${attr}]`).forEach((btn) => {
      btn.addEventListener('click', () => {
        state.filter[key] = btn.dataset[attr];
        btn.parentElement.querySelectorAll('button').forEach((b) => {
          const on = b === btn;
          b.classList.toggle('active', on);
          b.setAttribute('aria-checked', String(on));
        });
        renderTree();
      });
    });
  };
  wireSegmented('tagmode', 'tagMode');
  wireSegmented('mode', 'mode');

  document.getElementById('clearFilters').addEventListener('click', () => {
    state.filter.query = '';
    state.filter.tags.clear();
    state.filter.status = '';
    state.filter.assigneeId = '';
    state.filter.includeDescendants = false;
    document.getElementById('searchInput').value = '';
    document.getElementById('statusFilter').value = '';
    document.getElementById('assigneeFilter').value = '';
    document.getElementById('includeDescendants').checked = false;
    renderTagChips();
    renderTree();
  });

  document.getElementById('expandAll').addEventListener('click', () => {
    for (const node of state.nodes) state.expanded.add(node.id);
    renderTree();
  });
  document.getElementById('collapseAll').addEventListener('click', () => {
    state.expanded.clear();
    for (const node of state.nodes) if (node.depth === 0) state.expanded.add(node.id);
    renderTree();
  });
}

// --- context menu ------------------------------------------------------------

function showContextMenu(node, event) {
  const menu = document.getElementById('contextMenu');
  menu.replaceChildren();

  const item = (label, fn) => {
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.addEventListener('click', () => { menu.hidden = true; fn(); });
    menu.appendChild(btn);
  };

  item('Add child node', () => addChild(node));
  item('Rename', () => renameNode(node));
  item('Duplicate (with subtree)', () => duplicateNode(node));
  menu.appendChild(document.createElement('hr'));
  item('Delete (with subtree)', () => deleteNode(node));

  menu.hidden = false;
  // Keep the menu on screen near the right/bottom edges.
  const { innerWidth, innerHeight } = window;
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(event.clientX, innerWidth - rect.width - 8)}px`;
  menu.style.top = `${Math.min(event.clientY, innerHeight - rect.height - 8)}px`;
}

document.addEventListener('click', () => {
  document.getElementById('contextMenu').hidden = true;
});

// --- node actions ------------------------------------------------------------

async function addChild(parent) {
  const name = prompt(`New node under "${parent.name}":`);
  if (!name || !name.trim()) return;
  try {
    const created = await api.createNode({
      project_id: state.projectId,
      parent_id: parent.id,
      name: name.trim(),
      // A child of a subsystem is usually an assembly; a child of an assembly is
      // usually a part. Just a starting guess -- it is editable in the panel.
      node_type: parent.node_type === 'subsystem' ? 'assembly' : 'part',
    });
    state.expanded.add(parent.id);
    await refreshTree({ keepSelection: false });
    await selectNode(created.id);
    toast(`Added "${created.name}"`);
  } catch (err) { showError(err); }
}

async function renameNode(node) {
  const name = prompt('Rename to:', node.name);
  if (!name || !name.trim() || name === node.name) return;
  try {
    await api.updateNode(node.id, { name: name.trim() });
    await refreshTree();
  } catch (err) { showError(err); }
}

async function duplicateNode(node) {
  try {
    const copy = await api.duplicateNode(node.id, { name: `${node.name} (copy)` });
    await refreshTree({ keepSelection: false });
    await selectNode(copy.id);
    toast('Duplicated.');
  } catch (err) { showError(err); }
}

async function deleteNode(node) {
  if (!confirm(`Delete "${node.name}" and everything under it?`)) return;
  try {
    const result = await api.deleteNode(node.id);
    if (state.selectedId === node.id) state.selectedId = null;
    await refreshTree({ keepSelection: false });
    toast(`Deleted ${result.deleted_count} node(s).`);
  } catch (err) { showError(err); }
}

async function moveNode(draggedId, targetId) {
  try {
    await api.moveNode(draggedId, { new_parent_id: targetId });
    state.expanded.add(targetId);
    await refreshTree();
    toast('Moved.');
  } catch (err) { showError(err); }
}

// --- project actions ---------------------------------------------------------

async function newProject() {
  const name = prompt('Name for the new tree (e.g. "Baja 2027 Car"):');
  if (!name || !name.trim()) return;
  const useTemplate = confirm(
    `Start "${name.trim()}" from the standard Baja subsystem template?\n\n` +
    'OK = the standard breakdown (Frame, Suspension, Drivetrain...).\n' +
    'Cancel = an empty tree with just a root node.\n\n' +
    'Either way this is a NEW tree. Your existing trees are not touched.'
  );
  try {
    const project = await api.createProject({
      name: name.trim(),
      season: (name.match(/\d{4}/) || [])[0] || null,
      template: useTemplate ? 'baja_standard' : 'blank',
    });
    await loadProjects(project.id);
    // Say the count, not just the name: a template tree is indistinguishable
    // from any other template tree at the top two levels.
    const created = state.projects.find((p) => p.id === project.id);
    toast(`New tree "${project.name}" — ${created ? created.node_count : 0} nodes. Others unchanged.`);
  } catch (err) { showError(err); }
}

async function cloneProject() {
  if (!state.project) return;
  const name = prompt(`Clone "${state.project.name}" to a new tree named:`);
  if (!name || !name.trim()) return;
  try {
    const project = await api.cloneProject({
      name: name.trim(),
      season: (name.match(/\d{4}/) || [])[0] || null,
      source_project_id: state.projectId,
      reset_status: 'concept',
    });
    await loadProjects(project.id);
    toast(`Cloned into "${project.name}"`);
  } catch (err) { showError(err); }
}

async function loadProjects(selectId = null) {
  state.projects = await api.listProjects();
  const picker = document.getElementById('projectPicker');
  picker.replaceChildren();
  for (const p of state.projects) {
    // Node count included deliberately: every tree built from the standard
    // template has identical subsystem names, so the count is the only thing
    // that visibly tells two trees apart in this list.
    const label = p.season ? `${p.name} (${p.season})` : p.name;
    const unit = p.node_count === 1 ? 'node' : 'nodes';
    picker.appendChild(new Option(`${label} · ${p.node_count} ${unit}`, p.id));
  }
  if (!state.projects.length) {
    clearDetail();
    toast('No projects yet — click "+ New Tree" to start.', true);
    return;
  }
  const target = selectId ?? state.projects[0].id;
  picker.value = target;
  await switchProject(target);
}

// --- start -------------------------------------------------------------------

initTree({
  onSelect: (node) => selectNode(node.id),
  onAddChild: addChild,
  onMove: moveNode,
  onContextMenu: showContextMenu,
});

initDetail({
  onSelectId: selectNode,
  onAddChild: addChild,
  onSaved: async () => { await refreshTree(); },
  onTagsChanged: async () => { await refreshTree(); },
  onFilesChanged: async () => { await refreshTree(); },
  onUploadStart: (count) => toast(`Uploading ${count} file(s)…`),
  onError: showError,
});

document.getElementById('projectPicker').addEventListener('change', (e) =>
  switchProject(e.target.value)
);
document.getElementById('newProjectBtn').addEventListener('click', newProject);
document.getElementById('cloneProjectBtn').addEventListener('click', cloneProject);

wireFilterBar();

loadProjects()
  .then(populateFilterSelects)
  .catch((err) => {
    showError(err);
    document.getElementById('treeRoot').textContent = 'Could not reach the API.';
  });
