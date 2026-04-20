import { useEffect, useState } from 'react'

async function fetchUsage() {
  const res = await fetch('/api/admin/usage')
  if (!res.ok) throw new Error('Failed to load usage data')
  return res.json()
}

const MODEL_SHORT = {
  'claude-haiku-4-5-20251001': 'Haiku',
  'claude-sonnet-4-6': 'Sonnet',
}

function fmt(n) {
  return n?.toLocaleString() ?? '—'
}

function fmtCost(n) {
  if (n === undefined || n === null) return '—'
  if (n < 0.01) return '<$0.01'
  return `$${n.toFixed(4)}`
}

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso + 'Z')
  return d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
}

export default function Admin() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setData(await fetchUsage())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  if (loading) return <div className="p-4 text-gray-500 text-sm">Loading usage data…</div>
  if (error) return <div className="p-4 text-red-400 text-sm">{error}</div>

  const { by_type, recent, totals } = data

  return (
    <div className="p-4 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-lg">Claude API Usage</h2>
        <button
          onClick={load}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          Refresh
        </button>
      </div>

      {/* Totals */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Input tokens', value: fmt(totals.input_tokens) },
          { label: 'Output tokens', value: fmt(totals.output_tokens) },
          { label: 'Est. total cost', value: fmtCost(totals.estimated_cost_usd) },
        ].map(({ label, value }) => (
          <div key={label} className="bg-gray-800 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400 mb-1">{label}</p>
            <p className="text-lg font-semibold text-gray-100">{value}</p>
          </div>
        ))}
      </div>

      {/* By call type */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-2">By call type</h3>
        {by_type.length === 0 ? (
          <p className="text-sm text-gray-500">No calls recorded yet.</p>
        ) : (
          <div className="space-y-2">
            {by_type.map((row, i) => (
              <div key={i} className="bg-gray-800 rounded-xl px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
                <span className="font-medium capitalize w-20">{row.call_type}</span>
                <span className="text-gray-400 text-xs">{MODEL_SHORT[row.model] ?? row.model}</span>
                <span className="text-gray-300">{fmt(row.calls)} calls</span>
                <span className="text-gray-400 text-xs">in {fmt(row.input_tokens)} / out {fmt(row.output_tokens)}</span>
                <span className="ml-auto text-violet-300 font-medium">{fmtCost(row.estimated_cost_usd)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recent calls */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-2">Recent calls</h3>
        {recent.length === 0 ? (
          <p className="text-sm text-gray-500">No calls recorded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-gray-300">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-1.5 pr-3 font-medium">Time</th>
                  <th className="text-left py-1.5 pr-3 font-medium">Type</th>
                  <th className="text-left py-1.5 pr-3 font-medium">Model</th>
                  <th className="text-right py-1.5 pr-3 font-medium">In</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Out</th>
                  <th className="text-right py-1.5 font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((r, i) => (
                  <tr key={i} className="border-b border-gray-800/50">
                    <td className="py-1.5 pr-3 text-gray-500">{fmtTime(r.created_at)}</td>
                    <td className="py-1.5 pr-3 capitalize">{r.call_type}</td>
                    <td className="py-1.5 pr-3 text-gray-400">{MODEL_SHORT[r.model] ?? r.model}</td>
                    <td className="py-1.5 pr-3 text-right">{fmt(r.input_tokens)}</td>
                    <td className="py-1.5 pr-3 text-right">{fmt(r.output_tokens)}</td>
                    <td className="py-1.5 text-right text-violet-300">{fmtCost(r.estimated_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
