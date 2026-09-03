// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/repository/AnalyticsRepository.kt
// @brief      Analytics repository interface
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.data.repository

import com.ely.agent.core.model.AnalyticsSummary
import com.ely.agent.core.network.NetworkResult

interface AnalyticsRepository {
    suspend fun getSummary(days: Int = 30): NetworkResult<AnalyticsSummary>
}
