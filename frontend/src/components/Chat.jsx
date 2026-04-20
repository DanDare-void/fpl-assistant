import { useState, useRef, useEffect } from 'react'
import { streamChat } from '../api'

function Message({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
          isUser
            ? 'bg-violet-600 text-white rounded-br-sm'
            : 'bg-gray-800 text-gray-100 rounded-bl-sm'
        }`}
      >
        {msg.content}
        {msg.streaming && (
          <span className="inline-block w-1.5 h-3.5 bg-gray-400 ml-0.5 align-middle animate-pulse" />
        )}
      </div>
    </div>
  )
}

export default function Chat() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const bottomRef = useRef(null)
  const abortRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send() {
    const text = input.trim()
    if (!text || loading) return

    const userMsg = { role: 'user', content: text }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setInput('')
    setLoading(true)
    setError(null)

    // Placeholder for assistant reply
    const assistantIdx = newMessages.length
    setMessages(prev => [...prev, { role: 'assistant', content: '', streaming: true }])

    abortRef.current = new AbortController()

    try {
      await streamChat(
        newMessages,
        chunk => {
          setMessages(prev => {
            const updated = [...prev]
            updated[assistantIdx] = {
              ...updated[assistantIdx],
              content: updated[assistantIdx].content + chunk,
            }
            return updated
          })
        },
        abortRef.current.signal,
      )
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError('Something went wrong. Please try again.')
      }
    } finally {
      setMessages(prev => {
        const updated = [...prev]
        if (updated[assistantIdx]) {
          updated[assistantIdx] = { ...updated[assistantIdx], streaming: false }
        }
        return updated
      })
      setLoading(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-1">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 mt-12 text-sm">
            <p className="text-2xl mb-2">⚽</p>
            <p className="font-medium text-gray-400">Ask anything about your FPL squad</p>
            <p className="mt-1">Captain picks, transfers, fixture analysis…</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <Message key={i} msg={msg} />
        ))}
        {error && (
          <p className="text-red-400 text-xs text-center mt-2">{error}</p>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="border-t border-gray-800 p-3 flex gap-2">
        <textarea
          ref={textareaRef}
          className="flex-1 bg-gray-800 text-gray-100 placeholder-gray-500 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-violet-500"
          rows={2}
          placeholder="Ask about transfers, captain, fixtures…"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          className="self-end bg-violet-600 hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl px-4 py-2 text-sm font-medium transition-colors"
        >
          {loading ? '…' : 'Send'}
        </button>
      </div>
    </div>
  )
}
