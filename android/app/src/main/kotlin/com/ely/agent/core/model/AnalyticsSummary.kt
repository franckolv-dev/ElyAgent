// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/core/model/AnalyticsSummary.kt
// @brief      Analytics summary data model
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
//             https://polyformproject.org/licenses/strict/1.0.0/
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
// =============================================================================

package com.ely.agent.core.model

data class HitlStats(val allow: Int, val deny: Int, val ban: Int)

data class AnalyticsSummary(
    val totalRequests: Int,
    val totalTokens: Long,
    val inputTokens: Long,
    val outputTokens: Long,
    val estimatedCost: Double,
    val activeSkills: Int,
    val hitlStats: HitlStats
)
