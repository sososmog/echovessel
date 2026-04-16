/**
 * useSSE — React hook that maintains an EventSource connection to
 * `/api/chat/events` and parses named events into typed ChatEvent objects.
 *
 * Stage 4 proper will call this from <App.tsx> (or a SSE provider
 * component) to expose the stream to the whole app. Components that
 * need events should consume `useChat()` / `usePersona()` which wrap
 * this hook — direct consumers of useSSE() are rare.
 *
 * Connection semantics:
 *   - One EventSource per hook instance (opened in useEffect on mount,
 *     closed on unmount).
 *   - EventSource auto-reconnects on network drops; on a transient error
 *     we set `connected=false` but keep the connection alive.
 *   - Unknown event names are logged via console.warn and dropped — the
 *     stream does NOT crash on an unexpected event.
 *
 * This file is Stage 4-prep only — components are not yet wired.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChatEvent } from '../api/types'
import { KNOWN_CHAT_EVENT_NAMES } from '../api/types'

type Listener = (event: ChatEvent) => void

export interface UseSSEResult {
  connected: boolean
  lastEvent: ChatEvent | null
  subscribe(listener: Listener): () => void
}

/**
 * Parse the `data` field of a SSE `MessageEvent` as JSON. Returns null
 * if parsing fails — caller logs and drops.
 */
function parseEventData(raw: string): unknown {
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export function useSSE(): UseSSEResult {
  const [connected, setConnected] = useState(false)
  const [lastEvent, setLastEvent] = useState<ChatEvent | null>(null)

  // Listeners are held in a ref so adding / removing a listener does not
  // trigger a re-render or reopen the connection.
  const listenersRef = useRef<Set<Listener>>(new Set())

  const dispatch = useCallback((event: ChatEvent) => {
    setLastEvent(event)
    for (const listener of listenersRef.current) {
      try {
        listener(event)
      } catch (err) {
        console.error('useSSE: listener threw', err)
      }
    }
  }, [])

  useEffect(() => {
    const es = new EventSource('/api/chat/events')

    const handleOpen = () => setConnected(true)
    const handleError = () => setConnected(false)

    es.addEventListener('open', handleOpen)
    es.addEventListener('error', handleError)

    // Register a handler for every known event name. Each handler parses
    // the JSON payload and forwards to the generic dispatcher as a
    // discriminated union member.
    const namedHandlers: Array<[string, (e: MessageEvent) => void]> = []

    for (const name of KNOWN_CHAT_EVENT_NAMES) {
      const handler = (ev: MessageEvent) => {
        const parsed = parseEventData(ev.data)
        if (parsed === null) {
          console.warn('useSSE: could not parse event data for', name, ev.data)
          return
        }
        // The cast is safe because `name` is the SSE event name the
        // backend emitted; the union discriminant is guaranteed by the
        // server-side contract. If the payload shape is wrong the
        // consumer will surface it at use site (not here).
        dispatch({ event: name, data: parsed } as ChatEvent)
      }
      es.addEventListener(name, handler as EventListener)
      namedHandlers.push([name, handler as EventListener as (e: MessageEvent) => void])
    }

    // Fallback: EventSource also delivers unnamed events to the default
    // `message` channel. If a new SSE event name appears without a
    // matching handler above, log it once so future stages know to add
    // it to `KNOWN_CHAT_EVENT_NAMES`.
    const handleMessage = (ev: MessageEvent) => {
      console.warn('useSSE: received unnamed or unknown SSE event', ev)
    }
    es.addEventListener('message', handleMessage)

    return () => {
      es.removeEventListener('open', handleOpen)
      es.removeEventListener('error', handleError)
      es.removeEventListener('message', handleMessage)
      for (const [name, handler] of namedHandlers) {
        es.removeEventListener(name, handler as EventListener)
      }
      es.close()
    }
  }, [dispatch])

  const subscribe = useCallback((listener: Listener) => {
    listenersRef.current.add(listener)
    return () => {
      listenersRef.current.delete(listener)
    }
  }, [])

  // `useMemo` keeps the result reference stable across renders where
  // none of the inputs have changed. Consumers can put the result in a
  // dep array without triggering churn.
  return useMemo<UseSSEResult>(
    () => ({ connected, lastEvent, subscribe }),
    [connected, lastEvent, subscribe],
  )
}
