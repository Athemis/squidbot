export type ChatStreamFrame =
  | { type: "chunk"; text: string }
  | { type: "error"; message: string }
  | { type: "done" }

export function parseChatStreamFrame(frameText: string): ChatStreamFrame {
  try {
    return JSON.parse(frameText) as ChatStreamFrame
  } catch {
    throw new Error("invalid chat stream frame")
  }
}

export async function readStreamErrorCode(response: Response): Promise<string | undefined> {
  try {
    const payload = (await response.clone().json()) as { error?: { code?: string } }
    return payload.error?.code
  } catch {
    return undefined
  }
}

export function shouldRetryWithFreshNonce(status: number, errorCode: string | undefined): boolean {
  return status === 403 && errorCode === "INVALID_NONCE"
}
