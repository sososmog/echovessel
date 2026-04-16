import { useState } from 'react'
import { TopBar } from '../components/TopBar'
import type { OnboardingPayload } from '../api/types'

type Step = 'welcome' | 'blank-write' | 'import-placeholder'

interface OnboardingProps {
  completeOnboarding: (payload: OnboardingPayload) => Promise<void>
  error: string | null
}

/**
 * Default display_name used when the user does not explicitly name the
 * persona in the minimal blank-write flow. Matches the "她的声音" /
 * "她在听" tone of the rest of the prototype UI. The user can rename
 * the persona later from Admin → 人格 → display_name (v1.x UI).
 */
const DEFAULT_DISPLAY_NAME = '她'

export function Onboarding({ completeOnboarding, error }: OnboardingProps) {
  const [step, setStep] = useState<Step>('welcome')
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const charCount = text.trim().length
  const canSubmit = charCount >= 10 && !submitting

  const handleSubmit = async () => {
    if (!canSubmit) return

    setSubmitting(true)
    try {
      await completeOnboarding({
        display_name: DEFAULT_DISPLAY_NAME,
        persona_block: text.trim(),
        // Stage 4 proper · self/user/mood/relationship blocks start empty
        // and fill in over time via the reflection + interaction loops,
        // or via Admin → 人格 editing. The backend accepts empty strings.
        self_block: '',
        user_block: '',
        mood_block: '',
      })
      // No navigation call — usePersona's refresh() after a successful
      // onboarding flips daemonState.onboarding_required to false and
      // App.tsx re-renders into the /chat route.
    } catch {
      // Error is surfaced via the `error` prop from usePersona().
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="onboarding-wrap">
      <TopBar mood="等你开始" />

      {step === 'welcome' && (
        <main className="onboarding">
          <h1 className="onboarding-title">
            一个会记住你的人<span className="onboarding-punct">。</span>
          </h1>
          <p className="onboarding-lead">
            在我们开始之前，先告诉我——这个 persona 是谁？
          </p>

          <div className="onboarding-paths">
            <button
              type="button"
              className="path-card"
              onClick={() => setStep('blank-write')}
            >
              <div className="path-card-index">01</div>
              <div className="path-card-body">
                <div className="path-card-title">我自己写</div>
                <p className="path-card-desc">
                  用几句话描述 ta 的性格、说话的调子、你们的关系。最简单的起点。
                </p>
              </div>
              <span className="path-card-arrow">→</span>
            </button>

            <button
              type="button"
              className="path-card"
              onClick={() => setStep('import-placeholder')}
            >
              <div className="path-card-index">02</div>
              <div className="path-card-body">
                <div className="path-card-title">
                  上传材料让它自动生成
                </div>
                <p className="path-card-desc">
                  聊天记录、文章、日记、语音——让导入器读完之后为你写出一个 persona。
                </p>
              </div>
              <span className="path-card-arrow">→</span>
            </button>
          </div>

          <div className="onboarding-footnote">
            所有内容都只存在你这台机器上。没有服务器，没有第三方。
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
            ← 返回
          </button>

          <h1 className="onboarding-title">
            这个 persona 是谁<span className="onboarding-punct">？</span>
          </h1>
          <p className="onboarding-lead">
            写几句话描述。可以是 ta 的性格、说话的习惯、你们的关系——任何你想让 ta 从一开始就知道的东西。
            <br />
            其他的（你的身份、发生过的事、你身边的人）之后可以慢慢告诉 ta。
          </p>

          <textarea
            className="onboarding-textarea"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={10}
            placeholder={`比如⋯⋯

你是一个愿意认真听我说话的朋友。
当我不开心的时候，你会先陪着我，而不是急着告诉我该怎么办。
你不会用"加油"这种空洞的话敷衍我。
如果我想要建议，你会给；如果我只是想被听见，你也愿意只是在这里。`}
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
                ? '正在初始化 persona⋯'
                : charCount === 0
                  ? '至少写几句就可以开始。之后随时能回来补充。'
                  : canSubmit
                    ? `${charCount} 字 · 足够开始了`
                    : `${charCount} 字 · 再写几句吧`}
            </div>
            <button
              type="button"
              className="onboarding-submit"
              disabled={!canSubmit}
              onClick={() => void handleSubmit()}
            >
              {submitting ? '⋯' : '开始对话 →'}
            </button>
          </div>
        </main>
      )}

      {step === 'import-placeholder' && (
        <main className="onboarding">
          <button
            type="button"
            className="onboarding-back"
            onClick={() => setStep('welcome')}
          >
            ← 返回
          </button>

          <h1 className="onboarding-title">
            上传材料<span className="onboarding-punct">。</span>
          </h1>
          <p className="onboarding-lead">
            这条路径还没开放。后续版本会支持 txt / md / pdf / docx / html / 聊天记录 / 音频。
            LLM 读完之后，会按语义把 persona 的人格、发生过的事、你身边的人、你身上的事实，
            分别写到对应的记忆层。
          </p>
          <p className="onboarding-lead" style={{ marginTop: -40 }}>
            现在先用"我自己写"开始——以后导入功能上线了，你随时可以从 Admin 页面补上。
          </p>
          <div className="onboarding-actions">
            <div className="onboarding-hint">即将推出</div>
            <button
              type="button"
              className="onboarding-submit"
              onClick={() => setStep('blank-write')}
            >
              先用"我自己写" →
            </button>
          </div>
        </main>
      )}
    </div>
  )
}
