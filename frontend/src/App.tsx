import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api, type AuthMode } from './api/client'
import type { Member, NodeDetail, ProjectSummary, TreeNode, TreeResponse } from './api/types'
import { ConnectionPicker } from './components/ConnectionPicker'
import { ContextMenu, type MenuTarget } from './components/ContextMenu'
import { DetailPanel } from './components/DetailPanel'
import { FilterBar } from './components/FilterBar'
import { FlowView } from './components/FlowView'
import { LearnView } from './components/LearnView'
import { OrdersView } from './components/OrdersView'
import { TeamPanel } from './components/TeamPanel'
import { ShopView } from './components/ShopView'
import { TimelineView } from './components/TimelineView'
import { TopBar, type Workspace } from './components/TopBar'
import { TreeView } from './components/TreeView'
import { useToast } from './hooks/useToast'
import {
  buildGroups,
  connectedNodeIds,
  connectionValues,
  type ConnectBy,
} from './lib/connections'
import {
  computeVisibility,
  emptyFilter,
  expandedForMatches,
  isFilterActive,
  type FilterState,
} from './lib/filter'
import { seasonFromName } from './lib/format'
import { ancestorIds, buildIndex } from './lib/tree'

/**
 * The Learn page in the URL: undefined when the URL is not a Learn link at
 * all, null for the Learn index, or a page id. Learn is the one section with
 * its own URLs, so "read the welding page" can be a link someone sends.
 */
function readLearnRoute(): number | null | undefined {
  const m = /^#\/learn(?:\/page\/(\d+))?\/?$/.exec(window.location.hash)
  if (!m) return undefined
  return m[1] ? Number(m[1]) : null
}

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [projectId, setProjectId] = useState<number | null>(null)
  const [tree, setTree] = useState<TreeResponse | null>(null)
  const [detail, setDetail] = useState<NodeDetail | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set<number>())
  const [filter, setFilter] = useState<FilterState>(emptyFilter)
  const [menu, setMenu] = useState<MenuTarget | null>(null)
  const [loading, setLoading] = useState(true)
  const [currentUser, setCurrentUser] = useState<Member | null>(null)
  const [authMode, setAuthMode] = useState<AuthMode>('cloudflare')
  const [teamOpen, setTeamOpen] = useState(false)

  // The card drill-down as an alternative to the tree. `flowFocusId` is which
  // node's children are on screen; null means the top. Both are pure view
  // state -- no extra fetch, no extra backend, same TreeIndex either way.
  // Which half of the app: the part tree, or the dated goals. The timeline is
  // project-wide and wants the full width, so it replaces the two-pane layout
  // rather than squeezing into the tree pane.
  const [workspace, setWorkspace] = useState<Workspace>(() =>
    readLearnRoute() !== undefined ? 'learn' : 'breakdown',
  )
  const [learnPageId, setLearnPageId] = useState<number | null>(() => readLearnRoute() ?? null)

  // The hash is the source of truth for Learn, so the browser's back button
  // walks back through the pages you read -- and out of Learn altogether.
  useEffect(() => {
    const onHash = () => {
      const route = readLearnRoute()
      if (route === undefined) {
        setWorkspace((w) => (w === 'learn' ? 'breakdown' : w))
        return
      }
      setWorkspace('learn')
      setLearnPageId(route)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const goWorkspace = useCallback((next: Workspace) => {
    setWorkspace(next)
    if (next === 'learn') {
      if (readLearnRoute() === undefined) window.location.hash = '#/learn'
    } else if (readLearnRoute() !== undefined) {
      // Replace rather than push: leaving Learn should not leave a history
      // entry that drops you straight back into it.
      window.history.replaceState(null, '', window.location.pathname + window.location.search)
    }
  }, [])

  const openLearnPage = useCallback((id: number | null) => {
    window.location.hash = id == null ? '#/learn' : `#/learn/page/${id}`
  }, [])
  const [view, setView] = useState<'tree' | 'flow'>('tree')
  const [flowFocusId, setFlowFocusId] = useState<number | null>(null)

  // Three tiers, matching app/security.py exactly:
  //   read      anyone signed in
  //   canEdit   any member -- change a part, tag it, attach a file, drag it
  //   isAdmin   add, delete, duplicate, and anything project- or team-wide
  //
  // These only hide controls. The server is what enforces the rule, and the two
  // are independent on purpose: a stale or wrong value here shows the wrong
  // buttons, but it never grants anything, because every write is checked
  // against the verified token rather than against what the page believes.
  const isAdmin = currentUser?.is_admin ?? false
  const canEdit = currentUser != null

  // Non-hierarchical links drawn in the right gutter: which field, and which of
  // its values are currently being drawn.
  const [connectBy, setConnectBy] = useState<ConnectBy>('tag')
  const [connections, setConnections] = useState<string[]>([])

  const { toast, show, showError } = useToast()

  // Which project the expanded-set currently belongs to, so a plain refresh
  // keeps the user's open branches but a project switch starts fresh.
  const expandedFor = useRef<number | null>(null)

  // The "who are you?" prompt is once per session, never on a re-render.
  const askedForName = useRef(false)

  const index = useMemo(() => (tree ? buildIndex(tree) : null), [tree])

  const visibility = useMemo(
    () => (index ? computeVisibility(index, filter) : null),
    [index, filter],
  )

  const connValues = useMemo(
    () => (index ? connectionValues(index, connectBy, tree?.members ?? []) : []),
    [index, connectBy, tree?.members],
  )

  const groups = useMemo(() => buildGroups(connValues, connections), [connValues, connections])

  // Matches buried in collapsed branches would be invisible, so ancestors of
  // matches are opened for rendering — derived, never written back to state.
  // Connected nodes get the same treatment: a link you cannot see is useless.
  const effectiveExpanded = useMemo(() => {
    if (!index) return expanded
    let next = expanded
    if (visibility?.active) next = expandedForMatches(index, next, visibility.matched)
    if (groups.length) next = expandedForMatches(index, next, connectedNodeIds(groups))
    return next
  }, [index, visibility, expanded, groups])

  /* ------------------------------------------------------------- loading */

  const loadTree = useCallback(async (id: number) => {
    const payload = await api.getTree(id)
    setTree(payload)
    if (expandedFor.current !== id) {
      // First view of this project: open the top two levels so the page is not
      // a single collapsed line.
      setExpanded(new Set(payload.nodes.filter((n) => n.depth <= 1).map((n) => n.id)))
      expandedFor.current = id
    }
    return payload
  }, [])

  useEffect(() => {
    let cancelled = false
    api.me().then((m) => { if (!cancelled) setCurrentUser(m) }).catch(() => {})
    api.health().then((h) => { if (!cancelled) setAuthMode(h.auth_mode) }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    api
      .listProjects()
      .then((list) => {
        if (cancelled) return
        setProjects(list)
        if (list.length > 0) setProjectId((cur) => cur ?? list[0].id)
        else show('No projects yet — click "+ New Tree" to start.', true)
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        showError(err)
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [show, showError])

  useEffect(() => {
    if (projectId == null) return
    let cancelled = false
    loadTree(projectId).catch((err: unknown) => {
      if (!cancelled) showError(err)
    })
    return () => {
      cancelled = true
    }
  }, [projectId, loadTree, showError])

  useEffect(() => {
    if (selectedId == null) {
      setDetail(null)
      return
    }
    let cancelled = false
    api
      .getNode(selectedId)
      .then((d) => {
        if (!cancelled) setDetail(d)
      })
      .catch((err: unknown) => {
        if (!cancelled) showError(err)
      })
    return () => {
      cancelled = true
    }
  }, [selectedId, showError])

  /** Re-fetch the tree and the open node after any mutation. */
  const refresh = useCallback(async () => {
    if (projectId == null) return
    try {
      const payload = await loadTree(projectId)
      if (selectedId != null && payload.nodes.some((n) => n.id === selectedId)) {
        setDetail(await api.getNode(selectedId))
      } else {
        setSelectedId(null)
        setDetail(null)
      }
    } catch (err) {
      showError(err)
    }
  }, [projectId, selectedId, loadTree, showError])

  /* ------------------------------------------------------------- actions */

  const switchProject = (id: number) => {
    setProjectId(id)
    setSelectedId(null)
    setDetail(null)
    // The focused node belongs to the tree we are leaving. Keeping its id would
    // point at nothing, and FlowView would fall back to the top anyway -- do it
    // explicitly so the breadcrumb cannot flash a stale name first.
    setFlowFocusId(null)
  }

  const addChild = async (parent: TreeNode) => {
    const name = prompt(`New node under "${parent.name}":`)
    if (!name?.trim() || projectId == null) return
    try {
      const created = await api.createNode({
        project_id: projectId,
        parent_id: parent.id,
        name: name.trim(),
        // A child of a subsystem is usually an assembly; of an assembly, a part.
        // Just a starting guess — editable in the detail panel.
        node_type: parent.node_type === 'subsystem' ? 'assembly' : 'part',
      })
      setExpanded((cur) => new Set(cur).add(parent.id))
      setSelectedId(created.id)
      await loadTree(projectId)
      setDetail(created)
      show(`Added "${created.name}"`)
    } catch (err) {
      showError(err)
    }
  }

  const renameNode = async (nodeId: number, currentName: string) => {
    const name = prompt('Rename to:', currentName)
    if (!name?.trim() || name === currentName) return
    try {
      await api.updateNode(nodeId, { name: name.trim() })
      await refresh()
    } catch (err) {
      showError(err)
    }
  }

  const duplicateNode = async (nodeId: number, currentName: string) => {
    try {
      const copy = await api.duplicateNode(nodeId, `${currentName} (copy)`)
      setSelectedId(copy.id)
      if (projectId != null) await loadTree(projectId)
      setDetail(copy)
      show('Duplicated.')
    } catch (err) {
      showError(err)
    }
  }

  const deleteNode = async (nodeId: number, currentName: string) => {
    if (!confirm(`Delete "${currentName}" and everything under it?`)) return
    try {
      const result = await api.deleteNode(nodeId)
      if (selectedId === nodeId) {
        setSelectedId(null)
        setDetail(null)
      }
      if (projectId != null) await loadTree(projectId)
      show(`Deleted ${result.deleted_count} node(s).`)
    } catch (err) {
      showError(err)
    }
  }

  const moveNode = async (draggedId: number, targetId: number) => {
    try {
      await api.moveNode(draggedId, targetId)
      setExpanded((cur) => new Set(cur).add(targetId))
      await refresh()
      show('Moved.')
    } catch (err) {
      showError(err)
    }
  }

  const newProject = async () => {
    const name = prompt('Name for the new tree (e.g. "Baja 2027 Car"):')
    if (!name?.trim()) return
    const useTemplate = confirm(
      `Start "${name.trim()}" from the standard Baja subsystem template?\n\n` +
        'OK = the standard breakdown (Frame, Suspension, Drivetrain...).\n' +
        'Cancel = an empty tree with just a root node.\n\n' +
        'Either way this is a NEW tree. Your existing trees are not touched.',
    )
    try {
      const project = await api.createProject({
        name: name.trim(),
        season: seasonFromName(name),
        template: useTemplate ? 'baja_standard' : 'blank',
      })
      const list = await api.listProjects()
      setProjects(list)
      switchProject(project.id)
      // Say the count, not just the name. A template tree looks identical to
      // every other template tree at the top two levels, so "Created X" alone
      // is indistinguishable from having renamed the tree you were looking at.
      const created = list.find((p) => p.id === project.id)
      show(`New tree "${project.name}" — ${created?.node_count ?? 0} nodes. Others unchanged.`)
    } catch (err) {
      showError(err)
    }
  }

  const cloneProject = async () => {
    if (projectId == null || !tree) return
    const name = prompt(`Clone "${tree.project.name}" to a new tree named:`)
    if (!name?.trim()) return
    try {
      const project = await api.cloneProject({
        name: name.trim(),
        season: seasonFromName(name),
        source_project_id: projectId,
        reset_status: 'concept',
      })
      setProjects(await api.listProjects())
      switchProject(project.id)
      show(`Cloned into "${project.name}"`)
    } catch (err) {
      showError(err)
    }
  }

  const deleteProject = async () => {
    if (projectId == null || !tree) return
    const name = tree.project.name
    const nodeCount = tree.nodes.length
    // attachment_counts is a map keyed by node id, not a field on the node.
    const fileCount = Object.values(tree.attachment_counts).reduce((a, b) => a + b, 0)

    // Type-the-name rather than a plain confirm. This destroys a whole season's
    // work in one click and there is no undo, so the cost of a slip is far
    // higher than the cost of typing.
    const typed = prompt(
      `Permanently delete "${name}"?

` +
        `${nodeCount} node${nodeCount === 1 ? '' : 's'} and ${fileCount} file ` +
        `attachment${fileCount === 1 ? '' : 's'} go with it. This cannot be undone.

` +
        `Type the tree's name to confirm:`,
    )
    if (typed === null) return
    if (typed.trim() !== name) {
      show('That did not match the name — nothing was deleted.', true)
      return
    }

    try {
      await api.deleteProject(projectId)
      const list = await api.listProjects()
      setProjects(list)
      // Move to whatever is left, or to an empty state if that was the last one.
      const next = list[0]?.id ?? null
      expandedFor.current = null
      setSelectedId(null)
      setDetail(null)
      if (next == null) setTree(null)
      setProjectId(next)
      show(`Deleted "${name}".`)
    } catch (err) {
      showError(err)
    }
  }

  const setMyName = useCallback(
    async (currentName: string, firstTime: boolean) => {
      const message = firstTime
        ? `You are showing up as "${currentName}".

` +
          'That comes from your email address. Enter your name so teammates can ' +
          'tell who is assigned to what:'
        : 'Your display name:'
      const name = prompt(message, firstTime ? '' : currentName)
      if (name === null) return
      if (!name.trim()) return
      try {
        const updated = await api.updateProfile({ name: name.trim() })
        setCurrentUser(updated)
        // The assignee dropdown reads from the tree payload, so refresh it.
        if (projectId != null) await loadTree(projectId)
        show(`You are now shown as "${updated.name}".`)
      } catch (err) {
        showError(err)
      }
    },
    [projectId, loadTree, show, showError],
  )

  // First visit after Cloudflare let them in: their name is still the email
  // local part. Ask once. auth_mode=none is the shared local dev user, which
  // nobody needs to name.
  useEffect(() => {
    if (askedForName.current || authMode === 'none') return
    if (!currentUser || currentUser.name_confirmed) return
    askedForName.current = true
    void setMyName(currentUser.name, true)
  }, [currentUser, authMode, setMyName])

  /**
   * Switch between the tree and the cards, carrying the place you were.
   *
   * Going to cards focuses the PARENT of whatever is selected, so the node you
   * were looking at is on screen among its siblings rather than the view
   * starting over at the top. Coming back the other way needs nothing: the
   * tree renders from selectedId, which the cards keep up to date.
   */
  const switchView = (next: 'tree' | 'flow') => {
    if (next === 'flow' && selectedId != null && index) {
      const node = index.byId.get(selectedId)
      if (node) setFlowFocusId(node.parent_id)
    }
    setView(next)
  }

  const toggle = (id: number) => {
    setExpanded((cur) => {
      const next = new Set(cur)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  /* -------------------------------------------------------------- render */

  const ancestors = useMemo(() => {
    if (!detail || !index) return []
    return ancestorIds(detail)
      .map((id) => index.byId.get(id))
      .filter((n): n is TreeNode => Boolean(n))
  }, [detail, index])

  const menuNode = menu && index ? index.byId.get(menu.nodeId) : null

  return (
    <>
      <TopBar
        projects={projects}
        projectId={projectId}
        currentUser={currentUser}
        authMode={authMode}
        isAdmin={isAdmin}
        workspace={workspace}
        onWorkspace={goWorkspace}
        onSwitch={switchProject}
        onNew={() => void newProject()}
        onClone={() => void cloneProject()}
        onDelete={() => void deleteProject()}
        onEditName={() =>
          void setMyName(currentUser?.name ?? '', false)
        }
        onManageTeam={() => setTeamOpen(true)}
        onSignOut={() => {
          if (authMode === 'cloudflare') {
            // Cloudflare owns the session; this clears their cookie and the
            // next request re-runs the Access policy.
            window.location.href = '/cdn-cgi/access/logout'
            return
          }
          void api.logout().then(() => { window.location.href = '/login' })
        }}
      />

      {/* The timeline is its own workspace: full width, and without the
          filter bar, which filters parts and has nothing to say about dates. */}
      {workspace === 'timeline' && projectId != null && tree && (
        <TimelineView
          projectId={projectId}
          projectName={tree.project.name}
          nodes={tree.nodes}
          members={tree.members}
          canEdit={canEdit}
          isAdmin={isAdmin}
          onOpenNode={(id) => {
            // A goal links to a part; opening it has to take you to where
            // parts live, not just select something you cannot see.
            setWorkspace('breakdown')
            setSelectedId(id)
          }}
          onError={showError}
          onToast={show}
        />
      )}

      {workspace === 'timeline' && (projectId == null || !tree) && (
        <p className="loading">No tree selected, so there is nothing to plan yet.</p>
      )}

      {/* The cut list is its own section for the same reason as the timeline:
          full width, and no filter bar, which filters parts of the car rather
          than parts to be made. */}
      {workspace === 'shop' && projectId != null && tree && (
        <ShopView
          projectId={projectId}
          projectName={tree.project.name}
          // This car's own subsystems, taken straight from the top level of its
          // tree, so the suggestions say "Front Suspension" because that is
          // what THIS team called it -- not a list hardcoded here.
          subsystems={tree.nodes
            .filter((n) => n.depth === 1)
            .map((n) => n.name)
            .sort((a, b) => a.localeCompare(b))}
          members={tree.members}
          canEdit={canEdit}
          isAdmin={isAdmin}
          onError={showError}
          onToast={show}
        />
      )}

      {workspace === 'shop' && (projectId == null || !tree) && (
        <p className="loading">No tree selected, so there is nothing to make yet.</p>
      )}

      {/* Orders belong to a tree, like the cut list: a season's budget is
          that car's, and last year's orders stay with last year's tree. */}
      {workspace === 'orders' && projectId != null && tree && (
        <OrdersView
          projectId={projectId}
          projectName={tree.project.name}
          subsystems={tree.nodes
            .filter((n) => n.depth === 1)
            .map((n) => n.name)
            .sort((a, b) => a.localeCompare(b))}
          members={tree.members}
          currentUserId={currentUser?.id ?? null}
          isAdmin={isAdmin}
          onError={showError}
          onToast={show}
        />
      )}

      {workspace === 'orders' && (projectId == null || !tree) && (
        <p className="loading">No tree selected, so there is nothing to order yet.</p>
      )}

      {/* Learn is the team's, not a tree's: it does not wait for a project.
          No canEdit: it is guidance, so only admins change it. */}
      {workspace === 'learn' && (
        <LearnView
          pageId={learnPageId}
          onOpenPage={openLearnPage}
          isAdmin={isAdmin}
          onError={showError}
          onToast={show}
        />
      )}

      {workspace === 'breakdown' && (
      <>
      <FilterBar
        tags={tree?.tags ?? []}
        members={tree?.members ?? []}
        filter={filter}
        matchedCount={visibility?.matched.size ?? 0}
        totalCount={tree?.nodes.length ?? 0}
        filterActive={isFilterActive(filter)}
        onChange={setFilter}
      />

      <main className="layout">
        <section className="pane tree-pane" aria-label="Vehicle breakdown">
          <div className="pane-head">
            <h2>Breakdown</h2>

            <ConnectionPicker
              connectBy={connectBy}
              values={connValues}
              selected={connections}
              onChangeField={(by) => {
                // Value keys are field-specific, so a field change resets them.
                setConnectBy(by)
                setConnections([])
              }}
              onToggle={(key) =>
                setConnections((cur) =>
                  cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key],
                )
              }
              onClear={() => setConnections([])}
            />

            <div className="pane-head-actions">
              {/* Expand/Collapse act on the tree's open branches; the card view
                  shows exactly one level and has none, so they go away rather
                  than sitting there doing nothing. */}
              {view === 'tree' && (
                <>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setExpanded(new Set((tree?.nodes ?? []).map((n) => n.id)))}
                  >
                    Expand
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() =>
                      setExpanded(
                        new Set((tree?.nodes ?? []).filter((n) => n.depth === 0).map((n) => n.id)),
                      )
                    }
                  >
                    Collapse
                  </button>
                </>
              )}

              <div className="segmented" role="group" aria-label="View style">
                {(['tree', 'flow'] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    className={view === v ? 'active' : ''}
                    aria-pressed={view === v}
                    title={v === 'tree' ? 'The whole structure at once' : 'One level at a time'}
                    onClick={() => switchView(v)}
                  >
                    {v === 'tree' ? 'Tree' : 'Cards'}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {loading && <p className="loading">Loading…</p>}
          {/* Deleting the last tree leaves nothing to render. Without this the
              pane is simply blank, which reads as a bug rather than a state. */}
          {!loading && projects.length === 0 && (
            <p className="loading">
              No trees yet — click “+ New Tree” to start one.
            </p>
          )}
          {!loading && index && visibility && view === 'flow' && (
            <FlowView
              index={index}
              visibility={visibility}
              members={tree?.members ?? []}
              focusId={flowFocusId}
              selectedId={selectedId}
              isolate={filter.mode === 'isolate'}
              onFocus={setFlowFocusId}
              onSelect={setSelectedId}
            />
          )}

          {!loading && index && visibility && view === 'tree' && (
            <TreeView
              index={index}
              visibility={visibility}
              expanded={effectiveExpanded}
              selectedId={selectedId}
              isolate={filter.mode === 'isolate'}
              groups={groups}
              canEdit={canEdit}
              isAdmin={isAdmin}
              onToggle={toggle}
              onSelect={setSelectedId}
              onAddChild={(n) => void addChild(n)}
              onMove={(a, b) => void moveNode(a, b)}
              onContextMenu={(node, x, y) => setMenu({ nodeId: node.id, name: node.name, x, y })}
            />
          )}

          {/* Both of these work for a plain member -- dragging re-parents, and
              their right-click menu carries Rename -- so the hint stands for
              anyone who can edit. Neither applies to the cards, which navigate
              rather than restructure. */}
          {canEdit && view === 'tree' && (
            <p className="hint">Drag a row onto another to re-parent it. Right-click for actions.</p>
          )}
          {view === 'flow' && (
            <p className="hint">Click a card to open it. Use the breadcrumb to come back up.</p>
          )}
        </section>

        {/* has-node drives the mobile layout: with nothing selected the detail
            pane is hidden entirely on a phone rather than taking half the
            screen to say "select a part", and the tree gets the whole view. */}
        <section
          className={`pane detail-pane${detail ? ' has-node' : ''}`}
          aria-label="Node details"
        >
          {detail && index ? (
            <>
              <button
                type="button"
                className="btn detail-close"
                onClick={() => setSelectedId(null)}
              >
                ← Back to tree
              </button>
              <DetailPanel
                node={detail}
                ancestors={ancestors}
                tags={tree?.tags ?? []}
                members={tree?.members ?? []}
                canEdit={canEdit}
                isAdmin={isAdmin}
                onSelect={setSelectedId}
                onAddChild={(n) => void addChild(n)}
                onChanged={() => void refresh()}
                onError={showError}
                onBusy={show}
              />
            </>
          ) : (
            <div className="detail-empty">
              <p>Select a part to see its details, tags and files.</p>
            </div>
          )}
        </section>
      </main>

      </>
      )}

      {menu && menuNode && canEdit && (
        <ContextMenu
          target={menu}
          isAdmin={isAdmin}
          onClose={() => setMenu(null)}
          onAddChild={() => void addChild(menuNode)}
          onRename={() => void renameNode(menuNode.id, menuNode.name)}
          onDuplicate={() => void duplicateNode(menuNode.id, menuNode.name)}
          onDelete={() => void deleteNode(menuNode.id, menuNode.name)}
        />
      )}

      {teamOpen && (
        <TeamPanel
          currentUser={currentUser}
          onClose={() => setTeamOpen(false)}
          onChanged={() => {
            // A promotion can change what THIS user may do (they can demote
            // themselves), and names shown in the assignee dropdown come from
            // the tree payload, so refresh both.
            void api.me().then(setCurrentUser).catch(showError)
            if (projectId != null) void loadTree(projectId)
          }}
          onError={showError}
        />
      )}

      {toast && <div className={`toast${toast.isError ? ' error' : ''}`}>{toast.message}</div>}
    </>
  )
}
