import { useCallback, useEffect, useRef, useState } from 'react'
import { TopBar } from '../components/TopBar'
import { useVoiceClone } from '../hooks/useVoiceClone'
import type { VoiceSample } from '../api/types'

interface VoiceCloneProps {
  onBack: () => void
}

export function VoiceClone({ onBack }: VoiceCloneProps) {
  const wiz = useVoiceClone()

  return (
    <div className="admin-wrap">
      <TopBar
        mood="克隆新声音"
        back={{ label: 'Admin', onClick: onBack }}
      />
      <div className="voice-clone-layout">
        <StepHeader step={wiz.step} />

        {wiz.error && <div className="voice-clone-error">⚠ {wiz.error}</div>}

        {wiz.step === 'upload' && (
          <UploadStep
            samples={wiz.samples}
            minimumRequired={wiz.minimumRequired}
            uploading={wiz.uploading}
            onUpload={wiz.uploadSample}
            onRemove={wiz.removeSample}
          />
        )}

        {wiz.step === 'clone' && (
          <CloneStep
            sampleCount={wiz.samples.length}
            cloning={wiz.cloning}
            onClone={wiz.startClone}
            onBackToUpload={() => {
              // removing one sample drops back below the min, flipping
              // `step` to 'upload' via the hook derivation.
              if (wiz.samples.length > 0) {
                void wiz.removeSample(wiz.samples[0]!.sample_id)
              }
            }}
          />
        )}

        {wiz.step === 'preview' && wiz.cloneResult !== null && (
          <PreviewStep
            voiceId={wiz.cloneResult.voice_id}
            displayName={wiz.cloneResult.display_name}
            previewText={wiz.cloneResult.preview_text}
            previewAudioUrl={wiz.cloneResult.preview_audio_url}
            activating={wiz.activating}
            activated={wiz.activated}
            onPreview={wiz.previewAudio}
            onActivate={wiz.activateVoice}
            onDone={onBack}
            onReset={wiz.reset}
          />
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// Step header — 3-dot progress indicator
// ═══════════════════════════════════════════════════════════

function StepHeader({ step }: { step: 'upload' | 'clone' | 'preview' }) {
  const steps: { id: typeof step; label: string; sub: string }[] = [
    { id: 'upload', label: '上传样本', sub: '3+ 段纯净录音' },
    { id: 'clone', label: '命名并生成', sub: 'FishAudio 训练' },
    { id: 'preview', label: '试听并激活', sub: '写入 config.toml' },
  ]
  const currentIdx = steps.findIndex((s) => s.id === step)
  return (
    <div className="voice-clone-steps">
      {steps.map((s, i) => {
        const state =
          i < currentIdx ? 'done' : i === currentIdx ? 'active' : 'future'
        return (
          <div key={s.id} className={`voice-clone-step voice-clone-step--${state}`}>
            <div className="voice-clone-step-num">{i + 1}</div>
            <div>
              <div className="voice-clone-step-label">{s.label}</div>
              <div className="voice-clone-step-sub">{s.sub}</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// Step 1 — Upload samples (drag + drop)
// ═══════════════════════════════════════════════════════════

function UploadStep({
  samples,
  minimumRequired,
  uploading,
  onUpload,
  onRemove,
}: {
  samples: VoiceSample[]
  minimumRequired: number
  uploading: boolean
  onUpload: (f: File) => Promise<void>
  onRemove: (id: string) => Promise<void>
}) {
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      for (const f of Array.from(files)) {
        try {
          await onUpload(f)
        } catch {
          // Error surfaced via hook state; stop batching so the user
          // can fix it before queueing more.
          return
        }
      }
    },
    [onUpload],
  )

  return (
    <div className="admin-section">
      <div className="admin-section-head">
        <h1 className="admin-section-title">上传声音样本</h1>
        <p className="admin-section-lead">
          拖入或选择 <strong>{minimumRequired}</strong>
          {' '}段以上的纯净录音（建议每段 10-30s · 单说话人 · 无背景音乐）。
        </p>
      </div>

      <div
        className={`voice-clone-drop ${dragActive ? 'is-active' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragActive(true)
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragActive(false)
          if (e.dataTransfer.files.length > 0) {
            void handleFiles(e.dataTransfer.files)
          }
        }}
        onClick={() => fileInputRef.current?.click()}
      >
        <div className="voice-clone-drop-glyph">🎙</div>
        <div className="voice-clone-drop-title">
          {uploading ? '上传中…' : '拖入音频文件到这里'}
        </div>
        <div className="voice-clone-drop-sub">
          或点击选择 · 支持 mp3 / wav / m4a · 单文件 ≤ 50MB
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="audio/*"
          multiple
          style={{ display: 'none' }}
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              void handleFiles(e.target.files)
              e.target.value = ''
            }
          }}
        />
      </div>

      <div className="voice-clone-sample-list">
        <div className="voice-clone-sample-count">
          已上传 <strong>{samples.length}</strong> /{' '}
          <strong>{minimumRequired}</strong>+ 条
        </div>
        {samples.length === 0 && (
          <div className="voice-clone-sample-empty">还没有上传任何样本。</div>
        )}
        {samples.map((s) => (
          <div key={s.sample_id} className="voice-clone-sample-row">
            <div className="voice-clone-sample-name">{s.filename}</div>
            <div className="voice-clone-sample-size">
              {formatBytes(s.size_bytes)}
              {s.duration_seconds !== null &&
                ` · ${s.duration_seconds.toFixed(1)}s`}
            </div>
            <button
              type="button"
              className="voice-clone-sample-del"
              onClick={() => void onRemove(s.sample_id)}
            >
              删除
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// Step 2 — Name + train
// ═══════════════════════════════════════════════════════════

function CloneStep({
  sampleCount,
  cloning,
  onClone,
  onBackToUpload,
}: {
  sampleCount: number
  cloning: boolean
  onClone: (displayName: string) => Promise<void>
  onBackToUpload: () => void
}) {
  const [name, setName] = useState('')

  return (
    <div className="admin-section">
      <div className="admin-section-head">
        <h1 className="admin-section-title">命名并生成</h1>
        <p className="admin-section-lead">
          已有 <strong>{sampleCount}</strong> 条样本。
          给这个声音起一个名字（之后可以在 Voice 管理页看到）。
        </p>
      </div>

      <div className="block-editor" style={{ maxWidth: 520 }}>
        <header className="block-editor-head">
          <div className="block-editor-label-row">
            <h3 className="block-editor-label">声音名称</h3>
            <span className="block-editor-engname">display_name</span>
          </div>
          <p className="block-editor-hint">
            例如 "我的声音 2026-04-16" 或 "温柔版"
          </p>
        </header>
        <input
          className="voice-clone-name-input"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="起个名字..."
          disabled={cloning}
          maxLength={128}
        />
        <div className="block-editor-actions">
          <button
            type="button"
            className="voice-clone-secondary"
            onClick={onBackToUpload}
            disabled={cloning}
          >
            ← 返回上传
          </button>
          <button
            type="button"
            className="block-editor-save"
            disabled={!name.trim() || cloning}
            onClick={() => void onClone(name.trim())}
          >
            {cloning ? '训练中⋯（20-60s）' : '开始训练'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// Step 3 — Preview + activate
// ═══════════════════════════════════════════════════════════

function PreviewStep({
  voiceId,
  displayName,
  previewText,
  previewAudioUrl,
  activating,
  activated,
  onPreview,
  onActivate,
  onDone,
  onReset,
}: {
  voiceId: string
  displayName: string
  previewText: string
  previewAudioUrl: string | null
  activating: boolean
  activated: boolean
  onPreview: (text: string) => Promise<Blob>
  onActivate: () => Promise<void>
  onDone: () => void
  onReset: () => void
}) {
  const [customText, setCustomText] = useState(previewText)
  const [customAudioUrl, setCustomAudioUrl] = useState<string | null>(null)
  const [fetching, setFetching] = useState(false)

  // Revoke object URLs on unmount / when replaced so we don't leak blob
  // references once the user dismisses the wizard.
  useEffect(() => {
    return () => {
      if (customAudioUrl !== null) {
        URL.revokeObjectURL(customAudioUrl)
      }
    }
  }, [customAudioUrl])

  const handlePreview = useCallback(async () => {
    setFetching(true)
    try {
      const blob = await onPreview(customText)
      const url = URL.createObjectURL(blob)
      setCustomAudioUrl((prev) => {
        if (prev !== null) URL.revokeObjectURL(prev)
        return url
      })
    } finally {
      setFetching(false)
    }
  }, [customText, onPreview])

  return (
    <div className="admin-section">
      <div className="admin-section-head">
        <h1 className="admin-section-title">试听 & 激活</h1>
        <p className="admin-section-lead">
          训练完成。<strong>{displayName}</strong> · voice_id{' '}
          <code>{voiceId}</code>
        </p>
      </div>

      {/* Default preview audio from the clone response */}
      {previewAudioUrl !== null && (
        <div className="voice-card" style={{ marginBottom: 16 }}>
          <div className="voice-card-status">
            <div
              className="voice-card-dot"
              style={{ background: 'rgba(120, 255, 180, 0.7)' }}
            />
            <div>
              <div className="voice-card-name">默认试听</div>
              <div className="voice-card-meta">{previewText}</div>
            </div>
          </div>
          <div className="voice-card-actions">
            <audio controls src={previewAudioUrl} />
          </div>
        </div>
      )}

      {/* Custom text preview */}
      <div className="block-editor" style={{ marginBottom: 24 }}>
        <header className="block-editor-head">
          <div className="block-editor-label-row">
            <h3 className="block-editor-label">用自己的文字试听</h3>
          </div>
        </header>
        <textarea
          className="block-editor-textarea"
          value={customText}
          onChange={(e) => setCustomText(e.target.value)}
          rows={3}
          maxLength={500}
        />
        <div className="block-editor-actions">
          <button
            type="button"
            className="block-editor-save"
            disabled={!customText.trim() || fetching}
            onClick={() => void handlePreview()}
          >
            {fetching ? '生成中⋯' : '生成试听'}
          </button>
        </div>
        {customAudioUrl !== null && (
          <audio
            controls
            src={customAudioUrl}
            style={{ width: '100%', marginTop: 12 }}
          />
        )}
      </div>

      <div className="voice-clone-activate">
        {!activated && (
          <>
            <p className="voice-clone-activate-hint">
              激活会把 <code>voice_id</code> 写到 config.toml，
              从下一条 persona 回复开始生效。
            </p>
            <div className="voice-clone-activate-actions">
              <button
                type="button"
                className="voice-clone-secondary"
                onClick={onReset}
                disabled={activating}
              >
                重新训练
              </button>
              <button
                type="button"
                className="voice-clone-activate-btn"
                onClick={() => void onActivate()}
                disabled={activating}
              >
                {activating ? '激活中⋯' : '✓ 激活这个声音'}
              </button>
            </div>
          </>
        )}
        {activated && (
          <>
            <p className="voice-clone-activate-done">
              ✓ 已激活 · 下一条回复会用这个声音。
            </p>
            <div className="voice-clone-activate-actions">
              <button
                type="button"
                className="voice-clone-activate-btn"
                onClick={onDone}
              >
                返回 Admin
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════

function formatBytes(n: number): string {
  if (n < 1024) return `${n}B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`
  return `${(n / 1024 / 1024).toFixed(1)}MB`
}
