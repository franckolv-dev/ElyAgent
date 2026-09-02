package com.ely.agent.data.repository

import com.ely.agent.core.model.AnalyticsSummary
import com.ely.agent.core.network.NetworkResult

interface AnalyticsRepository {
    suspend fun getSummary(days: Int = 30): NetworkResult<AnalyticsSummary>
}
