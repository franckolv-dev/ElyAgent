package com.ely.agent.core.di

import android.content.Context
import androidx.room.Room
import com.ely.agent.core.database.ElyDatabase
import com.ely.agent.core.database.dao.ConversationDao
import com.ely.agent.core.database.dao.MessageDao
import com.ely.agent.core.database.dao.SkillDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {
    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): ElyDatabase =
        Room.databaseBuilder(context, ElyDatabase::class.java, "ely_database")
            .fallbackToDestructiveMigration()
            .build()

    @Provides fun provideMessageDao(db: ElyDatabase): MessageDao = db.messageDao()
    @Provides fun provideConversationDao(db: ElyDatabase): ConversationDao = db.conversationDao()
    @Provides fun provideSkillDao(db: ElyDatabase): SkillDao = db.skillDao()
}
