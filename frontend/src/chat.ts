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
  const seen = new Set<string>();
  const visible: Message[] = [];
  for (const message of messages) {
    const body = cleanBody(message.body);
    if (!body || message.speaker === "system") continue;
    if (HIDDEN.some((pattern) => pattern.test(body))) continue;
    const fingerprint = body.replace(/\s+/g, " ").slice(0, 180);
    if (seen.has(fingerprint)) continue;
    seen.add(fingerprint);
    visible.push({ ...message, body, artifact_ids: [] });
  }
  return visible;
}

export function isStatusLine(body: string): boolean {
  if (body.length > 320) return false;
  return /^(on it|search|searched|fetch|fetching|pull|pulling|thought|looking|checking|running|found|opening|cloned)/i.test(
    body.trim(),
  );
}

export function cleanBody(body: string): string {
  return body
    .replace(/ATTACHMENT:\{[\s\S]*?\}/g, "")
    .replace(/https:\/\/(?:app|api)\.devin\.ai\/attachments\/\S+/g, "")
    .replace(/^\[(?:planner|search|structure|design|reviewer|system)\]\s*/i, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
