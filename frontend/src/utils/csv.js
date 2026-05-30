/**
 * CropSentinel — CSV export helpers
 * =================================
 *
 * Tiny, dependency-free CSV serializer + browser download trigger.
 * Used by every data-table page ("Export CSV" button) so that what the
 * user sees on screen is what ends up in the file — we serialize the
 * already-filtered/sorted array, not a fresh server round-trip.
 *
 * Escaping rules (RFC 4180):
 *   - Fields containing `,`, `"`, `\n`, or `\r` are wrapped in double
 *     quotes.
 *   - Literal `"` inside a quoted field is doubled to `""`.
 *   - null/undefined render as empty string.
 *   - Dates render via .toISOString() so Excel/Sheets parse them.
 *   - Objects/arrays are JSON.stringify'd (rare, but beats "[object Object]").
 *
 * Excel quirk: we prepend a UTF-8 BOM so Excel on Windows doesn't
 * mojibake non-ASCII characters (domain names, Unicode filenames).
 */

function escapeCell(value) {
  if (value == null) return ''
  if (value instanceof Date) return value.toISOString()
  let str = typeof value === 'object' ? JSON.stringify(value) : String(value)
  if (/[",\r\n]/.test(str)) {
    str = `"${str.replace(/"/g, '""')}"`
  }
  return str
}

/**
 * Build a CSV string from rows + column definitions.
 *
 * @param {Array<object>} rows
 * @param {Array<{key: string, label?: string, value?: (row) => any}>} columns
 * @returns {string}
 */
export function toCsv(rows, columns) {
  const headers = columns.map(c => escapeCell(c.label ?? c.key)).join(',')
  const body = rows.map(row =>
    columns.map(c => escapeCell(c.value ? c.value(row) : row[c.key])).join(',')
  ).join('\r\n')
  return headers + '\r\n' + body
}

/**
 * Trigger a browser download of `content` as `filename`.
 * Safe to call repeatedly — each call creates and revokes its own
 * Blob URL.
 */
export function downloadText(filename, content, mime = 'text/csv;charset=utf-8') {
  // UTF-8 BOM so Excel on Windows opens it correctly.
  const BOM = '\uFEFF'
  const blob = new Blob([BOM + content], { type: mime })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/**
 * One-shot helper: serialize rows and immediately trigger download.
 * The filename gets a YYYY-MM-DD stamp appended if you don't include
 * one yourself.
 */
export function exportCsv(filename, rows, columns) {
  const stamped = /\d{4}-\d{2}-\d{2}/.test(filename)
    ? filename
    : filename.replace(/(\.csv)?$/i, `_${new Date().toISOString().slice(0, 10)}.csv`)
  downloadText(stamped, toCsv(rows, columns))
}
