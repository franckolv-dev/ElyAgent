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
 * Intercepteur OkHttp qui remplace dynamiquement le host/port/scheme de chaque requête
 * par l'URL serveur stockée dans DataStore.
 *
 * Tourne sur les threads OkHttp (background) → runBlocking ici est sûr, pas d'ANR.
 * Retrofit est initialisé avec une URL fictive ; cet intercepteur la surcharge à l'exécution.
 */
@Singleton
class BaseUrlInterceptor @Inject constructor(
    private val dataStore: DataStore<UserPreferences>
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val stored = runBlocking { dataStore.data.first().serverUrl }
        val baseUrl = stored.takeIf { it.isNotBlank() }
            ?.trimEnd('/')
            ?.let { "$it/" }
            ?: "http://10.0.2.2:8000/"

        val parsed = baseUrl.toHttpUrlOrNull()
        val original = chain.request()

        val newRequest = if (parsed != null) {
            val newUrl = original.url.newBuilder()
                .scheme(parsed.scheme)
                .host(parsed.host)
                .port(parsed.port)
                .build()
            original.newBuilder().url(newUrl).build()
        } else {
            original
        }

        return chain.proceed(newRequest)
    }
}
