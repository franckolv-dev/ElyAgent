// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/api/SkillsApi.kt
// @brief      Skills API — marketplace endpoints
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.data.remote.api

import com.ely.agent.data.remote.dto.SkillDto
import retrofit2.http.GET

interface SkillsApi {
    @GET("skills/")
    suspend fun getSkills(): List<SkillDto>
}
