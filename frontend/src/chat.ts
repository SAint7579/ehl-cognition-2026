import type { Message } from "./types";

const HIDDEN = [
  /you are devin running this investigation/i,
  /stay in this same devin/i,
  /operator follow-up:/i,
  /prefix your reply/i,
  /playbooks\/protein/i,
  /importing artifacts from/i,
  /science is running in a devin/i,
  /attachment download failed/i,
  /working in the sandbox/i,
  /restoring results from the sandbox/i,
  /internal operating instructions/i,
  /internal note, not for chat/i,
  /do not move work to/i,
  /do not run science on the operator/i,
];

export function visibleMessages(messages: Message[]): Message[] {
  return messages
    .map((message) => ({ ...message, body: cleanBody(message.body), artifact_ids: [] }))
    .filter((message) => {
      if (!message.body) return false;
      if (message.speaker === "system") return false;
      return !HIDDEN.some((pattern) => pattern.test(message.body));
    });
}

export function cleanBody(body: string): string {
  return body
    .replace(/ATTACHMENT:\{[\s\S]*?\}/g, "")
    .replace(/https:\/\/(?:app|api)\.devin\.ai\/attachments\/\S+/g, "")
    .replace(/^\[(?:planner|search|structure|design|reviewer|system)\]\s*/i, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
