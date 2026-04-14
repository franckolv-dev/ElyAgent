package com.ely.agent.ui.components.avatar

import androidx.compose.ui.graphics.Color

/**
 * États de l'avatar ELY — miroir exact des états du desktop (CyberpunkAvatar.tsx).
 * Chaque état a une couleur et un label HUD identiques à la version web.
 */
enum class AvatarState(val color: Color, val label: String) {
    /** En attente — cyan  */
    IDLE(Color(0xFF00D2FF), "IDLE"),
    /** Traitement en cours — violet */
    THINKING(Color(0xFFAA00FF), "PROCESSING"),
    /** Réponse en cours — vert lime */
    SPEAKING(Color(0xFF00FF5A), "SPEAKING"),
    /** Action critique (HITL) — rouge */
    ALERT(Color(0xFFFF1E37), "ALERT"),
    /** Écoute vocale — jaune */
    LISTENING(Color(0xFFFFD200), "LISTENING")
}
