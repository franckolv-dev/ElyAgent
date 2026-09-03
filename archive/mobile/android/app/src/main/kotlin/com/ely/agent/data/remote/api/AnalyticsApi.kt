// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/api/AnalyticsApi.kt
// @brief      Analytics API endpoints
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.data.remote.api

import com.ely.agent.data.remote.dto.AnalyticsSummaryDto
import retrofit2.http.GET
import retrofit2.http.Query

interface AnalyticsApi {
    @GET("analytics/summary")
    suspend fun getSummary(@Query("days") days: Int = 30): AnalyticsSummaryDto
}
