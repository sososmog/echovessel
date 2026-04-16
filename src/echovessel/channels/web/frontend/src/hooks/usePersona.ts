/**
 * usePersona — hook that fetches and manages persona state.
 *
 * Stage 4 proper will call this from <App.tsx> (for boot-time routing
 * based on `daemonState.onboarding_required`), from <Admin.tsx> (to read
 * `persona` and call `updatePersona` / `toggleVoice`), and from
 * <Onboarding.tsx> (to call `completeOnboarding`). Component flow:
 *
 *   const {
 *     persona, daemonState, loading, error,
 *     refresh, updatePersona, toggleVoice, completeOnboarding,
 *   } = usePersona()
 *
 * State flow:
 *   - On mount, fetches `/api/state` and `/api/admin/persona` in
 *     parallel and populates both slots.
 *   - `refresh()` re-fetches both.
 *   - `updatePersona(payload)` POSTs, then refreshes so the admin
 *     screen always shows the canonical server state.
 *   - `toggleVoice(enabled)` POSTs, then optimistically updates local
 *     state — the SSE `chat.settings.updated` broadcast will also
 *     arrive and confirm (or correct) the value.
 *   - `completeOnboarding(payload)` POSTs, then refreshes so the boot
 *     router transitions away from the onboarding screen.
 *   - Subscribes to the SSE `chat.settings.updated` event via
 *     `useSSE().subscribe(...)` so toggling voice in one tab updates
 *     the others.
 *
 * This file is Stage 4-prep only — components are not yet wired.
 */

import { useCallback, useEffect, useState } from 'react'
import {
  getPersona,
  getState,
  postOnboarding,
  postPersonaUpdate,
  postVoiceToggle,
} from '../api/client'
import type {
  ChatEvent,
  DaemonState,
  OnboardingPayload,
  PersonaStateApi,
  PersonaUpdatePayload,
} from '../api/types'
import { ApiError } from '../api/types'
import { useSSE } from './useSSE'

export interface UsePersonaResult {
  persona: PersonaStateApi | null
  daemonState: DaemonState | null
  loading: boolean
  error: string | null
  refresh(): Promise<void>
  updatePersona(payload: PersonaUpdatePayload): Promise<void>
  toggleVoice(enabled: boolean): Promise<void>
  completeOnboarding(payload: OnboardingPayload): Promise<void>
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  if (err instanceof Error) return err.message
  return 'unknown error'
}

export function usePersona(): UsePersonaResult {
  const [persona, setPersona] = useState<PersonaStateApi | null>(null)
  const [daemonState, setDaemonState] = useState<DaemonState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { subscribe } = useSSE()

  const refresh = useCallback(async (): Promise<void> => {
    setLoading(true)
    setError(null)
    try {
      const [stateValue, personaValue] = await Promise.all([
        getState(),
        getPersona(),
      ])
      setDaemonState(stateValue)
      setPersona(personaValue)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial fetch on mount.
  useEffect(() => {
    void refresh()
  }, [refresh])

  // Cross-tab sync: reflect voice toggles from other tabs.
  useEffect(() => {
    const unsubscribe = subscribe((event: ChatEvent) => {
      if (event.event !== 'chat.settings.updated') return
      const next = event.data.voice_enabled
      setPersona((prev) =>
        prev === null ? prev : { ...prev, voice_enabled: next },
      )
      setDaemonState((prev) =>
        prev === null
          ? prev
          : { ...prev, persona: { ...prev.persona, voice_enabled: next } },
      )
    })
    return unsubscribe
  }, [subscribe])

  const updatePersona = useCallback(
    async (payload: PersonaUpdatePayload): Promise<void> => {
      setError(null)
      try {
        await postPersonaUpdate(payload)
        await refresh()
      } catch (err) {
        setError(errorMessage(err))
        throw err
      }
    },
    [refresh],
  )

  const toggleVoice = useCallback(
    async (enabled: boolean): Promise<void> => {
      setError(null)
      try {
        const result = await postVoiceToggle(enabled)
        // Optimistic local update using the server's confirmed value.
        setPersona((prev) =>
          prev === null
            ? prev
            : { ...prev, voice_enabled: result.voice_enabled },
        )
        setDaemonState((prev) =>
          prev === null
            ? prev
            : {
                ...prev,
                persona: {
                  ...prev.persona,
                  voice_enabled: result.voice_enabled,
                },
              },
        )
      } catch (err) {
        setError(errorMessage(err))
        throw err
      }
    },
    [],
  )

  const completeOnboarding = useCallback(
    async (payload: OnboardingPayload): Promise<void> => {
      setError(null)
      try {
        await postOnboarding(payload)
        await refresh()
      } catch (err) {
        setError(errorMessage(err))
        throw err
      }
    },
    [refresh],
  )

  return {
    persona,
    daemonState,
    loading,
    error,
    refresh,
    updatePersona,
    toggleVoice,
    completeOnboarding,
  }
}
