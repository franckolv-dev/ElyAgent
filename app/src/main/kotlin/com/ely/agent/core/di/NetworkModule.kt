package com.ely.agent.core.di

import com.ely.agent.core.network.AuthInterceptor
import com.ely.agent.core.network.BaseUrlInterceptor
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
        baseUrlInterceptor: BaseUrlInterceptor
    ): OkHttpClient =
        OkHttpClient.Builder()
            // BaseUrlInterceptor en premier pour réécrire l'URL avant l'auth
            .addInterceptor(baseUrlInterceptor)
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
        // URL de base fictive — BaseUrlInterceptor la remplace dynamiquement à chaque requête.
        // Plus de runBlocking ici → plus d'ANR au démarrage.
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
}
