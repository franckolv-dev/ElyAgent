// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/core/network/DynamicUrlInterceptor.kt
// @brief      OkHttp interceptor — rewrites request base URL from DataStore
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
// =============================================================================

package com.ely.agent.core.network

import android.util.Log
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
 * Rewrites every outgoing request to use the server URL stored in DataStore.
 *
 * The Retrofit client is built once as a Hilt singleton with a placeholder
 * base URL ("http://localhost/"); this interceptor substitutes the real host
 * (scheme, hostname, port) from DataStore on every request, so the user can
 * change the server URL from the login screen without restarting the app.
 *
 * Preserves the original path, query string and fragment from the Retrofit
 * request — only the authority (scheme://host:port) part is replaced.
 */
@Singleton
class DynamicUrlInterceptor @Inject constructor(
    private val dataStore: DataStore<UserPreferences>
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val rawUrl = runBlocking { dataStore.data.first().serverUrl }
        val baseUrl = rawUrl.trim().trimEnd('/').ifBlank { "http://10.0.2.2:8000" }

        val parsedBase = baseUrl.toHttpUrlOrNull()
        if (parsedBase == null) {
            Log.w(TAG, "Invalid server URL in DataStore: '$baseUrl' — proceeding with placeholder")
            return chain.proceed(chain.request())
        }

        val originalUrl = chain.request().url

        // Build the new URL from the base URL (correct scheme/host/port)
        // and graft the original path + query + fragment on top.
        val newUrl = parsedBase.newBuilder()
            .encodedPath(originalUrl.encodedPath)
            .encodedQuery(originalUrl.encodedQuery)
            .encodedFragment(originalUrl.encodedFragment)
            .build()

        Log.d(TAG, "Rewriting ${originalUrl} → ${newUrl}")

        return chain.proceed(chain.request().newBuilder().url(newUrl).build())
    }

    companion object {
        private const val TAG = "DynamicUrlInterceptor"
    }
}
