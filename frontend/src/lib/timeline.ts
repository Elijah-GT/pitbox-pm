import type { GoalKind, GoalPriority, Milestone } from '../api/types'

/** Full names for the dropdowns. */
export const PRIORITY_LABELS: Record<GoalPriority, string> = {
  sae: 'Baja SAE deadline',
  critical: 'Critical',
  normal: 'Normal',
  low: 'Low',
}
export const PRIORITY_ORDER = Object.keys(PRIORITY_LABELS) as GoalPriority[]

export const KIND_LABELS: Record<GoalKind, string> = {
  design: 'Design',
  manufacturing: 'Manufacturing',
  other: 'Other',
}
export const KIND_ORDER = Object.keys(KIND_LABELS) as GoalKind[]

/** Short forms for the flags, where there is room for three characters. */
export const PRIORITY_TAGS: Partial<Record<GoalPriority, string>> = {
  sae: 'SAE',
  critical: 'CRIT',
}
export const KIND_TAGS: Partial<Record<GoalKind, string>> = {
  design: 'DES',
  manufacturing: 'MFG',
}

/**
 * Laying dated goals out along a horizontal axis.
 *
 * Kept out of the component because the fiddly parts — parsing a date without
 * letting a timezone move it, and stopping labels from landing on top of each
 * other — are logic, not markup, and are much easier to reason about here.
 */

/** A goal's state, which is the whole colour story on the timeline. */
export type GoalState = 'done' | 'overdue' | 'soon' | 'ahead'

/** How many days out still counts as "soon". Roughly a sprint. */
export const SOON_DAYS = 21

const DAY_MS = 86_400_000

/**
 * Parse "2026-02-12" as a LOCAL calendar day.
 *
 * `new Date('2026-02-12')` parses as UTC midnight, which in any negative
 * offset is the 11th locally — so a deadline would render one day early for
 * everyone west of Greenwich, which is the entire team. Splitting the parts
 * and using the local constructor keeps the day the day.
 */
export function parseDay(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, (m ?? 1) - 1, d ?? 1)
}

/** Today at local midnight, so day comparisons are not skewed by the clock. */
export function today(): Date {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate())
}

/** Whole days from a to b. Both are midnights, so no rounding surprises. */
export function daysBetween(a: Date, b: Date): number {
  return Math.round((b.getTime() - a.getTime()) / DAY_MS)
}

export function goalState(m: Milestone, now: Date = today()): GoalState {
  if (m.done) return 'done'
  const due = parseDay(m.due_date)
  const left = daysBetween(now, due)
  if (left < 0) return 'overdue'
  if (left <= SOON_DAYS) return 'soon'
  return 'ahead'
}

/** "3 days late", "due today", "in 2 weeks" — the phrasing people actually use. */
export function dueLabel(m: Milestone, now: Date = today()): string {
  const left = daysBetween(now, parseDay(m.due_date))
  if (m.done) return 'done'
  if (left === 0) return 'due today'
  if (left === 1) return 'due tomorrow'
  if (left === -1) return '1 day late'
  if (left < 0) return `${-left} days late`
  if (left < 14) return `in ${left} days`
  if (left < 60) return `in ${Math.round(left / 7)} weeks`
  return `in ${Math.round(left / 30)} months`
}

export function formatDay(iso: string): string {
  return parseDay(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export interface Span {
  start: Date
  end: Date
  /** First of each month inside the span, for gridlines and labels. */
  months: Date[]
}

/**
 * The window the axis covers: every goal, plus today, padded out to whole
 * months so the gridlines land on month boundaries.
 *
 * Today is always included even when every goal is in the future — an axis
 * that starts after today cannot show you where you are, which is most of the
 * point of looking at it.
 */
export function spanOf(milestones: Milestone[], now: Date = today()): Span {
  const days = milestones.map((m) => parseDay(m.due_date))
  const all = [...days, now]
  const min = new Date(Math.min(...all.map((d) => d.getTime())))
  const max = new Date(Math.max(...all.map((d) => d.getTime())))

  const start = new Date(min.getFullYear(), min.getMonth(), 1)
  // Day 0 of the following month is the last day of `max`'s month.
  const end = new Date(max.getFullYear(), max.getMonth() + 1, 0)

  const months: Date[] = []
  const cursor = new Date(start)
  while (cursor <= end) {
    months.push(new Date(cursor))
    cursor.setMonth(cursor.getMonth() + 1)
  }

  return { start, end, months }
}

/** Where a day sits on the axis, 0–100. */
export function positionOf(day: Date, span: Span): number {
  const total = daysBetween(span.start, span.end)
  if (total <= 0) return 50
  const at = daysBetween(span.start, day)
  return Math.min(100, Math.max(0, (at / total) * 100))
}

export interface Placed {
  milestone: Milestone
  /** 0–100 along the axis. */
  pct: number
  /** Alternating, the way the whiteboard does it. */
  side: 'above' | 'below'
  /** Which row out from the axis, so crowded dates do not overlap. */
  lane: number
  /** Near the right-hand end, so the label grows left from its dot instead. */
  atEnd: boolean
  state: GoalState
}

/**
 * A label is about this much of the track wide. Used only to decide whether
 * two labels would collide — the track has a min-width in CSS, so this stays
 * roughly honest instead of drifting with the viewport.
 */
const LABEL_PCT = 13

/**
 * Past this point along the axis a label is flipped to grow leftwards from its
 * dot, so the last goal of the season does not hang off the end of the track.
 * Shared with the component so the lane maths and the CSS cannot disagree --
 * they did, and two labels in the same lane overlapped.
 */
export const AT_END_PCT = 85

/**
 * Place every goal: alternating sides, then stacked into lanes so a cluster of
 * dates in one week does not become a pile of unreadable overlapping text.
 *
 * Greedy and simple: walk in date order, and on each side take the first lane
 * whose last label has already ended before this one starts.
 */
export function placeAll(milestones: Milestone[], span: Span, now: Date = today()): Placed[] {
  // Lowest occupied right edge per lane, per side.
  const edges: Record<'above' | 'below', number[]> = { above: [], below: [] }

  return [...milestones]
    .sort((a, b) => a.due_date.localeCompare(b.due_date) || a.id - b.id)
    .map((milestone, i) => {
      const pct = positionOf(parseDay(milestone.due_date), span)
      const side: 'above' | 'below' = i % 2 === 0 ? 'above' : 'below'

      // The span the LABEL covers, which is not the span from the dot: a
      // flipped label sits to the left of its dot.
      const atEnd = pct > AT_END_PCT
      const left = atEnd ? pct - LABEL_PCT : pct
      const right = left + LABEL_PCT

      const lanes = edges[side]
      let lane = lanes.findIndex((edge) => edge <= left)
      if (lane === -1) {
        lane = lanes.length
        lanes.push(0)
      }
      lanes[lane] = right

      return { milestone, pct, side, lane, atEnd, state: goalState(milestone, now) }
    })
}
