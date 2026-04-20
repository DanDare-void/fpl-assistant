const BASE = '/api'

export async function fetchSquad() {
  const res = await fetch(`${BASE}/squad`)
  if (!res.ok) throw new Error(`Squad fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchFixtures(gameweek = null) {
  const url = gameweek ? `${BASE}/fixtures?gameweek=${gameweek}` : `${BASE}/fixtures`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Fixtures fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchFdr(numGameweeks = 6) {
  const res = await fetch(`${BASE}/fdr?num_gameweeks=${numGameweeks}`)
  if (!res.ok) throw new Error(`FDR fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchLatestReport() {
  const res = await fetch(`${BASE}/report/latest`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Report fetch failed: ${res.status}`)
  return res.json()
}

export async function triggerReport() {
  const res = await fetch(`${BASE}/report/generate`, { method: 'POST' })
  if (!res.ok) throw new Error(`Report trigger failed: ${res.status}`)
  return res.json()
}

/**
 * Stream a chat response.
 * @param {Array} messages  - [{role, content}, ...]
 * @param {function} onChunk - called with each decoded text chunk
 * @param {AbortSignal} signal
 */
export async function streamChat(messages, onChunk, signal) {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
    signal,
  })
  if (!res.ok) throw new Error(`Chat request failed: ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() // keep incomplete line
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const data = line.slice(6)
      if (data === '[DONE]') return
      onChunk(data.replace(/\\n/g, '\n'))
    }
  }
}
