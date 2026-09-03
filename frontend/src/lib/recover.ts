/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/recover.ts
 * @brief      Récupération post-déploiement après un ChunkLoadError.
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 *
 * Après un rebuild du frontend, un onglet ouvert garde l'ancien JS et réclame
 * des chunks dont le hash a changé → ChunkLoadError. Un simple `location.reload()`
 * ne suffit pas toujours : le service worker (ou le cache HTTP) peut re-servir
 * un shell périmé, laissant l'onglet coincé sur l'écran d'erreur.
 *
 * Ce helper neutralise toute source de stale : il DÉSENREGISTRE le service
 * worker et VIDE tous ses caches, puis recharge — le navigateur refetch alors
 * le shell + les chunks frais depuis le réseau. Le SW se ré-enregistre tout
 * seul au chargement suivant (ServiceWorkerRegister). Best-effort : chaque étape
 * est protégée pour que la recharge ait lieu quoi qu'il arrive.
 */

export async function hardRecoverAndReload(): Promise<void> {
  try {
    if (typeof navigator !== "undefined" && "serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((r) => r.unregister()));
    }
  } catch {
    /* best-effort */
  }
  try {
    if (typeof caches !== "undefined") {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    }
  } catch {
    /* best-effort */
  }
  if (typeof window !== "undefined") window.location.reload();
}
