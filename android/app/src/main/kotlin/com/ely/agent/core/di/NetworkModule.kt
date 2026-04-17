// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/core/di/NetworkModule.kt
// @brief      Hilt module for network
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

package com.ely.agent.core.di

import com.ely.agent.core.network.AuthInterceptor
import com.ely.agent.core.network.DynamicUrlInterceptor
import com.ely.agent.data.remote.api.*
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides
    @Singleton
    fun provideMoshi(): Moshi = Moshi.Builder()
        .addLast(KotlinJsonAdapterFactory())
        .build()

    @Provides
    @Singleton
    fun provideOkHttpClient(
        authInterceptor: AuthInterceptor,
        dynamicUrlInterceptor: DynamicUrlInterceptor
    ): OkHttpClient =
        OkHttpClient.Builder()
            // DynamicUrlInterceptor must be first so it rewrites the URL before auth
            .addInterceptor(dynamicUrlInterceptor)
            .addInterceptor(authInterceptor)
            .addInterceptor(HttpLoggingInterceptor().apply {
                level = HttpLoggingInterceptor.Level.BODY
            })
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .build()

    @Provides
    @Singleton
    fun provideRetrofit(okHttpClient: OkHttpClient, moshi: Moshi): Retrofit =
        // Base URL is a placeholder — DynamicUrlInterceptor overwrites host/scheme/port
        // on every request using the value stored in DataStore, so the app never needs
        // to be restarted when the user changes the server URL.
        Retrofit.Builder()
            .baseUrl("http://localhost/")
            .client(okHttpClient)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()

    @Provides @Singleton
    fun provideAuthApi(retrofit: Retrofit): AuthApi = retrofit.create(AuthApi::class.java)

    @Provides @Singleton
    fun provideDeviceTokenApi(retrofit: Retrofit): DeviceTokenApi = retrofit.create(DeviceTokenApi::class.java)

    @Provides @Singleton
    fun provideSkillsApi(retrofit: Retrofit): SkillsApi = retrofit.create(SkillsApi::class.java)

    @Provides @Singleton
    fun provideAnalyticsApi(retrofit: Retrofit): AnalyticsApi = retrofit.create(AnalyticsApi::class.java)

    @Provides @Singleton
    fun provideTranscribeApi(retrofit: Retrofit): TranscribeApi = retrofit.create(TranscribeApi::class.java)

    @Provides @Singleton
    fun provideHitlApi(retrofit: Retrofit): HitlApi = retrofit.create(HitlApi::class.java)

    @Provides @Singleton
    fun provideConversationsApi(retrofit: Retrofit): ConversationsApi = retrofit.create(ConversationsApi::class.java)
}
