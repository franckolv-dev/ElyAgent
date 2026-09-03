// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/dto/AnalyticsSummaryDto.kt
// @brief      Analytics summary DTO
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class HitlStatsDto(val allow: Int = 0, val deny: Int = 0, val ban: Int = 0)

@JsonClass(generateAdapter = true)
data class AnalyticsSummaryDto(
    @Json(name = "total_requests") val totalRequests: Int = 0,
    @Json(name = "total_tokens") val totalTokens: Long = 0,
    @Json(name = "input_tokens") val inputTokens: Long = 0,
    @Json(name = "output_tokens") val outputTokens: Long = 0,
    @Json(name = "estimated_cost") val estimatedCost: Double = 0.0,
    @Json(name = "active_skills") val activeSkills: Int = 0,
    @Json(name = "hitl_stats") val hitlStats: HitlStatsDto = HitlStatsDto()
)
