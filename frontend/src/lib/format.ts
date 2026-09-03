import type { Status } from '../api/types'

// Declaration order is the order of the dropdown and the filter, so this
// reads as the life of a part: drawn, checked, bought or made, then fitted.
// "Not installed" sits immediately before "Installed" because that is what it
// means here -- the part exists and is ready, it is just not on the car yet.
export const STATUS_LABELS: Record<Status, string> = {
  concept: 'Concept',
  design: 'Design',
  in_review: 'In Review',
  ordered: 'Ordered',
  in_fabrication: 'In Fabrication',
  assembled: 'Assembled',
  not_installed: 'Not Installed',
  installed: 'Installed',
}

export const STATUS_COLORS: Record<Status, string> = {
  concept: '#767d8c',
  design: '#3b82f6',
  in_review: '#8b5cf6',
  ordered: '#14b8a6',
  in_fabrication: '#f59e0b',
  assembled: '#84cc16',
  // Rose, not another yellow: these are 8px pips, and the amber already used
  // by In Fabrication is too close to read apart at that size. It also says
  // "outstanding" without saying "broken", which red would.
  not_installed: '#fb7185',
  installed: '#22c55e',
}

export const STATUS_ORDER = Object.keys(STATUS_LABELS) as Status[]

/** Cost is stored as integer cents; forms and displays work in dollars. */
export function centsToDollars(cents: number | null): string {
  return cents == null ? '' : (cents / 100).toFixed(2)
}

export function formatMoney(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`
}

export function humanSize(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i += 1
  }
  return `${value < 10 && i > 0 ? value.toFixed(1) : Math.round(value)} ${units[i]}`
}

/** Pull a 4-digit season out of a project name like "Baja 2027 Car". */
export function seasonFromName(name: string): string | null {
  return /\d{4}/.exec(name)?.[0] ?? null
}
