export type ConfigPatch = {
  channels?: {
    matrix_enabled?: boolean
    email_enabled?: boolean
  }
  heartbeat?: {
    enabled?: boolean
    interval_minutes?: number
  }
}

export async function patchConfig(payload: ConfigPatch, nonce: string): Promise<Response> {
  return fetch("/api/config", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      "X-Squidbot-Local-Nonce": nonce
    },
    body: JSON.stringify(payload)
  })
}
