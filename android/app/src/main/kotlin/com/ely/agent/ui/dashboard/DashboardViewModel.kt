package com.ely.agent.ui.dashboard

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ely.agent.core.model.AnalyticsSummary
import com.ely.agent.core.network.NetworkResult
import com.ely.agent.data.repository.AnalyticsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

data class DashboardUiState(
    val summary: AnalyticsSummary? = null,
    val selectedPeriod: Int = 30,
    val isLoading: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class DashboardViewModel @Inject constructor(private val analyticsRepository: AnalyticsRepository) : ViewModel() {
    private val _uiState = MutableStateFlow(DashboardUiState())
    val uiState: StateFlow<DashboardUiState> = _uiState.asStateFlow()

    init { loadSummary() }

    fun setPeriod(days: Int) { _uiState.update { it.copy(selectedPeriod = days) }; loadSummary() }

    private fun loadSummary() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            when (val r = analyticsRepository.getSummary(_uiState.value.selectedPeriod)) {
                is NetworkResult.Success -> _uiState.update { it.copy(summary = r.data, isLoading = false) }
                is NetworkResult.Error -> _uiState.update { it.copy(isLoading = false, error = "Erreur ${r.code}") }
                is NetworkResult.Exception -> _uiState.update { it.copy(isLoading = false, error = r.throwable.message) }
            }
        }
    }
}
