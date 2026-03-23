package com.ely.agent.core.database.dao

import androidx.room.*
import com.ely.agent.core.database.entity.SkillEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface SkillDao {
    @Query("SELECT * FROM skills ORDER BY displayName ASC")
    fun observeAll(): Flow<List<SkillEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(skills: List<SkillEntity>)

    @Update
    suspend fun update(skill: SkillEntity)

    @Query("DELETE FROM skills")
    suspend fun deleteAll()
}
