/**
 * useMemorySearch — keyword search over L3 events + L4 thoughts.
 *
 * Wraps GET /api/admin/memory/search. The hook is debounced (~250 ms)
 * so typing into the admin search bar doesn't fire a request per
 * keystroke; the latest query wins via an in-flight cancel signal.
 *
 * The return value mirrors :func:`useMemoryEvents` shape so the
 * Events / Thoughts tabs can swap their default list out for the
 * search results without extensive component-side branching.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { searchMemory } from '../api/client'
import type {
  MemoryEvent,
  MemorySearchResponse,
  MemorySearchSnippet,
  MemorySearchType,
  MemoryThought,
} from '../api/types'
import { ApiError } from '../api/types'

const DEFAULT_DEBOUNCE_MS = 250
const DEFAULT_PAGE_SIZE = 20

export interface UseMemorySearchResult {
  query: string
  setQuery(next: string): void
  tag: string | null
  setTag(next: string | null): void
  results: (MemoryEvent | MemoryThought)[]
  snippets: Map<number, string>
  total: number
  loading: boolean
  error: string | null
  /** True when a non-empty query is active and results are ready. */
  active: boolean
  clear(): void
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  if (err instanceof Error) return err.message
  return 'unknown error'
}

export function useMemorySearch(
  type: MemorySearchType = 'all',
  pageSize: number = DEFAULT_PAGE_SIZE,
  debounceMs: number = DEFAULT_DEBOUNCE_MS,
): UseMemorySearchResult {
  const [query, setQuery] = useState('')
  const [tag, setTag] = useState<string | null>(null)
  const [response, setResponse] = useState<MemorySearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Tracks the latest dispatched query; if a slower in-flight request
  // resolves after a faster one, we ignore it.
  const latestQueryToken = useRef(0)

  useEffect(() => {
    const trimmed = query.trim()
    if (!trimmed) {
      // Empty query — drop any prior results so the calling component
      // re-renders the default list.
      setResponse(null)
      setError(null)
      setLoading(false)
      return
    }

    const myToken = ++latestQueryToken.current
    setLoading(true)
    setError(null)
    const handle = setTimeout(() => {
      searchMemory(trimmed, { type, tag, limit: pageSize, offset: 0 })
        .then((r) => {
          if (latestQueryToken.current !== myToken) return
          setResponse(r)
        })
        .catch((err: unknown) => {
          if (latestQueryToken.current !== myToken) return
          setError(errorMessage(err))
          setResponse(null)
        })
        .finally(() => {
          if (latestQueryToken.current !== myToken) return
          setLoading(false)
        })
    }, debounceMs)
    return () => clearTimeout(handle)
  }, [query, tag, type, pageSize, debounceMs])

  const snippets = useMemo(() => {
    const m = new Map<number, string>()
    if (!response) return m
    for (const s of response.matched_snippets) {
      m.set(s.node_id, s.snippet)
    }
    return m
  }, [response])

  const clear = useCallback(() => {
    latestQueryToken.current += 1
    setQuery('')
    setTag(null)
    setResponse(null)
    setError(null)
    setLoading(false)
  }, [])

  const active = query.trim().length > 0
  const results = response?.items ?? []
  const total = response?.total ?? 0

  // Defensive cast: ``MemorySearchSnippet`` lives on the response;
  // surface it via ``snippets`` Map but also expose the raw shape if
  // a future caller needs ordering. Currently unused — prefix with _.
  const _snippetsList: MemorySearchSnippet[] = response?.matched_snippets ?? []
  void _snippetsList

  return {
    query,
    setQuery,
    tag,
    setTag,
    results,
    snippets,
    total,
    loading,
    error,
    active,
    clear,
  }
}
