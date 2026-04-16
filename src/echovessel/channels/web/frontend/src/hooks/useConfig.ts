/**
 * useConfig — fetch + edit the daemon's live config from the Admin
 * Config tab.
 *
 * State:
 *   - `config`: latest snapshot from GET /api/admin/config, or null
 *     while loading.
 *   - `loading`: true during the initial fetch (and during refresh()).
 *   - `saving`: true while a PATCH is in flight.
 *   - `error`: last API error (cleared when the next request starts).
 *   - `lastSaved`: epoch-ms timestamp of the most recent successful
 *     save, so the UI can render a "saved ✓" flash.
 *
 * Actions:
 *   - `refresh()` re-runs GET /api/admin/config.
 *   - `save(patch)` PATCHes and then refreshes so the returned
 *     `config` reflects server truth (reload_triggered may have
 *     changed more than the caller sent — e.g. reload() log).
 */

import { useCallback, useEffect, useState } from 'react'
import { getConfig, patchConfig } from '../api/client'
import { ApiError } from '../api/types'
import type { ConfigGetResponse, ConfigPatchPayload } from '../api/types'

export interface UseConfigResult {
  config: ConfigGetResponse | null
  loading: boolean
  saving: boolean
  error: string | null
  lastSaved: number | null
  refresh(): Promise<void>
  save(patch: ConfigPatchPayload): Promise<void>
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  if (err instanceof Error) return err.message
  return 'unknown error'
}

export function useConfig(): UseConfigResult {
  const [config, setConfig] = useState<ConfigGetResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastSaved, setLastSaved] = useState<number | null>(null)

  const refresh = useCallback(async (): Promise<void> => {
    setLoading(true)
    setError(null)
    try {
      const next = await getConfig()
      setConfig(next)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const save = useCallback(
    async (patch: ConfigPatchPayload): Promise<void> => {
      setError(null)
      setSaving(true)
      try {
        await patchConfig(patch)
        setLastSaved(Date.now())
        // Re-read so the UI shows server-truth (the server may have
        // coerced types, and the `system.uptime_seconds` ticks up too).
        const next = await getConfig()
        setConfig(next)
      } catch (err) {
        setError(errorMessage(err))
        throw err
      } finally {
        setSaving(false)
      }
    },
    [],
  )

  return { config, loading, saving, error, lastSaved, refresh, save }
}
