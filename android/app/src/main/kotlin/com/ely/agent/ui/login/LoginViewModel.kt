// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/ui/login/LoginViewModel.kt
// @brief      Login ViewModel — auth state management
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
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

package com.ely.agent.ui.login

import androidx.datastore.core.DataStore
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ely.agent.UserPreferences
import com.ely.agent.core.network.NetworkResult
import com.ely.agent.data.repository.AuthRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

data class LoginUiState(
    val email: String = "",
    val password: String = "",
    val serverUrl: String = "",
    val isLoading: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class LoginViewModel @Inject constructor(
    private val authRepository: AuthRepository,
    private val dataStore: DataStore<UserPreferences>
) : ViewModel() {

    private val _uiState = MutableStateFlow(LoginUiState())
    val uiState: StateFlow<LoginUiState> = _uiState.asStateFlow()

    init {
        // Pre-fill the URL field from DataStore so the user sees the saved value
        viewModelScope.launch {
            val savedUrl = dataStore.data.first().serverUrl
            if (savedUrl.isNotBlank()) {
                _uiState.update { it.copy(serverUrl = savedUrl) }
            }
        }
    }

    fun onEmailChange(v: String) = _uiState.update { it.copy(email = v) }
    fun onPasswordChange(v: String) = _uiState.update { it.copy(password = v) }

    fun onServerUrlChange(v: String) {
        // Strip all whitespace — Android autocomplete often inserts a space after
        // "https" when picked from the suggestion bar, which breaks URL parsing.
        val cleaned = v.filter { !it.isWhitespace() }
        _uiState.update { it.copy(serverUrl = cleaned) }
    }

    fun login(onSuccess: () -> Unit) {
        val s = _uiState.value
        if (s.email.isBlank() || s.password.isBlank()) {
            _uiState.update { it.copy(error = "Identifiant et mot de passe requis") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }

            // Persist the server URL to DataStore BEFORE the network call so
            // DynamicUrlInterceptor uses the correct host for this and all future requests.
            val urlToSave = s.serverUrl.trimEnd('/').ifBlank { "http://10.0.2.2:8000" }
            dataStore.updateData { prefs ->
                prefs.toBuilder().setServerUrl(urlToSave).build()
            }

            when (val r = authRepository.login(s.email, s.password)) {
                is NetworkResult.Success -> onSuccess()
                is NetworkResult.Error -> _uiState.update {
                    it.copy(isLoading = false, error = "Erreur ${r.code}: ${r.message}")
                }
                is NetworkResult.Exception -> _uiState.update {
                    it.copy(isLoading = false, error = r.throwable.message ?: "Erreur réseau")
                }
            }
        }
    }
}
