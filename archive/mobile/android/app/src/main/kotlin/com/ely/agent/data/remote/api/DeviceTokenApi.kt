// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/remote/api/DeviceTokenApi.kt
// @brief      Device token registration API
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.data.remote.api

import com.ely.agent.data.remote.dto.DeviceTokenRequest
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.PUT

interface DeviceTokenApi {
    @PUT("api/device-token")
    suspend fun registerToken(@Body body: DeviceTokenRequest): Response<Unit>
}
