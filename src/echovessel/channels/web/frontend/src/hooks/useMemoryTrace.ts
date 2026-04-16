/**
 * useMemoryTrace — provenance lineage fetcher for the admin Events /
 * Thoughts tabs. One hook per card; the hook is lazy (does nothing
 * until `load()` is called) so a page that never expands any card
 * makes zero extra requests.
 *
 * Two entry points:
 *
 *   useMemoryTrace({ kind: 'thought', nodeId })  → fetches
 *     GET /api/admin/memory/thoughts/{id}/trace
 *     and exposes `data.source_events + data.source_sessions`.
 *
 *   useMemoryTrace({ kind: 'event', nodeId })    → fetches
 *     GET /api/admin/memory/events/{id}/dependents
 *     and exposes `data.dependent_thoughts`.
 *
 * The returned `data` is the raw response envelope (not normalised)
 * so consumers can switch on kind to pick the right array.
 */

import { useCallback, useState } from 'react'
import { getEventDependents, getThoughtTrace } from '../api/client'
import { ApiError } from '../api/types'
import type {
  EventDependentsResponse,
  ThoughtTraceResponse,
} from '../api/types'

export type TraceKind = 'thought' | 'event'

export type TraceData =
  | { kind: 'thought'; response: ThoughtTraceResponse }
  | { kind: 'event'; response: EventDependentsResponse }

export interface UseMemoryTraceResult {
  data: TraceData | null
  loading: boolean
  error: string | null
  load(): Promise<void>
  clear(): void
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  if (err instanceof Error) return err.message
  return 'unknown error'
}

export function useMemoryTrace(opts: {
  kind: TraceKind
  nodeId: number
}): UseMemoryTraceResult {
  const { kind, nodeId } = opts
  const [data, setData] = useState<TraceData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (): Promise<void> => {
    setLoading(true)
    setError(null)
    try {
      if (kind === 'thought') {
        const resp = await getThoughtTrace(nodeId)
        setData({ kind: 'thought', response: resp })
      } else {
        const resp = await getEventDependents(nodeId)
        setData({ kind: 'event', response: resp })
      }
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [kind, nodeId])

  const clear = useCallback(() => {
    setData(null)
    setError(null)
  }, [])

  return { data, loading, error, load, clear }
}
