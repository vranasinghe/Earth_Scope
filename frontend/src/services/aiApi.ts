// AI assistant API. The browser only talks to the Earth Scope backend; the Gemini key and the
// call to Google stay on the server.
import type { AiChatRequest, AiChatResponse, AiStatus } from '../types/ai'
import { getJson } from './api'

export const aiApi = {
  status: (signal?: AbortSignal) => getJson<AiStatus>('/api/ai/status', undefined, signal),
  chat: (body: AiChatRequest, signal?: AbortSignal) => getJson<AiChatResponse>('/api/ai/chat', undefined, signal, body),
}
