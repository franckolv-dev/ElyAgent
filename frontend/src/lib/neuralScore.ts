// Score « neural » affiché à côté du modèle actif (échelle 0-100).
// Audit 02/09/2026 : il était tiré de Math.random() à chaque tour — un
// chiffre inventé. Il reflète désormais le palier du modèle, et rien d'autre :
// même modèle, même score.
export function neuralScoreForModel(modelUsed: string): number {
  const m = modelUsed.toLowerCase();
  // Anthropic
  if (m.includes("opus"))                           return 99;
  if (m.includes("sonnet"))                         return 95;
  if (m.includes("haiku"))                          return 85;
  // OpenAI
  if (m.includes("gpt-5"))                          return 96;
  if (m.includes("gpt-4"))                          return 88;
  // DeepSeek
  if (m.includes("reasoner") || m.includes("-pro")) return 94;
  if (m.includes("deepseek"))                       return 82;
  // Gemini
  if (m.includes("gemini") && m.includes("pro"))    return 91;
  if (m.includes("flash"))                          return 81;
  // Mistral — Magistral (raisonnement)
  if (m.includes("magistral-medium"))               return 94;
  if (m.includes("magistral-small"))                return 89;
  // Mistral — classiques
  if (m.includes("mistral-large"))                  return 88;
  if (m.includes("mistral-medium"))                 return 82;
  if (m.includes("mistral-small"))                  return 77;
  // Mistral — Ministral (léger)
  if (m.includes("ministral-14b"))                  return 75;
  if (m.includes("ministral-8b"))                   return 69;
  // Kimi / Qwen cloud
  if (m.includes("kimi") || m.includes("qwen3.7"))  return 90;
  // Local (LM Studio / Ollama)
  if (m.includes("gemma") || m.includes("qwen") || m.includes("llama") || m.includes("ollama")) return 70;
  return 80; // unknown model
}
