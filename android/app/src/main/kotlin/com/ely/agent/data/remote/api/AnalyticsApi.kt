// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/api/AnalyticsApi.kt
// @brief      Analytics API endpoints
//
// @author     Franck OLLIVIER <franck.olv@gmail.com>
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

package com.ely.agent.data.remote.api

import com.ely.agent.data.remote.dto.AnalyticsSummaryDto
import retrofit2.http.GET
import retrofit2.http.Query

interface AnalyticsApi {
    @GET("api/analytics/summary")
    suspend fun getSummary(@Query("days") days: Int = 30): AnalyticsSummaryDto
}
