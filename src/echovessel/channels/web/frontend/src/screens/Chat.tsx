import { useState } from 'react'
import { TopBar } from '../components/TopBar'
import { useChat } from '../hooks/useChat'
import type { ChatMessage as HookMessage } from '../hooks/useChat'
import type {
  ChatMessage as PrototypeMessage,
  VoiceMeta,
} from '../types'

interface ChatProps {
  moodBlock: string
  onOpenAdmin: () => void
}

export function Chat({ moodBlock, onOpenAdmin }: ChatProps) {
  const { messages, send, error } = useChat()
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)

  const moodSummary = moodBlock.trim().split(/[\n。]/)[0] || '平静、愿意倾听'

  const handleSend = async () => {
    const text = draft.trim()
    if (text.length === 0 || sending) return
    setDraft('')
    setSending(true)
    try {
      await send(text)
    } finally {
      setSending(false)
    }
  }

  const timeline = messages.map(toPrototypeShape)

  return (
    <div className="chat-wrap">
      <TopBar
        mood={moodSummary}
        primary={{ label: 'Admin', onClick: onOpenAdmin }}
      />

      <main className="chat-main">
        {timeline.length === 0 && <EmptyState />}
        {timeline.map((message, idx) => (
          <Exchange
            key={message.id}
            message={message}
            index={idx}
            isFirstOfTurn={isFirstOfTurn(timeline, idx)}
          />
        ))}
      </main>

      <div className="composer">
        <div className="composer-inner">
          {error !== null && (
            <div
              className="composer-field"
              style={{
                justifyContent: 'center',
                color: 'rgba(255, 120, 120, 0.78)',
                fontSize: 13,
                marginBottom: 8,
                background: 'rgba(255, 80, 80, 0.08)',
              }}
            >
              ⚠ {error}
            </div>
          )}
          <div className="composer-field">
            <input
              className="composer-input"
              type="text"
              placeholder="想说点什么⋯"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && draft.trim()) void handleSend()
              }}
              disabled={sending}
            />
            <button
              type="button"
              className="composer-send"
              onClick={() => void handleSend()}
              disabled={sending || draft.trim().length === 0}
            >
              {sending ? '⋯' : '发送'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Adapter: hook shape → prototype shape ──────────────────────────────
//
// Why adapter (not rewrite):
//   The prototype's render tree (Exchange / YouBubble / Letter /
//   VoiceButton) was designed around the prototype's rich ChatMessage
//   shape (paragraph array + VoiceMeta). Rewriting to render flat
//   strings would throw away the typography (paragraph breaks, letter
//   layout, cursor-on-last-line streaming indicator). An adapter
//   function is ~15 lines and keeps the whole render subtree intact.
//   See §6 of the Stage 4-proper tracker for the tradeoff discussion.

function toPrototypeShape(m: HookMessage): PrototypeMessage {
  return {
    id: m.id,
    // Prototype roles are 'you' (user) / 'them' (persona). Hook roles
    // are 'user' / 'persona'. Straight mapping.
    role: m.role === 'user' ? 'you' : 'them',
    // Use message_id when available (stable within a turn) otherwise
    // fall back to the client uuid. No true turn-grouping exists in
    // v1 — every hook message is its own turn for display purposes.
    turnId: m.message_id !== undefined ? `srv-${m.message_id}` : m.id,
    timestampLabel: formatTimestamp(m.timestamp),
    // Split on blank-line paragraph breaks to keep the letter-style
    // rendering. Fallback to a single paragraph for short replies.
    content: splitParagraphs(m.content),
    streaming: m.streaming,
    // Voice: if the hook message carries a voice_url (from
    // chat.message.voice_ready SSE), surface it through the prototype's
    // VoiceMeta shape so the VoiceButton component renders a real
    // <audio> player.
    voice: m.voice_url
      ? { duration: '', toneLabel: '她的声音', url: m.voice_url }
      : undefined,
  }
}

function splitParagraphs(content: string): string[] {
  if (content.length === 0) return ['']
  // Prefer double-newline paragraph breaks; fall back to single-line
  // splits for short streaming replies so the cursor blink lands on
  // the correct line.
  const paras = content.split(/\n{2,}/).map((p) => p.trim()).filter((p) => p.length > 0)
  if (paras.length === 0) return [content]
  return paras
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    const hh = d.getHours().toString().padStart(2, '0')
    const mm = d.getMinutes().toString().padStart(2, '0')
    return `${hh}:${mm}`
  } catch {
    return ''
  }
}

function isFirstOfTurn(
  timeline: PrototypeMessage[],
  idx: number,
): boolean {
  if (idx === 0) return true
  const prev = timeline[idx - 1]
  const curr = timeline[idx]
  if (!prev || !curr) return true
  return prev.turnId !== curr.turnId
}

// ─── Empty-state + render components (unchanged logic, trimmed) ─────────

function EmptyState() {
  return (
    <div
      style={{
        textAlign: 'center',
        color: 'rgba(255, 255, 255, 0.38)',
        fontSize: 14,
        letterSpacing: '0.06em',
        padding: '120px 32px 0',
        lineHeight: 1.8,
      }}
    >
      还没有消息。
      <br />
      随便说点什么开始吧。
    </div>
  )
}

interface ExchangeProps {
  message: PrototypeMessage
  index: number
  isFirstOfTurn: boolean
}

function Exchange({ message, index, isFirstOfTurn }: ExchangeProps) {
  const sideClass = message.role === 'you' ? 'you' : 'them'
  const turnClass = isFirstOfTurn ? 'turn-break' : ''
  const delay = Math.min(index * 0.08, 1.2)

  return (
    <div
      className={`exchange ${sideClass} ${turnClass}`.trim()}
      style={{ animationDelay: `${delay}s` }}
    >
      <div className="msg-wrap">
        {message.timestampLabel && (
          <div className="meta">{message.timestampLabel}</div>
        )}
        {message.role === 'you' ? (
          <YouBubble content={message.content} />
        ) : (
          <Letter
            content={message.content}
            voice={message.voice}
            streaming={message.streaming}
          />
        )}
      </div>
    </div>
  )
}

function YouBubble({ content }: { content: string[] }) {
  return (
    <div className="you-bubble">
      {content.map((p, i) => (
        <p key={i}>{p}</p>
      ))}
    </div>
  )
}

interface LetterProps {
  content: string[]
  voice?: VoiceMeta
  streaming?: boolean
}

function Letter({ content, voice, streaming }: LetterProps) {
  return (
    <div className="letter">
      {content.map((p, i) => {
        const isLast = i === content.length - 1
        return (
          <p key={i}>
            {p}
            {streaming && isLast && <span className="cursor" />}
          </p>
        )
      })}
      {voice && <VoiceButton meta={voice} />}
    </div>
  )
}

function VoiceButton({ meta }: { meta: VoiceMeta }) {
  const [playing, setPlaying] = useState(false)
  const [audioEl] = useState(() => {
    if (typeof Audio === 'undefined') return null
    return new Audio()
  })

  const handleClick = () => {
    if (!audioEl) return
    if (playing) {
      audioEl.pause()
      audioEl.currentTime = 0
      setPlaying(false)
      return
    }
    if (meta.url) {
      audioEl.src = meta.url
      audioEl.onended = () => setPlaying(false)
      audioEl.onerror = () => setPlaying(false)
      audioEl.play().catch(() => setPlaying(false))
      setPlaying(true)
    }
  }

  if (!meta.url) return null

  return (
    <button type="button" className="voice" onClick={handleClick}>
      <div className="voice-dot">
        <svg viewBox="0 0 12 12" xmlns="http://www.w3.org/2000/svg">
          <path d="M2 1 L10 6 L2 11 Z" />
        </svg>
      </div>
      <div className="voice-label">
        {playing ? '播放中 ' : '语音 '}
        <em>{playing ? '⋯' : meta.toneLabel}</em>
      </div>
    </button>
  )
}

