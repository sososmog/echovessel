import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { TopBar } from '../components/TopBar'
import {
  postImportUploadText,
  postPersonaBootstrapFromMaterial,
  postPersonaUpdate,
} from '../api/client'
import { ApiError } from '../api/types'
import type {
  OnboardingPayload,
  PersonaBootstrapResponse,
} from '../api/types'

type Step =
  | 'welcome'
  | 'blank-write'
  | 'import-upload'
  | 'import-waiting'
  | 'import-review'

interface OnboardingProps {
  completeOnboarding: (payload: OnboardingPayload) => Promise<void>
  error: string | null
}

/**
 * Default display_name used when the user does not explicitly name the
 * persona. The actual value depends on the current i18n locale — see
 * the `onboarding.default_display_name` key. The user can always rename
 * the persona later from Admin → Persona → display_name.
 */

const MIN_MATERIAL_CHARS = 80

export function Onboarding({ completeOnboarding, error }: OnboardingProps) {
  const { t } = useTranslation()
  const [step, setStep] = useState<Step>('welcome')

  // Blank-write state.
  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Import-upload state.
  const [material, setMaterial] = useState('')
  const [importError, setImportError] = useState<string | null>(null)
  const [bootstrap, setBootstrap] =
    useState<PersonaBootstrapResponse | null>(null)

  // Import-review edit state. Five blocks, individually editable
  // before we POST them to /api/admin/persona/onboarding.
  const [draftPersona, setDraftPersona] = useState('')
  const [draftSelf, setDraftSelf] = useState('')
  const [draftUser, setDraftUser] = useState('')
  const [draftMood, setDraftMood] = useState('')
  const [draftRelationship, setDraftRelationship] = useState('')

  const charCount = text.trim().length
  const canSubmit = charCount >= 10 && !submitting

  const handleSubmit = async () => {
    if (!canSubmit) return

    setSubmitting(true)
    try {
      await completeOnboarding({
        display_name: name.trim() || t('onboarding.default_display_name'),
        persona_block: text.trim(),
        self_block: '',
        user_block: '',
        mood_block: '',
      })
    } catch {
      // Error is surfaced via the `error` prop from usePersona().
    } finally {
      setSubmitting(false)
    }
  }

  const materialChars = material.trim().length
  const canRunImport = materialChars >= MIN_MATERIAL_CHARS && !submitting

  const handleRunImport = async () => {
    if (!canRunImport) return
    setImportError(null)
    setSubmitting(true)
    setStep('import-waiting')

    try {
      // Stage 1: persist the text upload. Reuses the generic import
      // upload endpoint — no onboarding-specific staging needed.
      const upload = await postImportUploadText({
        text: material.trim(),
        source_label: 'onboarding_material',
      })

      // Stage 2: server-side blocking call. Starts the pipeline, waits
      // for pipeline.done, drives the bootstrap LLM, returns five
      // suggested blocks.
      const result = await postPersonaBootstrapFromMaterial({
        upload_id: upload.upload_id,
        persona_display_name: t('onboarding.default_display_name'),
      })

      setBootstrap(result)
      setDraftPersona(result.suggested_blocks.persona_block)
      setDraftSelf(result.suggested_blocks.self_block)
      setDraftUser(result.suggested_blocks.user_block)
      setDraftMood(result.suggested_blocks.mood_block)
      setDraftRelationship(result.suggested_blocks.relationship_block)
      setStep('import-review')
    } catch (err) {
      let msg = t('onboarding.import_failed')
      if (err instanceof ApiError) {
        msg = err.detail
      } else if (err instanceof Error) {
        msg = err.message
      }
      setImportError(msg)
      setStep('import-upload')
    } finally {
      setSubmitting(false)
    }
  }

  const handleCommitReviewed = async () => {
    if (submitting) return
    setSubmitting(true)
    try {
      // Send only the four blocks the /onboarding endpoint accepts.
      await completeOnboarding({
        display_name: t('onboarding.default_display_name'),
        persona_block: draftPersona.trim(),
        self_block: draftSelf.trim(),
        user_block: draftUser.trim(),
        mood_block: draftMood.trim(),
      })
      // relationship_block is written via a follow-up PATCH below —
      // the onboarding contract intentionally does not include it, so
      // we use the partial-update endpoint once the persona exists.
      const rel = draftRelationship.trim()
      if (rel.length > 0) {
        try {
          await postPersonaUpdate({ relationship_block: rel })
        } catch {
          // Relationship write is best-effort — if it fails, the
          // persona is still fully onboarded with the other four
          // blocks. User can retry from Admin.
        }
      }
    } catch {
      // Error surfaces via the `error` prop.
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="onboarding-wrap">
      <TopBar mood={t('onboarding.topbar_mood')} />

      {step === 'welcome' && (
        <main className="onboarding">
          <h1 className="onboarding-title">
            {t('onboarding.welcome_title')}
            <span className="onboarding-punct">
              {t('onboarding.welcome_punct')}
            </span>
          </h1>
          <p className="onboarding-lead">
            {t('onboarding.welcome_subtitle')}
          </p>

          <div className="onboarding-paths">
            <button
              type="button"
              className="path-card"
              onClick={() => setStep('blank-write')}
            >
              <div className="path-card-index">01</div>
              <div className="path-card-body">
                <div className="path-card-title">
                  {t('onboarding.path_blank_title')}
                </div>
                <p className="path-card-desc">
                  {t('onboarding.path_blank_body')}
                </p>
              </div>
              <span className="path-card-arrow">→</span>
            </button>

            <button
              type="button"
              className="path-card"
              onClick={() => {
                setImportError(null)
                setStep('import-upload')
              }}
            >
              <div className="path-card-index">02</div>
              <div className="path-card-body">
                <div className="path-card-title">
                  {t('onboarding.path_material_title')}
                </div>
                <p className="path-card-desc">
                  {t('onboarding.path_material_body')}
                </p>
              </div>
              <span className="path-card-arrow">→</span>
            </button>
          </div>

          <div className="onboarding-footnote">
            {t('onboarding.footnote')}
          </div>
        </main>
      )}

      {step === 'blank-write' && (
        <main className="onboarding">
          <button
            type="button"
            className="onboarding-back"
            onClick={() => setStep('welcome')}
            disabled={submitting}
          >
            {t('onboarding.back')}
          </button>

          <h1 className="onboarding-title">
            {t('onboarding.blank_title')}
            <span className="onboarding-punct">
              {t('onboarding.blank_title_punct')}
            </span>
          </h1>
          <p className="onboarding-lead">
            {t('onboarding.blank_lead_line1')}
            <br />
            {t('onboarding.blank_lead_line2')}
          </p>

          <label className="onboarding-name-label">
            {t('onboarding.name_label')}{' '}
            <span className="onboarding-name-hint">
              {t('onboarding.name_hint')}
            </span>
          </label>
          <input
            className="onboarding-name-input"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('onboarding.name_placeholder')}
            maxLength={64}
            disabled={submitting}
          />

          <textarea
            className="onboarding-textarea"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={10}
            placeholder={t('onboarding.blank_textarea_placeholder')}
            autoFocus
            disabled={submitting}
          />

          {error !== null && (
            <div
              className="onboarding-hint"
              style={{
                color: 'rgba(255, 120, 120, 0.78)',
                marginTop: 12,
              }}
            >
              ⚠ {error}
            </div>
          )}

          <div className="onboarding-actions">
            <div className="onboarding-hint">
              {submitting
                ? t('onboarding.initialising')
                : charCount === 0
                  ? t('onboarding.need_a_few_sentences')
                  : canSubmit
                    ? t('onboarding.chars_enough', { count: charCount })
                    : t('onboarding.chars_more_needed', {
                        count: charCount,
                      })}
            </div>
            <button
              type="button"
              className="onboarding-submit"
              disabled={!canSubmit}
              onClick={() => void handleSubmit()}
            >
              {submitting ? '⋯' : t('onboarding.start_chat_cta')}
            </button>
          </div>
        </main>
      )}

      {step === 'import-upload' && (
        <main className="onboarding">
          <button
            type="button"
            className="onboarding-back"
            onClick={() => setStep('welcome')}
            disabled={submitting}
          >
            {t('onboarding.back')}
          </button>

          <h1 className="onboarding-title">
            {t('onboarding.upload_title')}
            <span className="onboarding-punct">
              {t('onboarding.upload_punct')}
            </span>
          </h1>
          <p className="onboarding-lead">
            {t('onboarding.upload_lead_line1')}
            <br />
            {t('onboarding.upload_lead_line2')}
          </p>

          <textarea
            className="onboarding-textarea"
            value={material}
            onChange={(e) => setMaterial(e.target.value)}
            rows={14}
            placeholder={t('onboarding.material_placeholder')}
            autoFocus
            disabled={submitting}
          />

          {importError !== null && (
            <div
              className="onboarding-hint"
              style={{
                color: 'rgba(255, 120, 120, 0.78)',
                marginTop: 12,
              }}
            >
              ⚠ {importError}
            </div>
          )}

          <div className="onboarding-actions">
            <div className="onboarding-hint">
              {materialChars === 0
                ? t('onboarding.need_min_chars', { min: MIN_MATERIAL_CHARS })
                : canRunImport
                  ? t('onboarding.material_ready', { count: materialChars })
                  : t('onboarding.material_more_needed', {
                      count: materialChars,
                      remaining: MIN_MATERIAL_CHARS - materialChars,
                    })}
            </div>
            <button
              type="button"
              className="onboarding-submit"
              disabled={!canRunImport}
              onClick={() => void handleRunImport()}
            >
              {t('onboarding.run_import_cta')}
            </button>
          </div>
        </main>
      )}

      {step === 'import-waiting' && (
        <main className="onboarding">
          <h1 className="onboarding-title">
            {t('onboarding.waiting_title')}
            <span className="onboarding-punct"></span>
          </h1>
          <p className="onboarding-lead">{t('onboarding.waiting_lead')}</p>
          <div
            className="onboarding-hint"
            style={{
              marginTop: 48,
              textAlign: 'center',
              fontSize: 14,
              color: 'rgba(255, 255, 255, 0.45)',
            }}
          >
            ⋯
          </div>
        </main>
      )}

      {step === 'import-review' && bootstrap !== null && (
        <main className="onboarding">
          <h1 className="onboarding-title">
            {t('onboarding.review_title')}
            <span className="onboarding-punct">
              {t('onboarding.review_punct')}
            </span>
          </h1>
          <p className="onboarding-lead">
            {t('onboarding.review_lead', {
              events: bootstrap.source_event_count,
              thoughts: bootstrap.source_thought_count,
            })}
          </p>

          <div className="onboarding-blocks">
            <BlockField
              label={t('onboarding.review_block_persona')}
              engName="persona_block"
              value={draftPersona}
              onChange={setDraftPersona}
              rows={6}
              disabled={submitting}
            />
            <BlockField
              label={t('onboarding.review_block_self')}
              engName="self_block"
              hint={t('onboarding.review_block_self_hint')}
              value={draftSelf}
              onChange={setDraftSelf}
              rows={3}
              disabled={submitting}
            />
            <BlockField
              label={t('onboarding.review_block_user')}
              engName="user_block"
              value={draftUser}
              onChange={setDraftUser}
              rows={6}
              disabled={submitting}
            />
            <BlockField
              label={t('onboarding.review_block_relationship')}
              engName="relationship_block"
              value={draftRelationship}
              onChange={setDraftRelationship}
              rows={5}
              disabled={submitting}
            />
            <BlockField
              label={t('onboarding.review_block_mood')}
              engName="mood_block"
              hint={t('onboarding.review_block_mood_hint')}
              value={draftMood}
              onChange={setDraftMood}
              rows={2}
              disabled={submitting}
            />
          </div>

          {error !== null && (
            <div
              className="onboarding-hint"
              style={{
                color: 'rgba(255, 120, 120, 0.78)',
                marginTop: 12,
              }}
            >
              ⚠ {error}
            </div>
          )}

          <div className="onboarding-actions">
            <div className="onboarding-hint">
              {submitting
                ? t('onboarding.writing_persona')
                : t('onboarding.review_ready')}
            </div>
            <button
              type="button"
              className="onboarding-submit"
              disabled={submitting}
              onClick={() => void handleCommitReviewed()}
            >
              {submitting ? '⋯' : t('onboarding.commit_cta')}
            </button>
          </div>
        </main>
      )}
    </div>
  )
}

interface BlockFieldProps {
  label: string
  engName: string
  hint?: string
  value: string
  onChange: (next: string) => void
  rows: number
  disabled: boolean
}

function BlockField({
  label,
  engName,
  hint,
  value,
  onChange,
  rows,
  disabled,
}: BlockFieldProps) {
  return (
    <section className="onboarding-block-field" style={{ marginBottom: 20 }}>
      <header style={{ marginBottom: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{label}</span>
        <span
          style={{
            fontSize: 11,
            marginLeft: 8,
            color: 'rgba(255, 255, 255, 0.38)',
            letterSpacing: '0.04em',
          }}
        >
          {engName}
        </span>
        {hint && (
          <div
            style={{
              fontSize: 12,
              marginTop: 2,
              color: 'rgba(255, 255, 255, 0.48)',
            }}
          >
            {hint}
          </div>
        )}
      </header>
      <textarea
        className="onboarding-textarea"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        disabled={disabled}
        style={{ width: '100%', minHeight: 0 }}
      />
    </section>
  )
}
