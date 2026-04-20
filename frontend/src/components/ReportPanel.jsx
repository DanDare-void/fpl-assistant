import { useEffect, useState } from 'react'
import { fetchLatestReport, triggerReport } from '../api'

function MarkdownBlock({ text }) {
  // Minimal markdown: headers, bold, bullet lists, horizontal rules
  const lines = text.split('\n')
  const elements = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    if (line.startsWith('### ')) {
      elements.push(
        <h3 key={i} className="text-base font-semibold text-violet-300 mt-5 mb-1">
          {line.slice(4)}
        </h3>
      )
    } else if (line.startsWith('## ')) {
      elements.push(
        <h2 key={i} className="text-lg font-bold text-white mt-6 mb-2">
          {line.slice(3)}
        </h2>
      )
    } else if (line.startsWith('# ')) {
      elements.push(
        <h1 key={i} className="text-xl font-bold text-white mt-6 mb-2">
          {line.slice(2)}
        </h1>
      )
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      elements.push(
        <li key={i} className="ml-4 text-sm text-gray-200 list-disc leading-relaxed">
          {renderInline(line.slice(2))}
        </li>
      )
    } else if (line.match(/^---+$/)) {
      elements.push(<hr key={i} className="border-gray-700 my-4" />)
    } else if (line.trim() === '') {
      elements.push(<div key={i} className="h-2" />)
    } else {
      elements.push(
        <p key={i} className="text-sm text-gray-200 leading-relaxed">
          {renderInline(line)}
        </p>
      )
    }
    i++
  }

  return <div>{elements}</div>
}

function renderInline(text) {
  // Bold: **text**
  const parts = text.split(/(\*\*[^*]+\*\*)/)
  return parts.map((part, i) =>
    part.startsWith('**') && part.endsWith('**')
      ? <strong key={i} className="text-white font-semibold">{part.slice(2, -2)}</strong>
      : part
  )
}

export default function ReportPanel() {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchLatestReport()
      setReport(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleGenerate() {
    setGenerating(true)
    setError(null)
    try {
      await triggerReport()
      // Poll every 4s for up to 90s
      let attempts = 0
      const poll = setInterval(async () => {
        attempts++
        const data = await fetchLatestReport().catch(() => null)
        if (data && (!report || data.created_at > report.created_at)) {
          clearInterval(poll)
          setReport(data)
          setGenerating(false)
        } else if (attempts > 22) {
          clearInterval(poll)
          setGenerating(false)
          setError('Report generation timed out. Try again.')
        }
      }, 4000)
    } catch (err) {
      setError(err.message)
      setGenerating(false)
    }
  }

  if (loading) return <div className="p-4 text-gray-500 text-sm">Loading report…</div>

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold text-lg">Weekly Report</h2>
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white rounded-lg px-3 py-1.5 font-medium transition-colors"
        >
          {generating ? 'Generating…' : 'Generate'}
        </button>
      </div>

      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      {generating && (
        <div className="text-center text-gray-500 text-sm py-8">
          <div className="animate-spin inline-block w-5 h-5 border-2 border-gray-600 border-t-violet-500 rounded-full mb-3" />
          <p>Analysing your squad with Claude…</p>
        </div>
      )}

      {!generating && report ? (
        <>
          <p className="text-xs text-gray-500 mb-4">
            Generated {new Date(report.created_at).toLocaleString()} · GW{report.gameweek}
          </p>
          <MarkdownBlock text={report.content} />
        </>
      ) : !generating && (
        <div className="text-center text-gray-500 text-sm py-8">
          <p>No report yet.</p>
          <p className="mt-1">Hit Generate to create your GW briefing.</p>
        </div>
      )}
    </div>
  )
}
