// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/ui/dashboard/DashboardViewModel.kt
// @brief      Dashboard ViewModel — analytics state
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
