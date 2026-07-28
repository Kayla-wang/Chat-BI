import { config } from "./config";

export class OllamaConnectionError extends Error {}

export class LlmClient {
  constructor(private url: string = config.ollamaUrl, private model: string = config.ollamaModel) {}

  async *chatStream(prompt: string): AsyncIterable<string> {
    let res: Response;
    try {
      res = await fetch(`${this.url}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: this.model, stream: true, messages: [{ role: "user", content: prompt }] }),
      });
    } catch (e) {
      throw new OllamaConnectionError(`cannot reach ollama at ${this.url}: ${(e as Error).message}`);
    }
    if (!res.ok || !res.body) throw new OllamaConnectionError(`ollama returned ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        const obj = JSON.parse(line);
        const content: string = obj?.message?.content ?? "";
        if (content) yield content;
      }
    }
  }
}
