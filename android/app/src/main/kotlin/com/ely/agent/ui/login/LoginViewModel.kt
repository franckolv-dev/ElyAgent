package com.ely.agent.ui.login

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ely.agent.core.network.NetworkResult
import com.ely.agent.data.repository.AuthRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

data class LoginUiState(
    val email: String = "",
    val password: String = "",
    val serverUrl: String = "http://10.0.2.2:8000",
    val isLoading: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class LoginViewModel @Inject constructor(private val authRepository: AuthRepository) : ViewModel() {
    private val _uiState = MutableStateFlow(LoginUiState())
    val uiState: StateFlow<LoginUiState> = _uiState.asStateFlow()

    fun onEmailChange(v: String) = _uiState.update { it.copy(email = v) }
    fun onPasswordChange(v: String) = _uiState.update { it.copy(password = v) }
    fun onServerUrlChange(v: String) = _uiState.update { it.copy(serverUrl = v) }

    fun login(onSuccess: () -> Unit) {
        val s = _uiState.value
        if (s.email.isBlank() || s.password.isBlank()) {
            _uiState.update { it.copy(error = "Email et mot de passe requis") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            when (val r = authRepository.login(s.email, s.password)) {
                is NetworkResult.Success -> onSuccess()
                is NetworkResult.Error -> _uiState.update { it.copy(isLoading = false, error = "Erreur ${r.code}: ${r.message}") }
                is NetworkResult.Exception -> _uiState.update { it.copy(isLoading = false, error = r.throwable.message ?: "Erreur réseau") }
            }
        }
    }
}
