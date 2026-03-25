package com.ely.agent.ui.settings

import androidx.datastore.core.DataStore
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ely.agent.UserPreferences
import com.ely.agent.core.model.Skill
import com.ely.agent.data.repository.SkillsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SettingsUiState(
    val serverUrl: String = "http://10.0.2.2:8000",
    val theme: String = "SYSTEM",
    val showAvatar: Boolean = true,
    val skills: List<Skill> = emptyList(),
    val isSaved: Boolean = false,
    val isLoggedOut: Boolean = false
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val dataStore: DataStore<UserPreferences>,
    private val skillsRepository: SkillsRepository
) : ViewModel() {
    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            dataStore.data.collect { p ->
                _uiState.update {
                    it.copy(
                        serverUrl = p.serverUrl.ifBlank { "http://10.0.2.2:8000" },
                        theme = p.theme.ifBlank { "SYSTEM" },
                        showAvatar = !p.hideAvatar   // hide_avatar défaut = false → showAvatar = true
                    )
                }
            }
        }
        viewModelScope.launch {
            skillsRepository.observeSkills().collect { s -> _uiState.update { it.copy(skills = s) } }
        }
        viewModelScope.launch { try { skillsRepository.refreshSkills() } catch (_: Exception) {} }
    }

    fun onServerUrlChange(v: String) = _uiState.update { it.copy(serverUrl = v) }
    fun onThemeChange(v: String) = _uiState.update { it.copy(theme = v) }
    fun onShowAvatarChange(v: Boolean) = _uiState.update { it.copy(showAvatar = v) }

    fun save() {
        viewModelScope.launch {
            dataStore.updateData { p ->
                p.toBuilder()
                    .setServerUrl(_uiState.value.serverUrl)
                    .setTheme(_uiState.value.theme)
                    .setHideAvatar(!_uiState.value.showAvatar)
                    .build()
            }
            _uiState.update { it.copy(isSaved = true) }
        }
    }

    fun logout() {
        viewModelScope.launch {
            dataStore.updateData { it.toBuilder().clearAccessToken().build() }
            _uiState.update { it.copy(isLoggedOut = true) }
        }
    }
}
