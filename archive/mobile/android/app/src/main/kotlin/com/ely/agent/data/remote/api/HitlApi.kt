// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/api/HitlApi.kt
// @brief      HITL API — human-in-the-loop actions
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.data.remote.api

import retrofit2.Response
import retrofit2.http.POST
import retrofit2.http.Path

interface HitlApi {
    @POST("validation/{actionId}/allow")
    suspend fun allow(@Path("actionId") actionId: String): Response<Unit>

    @POST("validation/{actionId}/deny")
    suspend fun deny(@Path("actionId") actionId: String): Response<Unit>
}
