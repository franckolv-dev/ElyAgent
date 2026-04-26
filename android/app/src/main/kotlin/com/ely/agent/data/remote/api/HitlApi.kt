// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/api/HitlApi.kt
// @brief      HITL API — human-in-the-loop actions
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
//             https://polyformproject.org/licenses/strict/1.0.0/
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
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
