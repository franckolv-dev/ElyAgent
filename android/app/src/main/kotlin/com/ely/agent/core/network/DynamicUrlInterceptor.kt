// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/core/network/DynamicUrlInterceptor.kt
// @brief      OkHttp interceptor — rewrites request base URL from DataStore
//
// @author     Franck OLLIVIER <franck.olv@gmail.com>
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

package com.ely.agent.core.network

import androidx.datastore.core.DataStore
import com.ely.agent.UserPreferences
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Rewrites the host/scheme/port of every outgoing request to match the
 * server URL currently stored in DataStore.
 *
 * This makes it possible to change the server URL in the login screen and
 * have the change take effect immediately — without restarting the app or
 * rebuilding the (singleton) Retrofit instance.
 */
@Singleton
class DynamicUrlInterceptor @Inject constructor(
    private val dataStore: DataStore<UserPreferences>
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val rawUrl = runBlocking { dataStore.data.first().serverUrl }
        val baseUrl = rawUrl.trimEnd('/').ifBlank { "http://10.0.2.2:8000" }
        val parsedBase = baseUrl.toHttpUrlOrNull()
            ?: return chain.proceed(chain.request()) // malformed URL — proceed as-is

        val newUrl = chain.request().url.newBuilder()
            .scheme(parsedBase.scheme)
            .host(parsedBase.host)
            .port(parsedBase.port)
            .build()

        return chain.proceed(chain.request().newBuilder().url(newUrl).build())
    }
}
