import type { WSMessage } from "./types";

/** Transport events must never overwrite the answer awaiting speech in React. */
export function isAvatarEvent(message: WSMessage): boolean {
  return ["start", "message", "hitl_pending", "hitl_resolved", "error", "stopped"].includes(message.type);
}
