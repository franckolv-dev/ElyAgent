package com.ely.agent.data.remote.api

import com.ely.agent.data.remote.dto.SkillDto
import com.ely.agent.data.remote.dto.SkillUpdateRequest
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.PUT
import retrofit2.http.Path

interface SkillsApi {
    @GET("api/skills/")
    suspend fun getSkills(): List<SkillDto>

    @PUT("api/skills/{name}")
    suspend fun updateSkill(
        @Path("name") name: String,
        @Body body: SkillUpdateRequest
    )
}
