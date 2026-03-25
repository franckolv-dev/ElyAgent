package com.ely.agent.data.repository

import com.ely.agent.core.database.dao.SkillDao
import com.ely.agent.core.database.entity.SkillEntity
import com.ely.agent.core.model.Skill
import com.ely.agent.data.remote.api.SkillsApi
import com.ely.agent.data.remote.dto.SkillUpdateRequest
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import javax.inject.Inject

class SkillsRepositoryImpl @Inject constructor(
    private val skillsApi: SkillsApi,
    private val skillDao: SkillDao
) : SkillsRepository {

    override fun observeSkills(): Flow<List<Skill>> =
        skillDao.observeAll().map { it.map { e -> e.toDomain() } }

    override suspend fun refreshSkills() {
        val dtos = skillsApi.getSkills()
        skillDao.deleteAll()
        skillDao.insertAll(dtos.map {
            SkillEntity(it.name, it.displayName, it.description, it.icon, it.enabled, it.version)
        })
    }

    override suspend fun toggleSkill(name: String, enabled: Boolean) {
        skillsApi.updateSkill(name, SkillUpdateRequest(enabled))
        skillDao.updateEnabled(name, enabled)
    }

    private fun SkillEntity.toDomain() = Skill(name, displayName, description, icon, enabled, version)
}
