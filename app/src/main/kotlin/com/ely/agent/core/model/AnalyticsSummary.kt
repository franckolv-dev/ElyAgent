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
