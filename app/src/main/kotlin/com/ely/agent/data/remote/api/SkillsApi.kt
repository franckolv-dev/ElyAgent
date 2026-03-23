package com.ely.agent.data.remote.api

import com.ely.agent.data.remote.dto.SkillDto
import retrofit2.http.GET

interface SkillsApi {
    @GET("api/skills/")
    suspend fun getSkills(): List<SkillDto>
}
