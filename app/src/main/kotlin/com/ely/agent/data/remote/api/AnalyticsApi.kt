package com.ely.agent.data.remote.api

import com.ely.agent.data.remote.dto.AnalyticsSummaryDto
import retrofit2.http.GET
import retrofit2.http.Query

interface AnalyticsApi {
    @GET("api/analytics/summary")
    suspend fun getSummary(@Query("days") days: Int = 30): AnalyticsSummaryDto
}
