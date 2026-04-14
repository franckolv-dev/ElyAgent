package com.ely.agent.data.repository

import com.ely.agent.core.model.AnalyticsSummary
import com.ely.agent.core.model.HitlStats
import com.ely.agent.core.network.NetworkResult
import com.ely.agent.core.network.safeApiCall
import com.ely.agent.data.remote.api.AnalyticsApi
import javax.inject.Inject

class AnalyticsRepositoryImpl @Inject constructor(
    private val analyticsApi: AnalyticsApi
) : AnalyticsRepository {

    override suspend fun getSummary(days: Int): NetworkResult<AnalyticsSummary> =
        safeApiCall {
            val dto = analyticsApi.getSummary(days)
            AnalyticsSummary(
                totalRequests = dto.totalRequests,
                totalTokens = dto.totalTokens,
                inputTokens = dto.inputTokens,
                outputTokens = dto.outputTokens,
                estimatedCost = dto.estimatedCost,
                activeSkills = dto.activeSkills,
                hitlStats = HitlStats(dto.hitlStats.allow, dto.hitlStats.deny, dto.hitlStats.ban)
            )
        }
}
