import { expect, it } from "vitest";
import { isAvatarEvent } from "../avatarEvents";
import type { WSMessage } from "../types";
it("keeps the answer when done and telemetry arrive in the same React batch", () => {
  const answer = {type:"message",role:"assistant",content:"Bonjour Franck"} as WSMessage;
  const events = [{type:"start"},answer,{type:"done"},{type:"token",content:""}] as WSMessage[];
  const state = events.reduce<WSMessage | null>((previous,event) => isAvatarEvent(event) ? event : previous, null);
  expect(state).toBe(answer);
});
it("retains interruption and approval events", () => {
  for (const type of ["stopped","error","hitl_pending","hitl_resolved"] as const) expect(isAvatarEvent({type})).toBe(true);
});
