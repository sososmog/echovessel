export type Role = 'you' | 'them'

export interface VoiceMeta {
  duration: string
  toneLabel: string // e.g. "她的声音" or "她的声音 · 温柔"
  url?: string      // set when real TTS audio is available
}

export interface ChatMessage {
  id: string
  role: Role
  turnId: string
  timestampLabel: string // empty string if this message continues a burst
  content: string[] // paragraphs / burst lines
  streaming?: boolean // if true, render a blinking cursor after the last paragraph
  voice?: VoiceMeta
}

export type AdminTab = 'persona' | 'events' | 'thoughts' | 'voice' | 'config'
